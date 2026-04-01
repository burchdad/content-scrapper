from dataclasses import dataclass
from urllib.parse import urlparse


MEDIA_HINT_TOKENS = {
    "video",
    "videos",
    "short",
    "shorts",
    "reel",
    "reels",
    "clip",
    "clips",
    "gif",
    "gifs",
    "meme",
    "memes",
    "stream",
    "trending",
}


@dataclass(frozen=True)
class SiteAgentProfile:
    agent_id: str
    domains: tuple[str, ...]
    prefer_static: bool = False
    force_dynamic: bool = False


class SiteAgentRegistry:
    def __init__(self) -> None:
        self._profiles = [
            SiteAgentProfile(
                agent_id="youtube-agent",
                domains=("youtube.com", "youtu.be"),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="tiktok-agent",
                domains=("tiktok.com",),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="instagram-agent",
                domains=("instagram.com",),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="giphy-agent",
                domains=("giphy.com",),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="tenor-agent",
                domains=("tenor.com",),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="imgur-agent",
                domains=("imgur.com",),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="tumblr-agent",
                domains=("tumblr.com",),
                prefer_static=True,
            ),
            SiteAgentProfile(
                agent_id="twitch-agent",
                domains=("twitch.tv",),
                force_dynamic=True,
            ),
            SiteAgentProfile(
                agent_id="kick-agent",
                domains=("kick.com",),
                force_dynamic=True,
            ),
            SiteAgentProfile(
                agent_id="reddit-agent",
                domains=("reddit.com",),
                prefer_static=True,
            ),
        ]
        self._default = SiteAgentProfile(agent_id="generic-web-agent", domains=())

    def resolve(self, url: str) -> SiteAgentProfile:
        host = _normalize_host(urlparse(url).netloc)
        if not host:
            return self._default
        for profile in self._profiles:
            if any(host == domain or host.endswith(f".{domain}") for domain in profile.domains):
                return profile
        return self._default

    def supports_candidate(self, url: str, intent: str) -> bool:
        if intent != "media":
            return True

        profile = self.resolve(url)
        if profile.agent_id != self._default.agent_id:
            return True

        normalized_url = url.lower()
        return any(token in normalized_url for token in MEDIA_HINT_TOKENS)


def _normalize_host(host: str) -> str:
    value = host.strip().lower()
    if value.startswith("www."):
        return value[4:]
    return value
