"""Threading, so a reply carrying a corrected file replaces the right old one."""

import re

from . import db
from .naming import short_id

MSGID_RE = re.compile(r"<[^>]+>")
SUBJECT_PREFIX_RE = re.compile(r"^(\s*(re|fwd|fw)\s*:\s*)+", re.IGNORECASE)

def first_header(headers: dict, key: str) -> str | None:
    """imap_tools hands headers over as {lower_key: (value, ...)}."""
    vals = (headers or {}).get(key.lower())
    if not vals:
        return None
    if isinstance(vals, (list, tuple)):
        return vals[0].strip() if vals else None
    return str(vals).strip()

def parse_references(headers: dict) -> list[str]:
    """Every Message-ID mentioned in In-Reply-To and References."""
    refs: list[str] = []
    for key in ("in-reply-to", "references"):
        raw = first_header(headers, key)
        if raw:
            refs.extend(MSGID_RE.findall(raw))
    return refs

def clean_subject(subject: str) -> str:
    s = SUBJECT_PREFIX_RE.sub("", subject or "")
    return re.sub(r"\s+", " ", s).strip()

def thread_for(conn, headers: dict, subject: str, sender: str,
               distributor: str, dry_run: bool) -> tuple[str, str | None]:
    """(thread_id, message_id). Replies join the conversation they answer;
    anything else starts a new one."""
    message_id = first_header(headers, "message-id")

    # answering something we've already filed? use that thread
    for ref in parse_references(headers):
        tid = db.thread_for_message(conn, ref)
        if tid:
            if not dry_run:
                db.touch_thread(conn, tid)
            return tid, message_id

    # new conversation: Message-ID is the best key, subject + sender the backup
    subject_norm = clean_subject(subject)
    thread_id = message_id or f"subj:{short_id(subject_norm + '|' + (sender or ''))}"
    if not dry_run:
        db.save_thread(conn, thread_id, message_id, subject_norm, distributor)
    return thread_id, message_id
