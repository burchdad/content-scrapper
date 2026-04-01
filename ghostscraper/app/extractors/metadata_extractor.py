import json
from typing import Any

from bs4 import BeautifulSoup

from app.extractors.base import ExtractionResult


def extract_metadata(html: str, base_url: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, Any] = {}
    notes: list[str] = []
    images: list[str] = []
    video_urls: list[str] = []
    embed_urls: list[str] = []

    canonical = soup.find("link", attrs={"rel": "canonical"})
    if canonical and canonical.get("href"):
        data["canonical_url"] = canonical["href"]

    title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("title")
    if title:
        if title.name == "meta":
            data["title"] = title.get("content")
        else:
            data["title"] = title.get_text(strip=True)

    description = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    if description and description.get("content"):
        data["description"] = description.get("content")

    for image_tag in soup.find_all("meta", attrs={"property": "og:image"}):
        if image_tag.get("content"):
            images.append(image_tag["content"])

    for video_tag in soup.find_all("meta", attrs={"property": "og:video"}):
        if video_tag.get("content"):
            video_urls.append(video_tag["content"])

    twitter_player = soup.find("meta", attrs={"name": "twitter:player"})
    if twitter_player and twitter_player.get("content"):
        embed_urls.append(twitter_player.get("content"))

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        content = script.string or script.get_text()
        if not content:
            continue
        try:
            payload = json.loads(content)
            notes.append("json_ld_parsed")
            if isinstance(payload, list):
                candidates = payload
            else:
                candidates = [payload]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                for key in ["name", "headline", "description", "price", "address", "image"]:
                    if key in item and key not in data:
                        data[key] = item[key]
                if "image" in item:
                    if isinstance(item["image"], list):
                        images.extend(item["image"])
                    elif isinstance(item["image"], str):
                        images.append(item["image"])
                if item.get("@type") == "VideoObject":
                    content_url = item.get("contentUrl")
                    embed_url = item.get("embedUrl")
                    if isinstance(content_url, str):
                        video_urls.append(content_url)
                    if isinstance(embed_url, str):
                        embed_urls.append(embed_url)
                    if "uploadDate" in item and "published_at" not in data:
                        data["published_at"] = item["uploadDate"]
        except Exception:
            notes.append("json_ld_parse_failed")

    if video_urls:
        data["video_urls"] = list(dict.fromkeys(video_urls))
    if embed_urls:
        data["embed_urls"] = list(dict.fromkeys(embed_urls))

    return ExtractionResult(data=data, images=list(dict.fromkeys(images)), notes=notes)
