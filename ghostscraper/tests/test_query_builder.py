from app.models.plans import ExtractionField, ScrapePlan
from app.discovery.query_builder import build_queries


def _media_plan() -> ScrapePlan:
    return ScrapePlan(
        intent="media",
        strategy="search_then_scrape",
        fields=[ExtractionField(name="video_urls", field_type="array")],
    )


def test_media_query_builder_adds_trend_queries():
    plan = _media_plan()

    queries = build_queries(plan, "top 10 meme gifs shorts tiktok trends")

    joined = " ".join(queries).lower()
    assert "trending" in joined
    assert "tiktok" in joined


def test_media_query_builder_optional_mature_queries():
    plan = _media_plan()

    queries = build_queries(plan, "top 10 meme gifs shorts tiktok trends", include_mature_content=True)

    joined = " ".join(queries).lower()
    assert "uncensored" in joined or "mature audience" in joined


def test_media_query_builder_scopes_to_source_packs():
    plan = _media_plan()

    queries = build_queries(
        plan,
        "creator economy trends",
        source_domains=["tiktok.com", "reddit.com"],
        source_terms=["viral clips", "community buzz"],
    )

    joined = " ".join(queries).lower()
    assert "site:tiktok.com" in joined
    assert "site:reddit.com" in joined
    assert "community buzz" in joined


def test_media_query_builder_renders_source_templates():
    plan = _media_plan()

    queries = build_queries(
        plan,
        "creator economy trends",
        source_templates=["{query} trend challenge this week", "site:youtube.com shorts {query} compilation"],
    )

    joined = " ".join(queries).lower()
    assert "trend challenge this week" in joined
    assert "site:youtube.com shorts creator economy trends compilation" in joined


def test_media_query_builder_focuses_instructional_query_terms():
    plan = _media_plan()

    queries = build_queries(
        plan,
        "Pull recent short-form videos, reels, memes, and gifs about entrepreneurship and money mindset from TikTok",
    )

    joined = " ".join(queries).lower()
    assert "entrepreneurship money mindset tiktok" in joined


def test_media_query_builder_drops_top_noise_for_short_query():
    plan = _media_plan()

    queries = build_queries(plan, "top dog video")

    joined = " ".join(queries).lower()
    assert "dog video" in joined
