from app.core.enums import Intent


INTENT_KEYWORDS = {
    Intent.CONTACTS: ["email", "phone", "contact", "lead", "linkedin"],
    Intent.PRICING: ["price", "pricing", "plan"],
    Intent.REAL_ESTATE: ["listing", "beds", "bath", "sqft", "property", "real estate"],
    Intent.PRODUCTS: ["product", "sku", "inventory", "add to cart"],
    Intent.ARTICLES: ["article", "blog", "author", "published"],
    Intent.MEDIA: [
        "video",
        "videos",
        "viral",
        "trending",
        "trend",
        "meme",
        "memes",
        "gif",
        "gifs",
        "image",
        "images",
        "photo",
        "photos",
        "gallery",
        "media",
        "social",
        "instagram",
        "tiktok",
        "youtube",
        "reel",
        "reels",
        "shorts",
    ],
}


def infer_intent(query: str) -> Intent:
    normalized = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k in normalized for k in keywords):
            return intent
    return Intent.GENERIC
