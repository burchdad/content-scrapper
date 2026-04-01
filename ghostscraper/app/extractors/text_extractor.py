from bs4 import BeautifulSoup


def extract_text(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:20]
    body_text = soup.get_text(" ", strip=True)
    return {
        "headings": " | ".join(headings),
        "text": body_text[:15000],
    }
