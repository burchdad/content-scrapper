from pathlib import Path

from app.extractors.media_extractor import extract_media_assets
from app.extractors.metadata_extractor import extract_metadata


def test_extract_metadata_includes_video_and_embed_fields():
    html = Path("tests/fixtures/media_page.html").read_text(encoding="utf-8")

    result = extract_metadata(html, "https://media.example.com/gallery")

    assert result.data["canonical_url"] == "https://media.example.com/gallery"
    assert "https://media.example.com/launch.mp4" in result.data["video_urls"]
    assert "https://www.youtube.com/embed/abc123" in result.data["embed_urls"]
    assert result.data["published_at"] == "2026-03-20T10:00:00Z"


def test_media_extractor_collects_video_audio_social_and_posters():
    html = Path("tests/fixtures/media_page.html").read_text(encoding="utf-8")

    result = extract_media_assets(html, "https://media.example.com/gallery")

    assert "https://media.example.com/video/trailer.mp4" in result.data["video_urls"]
    assert "https://media.example.com/video/alt.webm" in result.data["video_urls"]
    assert "https://media.example.com/audio/theme.mp3" in result.data["audio_urls"]
    assert "https://www.youtube.com/embed/abc123" in result.data["embed_urls"]
    assert "https://instagram.com/ghostbrand" in result.data["social_links"]
    assert "#campaign" in result.data["hashtags"]
    assert "https://media.example.com/video/poster.jpg" in result.images
