from app.services.site_agent_registry import SiteAgentRegistry


def test_resolve_known_domain_uses_specific_agent():
    registry = SiteAgentRegistry()

    profile = registry.resolve("https://www.youtube.com/watch?v=abc123")

    assert profile.agent_id == "youtube-agent"
    assert profile.prefer_static


def test_resolve_unknown_domain_uses_generic_agent():
    registry = SiteAgentRegistry()

    profile = registry.resolve("https://example.com/page")

    assert profile.agent_id == "generic-web-agent"


def test_supports_candidate_allows_known_media_domains():
    registry = SiteAgentRegistry()

    assert registry.supports_candidate("https://tenor.com/search/dog-gif", intent="media")


def test_supports_candidate_rejects_unhinted_generic_for_media():
    registry = SiteAgentRegistry()

    assert not registry.supports_candidate("https://app.tophat.com/register", intent="media")


def test_supports_candidate_allows_generic_with_media_hint():
    registry = SiteAgentRegistry()

    assert registry.supports_candidate("https://example.com/dog-video-compilation", intent="media")
