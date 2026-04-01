from pathlib import Path

from app.extractors.metadata_extractor import extract_metadata


def test_extract_metadata_from_json_ld_and_og():
    html = Path("tests/fixtures/contact_page.html").read_text(encoding="utf-8")

    result = extract_metadata(html, "https://example.com/contact")

    assert result.data["canonical_url"] == "https://example.com/contact"
    assert result.data["title"] == "Acme Roofing Contact"
    assert "https://example.com/images/hero.jpg" in result.images
    assert "json_ld_parsed" in result.notes
