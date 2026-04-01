from enum import Enum


class Intent(str, Enum):
    CONTACTS = "contacts"
    PRODUCTS = "products"
    REAL_ESTATE = "real_estate"
    ARTICLES = "articles"
    PRICING = "pricing"
    MEDIA = "media"
    GENERIC = "generic"


class Strategy(str, Enum):
    DIRECT_STATIC = "direct_static"
    DIRECT_DYNAMIC = "direct_dynamic"
    SEARCH_THEN_SCRAPE = "search_then_scrape"
    HYBRID = "hybrid"
