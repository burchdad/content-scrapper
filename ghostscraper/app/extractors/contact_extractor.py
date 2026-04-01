import re

from bs4 import BeautifulSoup

from app.extractors.base import ExtractionResult

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}")


def extract_contacts(html: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    emails = set(EMAIL_RE.findall(text))
    phones = set(PHONE_RE.findall(text))

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("mailto:"):
            emails.add(href.replace("mailto:", "").split("?")[0])
        if href.startswith("tel:"):
            phones.add(href.replace("tel:", ""))

    business_name = None
    title_tag = soup.find("title")
    if title_tag:
        business_name = title_tag.get_text(strip=True)

    social_links = [
        a["href"]
        for a in soup.find_all("a", href=True)
        if any(d in a["href"].lower() for d in ["linkedin.com", "facebook.com", "instagram.com"])
    ]

    return ExtractionResult(
        data={
            "business_name": business_name,
            "email": sorted(emails)[:5],
            "phone": sorted(phones)[:5],
            "social_links": sorted(set(social_links)),
        },
        notes=["contact_extraction_completed"],
    )
