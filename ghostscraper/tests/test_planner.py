from app.models.requests import ScrapeRequest
from app.planner.planner import Planner


def test_planner_infers_contacts_intent_and_strategy():
    planner = Planner()
    req = ScrapeRequest(query="Find email and phone for roofing companies in Texas")

    plan = planner.build_plan(req)

    assert plan.intent == "contacts"
    assert plan.strategy == "search_then_scrape"
    assert any(f.name == "email" for f in plan.fields)


def test_planner_prefers_hybrid_for_real_estate_with_websites():
    planner = Planner()
    req = ScrapeRequest(query="Get listing photos and beds baths sqft", websites=["https://example.com"])

    plan = planner.build_plan(req)

    assert plan.intent == "real_estate"
    assert plan.strategy == "hybrid"
    assert plan.click_galleries is True


def test_planner_infers_media_intent_and_dynamic_behavior():
    planner = Planner()
    req = ScrapeRequest(query="Pull all images, videos, reels, and social media assets from this campaign site")

    plan = planner.build_plan(req)

    assert plan.intent == "media"
    assert plan.use_playwright is True
    assert plan.click_galleries is True
    assert any(f.name == "video_urls" for f in plan.fields)


def test_planner_infers_media_intent_for_trend_prompt():
    planner = Planner()
    req = ScrapeRequest(query="top 10 trends")

    plan = planner.build_plan(req)

    assert plan.intent == "media"
