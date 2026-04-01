from app.intelligence.trafficking_scorer import score_record_risk
from app.models.records import ScrapedRecord


def test_trafficking_scorer_flags_multiple_signals():
    record = ScrapedRecord(
        source_url="https://example.com/listing",
        canonical_url=None,
        record_type="media",
        title="New in town escort",
        data={
            "description": "escort service, dm on telegram, hotel room available",
        },
        images=[],
        videos=[],
        downloaded_images=[],
        confidence=0.5,
        extraction_notes=[],
    )

    score, signals = score_record_risk(record)

    assert score > 0.4
    names = {signal.name for signal in signals}
    assert "commercial_sex_terms" in names
    assert "contact_off_platform" in names
