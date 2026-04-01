from app.core.enums import Intent
from app.models.plans import ExtractionField


DEFAULT_FIELDS: dict[Intent, list[ExtractionField]] = {
    Intent.CONTACTS: [
        ExtractionField(name="business_name", field_type="string"),
        ExtractionField(name="contact_name", field_type="string"),
        ExtractionField(name="email", field_type="email"),
        ExtractionField(name="phone", field_type="phone"),
        ExtractionField(name="website", field_type="url"),
        ExtractionField(name="address", field_type="string"),
        ExtractionField(name="linkedin_url", field_type="url"),
    ],
    Intent.REAL_ESTATE: [
        ExtractionField(name="address", field_type="string"),
        ExtractionField(name="city", field_type="string"),
        ExtractionField(name="state", field_type="string"),
        ExtractionField(name="price", field_type="number"),
        ExtractionField(name="beds", field_type="number"),
        ExtractionField(name="baths", field_type="number"),
        ExtractionField(name="sqft", field_type="number"),
        ExtractionField(name="description", field_type="string"),
        ExtractionField(name="image_urls", field_type="image_list"),
        ExtractionField(name="listing_agent", field_type="string"),
    ],
    Intent.PRODUCTS: [
        ExtractionField(name="product_name", field_type="string"),
        ExtractionField(name="price", field_type="number"),
        ExtractionField(name="sku", field_type="string"),
        ExtractionField(name="description", field_type="string"),
        ExtractionField(name="availability", field_type="string"),
        ExtractionField(name="image_urls", field_type="image_list"),
    ],
    Intent.ARTICLES: [
        ExtractionField(name="title", field_type="string", required=True),
        ExtractionField(name="author", field_type="string"),
        ExtractionField(name="published_at", field_type="string"),
        ExtractionField(name="summary", field_type="string"),
        ExtractionField(name="image_urls", field_type="image_list"),
    ],
    Intent.PRICING: [
        ExtractionField(name="plan_name", field_type="string"),
        ExtractionField(name="price", field_type="number"),
        ExtractionField(name="billing_interval", field_type="string"),
        ExtractionField(name="features", field_type="array"),
    ],
    Intent.MEDIA: [
        ExtractionField(name="title", field_type="string", required=True),
        ExtractionField(name="description", field_type="string"),
        ExtractionField(name="image_urls", field_type="image_list"),
        ExtractionField(name="video_urls", field_type="array"),
        ExtractionField(name="audio_urls", field_type="array"),
        ExtractionField(name="embed_urls", field_type="array"),
        ExtractionField(name="social_links", field_type="array"),
        ExtractionField(name="hashtags", field_type="array"),
    ],
    Intent.GENERIC: [
        ExtractionField(name="title", field_type="string"),
        ExtractionField(name="description", field_type="string"),
        ExtractionField(name="image_urls", field_type="image_list"),
        ExtractionField(name="video_urls", field_type="array"),
        ExtractionField(name="social_links", field_type="array"),
    ],
}


def infer_fields(intent: Intent, desired_fields: list[str] | None, custom_schema: dict | None) -> list[ExtractionField]:
    if custom_schema:
        fields: list[ExtractionField] = []
        for name, ftype in custom_schema.items():
            safe_type = ftype if ftype in {"string", "number", "url", "email", "phone", "image_list", "object", "array"} else "string"
            fields.append(ExtractionField(name=name, field_type=safe_type))
        return fields

    if desired_fields:
        return [ExtractionField(name=name, field_type="string") for name in desired_fields]

    return DEFAULT_FIELDS[intent]
