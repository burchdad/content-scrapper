import re

from bs4 import BeautifulSoup

from app.extractors.base import ExtractionResult


def _extract_number(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def extract_listing(html: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    price = _extract_number(text, r"\$\s*([\d,]+(?:\.\d+)?)")
    beds = _extract_number(text, r"([\d.]+)\s*beds?")
    baths = _extract_number(text, r"([\d.]+)\s*baths?")
    sqft = _extract_number(text, r"([\d,]+)\s*sq\s*ft")

    address = None
    for cand in soup.find_all(["h1", "h2", "p", "span"]):
        t = cand.get_text(" ", strip=True)
        if any(tok in t.lower() for tok in ["street", "st", "avenue", "ave", "road", "rd", "drive", "dr"]):
            address = t
            break

    return ExtractionResult(
        data={
            "address": address,
            "price": price,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "description": text[:1000],
        },
        notes=["listing_extraction_completed"],
    )
