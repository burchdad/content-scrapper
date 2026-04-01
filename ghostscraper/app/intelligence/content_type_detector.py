def detect_content_type(query: str) -> str:
    q = query.lower()
    if "listing" in q or "real estate" in q:
        return "real_estate"
    if "product" in q:
        return "products"
    if "contact" in q or "email" in q:
        return "contacts"
    return "generic"
