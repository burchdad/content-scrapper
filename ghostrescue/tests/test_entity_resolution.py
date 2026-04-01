import pytest

from app.models.schemas import EntityIngestPayload
from app.services.entity_resolution.fuzzy_matcher import FuzzyMatcher
from app.services.entity_resolution.resolver import EntityResolver


class TestFuzzyMatcher:
    def test_exact_match(self):
        matcher = FuzzyMatcher(threshold=85.0)
        candidates = [("entity-001", "Jane Doe", [])]
        results = matcher.match("Jane Doe", candidates)
        assert results
        assert results[0].entity_id == "entity-001"
        assert results[0].score >= 95.0

    def test_alias_match(self):
        matcher = FuzzyMatcher(threshold=85.0)
        candidates = [("entity-002", "Maria Garcia", ["Maria G", "MG_online"])]
        results = matcher.match("Maria G", candidates)
        assert results
        assert results[0].matched_alias == "Maria G"

    def test_no_match_below_threshold(self):
        matcher = FuzzyMatcher(threshold=85.0)
        candidates = [("entity-003", "Robert Johnson", [])]
        results = matcher.match("completely different xyz person", candidates)
        assert not results

    def test_case_insensitive(self):
        matcher = FuzzyMatcher(threshold=85.0)
        candidates = [("entity-004", "Alice Smith", [])]
        results = matcher.match("ALICE SMITH", candidates)
        assert results
        assert results[0].score >= 95.0

    def test_word_order_invariant(self):
        matcher = FuzzyMatcher(threshold=85.0)
        candidates = [("entity-005", "John Michael Brown", [])]
        results = matcher.match("Brown John Michael", candidates)
        # token_sort_ratio handles reordered words
        assert results

    def test_partial_abbreviation(self):
        matcher = FuzzyMatcher(threshold=80.0)
        candidates = [("entity-006", "Ana Lucia Perez", [])]
        results = matcher.match("Ana L. Perez", candidates)
        assert results


@pytest.mark.asyncio
async def test_resolve_creates_new_entity(db_session):
    resolver = EntityResolver(db_session)
    payload = EntityIngestPayload(
        canonical_name="Maria Torres",
        entity_type="person",
        aliases=["Maria T"],
        source_name="test_source",
    )
    result = await resolver.resolve(payload)
    assert result.action == "created"
    assert result.entity_id.startswith("entity-")
    assert result.canonical_name == "Maria Torres"
    assert "intelligence leads" in result.disclaimer.lower()


@pytest.mark.asyncio
async def test_resolve_deduplicates_same_entity(db_session):
    resolver = EntityResolver(db_session)
    first = await resolver.resolve(
        EntityIngestPayload(canonical_name="Carlos Rivera Mendez", source_name="source_a")
    )
    assert first.action == "created"

    # Exact same name → should match at threshold
    second = await resolver.resolve(
        EntityIngestPayload(canonical_name="Carlos Rivera Mendez", source_name="source_b")
    )
    assert second.entity_id == first.entity_id
    assert second.action in ("merged", "linked")


@pytest.mark.asyncio
async def test_resolve_distinct_names_create_separate_entities(db_session):
    resolver = EntityResolver(db_session)
    a = await resolver.resolve(EntityIngestPayload(canonical_name="Aisha Okonkwo", source_name="s1"))
    b = await resolver.resolve(EntityIngestPayload(canonical_name="Svetlana Petrov", source_name="s2"))
    assert a.entity_id != b.entity_id
    assert a.action == "created"
    assert b.action == "created"


@pytest.mark.asyncio
async def test_resolve_absorbs_aliases(db_session):
    resolver = EntityResolver(db_session)
    result = await resolver.resolve(
        EntityIngestPayload(
            canonical_name="John Doe",
            aliases=["JD", "Johnny"],
            source_name="test",
        )
    )
    assert result.action == "created"
    assert result.entity_id.startswith("entity-")
