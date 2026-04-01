from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.crawler.url_frontier import FrontierItem


def discover_next_links(html: str, base_url: str, depth: int) -> list[FrontierItem]:
    soup = BeautifulSoup(html, "lxml")
    links: list[FrontierItem] = []

    rel_next = soup.find("a", attrs={"rel": "next"})
    if rel_next and rel_next.get("href"):
        links.append(FrontierItem(url=rel_next["href"], depth=depth + 1, parent=base_url))

    for anchor in soup.find_all("a"):
        text = (anchor.get_text(" ", strip=True) or "").lower()
        href = anchor.get("href")
        if href and any(t in text for t in ["next", "more", "load more"]):
            links.append(FrontierItem(url=href, depth=depth + 1, parent=base_url))

    parsed = urlparse(base_url)
    q = parse_qs(parsed.query)
    if "page" in q:
        try:
            current = int(q["page"][0])
            q["page"] = [str(current + 1)]
            new_url = urlunparse(parsed._replace(query=urlencode(q, doseq=True)))
            links.append(FrontierItem(url=new_url, depth=depth + 1, parent=base_url))
        except ValueError:
            pass

    dedup = {l.url: l for l in links}
    return list(dedup.values())
