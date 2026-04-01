from urllib.parse import urlparse


def is_allowed(url: str, allowed_domains: list[str] | None, blocked_domains: list[str] | None) -> bool:
    domain = urlparse(url).netloc.lower()
    if blocked_domains and any(domain.endswith(b.lower()) for b in blocked_domains):
        return False
    if allowed_domains and not any(domain.endswith(a.lower()) for a in allowed_domains):
        return False
    return True
