import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.extractors.base import ExtractionResult

SOCIAL_DOMAINS = [
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "pinterest.com",
    "vimeo.com",
]

HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_]{2,50})")


def _normalize_url(base_url: str, value: str | None) -> str | None:
    if not value:
        return None
    url = urljoin(base_url, value.strip())
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return None
    return url


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for url in urls:
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        results.append(url)
    return results


def extract_media_assets(
    html: str,
    base_url: str,
    dynamic_video_candidates: list[str] | None = None,
) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    video_urls: list[str] = []
    audio_urls: list[str] = []
    embed_urls: list[str] = []
    social_links: list[str] = []
    poster_images: list[str] = []

    for video in soup.find_all("video"):
        src = _normalize_url(base_url, video.get("src"))
        if src:
            video_urls.append(src)
        poster = _normalize_url(base_url, video.get("poster"))
        if poster:
            poster_images.append(poster)
        for source in video.find_all("source"):
            source_url = _normalize_url(base_url, source.get("src"))
            if source_url:
                video_urls.append(source_url)

    for audio in soup.find_all("audio"):
        src = _normalize_url(base_url, audio.get("src"))
        if src:
            audio_urls.append(src)
        for source in audio.find_all("source"):
            source_url = _normalize_url(base_url, source.get("src"))
            if source_url:
                audio_urls.append(source_url)

    for iframe in soup.find_all("iframe"):
        src = _normalize_url(base_url, iframe.get("src"))
        if not src:
            continue
        embed_urls.append(src)
        if any(domain in src.lower() for domain in SOCIAL_DOMAINS):
            social_links.append(src)

    for anchor in soup.find_all("a", href=True):
        href = _normalize_url(base_url, anchor.get("href"))
        if href and any(domain in href.lower() for domain in SOCIAL_DOMAINS):
            social_links.append(href)

    if dynamic_video_candidates:
        for candidate in dynamic_video_candidates:
            normalized = _normalize_url(base_url, candidate)
            if normalized:
                video_urls.append(normalized)

    hashtags = sorted({match.group(0) for match in HASHTAG_RE.finditer(soup.get_text(" ", strip=True))})

    data = {
        "video_urls": _dedupe(video_urls),
        "audio_urls": _dedupe(audio_urls),
        "embed_urls": _dedupe(embed_urls),
        "social_links": _dedupe(social_links),
        "hashtags": hashtags,
    }
    data = {key: value for key, value in data.items() if value}

    notes = []
    if data.get("video_urls"):
        notes.append("media_video_extraction_completed")
    if data.get("social_links") or data.get("embed_urls"):
        notes.append("media_social_extraction_completed")

    return ExtractionResult(data=data, images=_dedupe(poster_images), notes=notes)
