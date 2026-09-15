"""Work out which manufacturer an attachment belongs to.

One distributor sends files for several manufacturers, so for every file we look
through the email in a set order and stop at the first place a configured
manufacturer turns up:

  1. subject
  2. attachment filename
  3. recipient domain - anyone on To/Cc who isn't us or the distributor, so a
     file cc'd to intake@acme.com is an ACME file. Names only here; an id is
     just a few digits and would match a domain by accident.
  4. body
  ... and "unknown" if none of that pans out.

Inside each of those we try an exact name/alias/id first, then a fuzzy match so
typos still land. Exact always wins over fuzzy, and ids are never fuzzy-matched.
"""

import difflib
import re

UNKNOWN = "unknown"

# how close a word has to be to count as a fuzzy match, 0 (anything) to 1
# (identical). Override per distributor with fuzzy_threshold; 0 turns it off.
DEFAULT_FUZZY_THRESHOLD = 0.8

def names_of(manufacturer: dict) -> list[str]:
    """Name plus aliases, i.e. everything we'll match as plain text."""
    out: list[str] = []
    name = str(manufacturer.get("name", "")).strip().lower()
    if name:
        out.append(name)
    for alias in manufacturer.get("aliases", []) or []:
        a = str(alias).strip().lower()
        if a:
            out.append(a)
    return out

def ids_of(manufacturer: dict) -> list[str]:
    out: list[str] = []
    for mid in manufacturer.get("ids", []) or []:
        s = str(mid).strip().lower()
        if s:
            out.append(s)
    return out

def words(text: str) -> list[str]:
    """Lowercase alphanumeric words, the unit we fuzzy-match against."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())

def id_in(token: str, text: str) -> bool:
    # ids need a non-alphanumeric on both sides, otherwise "10" hits inside
    # "1001". \b won't do: filenames separate with underscores.
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None

def exact_match(manufacturers: list[dict], text: str, use_ids: bool) -> str | None:
    """First manufacturer whose name/alias appears in the text, or whose id lands
    on a boundary. Config order decides priority."""
    for man in manufacturers:
        name = str(man.get("name", "")).strip()
        if not name:
            continue
        for token in names_of(man):
            if token in text:
                return name
        if use_ids:
            for token in ids_of(man):
                if id_in(token, text):
                    return name
    return None

def fuzzy_match(manufacturers: list[dict], text: str, threshold: float) -> str | None:
    """Same idea, but for near misses. Each name/alias is compared to every word,
    and for multi-word names to sliding windows of words. No ids on purpose."""
    if threshold <= 0:
        return None
    found = words(text)
    if not found:
        return None
    for man in manufacturers:
        name = str(man.get("name", "")).strip()
        if not name:
            continue
        for token in names_of(man):
            span = len(token.split())
            windows = found if span <= 1 else [
                " ".join(found[i:i + span]) for i in range(len(found) - span + 1)
            ]
            for candidate in windows:
                if difflib.SequenceMatcher(None, token, candidate).ratio() >= threshold:
                    return name
    return None

def look_in(manufacturers: list[dict], text: str, threshold: float, use_ids: bool = True) -> str | None:
    """Search one piece of text: everyone's exact matches before anyone's fuzzy
    ones, so a solid hit never loses to a near miss on another manufacturer."""
    text = (text or "").lower()
    if not text.strip():
        return None
    return exact_match(manufacturers, text, use_ids) or fuzzy_match(manufacturers, text, threshold)

def find_manufacturer(distributor_rule: dict, *, filename: str = "", subject: str = "",
                      recipient_domains=(), body_fn=None) -> tuple[str, str]:
    """Returns (manufacturer, where_we_found_it) with the source being one of
    subject / filename / recipient / body / none. body_fn is a callable so the
    body is only pulled apart if nothing earlier matched."""
    manufacturers = distributor_rule.get("manufacturers", []) or []
    if not manufacturers:
        return UNKNOWN, "none"
    threshold = float(distributor_rule.get("fuzzy_threshold", DEFAULT_FUZZY_THRESHOLD))

    hit = look_in(manufacturers, subject, threshold)
    if hit:
        return hit, "subject"
    hit = look_in(manufacturers, filename, threshold)
    if hit:
        return hit, "filename"
    for domain in recipient_domains:
        hit = look_in(manufacturers, domain, threshold, use_ids=False)
        if hit:
            return hit, "recipient"
    if body_fn is not None:
        hit = look_in(manufacturers, body_fn(), threshold)
        if hit:
            return hit, "body"
    return UNKNOWN, "none"
