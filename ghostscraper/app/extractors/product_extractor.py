import re

from bs4 import BeautifulSoup

from app.extractors.base import ExtractionResult


def extract_product(html: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.find("h1") or soup.find("title"))
    price_match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", soup.get_text(" ", strip=True))

    return ExtractionResult(
        data={
            "product_name": title.get_text(strip=True) if title else None,
            "price": float(price_match.group(1).replace(",", "")) if price_match else None,
            "availability": "in_stock" if "in stock" in soup.get_text(" ", strip=True).lower() else None,
        },
        notes=["product_extraction_completed"],
    )
