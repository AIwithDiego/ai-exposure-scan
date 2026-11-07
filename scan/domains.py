"""Shared host helpers."""

GENERIC_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov"}


def registrable(host):
    """Heuristic registrable domain: 'www.shop.example.co.uk' -> 'example.co.uk', 'www.zexel.io' -> 'zexel.io'."""
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.replace(".", "").isdigit():
        return host
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in GENERIC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])
