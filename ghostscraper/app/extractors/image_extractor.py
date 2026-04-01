from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

JUNK_HINTS = ["logo", "icon", "sprite", "avatar", "placeholder"]


def _parse_srcset(srcset: str) -> list[str]:
    urls: list[str] = []
    for part in srcset.split(","):
        url = part.strip().split(" ")[0]
        if url:
            urls.append(url)
    return urls


def _is_probable_content_image(url: str, alt_text: str = "") -> bool:
    joined = f"{url} {alt_text}".lower()
    return not any(h in joined for h in JUNK_HINTS)


def extract_images(html: str, base_url: str, dynamic_candidates: list[str] | None = None) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []

    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        for attr in ["src", "data-src", "data-lazy-src", "currentSrc"]:
            value = img.get(attr)
            if value:
                full = urljoin(base_url, value)
                if _is_probable_content_image(full, alt):
                    candidates.append(full)
        srcset = img.get("srcset")
        if srcset:
            for url in _parse_srcset(srcset):
                full = urljoin(base_url, url)
                if _is_probable_content_image(full, alt):
                    candidates.append(full)

    for tag in soup.find_all(style=True):
        style = tag.get("style", "")
        if "background-image" in style and "url(" in style:
            frag = style.split("url(", 1)[1].split(")", 1)[0].strip("'\"")
            full = urljoin(base_url, frag)
            if _is_probable_content_image(full):
                candidates.append(full)

    if dynamic_candidates:
        for c in dynamic_candidates:
            full = urljoin(base_url, c)
            if _is_probable_content_image(full):
                candidates.append(full)

    normalized = []
    seen: set[str] = set()
    for url in candidates:
        if url.startswith("data:"):
            continue
        parsed = urlparse(url)
        if not parsed.scheme.startswith("http"):
            continue
        key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(url)

    return normalized
