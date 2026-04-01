from app.models.requests import ScrapeRequest
from app.services.scrape_orchestrator import (
    _candidate_matches_query_tokens,
    _is_generic_meme_media_seed,
    _is_candidate_target_url,
    _is_media_like_request,
    _matches_domains,
    _seed_matches_query,
)


def test_media_candidate_filter_drops_known_robots_blocked_hosts_when_enabled():
    assert not _is_candidate_target_url(
        "https://www.youtube.com/shorts/abc123",
        intent="media",
        respect_robots=True,
    )


def test_media_candidate_filter_allows_same_host_when_robots_not_enforced():
    assert _is_candidate_target_url(
        "https://www.youtube.com/shorts/abc123",
        intent="media",
        respect_robots=False,
    )


def test_media_candidate_filter_blocks_known_robots_hosts():
    assert not _is_candidate_target_url(
        "https://www.reddit.com/r/popular/",
        intent="media",
        respect_robots=True,
    )


def test_matches_domains_accepts_subdomains():
    assert _matches_domains("https://www.reddit.com/r/popular", ["reddit.com", "giphy.com"])


def test_matches_domains_rejects_unrelated_hosts():
    assert not _matches_domains("https://www.pullandbear.com/es/", ["reddit.com", "giphy.com"])


def test_is_media_like_request_when_videos_enabled():
    request = ScrapeRequest(query="boobs", include_videos=True)
    assert _is_media_like_request("generic", request)


def test_is_media_like_request_when_media_fields_requested():
    request = ScrapeRequest(query="top 10", include_videos=False, desired_fields=["video_urls", "title"])
    assert _is_media_like_request("generic", request)


def test_is_media_like_request_false_for_plain_generic():
    request = ScrapeRequest(query="company contact list", include_videos=False, desired_fields=["name", "email"])
    assert not _is_media_like_request("generic", request)


def test_is_media_like_request_false_for_non_generic_intent():
    request = ScrapeRequest(query="find home listings", include_videos=True)
    assert not _is_media_like_request("real_estate", request)


def test_seed_matches_query_for_topical_media_search():
    assert _seed_matches_query("https://example.com/dog-videos", "top dog video")


def test_seed_does_not_match_unrelated_topic_query():
    assert not _seed_matches_query("https://giphy.com/trending-gifs", "top dog video")


def test_generic_meme_media_seed_detection_for_giphy():
    assert _is_generic_meme_media_seed("https://giphy.com/trending-gifs")


def test_generic_meme_media_seed_detection_for_youtube_false():
    assert not _is_generic_meme_media_seed("https://www.youtube.com/feed/trending")


def test_candidate_matches_query_tokens_from_url():
    candidate = {"url": "https://example.com/dog-videos"}
    assert _candidate_matches_query_tokens(candidate, ["dog"])


def test_candidate_does_not_match_query_tokens_when_unrelated():
    candidate = {"url": "https://example.com/trending-memes", "title": "Trending memes"}
    assert not _candidate_matches_query_tokens(candidate, ["dog"])


def test_candidate_requires_all_tokens_for_two_token_query():
    candidate = {"url": "https://example.com/dog-videos"}
    assert not _candidate_matches_query_tokens(candidate, ["dog", "park"])


def test_candidate_matches_when_two_token_query_has_full_overlap():
    candidate = {"url": "https://example.com/dog-park-videos"}
    assert _candidate_matches_query_tokens(candidate, ["dog", "park"])
