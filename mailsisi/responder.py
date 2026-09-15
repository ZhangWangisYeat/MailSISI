"""Optional acknowledgement replies.

Off by default, and cautious when on: it always writes the reply to a drafts
folder so there's a record, and only actually emails the distributor when
responder.send is true, because that's a message leaving the building.
"""

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from .config import get_env
from .naming import safe_filename
from .threads import clean_subject, first_header

def _body_text(msg) -> str:
    text = msg.text or msg.html or ""
    return text[:4000]

def _match_rules(rules: list[dict], subject: str, body: str, had_attachments: bool) -> str | None:
    haystack = f"{subject}\n{body}".lower()
    for rule in rules or []:
        if rule.get("requires_no_attachment") and had_attachments:
            continue
        if any(kw.lower() in haystack for kw in rule.get("contains", [])):
            return rule.get("template")
    return None

def _claude_reply(claude_cfg: dict, msg, distributor: str, had_attachments: bool, logger) -> str | None:
    """Ask Claude what to say. None means say nothing and fall back to the rules."""
    try:
        import anthropic
    except ImportError:
        logger.warning("responder.claude.enabled is on but the anthropic package is not "
                       "installed, falling back to rules. Run: pip install anthropic")
        return None

    api_key = get_env("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY is not set, falling back to rules.")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    system = (
        "You are a data-intake assistant for a company that receives data files from "
        "distributors by email. Read the distributor's email and write a brief, professional "
        "reply (2-4 sentences). If the email needs no reply, respond with exactly NO_REPLY. "
        "Never promise anything beyond acknowledging receipt or asking for a missing/corrected file."
    )
    user = (
        f"Distributor: {distributor}\n"
        f"Had attachment(s): {'yes' if had_attachments else 'no'}\n"
        f"Subject: {msg.subject}\n\n"
        f"Body:\n{_body_text(msg)}"
    )
    try:
        resp = client.messages.create(
            model=claude_cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=claude_cfg.get("max_tokens", 400),
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:  # a network hiccup must never take the intake down
        logger.warning(f"Claude triage failed ({e}); falling back to rules.")
        return None

    if not text or text.upper().startswith("NO_REPLY"):
        return None
    return text

def reply_text(rcfg: dict, msg, distributor: str, had_attachments: bool, logger) -> str | None:
    subject = msg.subject or ""
    body = _body_text(msg)

    claude_cfg = rcfg.get("claude", {}) or {}
    if claude_cfg.get("enabled"):
        text = _claude_reply(claude_cfg, msg, distributor, had_attachments, logger)
        if text is not None:
            return text  # None means Claude bowed out, so try the rules

    template = _match_rules(rcfg.get("rules", []), subject, body, had_attachments)
    if template is None and had_attachments:
        template = rcfg.get("default_template")
    if not template:
        return None
    return template.format(from_name=rcfg.get("from_name", "Data Intake")).strip()

def _save_draft(rcfg: dict, msg, text: str, logger, dry_run: bool) -> None:
    drafts_dir = Path(rcfg.get("drafts_dir", "./responses"))
    subject = f"Re: {clean_subject(msg.subject)}"
    fname = safe_filename(f"{msg.uid}_{clean_subject(msg.subject)}")[:80] + ".txt"
    content = f"To: {msg.from_}\nSubject: {subject}\n\n{text}\n"
    if dry_run:
        logger.info(f"  [DRY RUN] would draft reply to {drafts_dir / fname}")
        return
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / fname).write_text(content, encoding="utf-8")
    logger.info(f"  draft saved to {drafts_dir / fname}")

def _send_reply(rcfg: dict, msg, text: str, logger) -> None:
    smtp_cfg = rcfg.get("smtp", {}) or {}
    host = smtp_cfg.get("host")
    port = int(smtp_cfg.get("port", 587))
    user = get_env("SMTP_USERNAME", required=True)
    pwd = get_env("SMTP_PASSWORD", required=True)

    mime = MIMEText(text, "plain", "utf-8")
    mime["From"] = formataddr((rcfg.get("from_name", "Data Intake"), user))
    mime["To"] = msg.from_
    mime["Subject"] = f"Re: {clean_subject(msg.subject)}"
    in_reply_to = first_header(msg.headers, "message-id")
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
        mime["References"] = in_reply_to

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, pwd)
        server.send_message(mime)
    logger.info(f"  reply sent to {msg.from_}")

def maybe_reply(cfg: dict, msg, distributor: str, had_attachments: bool,
                logger, dry_run: bool) -> bool:
    """True if this message got a reply drafted or sent."""
    rcfg = cfg.get("responder", {}) or {}
    if not rcfg.get("enabled"):
        return False

    text = reply_text(rcfg, msg, distributor, had_attachments, logger)
    if not text:
        return False

    _save_draft(rcfg, msg, text, logger, dry_run)  # keep a copy either way
    if rcfg.get("send") and not dry_run:
        try:
            _send_reply(rcfg, msg, text, logger)
        except Exception as e:
            logger.error(f"  Failed to send reply to {msg.from_}: {e}")
    return True
