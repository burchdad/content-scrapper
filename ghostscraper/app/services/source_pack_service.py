from app.models.source_packs import ResolvedSourcePacks, SourcePack


class SourcePackService:
    def __init__(self) -> None:
        self._packs = [
            _pack(
                pack_id="short-video-viral",
                name="Short Video Viral",
                category="video",
                description="Short-form video and viral clip sources across public trend and discovery pages.",
                domains=["tiktok.com", "youtube.com", "instagram.com", "snapchat.com", "triller.co", "likee.video"],
                seed_urls=[
                    "https://www.youtube.com/feed/trending",
                    "https://www.youtube.com/shorts",
                    "https://www.instagram.com/explore/",
                    "https://www.snapchat.com/discover",
                    "https://triller.co/",
                ],
                query_terms=["trending videos", "viral clips", "shorts", "reels"],
                intent_terms={
                    "media": ["fyp", "trend challenge", "viral edit", "creator clips"],
                    "articles": ["creator trend report", "platform trend recap"],
                },
                intent_query_templates={
                    "media": [
                        "{query} trend challenge this week",
                        "{query} viral short video",
                        "site:youtube.com shorts {query} compilation",
                    ],
                },
            ),
            _pack(
                pack_id="meme-gif-culture",
                name="Meme and GIF Culture",
                category="memes",
                description="Public meme, GIF, reaction-image, and internet-culture aggregators.",
                domains=["giphy.com", "tenor.com", "knowyourmeme.com", "imgur.com", "9gag.com"],
                seed_urls=[
                    "https://giphy.com/trending-gifs",
                    "https://tenor.com/search/trending-gifs",
                    "https://knowyourmeme.com/",
                    "https://imgur.com/hot",
                    "https://9gag.com/trending",
                ],
                query_terms=["memes", "gifs", "reaction images", "internet jokes"],
                intent_terms={
                    "media": ["reaction gif", "template meme", "viral image macro"],
                    "articles": ["meme explainer", "internet culture trend"],
                },
                intent_query_templates={
                    "media": [
                        "{query} meme template",
                        "{query} reaction gif trending",
                    ],
                },
            ),
            _pack(
                pack_id="social-discussion",
                name="Social Discussion",
                category="community",
                description="High-signal public communities and discussion hubs for emerging topics and links.",
                domains=["reddit.com", "news.ycombinator.com", "tumblr.com", "lemmy.world", "producthunt.com"],
                seed_urls=[
                    "https://www.reddit.com/r/popular/",
                    "https://news.ycombinator.com/",
                    "https://www.tumblr.com/explore/trending",
                    "https://lemmy.world/",
                    "https://www.producthunt.com/",
                ],
                query_terms=["community buzz", "discussion threads", "what people are sharing", "popular posts"],
                intent_terms={
                    "articles": ["discussion roundup", "community reaction"],
                    "products": ["user recommendations", "best tools discussion"],
                    "media": ["what people are watching", "viral discussion thread"],
                    "contacts": ["founder ama", "team contact thread"],
                },
                intent_query_templates={
                    "products": ["{query} recommendations reddit", "{query} review thread"],
                    "media": ["{query} reddit trend thread", "{query} community buzz"],
                },
            ),
            _pack(
                pack_id="livestream-clips",
                name="Livestream Clips",
                category="video",
                description="Public live-stream clip, VOD, and highlight discovery sources.",
                domains=["twitch.tv", "kick.com", "streamable.com", "medal.tv"],
                seed_urls=[
                    "https://www.twitch.tv/directory",
                    "https://kick.com/browse",
                    "https://streamable.com/",
                    "https://medal.tv/clips",
                ],
                query_terms=["stream highlights", "clips", "live reactions", "gaming moments"],
                intent_terms={
                    "media": ["vod clips", "best moments", "stream highlights"],
                    "articles": ["livestream recap", "streaming highlights roundup"],
                },
                intent_query_templates={
                    "media": ["{query} livestream clip", "{query} highlight reel"],
                },
            ),
            _pack(
                pack_id="creator-portfolios",
                name="Creator Portfolios",
                category="creators",
                description="Visual creator portfolios, design galleries, and artist showcase sources.",
                domains=["behance.net", "dribbble.com", "deviantart.com", "artstation.com"],
                seed_urls=[
                    "https://www.behance.net/galleries",
                    "https://dribbble.com/shots/popular",
                    "https://www.deviantart.com/daily-deviations",
                    "https://www.artstation.com/?sort_by=trending",
                ],
                query_terms=["visual trends", "design inspiration", "art trends", "creator showcase"],
                intent_terms={
                    "media": ["art direction", "visual concept", "portfolio highlights"],
                    "contacts": ["creative director", "portfolio contact"],
                    "articles": ["design trend report", "creative showcase"],
                },
                intent_query_templates={
                    "media": ["{query} creative showcase", "{query} portfolio project"],
                    "contacts": ["{query} art director contact"],
                },
            ),
            _pack(
                pack_id="photo-sharing",
                name="Photo Sharing",
                category="images",
                description="Public photography and image discovery sources for visual trend collection.",
                domains=["flickr.com", "500px.com", "unsplash.com", "pexels.com"],
                seed_urls=[
                    "https://www.flickr.com/explore",
                    "https://500px.com/popular",
                    "https://unsplash.com/photos",
                    "https://www.pexels.com/discover/",
                ],
                query_terms=["photo trends", "popular photos", "visual themes", "top images"],
                intent_terms={
                    "media": ["photo series", "image collection", "editorial photography"],
                    "articles": ["photo essay", "visual story"],
                },
                intent_query_templates={
                    "media": ["{query} image gallery", "{query} photo collection"],
                },
            ),
            _pack(
                pack_id="music-scenes",
                name="Music Scenes",
                category="culture",
                description="Music charts, discovery, and fan-discussion sources for artist and track momentum.",
                domains=["soundcloud.com", "bandcamp.com", "billboard.com", "genius.com", "audiomack.com"],
                seed_urls=[
                    "https://soundcloud.com/charts/top",
                    "https://bandcamp.com/discover",
                    "https://www.billboard.com/charts/",
                    "https://genius.com/",
                    "https://audiomack.com/charts",
                ],
                query_terms=["music trends", "viral songs", "artist buzz", "charting tracks"],
                intent_terms={
                    "media": ["music video clips", "fan edit", "live performance"],
                    "articles": ["chart report", "music scene recap"],
                    "products": ["merch drop", "vinyl release"],
                },
                intent_query_templates={
                    "media": ["{query} live performance clip", "{query} viral song edit"],
                    "products": ["{query} merch drop"],
                },
            ),
            _pack(
                pack_id="gaming-culture",
                name="Gaming Culture",
                category="culture",
                description="Gaming culture, esports, and clip-heavy public sources.",
                domains=["ign.com", "polygon.com", "gamespot.com", "dexerto.com", "steamcommunity.com"],
                seed_urls=[
                    "https://www.ign.com/",
                    "https://www.polygon.com/",
                    "https://www.gamespot.com/news/",
                    "https://www.dexerto.com/",
                    "https://steamcommunity.com/app/730/screenshots/",
                ],
                query_terms=["gaming trends", "esports clips", "viral gameplay", "gaming memes"],
                intent_terms={
                    "media": ["clip compilation", "gameplay edit", "patch reaction"],
                    "articles": ["meta breakdown", "esports recap"],
                    "products": ["game sale", "hardware drop"],
                },
                intent_query_templates={
                    "media": ["{query} gameplay clip", "{query} esports highlight"],
                    "products": ["{query} best gaming hardware"],
                },
            ),
            _pack(
                pack_id="fashion-resale",
                name="Fashion Resale",
                category="commerce",
                description="Public resale and streetwear marketplaces with strong image-driven listings.",
                domains=["depop.com", "poshmark.com", "grailed.com", "vestiairecollective.com"],
                seed_urls=[
                    "https://www.depop.com/",
                    "https://poshmark.com/",
                    "https://www.grailed.com/",
                    "https://www.vestiairecollective.com/",
                ],
                query_terms=["fashion trends", "streetwear drops", "resale listings", "popular styles"],
                intent_terms={
                    "products": ["most watched listing", "designer resale", "streetwear drop"],
                    "media": ["outfit inspo", "lookbook"],
                    "pricing": ["resale price", "market value"],
                },
                intent_query_templates={
                    "products": ["{query} streetwear listing", "{query} grailed listing"],
                    "pricing": ["{query} resale price"],
                },
            ),
            _pack(
                pack_id="marketplaces-handmade",
                name="Marketplaces and Handmade",
                category="commerce",
                description="Public handmade and marketplace sources for product trend discovery.",
                domains=["etsy.com", "ebay.com", "mercari.com"],
                seed_urls=[
                    "https://www.etsy.com/",
                    "https://www.ebay.com/deals",
                    "https://www.mercari.com/",
                ],
                query_terms=["top sellers", "popular products", "gift trends", "handmade trends"],
                intent_terms={
                    "products": ["best seller", "customer favorite", "top reviewed"],
                    "pricing": ["price trend", "sale price", "market price"],
                    "articles": ["gift guide", "shopping roundup"],
                },
                intent_query_templates={
                    "products": ["{query} best seller", "{query} etsy listing"],
                    "pricing": ["{query} price trend"],
                },
            ),
            _pack(
                pack_id="startup-launches",
                name="Startup Launches",
                category="launches",
                description="Launch surfaces and startup communities for new-product and founder momentum.",
                domains=["producthunt.com", "indiehackers.com", "betalist.com", "news.ycombinator.com"],
                seed_urls=[
                    "https://www.producthunt.com/",
                    "https://www.indiehackers.com/",
                    "https://betalist.com/",
                    "https://news.ycombinator.com/show",
                ],
                query_terms=["new launches", "startup buzz", "hot tools", "product launches"],
                intent_terms={
                    "products": ["new app launch", "tool launch", "startup launch"],
                    "contacts": ["founder contact", "launch team"],
                    "articles": ["launch roundup", "startup spotlight"],
                },
                intent_query_templates={
                    "products": ["{query} product hunt", "{query} startup launch"],
                    "contacts": ["{query} founder email"],
                },
            ),
            _pack(
                pack_id="dealwatch",
                name="Deal Watch",
                category="commerce",
                description="Deal communities and discount aggregators for fast-moving product attention.",
                domains=["slickdeals.net", "dealnews.com", "meh.com", "woot.com"],
                seed_urls=[
                    "https://slickdeals.net/",
                    "https://www.dealnews.com/",
                    "https://meh.com/",
                    "https://www.woot.com/",
                ],
                query_terms=["hot deals", "trending deals", "popular discounts", "deal alerts"],
                intent_terms={
                    "products": ["lowest price", "best deal", "discount alert"],
                    "pricing": ["deal price", "coupon", "sale alert"],
                },
                intent_query_templates={
                    "products": ["{query} hot deal", "{query} slickdeals"],
                    "pricing": ["{query} discount price"],
                },
            ),
            _pack(
                pack_id="news-wires",
                name="News Wires",
                category="news",
                description="High-velocity public news sources for breaking developments and emerging topics.",
                domains=["reuters.com", "apnews.com", "bbc.com", "theguardian.com", "npr.org"],
                seed_urls=[
                    "https://www.reuters.com/world/",
                    "https://apnews.com/",
                    "https://www.bbc.com/news",
                    "https://www.theguardian.com/international",
                    "https://www.npr.org/sections/news/",
                ],
                query_terms=["breaking news", "developing story", "latest headlines", "emerging topic"],
                intent_terms={
                    "articles": ["analysis", "latest coverage", "news explainer"],
                    "media": ["news footage", "field video"],
                    "contacts": ["press office", "newsroom contact"],
                },
                intent_query_templates={
                    "articles": ["{query} developing story", "{query} latest coverage"],
                    "contacts": ["{query} newsroom contact"],
                },
            ),
            _pack(
                pack_id="events-nightlife",
                name="Events and Nightlife",
                category="events",
                description="Public event-discovery sources for concerts, nightlife, festivals, and meetups.",
                domains=["eventbrite.com", "meetup.com", "ra.co", "songkick.com", "bandsintown.com"],
                seed_urls=[
                    "https://www.eventbrite.com/d/online/all-events/",
                    "https://www.meetup.com/find/",
                    "https://ra.co/events/us/newyork",
                    "https://www.songkick.com/metro-areas/7644-us-new-york",
                    "https://www.bandsintown.com/",
                ],
                query_terms=["events this week", "nightlife trends", "festival buzz", "concert buzz"],
                intent_terms={
                    "articles": ["event guide", "festival roundup"],
                    "media": ["aftermovie", "promo flyer", "event photos"],
                    "products": ["tickets", "vip package"],
                },
                intent_query_templates={
                    "media": ["{query} event photos", "{query} concert clip"],
                    "products": ["{query} tickets"],
                },
            ),
            _pack(
                pack_id="local-classifieds",
                name="Local Classifieds",
                category="classifieds",
                description="Public classifieds and local listing surfaces for broad public-market scanning.",
                domains=["craigslist.org", "gumtree.com", "kijiji.ca"],
                seed_urls=[
                    "https://www.craigslist.org/about/sites",
                    "https://www.gumtree.com/",
                    "https://www.kijiji.ca/",
                ],
                query_terms=["local listings", "classified ads", "public postings", "regional ads"],
                intent_terms={
                    "real_estate": ["for rent", "for sale by owner", "apartment listing"],
                    "products": ["used item listing", "local seller"],
                    "pricing": ["asking price", "local market price"],
                    "contacts": ["seller phone", "poster email"],
                },
                intent_query_templates={
                    "real_estate": ["{query} apartment listing", "{query} house for rent"],
                    "products": ["{query} used listing"],
                    "contacts": ["{query} seller phone"],
                },
            ),
        ]
        self._pack_map = {pack.pack_id: pack for pack in self._packs}

    def default_pack_ids_for_intent(self, intent: str | None) -> list[str]:
        if intent == "media":
            return [
                "short-video-viral",
                "meme-gif-culture",
                "social-discussion",
                "livestream-clips",
                "photo-sharing",
            ]
        if intent == "products":
            return ["marketplaces-handmade", "dealwatch", "startup-launches"]
        if intent == "real_estate":
            return ["local-classifieds"]
        if intent == "articles":
            return ["news-wires", "social-discussion"]
        if intent == "contacts":
            return ["social-discussion", "startup-launches"]
        return []

    def list_packs(self, category: str | None = None) -> list[SourcePack]:
        if not category:
            return list(self._packs)
        return [pack for pack in self._packs if pack.category == category]

    def get_pack(self, pack_id: str) -> SourcePack | None:
        return self._pack_map.get(pack_id)

    def unknown_pack_ids(self, pack_ids: list[str] | None) -> list[str]:
        if not pack_ids:
            return []
        return [pack_id for pack_id in pack_ids if pack_id not in self._pack_map]

    def resolve(self, pack_ids: list[str] | None, intent: str | None = None) -> ResolvedSourcePacks:
        resolved_ids: list[str] = []
        categories: list[str] = []
        domains: list[str] = []
        domain_categories: dict[str, list[str]] = {}
        seed_urls: list[str] = []
        query_terms: list[str] = []
        query_templates: list[str] = []
        for pack_id in pack_ids or []:
            pack = self._pack_map.get(pack_id)
            if not pack:
                continue
            resolved_ids.append(pack.pack_id)
            categories.append(pack.category)
            domains.extend(pack.domains)
            for domain in pack.domains:
                existing = domain_categories.get(domain, [])
                existing.append(pack.category)
                domain_categories[domain] = _dedupe(existing)
            seed_urls.extend(pack.seed_urls)
            query_terms.extend(pack.query_terms)
            if intent:
                query_terms.extend(pack.intent_terms.get(intent, []))
                query_templates.extend(pack.intent_query_templates.get(intent, []))
        return ResolvedSourcePacks(
            pack_ids=_dedupe(resolved_ids),
            categories=_dedupe(categories),
            domains=_dedupe(domains),
            domain_categories={key: _dedupe(value) for key, value in domain_categories.items()},
            seed_urls=_dedupe(seed_urls),
            query_terms=_dedupe(query_terms),
            query_templates=_dedupe(query_templates),
        )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _pack(
    pack_id: str,
    name: str,
    category: str,
    description: str,
    domains: list[str],
    seed_urls: list[str],
    query_terms: list[str],
    intent_terms: dict[str, list[str]] | None = None,
    intent_query_templates: dict[str, list[str]] | None = None,
) -> SourcePack:
    return SourcePack(
        pack_id=pack_id,
        name=name,
        category=category,
        description=description,
        domains=domains,
        seed_urls=seed_urls,
        query_terms=query_terms,
        intent_terms=intent_terms or {},
        intent_query_templates=intent_query_templates or {},
    )