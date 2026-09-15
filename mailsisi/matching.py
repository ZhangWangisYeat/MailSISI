"""Who sent this? Maps a From address onto a configured distributor."""

def build_sender_map(sender_rules: list[dict]) -> tuple[dict, dict]:
    """Two lookups: exact address -> distributor, and domain -> distributor."""
    email_map: dict[str, str] = {}
    domain_map: dict[str, str] = {}
    for rule in sender_rules:
        distributor = rule["distributor"]
        for addr in rule.get("email", []) or []:
            email_map[addr.lower().strip()] = distributor
        domain = rule.get("domain", "")
        if domain:
            domain_map[domain.lower().strip().lstrip("@")] = distributor
    return email_map, domain_map

def distributor_for(from_addr: str, email_map: dict, domain_map: dict) -> str | None:
    """The distributor behind this address, or None if it isn't whitelisted."""
    addr = (from_addr or "").lower().strip()
    if not addr:
        return None
    if addr in email_map:
        return email_map[addr]
    domain = addr.split("@")[-1] if "@" in addr else ""
    return domain_map.get(domain)
