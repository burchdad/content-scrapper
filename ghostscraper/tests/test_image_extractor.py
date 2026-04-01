from pathlib import Path

from app.extractors.image_extractor import _parse_srcset, extract_images


def test_parse_srcset():
    srcset = "https://x/a.jpg 320w, https://x/b.jpg 640w"
    parsed = _parse_srcset(srcset)
    assert parsed == ["https://x/a.jpg", "https://x/b.jpg"]


def test_extract_images_filters_junk():
    html = Path("tests/fixtures/contact_page.html").read_text(encoding="utf-8")
    images = extract_images(html, "https://example.com")

    assert "https://example.com/images/property-front.jpg" in images
    assert all("logo" not in i for i in images)
