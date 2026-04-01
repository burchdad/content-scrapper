from app.discovery.candidate_ranker import rank_candidates


def test_rank_candidates_prefers_source_pack_domains():
    candidates = [
        {"url": "https://example.com/viral-video-shorts"},
        {"url": "https://www.tiktok.com/@creator/video/123"},
    ]

    ranked = rank_candidates(candidates, preferred_domains=["tiktok.com"], intent="media")

    assert ranked[0]["url"].startswith("https://www.tiktok.com")


def test_rank_candidates_applies_intent_category_weighting():
    candidates = [
        {"url": "https://www.reuters.com/world/economy"},
        {"url": "https://www.reddit.com/r/worldnews/comments/123"},
    ]

    ranked = rank_candidates(
        candidates,
        preferred_categories=["news", "community"],
        domain_categories={"reuters.com": ["news"], "reddit.com": ["community"]},
        intent="articles",
    )

    assert ranked[0]["url"].startswith("https://www.reuters.com")


def test_rank_candidates_filters_blocked_domain_suffixes():
    candidates = [
        {"url": "https://sub.badsite.com/path"},
        {"url": "https://example.org/ok"},
    ]

    ranked = rank_candidates(candidates, blocked_domains={"badsite.com"})

    assert len(ranked) == 1
    assert ranked[0]["url"] == "https://example.org/ok"


def test_rank_candidates_boosts_query_overlap_for_media():
    candidates = [
        {
            "url": "https://giphy.com/trending-gifs",
            "title": "Trending GIFs",
            "snippet": "Latest reaction memes",
        },
        {
            "url": "https://www.dailymotion.com/video/x8dogstory",
            "title": "Top dog video compilation",
            "snippet": "Best dog video clips",
        },
    ]

    ranked = rank_candidates(candidates, intent="media", query="top dog video")

    assert ranked[0]["url"].startswith("https://www.dailymotion.com")