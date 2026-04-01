import logging
from time import perf_counter
from urllib.parse import urljoin, urlparse

from app.crawler.link_filter import is_allowed
from app.crawler.paginator import discover_next_links
from app.crawler.url_frontier import URLFrontier
from app.discovery.candidate_ranker import rank_candidates
from app.discovery.query_builder import build_queries
from app.discovery.search_provider import NullSearchProvider, SearchProvider
from app.extractors.contact_extractor import extract_contacts
from app.extractors.image_extractor import extract_images
from app.extractors.listing_extractor import extract_listing
from app.extractors.media_extractor import extract_media_assets
from app.extractors.metadata_extractor import extract_metadata
from app.extractors.product_extractor import extract_product
from app.fetchers.dynamic_fetcher import DynamicFetcher
from app.fetchers.robots import robots_allows
from app.fetchers.static_fetcher import StaticFetcher
from app.intelligence.deduper import Deduper
from app.intelligence.scorer import ConfidenceScorer
from app.models.fetch import BrowserFetchOptions
from app.models.records import ScrapedRecord
from app.models.requests import ScrapeRequest
from app.models.responses import JobDiagnostics, JobWarning, ScrapeResponse
from app.outputs.image_downloader import download_record_images
from app.outputs.normalizer import normalize_records
from app.planner.planner import Planner
from app.services.job_service import create_job_id
from app.services.site_agent_registry import SiteAgentRegistry
from app.services.source_pack_service import SourcePackService

logger = logging.getLogger(__name__)

SEARCH_RESULT_HOSTS = {
    "duckduckgo.com",
    "www.bing.com",
    "bing.com",
    "search.yahoo.com",
    "video.search.yahoo.com",
    "www.google.com",
}

KNOWN_MEDIA_DISCOVERY_HOSTS = {
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "reddit.com",
    "giphy.com",
    "tenor.com",
    "imgur.com",
    "9gag.com",
    "tumblr.com",
    "twitch.tv",
    "kick.com",
}

LOW_SIGNAL_MEDIA_HOSTS = {
    "merriam-webster.com",
    "collinsdictionary.com",
    "dictionary.com",
    "thefreedictionary.com",
    "wordreference.com",
    "vocabulary.com",
    "dictionary.cambridge.org",
}

ROBOTS_BLOCKED_MEDIA_HOSTS = {
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "snapchat.com",
    "reddit.com",
}

GENERIC_MEME_MEDIA_HOSTS = {
    "giphy.com",
    "tenor.com",
    "knowyourmeme.com",
    "9gag.com",
    "imgur.com",
}


class ScrapeOrchestrator:
    def __init__(
        self,
        planner: Planner | None = None,
        search_provider: SearchProvider | None = None,
        static_fetcher: StaticFetcher | None = None,
        dynamic_fetcher: DynamicFetcher | None = None,
        source_pack_service: SourcePackService | None = None,
        site_agent_registry: SiteAgentRegistry | None = None,
        storage_root: str = "./storage",
    ) -> None:
        self.planner = planner or Planner()
        self.search_provider = search_provider or NullSearchProvider()
        self.static_fetcher = static_fetcher or StaticFetcher()
        self.dynamic_fetcher = dynamic_fetcher or DynamicFetcher()
        self.source_pack_service = source_pack_service or SourcePackService()
        self.site_agent_registry = site_agent_registry or SiteAgentRegistry()
        self.storage_root = storage_root

    async def run_scrape_job(self, request: ScrapeRequest, job_id: str | None = None) -> ScrapeResponse:
        started = perf_counter()
        job_id = job_id or create_job_id()
        warnings: list[JobWarning] = []
        deduper = Deduper()
        scorer = ConfidenceScorer()

        logger.info("job.started", extra={"job_id": job_id, "query": request.query})

        plan = self.planner.build_plan(request)
        logger.info("planner.completed", extra={"job_id": job_id, "strategy": plan.strategy})
        media_like = _is_media_like_request(plan.intent, request)
        query_tokens = _query_focus_tokens(request.query) if media_like else []
        selected_pack_ids = request.source_pack_ids or self.source_pack_service.default_pack_ids_for_intent(plan.intent)
        if not selected_pack_ids and media_like:
            selected_pack_ids = self.source_pack_service.default_pack_ids_for_intent("media")
        source_packs = self.source_pack_service.resolve(selected_pack_ids, intent=plan.intent)

        target_urls = plan.target_urls
        if not target_urls and plan.strategy in {"search_then_scrape", "hybrid"} and request.use_search_discovery:
            candidate_queries = build_queries(
                plan,
                request.query,
                include_mature_content=request.include_mature_content,
                source_domains=source_packs.domains,
                source_terms=source_packs.query_terms,
                source_templates=source_packs.query_templates,
            )
            candidates: list[dict] = []
            for query in candidate_queries:
                candidates.extend(await self.search_provider.search(query, limit=8))
            ranked = rank_candidates(
                candidates,
                blocked_domains=set(request.blocked_domains or []),
                preferred_domains=source_packs.domains,
                preferred_categories=source_packs.categories,
                domain_categories=source_packs.domain_categories,
                intent=plan.intent,
                query=request.query,
            )
            filtered_ranked = [
                r
                for r in ranked
                if _is_candidate_target_url(
                    r.get("url", ""),
                    intent="media" if media_like else plan.intent,
                    respect_robots=request.respect_robots_txt,
                )
            ]
            if media_like and query_tokens:
                topical_ranked = [
                    r
                    for r in filtered_ranked
                    if _candidate_matches_query_tokens(r, query_tokens)
                ]
                if topical_ranked:
                    filtered_ranked = topical_ranked

            filtered_ranked = [
                r
                for r in filtered_ranked
                if self.site_agent_registry.supports_candidate(
                    r.get("url", ""),
                    intent="media" if media_like else plan.intent,
                )
            ]

            if media_like and source_packs.domains and not query_tokens:
                allowed_media_domains = list(dict.fromkeys(source_packs.domains + list(KNOWN_MEDIA_DISCOVERY_HOSTS)))
                filtered_ranked = [
                    r for r in filtered_ranked if _matches_domains(r.get("url", ""), allowed_media_domains)
                ]

            target_urls = [r["url"] for r in filtered_ranked][: max(1, min(request.max_pages, 10))]

            if source_packs.seed_urls and len(target_urls) < min(request.max_pages, 6) and (not query_tokens or not target_urls):
                appended = 0
                for seed in source_packs.seed_urls:
                    if seed in target_urls:
                        continue
                    if not _is_candidate_target_url(
                        seed,
                        intent="media" if media_like else plan.intent,
                        respect_robots=request.respect_robots_txt,
                    ):
                        continue
                    if media_like and not _seed_matches_query(seed, request.query):
                        continue
                    target_urls.append(seed)
                    appended += 1
                    if len(target_urls) >= max(1, min(request.max_pages, 10)):
                        break
                if not appended and media_like and not query_tokens:
                    for seed in source_packs.seed_urls:
                        if seed in target_urls:
                            continue
                        if not _is_candidate_target_url(
                            seed,
                            intent="media" if media_like else plan.intent,
                            respect_robots=request.respect_robots_txt,
                        ):
                            continue
                        if _is_generic_meme_media_seed(seed):
                            continue
                        target_urls.append(seed)
                        appended += 1
                        if len(target_urls) >= max(1, min(request.max_pages, 10)):
                            break
                if appended:
                    warnings.append(
                        JobWarning(
                            code="SOURCE_PACK_AUGMENTED",
                            message="Discovery augmented target URLs with curated source-pack seeds.",
                        )
                    )

        if not target_urls and source_packs.seed_urls:
            filtered_seeds = [
                seed
                for seed in source_packs.seed_urls
                if _is_candidate_target_url(
                    seed,
                    intent="media" if media_like else plan.intent,
                    respect_robots=request.respect_robots_txt,
                )
                and (not media_like or _seed_matches_query(seed, request.query))
            ]
            if media_like and not filtered_seeds and not query_tokens:
                filtered_seeds = [
                    seed
                    for seed in source_packs.seed_urls
                    if _is_candidate_target_url(
                        seed,
                        intent="media",
                        respect_robots=request.respect_robots_txt,
                    )
                    and not _is_generic_meme_media_seed(seed)
                ]
            if not filtered_seeds:
                filtered_seeds = [
                    seed
                    for seed in source_packs.seed_urls
                    if _is_candidate_target_url(
                        seed,
                        intent="media" if media_like else plan.intent,
                        respect_robots=request.respect_robots_txt,
                    )
                ]
            target_urls = filtered_seeds[: max(1, min(request.max_pages, 10))]
            if target_urls:
                warnings.append(
                    JobWarning(
                        code="SOURCE_PACK_FALLBACK",
                        message="Discovery used curated source-pack seed URLs after search produced no targets.",
                    )
                )

        if not target_urls:
            warnings.append(JobWarning(code="NO_TARGET_URLS", message="No target URLs were provided or discovered."))

        frontier = URLFrontier(seed_urls=target_urls, max_depth=request.max_depth)
        records: list[ScrapedRecord] = []
        stats = {"pages_processed": 0, "records_extracted": 0, "failures": 0, "elapsed_ms": 0}

        while frontier.has_next() and stats["pages_processed"] < request.max_pages:
            item = frontier.next()
            url = item.url
            site_agent = self.site_agent_registry.resolve(url)
            if not is_allowed(url, request.allowed_domains, request.blocked_domains):
                continue
            if url in frontier.visited:
                continue
            frontier.mark_visited(url)

            if request.respect_robots_txt:
                allowed = await robots_allows(url)
                if not allowed:
                    warnings.append(JobWarning(code="ROBOTS_BLOCKED", message="robots.txt disallowed scraping", url=url))
                    continue

            fetched = None
            try:
                use_dynamic_fetch = plan.use_playwright or request.mode == "dynamic"
                if request.mode == "auto":
                    if site_agent.prefer_static and not plan.use_playwright:
                        use_dynamic_fetch = False
                    elif site_agent.force_dynamic:
                        use_dynamic_fetch = True

                if use_dynamic_fetch:
                    options = BrowserFetchOptions(
                        timeout_ms=request.timeout_seconds * 1000,
                        click_galleries=plan.click_galleries,
                        user_agent=request.user_agent,
                    )
                    try:
                        fetched = await self.dynamic_fetcher.fetch(url, options)
                    except Exception as exc:
                        if _is_missing_playwright_browser(exc) and request.mode != "dynamic":
                            warnings.append(
                                JobWarning(
                                    code="PLAYWRIGHT_MISSING_FALLBACK",
                                    message="Playwright browser missing; using static fetch fallback.",
                                    url=url,
                                )
                            )
                            fetched = await self.static_fetcher.fetch(url)
                        else:
                            raise
                    if fetched.status_code == 408:
                        warnings.append(JobWarning(code="DYNAMIC_TIMEOUT", message="Dynamic fetch timed out", url=url))
                else:
                    fetched = await self.static_fetcher.fetch(url)

                if not fetched or not fetched.html:
                    stats["failures"] += 1
                    continue
            except Exception as exc:
                stats["failures"] += 1
                warnings.append(JobWarning(code="FETCH_FAILED", message=str(exc), url=url))
                logger.exception("fetch.failure", extra={"job_id": job_id, "url": url})
                continue

            md = extract_metadata(fetched.html, fetched.final_url)
            contacts = extract_contacts(fetched.html)
            imgs = extract_images(fetched.html, fetched.final_url, fetched.image_candidates)
            media = extract_media_assets(fetched.html, fetched.final_url, fetched.video_candidates)

            merged_data = {}
            merged_data.update(md.data)
            merged_data.update(contacts.data)
            merged_data.update(media.data)

            for metadata_images in [md.images, media.images]:
                for image in metadata_images:
                    if image not in imgs:
                        imgs.append(image)

            if plan.intent == "real_estate":
                listing = extract_listing(fetched.html)
                merged_data.update({k: v for k, v in listing.data.items() if v is not None})
                notes = md.notes + contacts.notes + media.notes + listing.notes
            elif plan.intent == "products":
                product = extract_product(fetched.html)
                merged_data.update({k: v for k, v in product.data.items() if v is not None})
                notes = md.notes + contacts.notes + media.notes + product.notes
            else:
                notes = md.notes + contacts.notes + media.notes
            notes.append(f"site_agent:{site_agent.agent_id}")

            title = merged_data.get("title") or merged_data.get("name")
            record = ScrapedRecord(
                source_url=url,
                canonical_url=merged_data.get("canonical_url"),
                record_type=plan.intent,
                title=str(title) if title else None,
                data=merged_data,
                images=imgs[: request.image_limit_per_record] if request.include_images else [],
                videos=merged_data.get("video_urls", [])[: request.video_limit_per_record] if request.include_videos else [],
                extraction_notes=notes,
            )

            normalized = normalize_records([record])
            deduped = deduper.filter_new_records(normalized)
            for r in deduped:
                required = [field.name for field in plan.fields if field.required]
                r.confidence = scorer.score(r, required_fields=required, requested_images=request.include_images)
            records.extend(deduped)

            if request.paginate or request.follow_internal_links:
                links = discover_next_links(fetched.html, fetched.final_url, item.depth)
                resolved = []
                for link in links:
                    resolved.append(type(link)(url=urljoin(fetched.final_url, link.url), depth=link.depth, parent=link.parent))
                frontier.add(resolved)

            stats["pages_processed"] += 1

        if request.download_images and records:
            records = await download_record_images(records, job_id=job_id, storage_root=self.storage_root)

        stats["records_extracted"] = len(records)
        stats["elapsed_ms"] = int((perf_counter() - started) * 1000)

        if not records:
            warnings.append(JobWarning(code="NO_RECORDS_EXTRACTED", message="No records could be extracted."))

        response = ScrapeResponse(
            job_id=job_id,
            status="completed",
            plan=plan.model_dump(),
            records=records,
            stats=stats,
            warnings=warnings,
            diagnostics=_build_job_diagnostics(warnings=warnings, stats=stats, records=records),
        )

        logger.info(
            "job.completed",
            extra={
                "job_id": job_id,
                "pages_processed": stats["pages_processed"],
                "records_extracted": stats["records_extracted"],
            },
        )
        return response


def _normalize_host(host: str) -> str:
    value = host.lower().strip()
    if value.startswith("www."):
        return value[4:]
    return value


def _is_candidate_target_url(url: str, intent: str, respect_robots: bool = True) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = _normalize_host(parsed.netloc)
    if not host:
        return False

    if host in {_normalize_host(h) for h in SEARCH_RESULT_HOSTS}:
        return False

    if intent == "media" and host in {_normalize_host(h) for h in LOW_SIGNAL_MEDIA_HOSTS}:
        return False

    if respect_robots and intent == "media" and host in {_normalize_host(h) for h in ROBOTS_BLOCKED_MEDIA_HOSTS}:
        return False

    return True


def _matches_domains(url: str, domains: list[str]) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = _normalize_host(parsed.netloc)
    if not host:
        return False

    normalized_domains = {_normalize_host(d) for d in domains}
    return any(host == d or host.endswith(f".{d}") for d in normalized_domains)


def _is_missing_playwright_browser(exc: Exception) -> bool:
    message = str(exc).lower()
    return "executable doesn't exist" in message and "playwright" in message


def _is_media_like_request(intent: str, request: ScrapeRequest) -> bool:
    if intent == "media":
        return True
    if intent != "generic":
        return False
    requested_fields = {field.lower() for field in (request.desired_fields or [])}
    media_fields = {"video_urls", "image_urls", "embed_urls", "social_links", "hashtags", "audio_urls"}
    return bool(request.include_videos or media_fields.intersection(requested_fields))


def _seed_matches_query(seed_url: str, query: str) -> bool:
    tokens = _query_focus_tokens(query)
    if not tokens:
        return True
    text = seed_url.lower()
    return any(token in text for token in tokens)


def _query_focus_tokens(query: str) -> list[str]:
    words = [part.strip(" ,.;:!?()[]{}\"'\n\t").lower() for part in query.split()]
    stopwords = {
        "a",
        "an",
        "and",
        "best",
        "clip",
        "clips",
        "for",
        "from",
        "get",
        "gif",
        "gifs",
        "in",
        "meme",
        "memes",
        "of",
        "on",
        "or",
        "reel",
        "reels",
        "short",
        "shorts",
        "the",
        "top",
        "trend",
        "trending",
        "video",
        "videos",
        "viral",
        "with",
    }
    tokens = [word for word in words if word and word not in stopwords and len(word) >= 3]
    return list(dict.fromkeys(tokens))


def _candidate_matches_query_tokens(candidate: dict, query_tokens: list[str]) -> bool:
    if not query_tokens:
        return True
    text = " ".join(
        str(candidate.get(part, ""))
        for part in ["url", "title", "snippet", "description"]
    ).lower()
    overlap = sum(1 for token in query_tokens if token in text)
    if len(query_tokens) <= 2:
        required_overlap = len(query_tokens)
    else:
        required_overlap = max(2, (len(query_tokens) + 1) // 2)
    return overlap >= required_overlap


def _is_generic_meme_media_seed(seed_url: str) -> bool:
    try:
        host = _normalize_host(urlparse(seed_url).netloc)
    except Exception:
        return False
    return host in {_normalize_host(h) for h in GENERIC_MEME_MEDIA_HOSTS}


def _build_job_diagnostics(warnings: list[JobWarning], stats: dict, records: list[ScrapedRecord]) -> JobDiagnostics | None:
    warning_counts: dict[str, int] = {}
    for warning in warnings:
        warning_counts[warning.code] = warning_counts.get(warning.code, 0) + 1

    if records:
        return JobDiagnostics(
            primary_issue=None,
            recommendation="Run complete. Use records preview or CSV export for structured review.",
            warning_counts=warning_counts,
        )

    if not warning_counts and not stats.get("failures"):
        return JobDiagnostics(
            primary_issue="NO_DATA",
            recommendation="Try adding source packs and a more specific query topic.",
            warning_counts=warning_counts,
        )

    if warning_counts.get("ROBOTS_BLOCKED", 0) >= 1:
        return JobDiagnostics(
            primary_issue="ROBOTS_BLOCKED",
            recommendation="Most candidate URLs disallowed scraping. Try different source packs or target public hosts that allow robots access.",
            warning_counts=warning_counts,
        )

    if warning_counts.get("FETCH_FAILED", 0) >= 1:
        return JobDiagnostics(
            primary_issue="FETCH_FAILURES",
            recommendation="Some targets failed to fetch. Retry with mode=static or reduce max_pages.",
            warning_counts=warning_counts,
        )

    if warning_counts.get("NO_TARGET_URLS", 0) >= 1:
        return JobDiagnostics(
            primary_issue="NO_TARGET_URLS",
            recommendation="No strong targets discovered. Add websites or source_pack_ids to constrain discovery.",
            warning_counts=warning_counts,
        )

    if warning_counts.get("NO_RECORDS_EXTRACTED", 0) >= 1:
        return JobDiagnostics(
            primary_issue="NO_RECORDS_EXTRACTED",
            recommendation="Targets were fetched but extraction yielded no records. Try broader desired_fields or dynamic mode.",
            warning_counts=warning_counts,
        )

    return JobDiagnostics(
        primary_issue="UNCLASSIFIED",
        recommendation="Review warnings and rerun with more specific source constraints.",
        warning_counts=warning_counts,
    )
