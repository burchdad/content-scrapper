from app.models.plans import ScrapePlan


def build_queries(
    plan: ScrapePlan,
    base_query: str,
    include_mature_content: bool = False,
    source_domains: list[str] | None = None,
    source_terms: list[str] | None = None,
    source_templates: list[str] | None = None,
) -> list[str]:
    focus_query = _focus_query(base_query)
    queries = [base_query]
    if focus_query != base_query:
        queries.append(focus_query)
    if plan.intent == "contacts":
        queries.extend([
            f"{base_query} contact email",
            f"{base_query} about us phone",
            f"site:.com {base_query} contact",
            f"{focus_query} contact email",
        ])
    elif plan.intent == "real_estate":
        queries.extend([
            f"{base_query} listings photos",
            f"{base_query} property details price beds baths",
            f"{base_query} real estate listing",
            f"{focus_query} real estate listing",
        ])
    elif plan.intent == "media":
        if include_mature_content:
            queries.extend([
                f"{base_query} uncensored trending clips",
                f"{base_query} mature audience media trends",
            ])
        queries.extend([
            f"{base_query} top trending memes gifs shorts",
            f"site:tiktok.com {base_query} trend videos this week",
            f"site:youtube.com shorts {base_query}",
            f"site:instagram.com reels {base_query}",
            f"{focus_query} trending short videos and memes",
            f"site:tiktok.com {focus_query} trend videos",
            f"site:youtube.com shorts {focus_query}",
        ])
    else:
        queries.extend([
            f"{base_query} official website",
            f"{base_query} details",
            f"{focus_query} details",
        ])

    extra_terms = _dedupe(source_terms or [])[:4]
    for term in extra_terms:
        queries.append(f"{focus_query} {term}")

    for template in _dedupe(source_templates or [])[:6]:
        queries.append(_render_template(template, focus_query))

    scoped_domains = _dedupe(source_domains or [])[:6]
    scoped_terms = extra_terms[:2] or [""]
    for domain in scoped_domains:
        for term in scoped_terms:
            suffix = f" {term}" if term else ""
            queries.append(f"site:{domain} {focus_query}{suffix}")

    return _dedupe(queries)[:12]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _render_template(template: str, base_query: str) -> str:
    if "{query}" in template:
        return template.replace("{query}", base_query)
    return f"{base_query} {template}".strip()


def _focus_query(base_query: str) -> str:
    words = [part.strip(" ,.;:!?()[]{}\"'").lower() for part in base_query.split()]
    stopwords = {
        "pull",
        "collect",
        "scrape",
        "extract",
        "find",
        "get",
        "give",
        "show",
        "please",
        "recent",
        "current",
        "top",
        "from",
        "with",
        "about",
        "and",
        "or",
        "the",
        "a",
        "an",
        "to",
        "of",
        "for",
    }
    kept = [w for w in words if w and w not in stopwords and len(w) > 2]
    if len(kept) < 1:
        return base_query
    return " ".join(kept[:12])
