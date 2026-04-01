from app.services.source_pack_service import SourcePackService


def test_source_pack_service_resolves_intent_specific_terms_and_templates():
    service = SourcePackService()

    resolved = service.resolve(["short-video-viral", "local-classifieds"], intent="media")

    assert "fyp" in resolved.query_terms
    assert any("{query} trend challenge this week" == template for template in resolved.query_templates)
    assert "for rent" not in resolved.query_terms


def test_source_pack_service_resolves_real_estate_terms_for_classifieds():
    service = SourcePackService()

    resolved = service.resolve(["local-classifieds"], intent="real_estate")

    assert "for rent" in resolved.query_terms
    assert any("apartment listing" in template for template in resolved.query_templates)


def test_source_pack_service_default_media_packs_are_populated():
    service = SourcePackService()

    defaults = service.default_pack_ids_for_intent("media")

    assert "short-video-viral" in defaults
    assert "meme-gif-culture" in defaults
    assert "social-discussion" in defaults