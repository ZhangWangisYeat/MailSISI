"""The main loop: read the mailbox, save attachments where they belong, let a
corrected file replace the one it corrects, optionally reply."""

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from imap_tools import AND, OR, MailBox

from . import db, responder
from .config import distributor_rule, get_env
from .manufacturers import UNKNOWN, find_manufacturer
from .matching import distributor_for
from .naming import (
    apply_template, logical_name, name_with_manufacturer, safe_filename, short_id, unique_path,
)
from .threads import clean_subject, first_header, thread_for

def _since_date(cfg: dict):
    """How far back to read, or None for everything. A fixed since_date wins (it's
    there to reach back for old files); otherwise since_days gives a window that
    rolls forward with today, so old mail falls off by itself."""
    fixed = cfg.get("since_date")
    if fixed:
        if isinstance(fixed, datetime):
            return fixed.date()
        if isinstance(fixed, date):
            return fixed
        try:
            return datetime.strptime(str(fixed), "%Y-%m-%d").date()
        except ValueError:
            return None
    days = cfg.get("since_days")
    if days:
        try:
            return date.today() - timedelta(days=int(days))
        except (ValueError, TypeError):
            return None
    return None

def _search_criteria(cfg: dict, email_map: dict, domain_map: dict):
    """Filter on the server so we never read the whole inbox: the date cutoff
    AND'd with an OR over the whitelisted senders. IMAP matches FROM as a
    substring, which is why a bare domain catches every address at it."""
    since = _since_date(cfg)
    date_kw = {"date_gte": since} if since else {}
    froms = list(email_map.keys()) + list(domain_map.keys())
    if not froms:
        return AND(**date_kw) if date_kw else "ALL"
    if len(froms) == 1:
        return AND(from_=froms[0], **date_kw)
    return AND(OR(from_=froms), **date_kw)

def _allowed_exts(cfg: dict) -> set[str] | None:
    """Lowercase, no dot. None means take everything."""
    exts = cfg.get("allowed_extensions")
    if not exts:
        return None
    return {str(e).lower().lstrip(".") for e in exts}

def _ext_ok(filename: str, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    ext = Path(filename or "").suffix.lower().lstrip(".")
    return ext in allowed

def _thread_folder(thread_id: str, msg) -> str:
    subj = clean_subject(msg.subject)
    if subj:
        return safe_filename(subj)[:60] or short_id(thread_id)
    return short_id(thread_id)

def _date_stamp(msg, cfg: dict) -> str:
    fmt = cfg.get("date_format", "%Y%m%d")
    when = msg.date or datetime.now()
    try:
        return when.strftime(fmt)
    except Exception:
        return datetime.now().strftime(fmt)

def _folder_for(cfg: dict, distributor: str, manufacturer: str, thread_id: str, msg) -> Path:
    out = Path(cfg["output_dir"])
    rule = distributor_rule(cfg, distributor)
    grouping = rule.get("grouping", cfg.get("grouping", "distributor"))
    dist = safe_filename(distributor)
    # the manufacturer folder gets the email's month-year on it (ACME_072026) so
    # every month lands in its own folder; manufacturer_folder_date: false for a
    # plain one
    man = safe_filename(manufacturer)
    if cfg.get("manufacturer_folder_date", True):
        man = safe_filename(f"{manufacturer}_{_date_stamp(msg, cfg)}")
    if grouping == "distributor_thread":
        return out / dist / _thread_folder(thread_id, msg)
    if grouping == "distributor_manufacturer":
        return out / dist / man
    if grouping == "manufacturer":
        return out / man
    return out / dist

def _body_of(msg) -> str:
    """Plain text if there is any, otherwise HTML with the tags knocked out."""
    if msg.text:
        return msg.text
    if msg.html:
        return re.sub(r"<[^>]+>", " ", msg.html)
    return ""

def _domain_of(addr: str) -> str:
    a = (addr or "").lower().strip()
    return a.split("@")[-1] if "@" in a else ""

def _outside_domains(msg, rule: dict, our_addr: str) -> list[str]:
    """To/Cc domains minus ourselves and the distributor. What's left are third
    parties whose domain might be the manufacturer (intake@acme.com). Order
    kept, no repeats."""
    our_addr = (our_addr or "").lower().strip()
    dist_emails = {str(e).lower().strip() for e in (rule.get("email") or [])}
    dist_domain = str(rule.get("domain") or "").lower().strip().lstrip("@")
    domains: list[str] = []
    recipients = list(getattr(msg, "to", ()) or ()) + list(getattr(msg, "cc", ()) or ())
    for addr in recipients:
        a = (addr or "").lower().strip()
        if "@" not in a or a == our_addr or a in dist_emails:
            continue
        dom = a.split("@")[-1]
        if dist_domain and dom == dist_domain:
            continue
        if dom not in domains:
            domains.append(dom)
    return domains

def _archive_old(cfg: dict, active_row, logger) -> None:
    old = Path(active_row["saved_path"])
    if not old.exists():
        return
    sdir = cfg.get("superseded_dir")
    if sdir:
        sp = Path(sdir)
        sp.mkdir(parents=True, exist_ok=True)
        target = unique_path(sp / old.name)
        old.replace(target)
        logger.info(f"    archived previous version to {target}")
    else:
        old.unlink()
        logger.info(f"    deleted previous version {old}")

def _save_attachment(cfg, conn, msg, att, seq, distributor, thread_id, logger, dry_run) -> int:
    payload = att.payload
    content_hash = hashlib.sha256(payload).hexdigest()
    original = att.filename or "attachment"
    logical = logical_name(original)

    # seen these exact bytes before (a reply quoting the same file, say)? move on
    if not dry_run:
        dup = db.attachment_with_hash(conn, content_hash)
        if dup:
            logger.info(f"  skipped '{original}', identical to a file we already have")
            return 0

    active = db.current_version(conn, thread_id, logical) if not dry_run else None

    rule = distributor_rule(cfg, distributor)
    manufacturer, source = find_manufacturer(
        rule,
        filename=original,
        subject=msg.subject or "",
        recipient_domains=_outside_domains(msg, rule, get_env("IMAP_USERNAME", "")),
        body_fn=lambda: _body_of(msg),
    )
    if manufacturer == UNKNOWN and rule.get("manufacturers"):
        logger.info(f"  '{original}' matched no manufacturer; naming it '{UNKNOWN}'")
    elif manufacturer != UNKNOWN:
        logger.info(f"  '{original}' -> manufacturer '{manufacturer}' (matched in {source})")

    naming_mode = rule.get("naming_mode", cfg.get("naming_mode"))
    if naming_mode == "manufacturer":
        filename = name_with_manufacturer(original, manufacturer)
    else:
        template = rule.get("naming_template", cfg.get("naming_template", "{distributor}_{date}_{stem}{ext}"))
        ctx = {
            "distributor": distributor,
            "manufacturer": manufacturer,
            "manufacturer__email_domain": _domain_of(msg.from_),
            "date": _date_stamp(msg, cfg),
            "send_date": _date_stamp(msg, cfg),
            "received": datetime.now().strftime(cfg.get("date_format", "%Y%m%d")),
            "thread": short_id(thread_id),
            "uid": str(msg.uid),
            "seq": seq,
            "hash": content_hash[:8],
        }
        filename = apply_template(template, ctx, original)

    dest_dir = _folder_for(cfg, distributor, manufacturer, thread_id, msg)
    dest = unique_path(dest_dir / filename, exclude=active["saved_path"] if active else None)

    if dry_run:
        verb = "replace" if active else "save"
        logger.info(f"  [DRY RUN] would {verb} '{original}' as {dest}")
        return 1

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Archive first, write second. A correction normally keeps the same filename,
    # so dest and the old path are usually the same file - archiving afterwards
    # would carry off the file we just wrote and leave nothing behind.
    if active:
        _archive_old(cfg, active, logger)

    dest.write_bytes(payload)
    version = (active["version"] + 1) if active else 1
    new_id = db.add_attachment(
        conn, str(msg.uid), thread_id, distributor, logical, original,
        str(dest), content_hash, len(payload), seq, version,
    )
    if active:
        db.mark_replaced(conn, active["id"], new_id)
        logger.info(f"  replaced '{original}' (version {active['version']} to {version}) as {dest}")
    else:
        logger.info(f"  saved '{original}' as {dest}")
    return 1

def _handle_message(cfg, conn, msg, email_map, domain_map, logger, dry_run) -> int:
    uid = str(msg.uid) if msg.uid else None
    if not uid or db.message_seen(conn, uid):
        return 0

    sender = (msg.from_ or "").lower()
    distributor = distributor_for(sender, email_map, domain_map)
    headers = msg.headers or {}
    message_id = first_header(headers, "message-id")

    if distributor is None:
        # remember the UID so we don't bother with it again, but download nothing
        if not dry_run:
            db.insert_message(conn, uid, message_id, None, sender, msg.subject, msg.date_str, None)
        return 0

    thread_id, _ = thread_for(conn, headers, msg.subject, sender, distributor, dry_run)
    allowed = _allowed_exts(cfg)
    attachments = [a for a in msg.attachments if a.payload and _ext_ok(a.filename, allowed)]

    if attachments:
        logger.info(f"UID {uid} from {sender} for '{distributor}' "
                    f"[thread {short_id(thread_id)}] ({len(attachments)} attachment(s))")
    saved = 0
    for seq, att in enumerate(attachments, 1):
        saved += _save_attachment(cfg, conn, msg, att, seq, distributor, thread_id, logger, dry_run)

    responded = responder.maybe_reply(cfg, msg, distributor, bool(attachments), logger, dry_run)
    if not dry_run:
        db.insert_message(conn, uid, message_id, thread_id, sender, msg.subject,
                          msg.date_str, distributor, responded=int(responded))
    return saved

def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

def run_once(cfg, conn, sender_map, logger, dry_run) -> int:
    host = get_env("IMAP_HOST", required=True)
    port = int(get_env("IMAP_PORT", "993"))
    user = get_env("IMAP_USERNAME", required=True)
    pwd = get_env("IMAP_PASSWORD", required=True)
    folder = cfg.get("mailbox_folder", "INBOX")
    email_map, domain_map = sender_map
    criteria = _search_criteria(cfg, email_map, domain_map)

    saved = 0
    logger.info(f"Connecting to {host}:{port} (folder: {folder})")
    with MailBox(host, port).login(user, pwd, initial_folder=folder) as mailbox:
        # The server does the filtering, so only whitelisted mail in the window
        # comes back. Listing the UIDs is cheap; pull the full body only for the
        # ones we haven't already handled.
        uids = mailbox.uids(criteria)
        pending = [u for u in uids if not db.message_seen(conn, u)]
        logger.info(f"{len(uids)} message(s) match the filter; {len(pending)} new to fetch.")
        for chunk in _chunks(pending, 200):
            for msg in mailbox.fetch(AND(uid=",".join(chunk)), mark_seen=False, bulk=True):
                saved += _handle_message(cfg, conn, msg, email_map, domain_map, logger, dry_run)

    if not dry_run:
        cap = cfg.get("db_max_messages", 20000)
        if cap and db.count_messages(conn) > cap:
            removed = db.prune_old_messages(conn, cap)
            if removed:
                logger.info(f"Database maintenance: pruned {removed} old skipped-email "
                            f"record(s) and compacted the file.")

    logger.info(f"Done. {saved} file(s) saved this run."
                + (" (dry run, nothing written)" if dry_run else ""))
    return saved
