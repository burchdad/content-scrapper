from urllib.parse import urlparse


MEDIA_DOMAINS = [
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "vimeo.com",
    "giphy.com",
    "tenor.com",
]


QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "best",
    "clip",
    "clips",
    "current",
    "find",
    "for",
    "from",
    "get",
    "gif",
    "gifs",
    "in",
    "latest",
    "meme",
    "memes",
    "new",
    "of",
    "on",
    "or",
    "reel",
    "reels",
    "short",
    "shorts",
    "show",
    "the",
    "this",
    "top",
    "trend",
    "trending",
    "video",
    "videos",
    "viral",
    "week",
    "with",
}


INTENT_CATEGORY_WEIGHTS = {
    "media": {"video": 4, "memes": 3, "images": 3, "culture": 2, "community": 2},
    "products": {"commerce": 4, "launches": 3, "classifieds": 2, "events": 2},
    "pricing": {"commerce": 4, "classifieds": 3, "events": 2},
    "real_estate": {"classifieds": 4, "events": 1},
    "articles": {"news": 4, "community": 3, "culture": 2, "events": 2},
    "contacts": {"community": 2, "launches": 2, "news": 2, "classifieds": 2},
}


def rank_candidates(
    candidates: list[dict],
    blocked_domains: set[str] | None = None,
    preferred_domains: list[str] | None = None,
    preferred_categories: list[str] | None = None,
    domain_categories: dict[str, list[str]] | None = None,
    intent: str | None = None,
    query: str | None = None,
) -> list[dict]:
    blocked = blocked_domains or set()
    preferred = [d.lower() for d in (preferred_domains or [])]
    preferred_cats = set(preferred_categories or [])
    domain_cat_map = {k.lower(): v for k, v in (domain_categories or {}).items()}
    seen_domains: set[str] = set()
    ranked: list[tuple[int, dict]] = []
    intent_weights = INTENT_CATEGORY_WEIGHTS.get(intent or "", {})
    query_tokens = _query_focus_tokens(query or "")

    for c in candidates:
        url = c.get("url", "")
        domain = _normalize_domain(urlparse(url).netloc)
        if not domain:
            continue
        if _matches_any_domain(domain, blocked):
            continue

        score = 0
        if domain not in seen_domains:
            score += 2
        if any(x in url.lower() for x in ["contact", "listing", "product", "pricing"]):
            score += 1
        if any(domain.endswith(media_domain) for media_domain in MEDIA_DOMAINS):
            score += 3
        if any(x in url.lower() for x in ["video", "shorts", "reel", "reels", "gif", "meme"]):
            score += 2
        if preferred and _matches_any_domain(domain, set(preferred)):
            score += 6

        matched_categories = _domain_categories_for(domain, domain_cat_map)
        for category in matched_categories:
            if category in preferred_cats:
                score += 2
            score += intent_weights.get(category, 0)

        if query_tokens:
            overlap = _token_overlap_count(query_tokens, c)
            if overlap > 0:
                score += min(overlap * 4, 12)
            else:
                score -= 4

        ranked.append((score, c))
        seen_domains.add(domain)

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked]


def _normalize_domain(domain: str) -> str:
    normalized = domain.strip().lower()
    if normalized.startswith("www."):
        return normalized[4:]
    return normalized


def _matches_any_domain(domain: str, domains: set[str]) -> bool:
    normalized = _normalize_domain(domain)
    return any(normalized == d or normalized.endswith(f".{d}") for d in domains)


def _domain_categories_for(domain: str, mapping: dict[str, list[str]]) -> list[str]:
    normalized = _normalize_domain(domain)
    categories: list[str] = []
    for mapped_domain, domain_categories in mapping.items():
        md = _normalize_domain(mapped_domain)
        if normalized == md or normalized.endswith(f".{md}"):
            categories.extend(domain_categories)
    return list(dict.fromkeys(categories))


def _query_focus_tokens(query: str) -> list[str]:
    words = [part.strip(" ,.;:!?()[]{}\"'\n\t").lower() for part in query.split()]
    tokens = [w for w in words if w and w not in QUERY_STOPWORDS and len(w) >= 3]
    return list(dict.fromkeys(tokens))


def _token_overlap_count(query_tokens: list[str], candidate: dict) -> int:
    text = " ".join(
        str(candidate.get(part, ""))
        for part in ["url", "title", "snippet", "description"]
    ).lower()
    return sum(1 for token in query_tokens if token in text)
