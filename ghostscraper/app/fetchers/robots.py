from urllib.parse import urlparse

import httpx


async def robots_allows(url: str, user_agent: str = "*") -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(robots_url)
        if resp.status_code != 200:
            return True
        content = resp.text.lower()
        if "disallow: /" in content and ("user-agent: *" in content or f"user-agent: {user_agent.lower()}" in content):
            return False
    except Exception:
        return True
    return True
