"""Filenames: cleaning them, building them from a template, avoiding collisions."""

import hashlib
from pathlib import Path

KEEP = (" ", ".", "_", "-")

def safe_filename(name: str) -> str:
    """Drop anything that doesn't belong in a filename."""
    cleaned = "".join(c for c in (name or "") if c.isalnum() or c in KEEP)
    return cleaned.strip().strip(".") or "file"

def logical_name(original_filename: str) -> str:
    """Identity of a file across versions. A corrected file in a reply almost
    always keeps its filename, so the lowercased name is good enough."""
    return (original_filename or "attachment").strip().lower()

def apply_template(template: str, ctx: dict, original_filename: str) -> str:
    """Fill in a naming template, keeping the extension."""
    ext = Path(original_filename or "").suffix
    stem = Path(original_filename or "attachment").stem
    fields = {
        "distributor": ctx.get("distributor", "unknown"),
        "manufacturer": ctx.get("manufacturer", "unknown"),
        # despite the name this is the sender's domain, e.g. gmail.com
        "manufacturer__email_domain": ctx.get("manufacturer__email_domain", ""),
        "date": ctx.get("date", ""),
        "send_date": ctx.get("send_date", ctx.get("date", "")),
        "received": ctx.get("received", ""),
        "stem": stem,
        "ext": ext,
        "original": original_filename or "attachment",
        "thread": ctx.get("thread", ""),
        "uid": ctx.get("uid", ""),
        "seq": ctx.get("seq", ""),
        "hash": ctx.get("hash", ""),
    }
    try:
        name = template.format(**fields)
    except (KeyError, IndexError, ValueError):
        name = f"{stem}{ext}"
    # a template without {ext} would leave the file unopenable
    if ext and not name.lower().endswith(ext.lower()):
        name += ext
    return safe_filename(name)

def name_with_manufacturer(original_filename: str, manufacturer: str) -> str:
    """Make sure the manufacturer shows up in the name without repeating it.
    Already in there? Leave the name alone. Otherwise stick it in front."""
    original = original_filename or "attachment"
    stem = Path(original).stem
    ext = Path(original).suffix
    known = bool(manufacturer) and manufacturer.lower() != "unknown"
    if known and manufacturer.lower() in stem.lower():
        return safe_filename(original)
    return safe_filename(f"{manufacturer}_{stem}{ext}")

def unique_path(path: Path, exclude: str | None = None) -> Path:
    """Append _1, _2, ... until the name is free. exclude counts as free, for when
    we mean to overwrite a file we put there ourselves."""
    if not path.exists() or (exclude and str(path) == str(exclude)):
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        cand = parent / f"{stem}_{i}{suffix}"
        if not cand.exists():
            return cand
        i += 1

def short_id(value: str) -> str:
    return hashlib.md5((value or "").encode("utf-8")).hexdigest()[:8]
