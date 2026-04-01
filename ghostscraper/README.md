# GhostScraper

GhostScraper is an instruction-driven scraping service that supports direct target scraping and intent-based discovery mode.

## Features

- Natural-language scrape jobs
- Deterministic planner for intent and strategy selection
- Static fetcher via httpx + retries
- Dynamic fetcher via Playwright for JS-heavy pages and galleries
- Metadata, contact, image, product, and real estate extraction modules
- Broad media extraction for images, videos, audio, embeds, hashtags, and social links
- Record normalization, deduplication, and confidence scoring
- FastAPI endpoints for scrape jobs and health checks
- Async queued scrape endpoint for background execution
- Multi-engine discovery fallback across DuckDuckGo, Bing, Google, and Yahoo
- Curated source-pack registry for public-source discovery across video, memes, communities, creators, commerce, events, and news

## Quick Start

1. Create a virtual environment and install dependencies.
2. Copy `.env.example` to `.env` and adjust values.
3. Install Playwright Chromium.
4. Run the API server.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --reload
```

## API Endpoints

- `POST /api/v1/jobs/scrape`
- `POST /api/v1/jobs/scrape/async`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/records`
- `GET /api/v1/jobs/{job_id}/export.csv`
- `POST /api/v1/safety/cases/from-job`
- `GET /api/v1/safety/cases`
- `GET /api/v1/safety/cases/{case_id}`
- `GET /api/v1/safety/cases/export.csv`
- `GET /api/v1/safety/cases/{case_id}/report`
- `PATCH /api/v1/safety/cases/{case_id}/report/workflow`
- `PATCH /api/v1/safety/cases/report/workflow/bulk`
- `GET /api/v1/safety/cases/{case_id}/report.json`
- `GET /api/v1/safety/persona`

Safety case report packages now include a submit-ready checklist and signoff metadata for reviewer approval workflows.
- `GET /api/v1/agent/presets`
- `POST /api/v1/agent/presets`
- `POST /api/v1/agent/presets/safety-default`
- `DELETE /api/v1/agent/presets/{preset_id}`
- `GET /api/v1/agent/history`
- `POST /api/v1/agent/history/submit`
- `POST /api/v1/agent/history/{history_id}/rerun`
- `GET /api/v1/source-packs`
- `GET /api/v1/source-packs/{pack_id}`
- `GET /api/v1/health`
- `GET /api/v1/health/dependencies`
- `GET /ui/jobs`
- `GET /ui/agent`

Queued jobs are processed by an in-process FIFO worker. Poll `GET /api/v1/jobs/{job_id}` for `queued`, `running`, `completed`, or `failed` status.
Use `GET /api/v1/jobs?status=queued&limit=20` to list recent jobs by status.
Use `GET /api/v1/jobs?limit=20&cursor=<next_cursor>` to fetch the next page.
The endpoint returns `{ "items": [...], "next_cursor": "..." }`.
Use `GET /api/v1/jobs/{job_id}/records?limit=20&offset=0` to preview extracted records without loading the full job document.
Use `GET /api/v1/jobs/{job_id}/records?fields=title,price,address` to preview only selected fields.
Use `GET /api/v1/jobs/{job_id}/export.csv?fields=title,price,address` to export a filtered CSV for one job.
Open `GET /ui/jobs` in the browser for a minimal visual job and records browser.
The UI shows record thumbnails when image URLs are present and lets you open full images in a new tab.
The UI now includes a one-click `Trend Pull Preset` and `Run Job` composer that can submit sync or async scrape jobs directly.
The UI also includes `Create Safety Case` for the selected job to generate a risk-scored investigation case from public findings.

## Agent Console

Open `GET /ui/agent` for a standalone personal console with:

- saved prompt presets per user
- request history with rerun actions
- quick toggles (mode, max pages, fields, mature-content discovery, async/sync)
- multi-select curated source packs that survive presets and reruns
- case board from Safety Ops cases
- export center links for JSON/CSV bundles

## Safety Ops Mode

Safety cases evaluate job records for trafficking-risk indicators and produce case files with:

- per-record risk score
- matched risk signals with evidence terms
- media/source SHA-256 hashes for evidence tracking

Create a case from a completed job:

```json
POST /api/v1/safety/cases/from-job
{
	"job_id": "<job_id>",
	"title": "Case title",
	"notes": "Optional investigator notes",
	"record_limit": 100,
	"min_risk_score": 0.45
}
```

## Broad Media Queries

You can now ask for broader media-oriented extraction, not only listings or product data.

Examples:

- `Pull all images, videos, and social media assets from this campaign site`
- `Scrape everything media-related: photos, reels, embeds, hashtags, and profile links`
- `Collect all media from these pages including images, video URLs, and social links`

Media-heavy queries trigger broader extraction for:

- image URLs
- video URLs
- audio URLs
- embed URLs
- social profile/post links
- hashtags

### Example Trend Request (From You or an Upstream AI Agent)

Use this request shape for broad social-media trend collection:

```json
{
	"query": "Pull the top 10 memes, gifs, shorts, and tiktok videos with current trends",
	"websites": null,
	"source_pack_ids": [
		"short-video-viral",
		"meme-gif-culture",
		"social-discussion",
		"livestream-clips",
		"music-scenes",
		"gaming-culture"
	],
	"mode": "auto",
	"use_search_discovery": true,
	"include_images": true,
	"include_videos": true,
	"include_mature_content": true,
	"max_pages": 10,
	"desired_fields": [
		"title",
		"image_urls",
		"video_urls",
		"embed_urls",
		"social_links",
		"hashtags"
	]
}
```

Notes:

- `include_mature_content=true` broadens discovery query generation; it does not bypass site/platform access controls.
- `source_pack_ids` scopes discovery to curated public sources, injects intent-aware query patterns, and adds fallback seed URLs when search engines return weak or empty results.
- The scraper still only targets publicly accessible content and respects configured guardrails.

## Source Packs

Built-in packs now include broad public-source coverage across:

- short-form video and viral clips
- memes and GIF culture
- social discussion communities
- livestream clips
- creator portfolios
- photo-sharing sites
- music scenes and charts
- gaming culture
- fashion resale
- marketplaces and handmade products
- startup launches
- deal communities
- news wires
- events and nightlife
- local classifieds

Use `GET /api/v1/source-packs` to inspect the full catalog and wire pack IDs into scrape requests.
Packs now expand queries differently by intent, so the same pack can contribute media-style, product-style, article-style, or real-estate-style search language as needed.

## Search Discovery Engines

Discovery can now use multiple engines with automatic fallback:

- DuckDuckGo HTML
- Bing HTML
- Google HTML
- Yahoo HTML

Set `DISCOVERY_PROVIDER` to one of:

- `auto`
- `duckduckgo_html`
- `bing_html`
- `google_html`
- `yahoo_html`

`auto` uses the composite fallback chain. Safari is a browser, not a search engine, so it is not configured as a standalone provider.

## Legal and Safety

GhostScraper is designed for publicly accessible content only. It does not attempt authentication bypass or protected-content scraping.
