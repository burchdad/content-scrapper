# GhostRescue AI

A **legal, compliant intelligence platform** for identifying human trafficking and missing persons patterns from **public, permitted data sources only**.

> ⚠️ **Disclaimer:** Outputs are intelligence leads, not verified conclusions. All data is sourced from public, legally permitted records only. This system does not generate accusations or legal determinations. Human review is required before any action is taken.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GhostRescue AI                               │
├──────────────┬──────────────┬──────────────┬────────────────────────┤
│  Data        │   Entity     │  NLP         │  Risk Scoring          │
│  Ingestion   │  Resolution  │  Engine      │  Pipeline              │
│  Services    │  Engine      │  (Classify)  │  (Multi-factor)        │
├──────────────┴──────────────┴──────────────┴────────────────────────┤
│                    FastAPI API Gateway                               │
│   POST /ingest  GET /entities  POST /analyze  GET /alerts           │
│   GET /graph/{id}  GET /health                                      │
├────────────────┬────────────────┬───────────────────────────────────┤
│  PostgreSQL    │  Neo4j         │  Redis + Celery                   │
│  (Core store)  │  (Graph)       │  (Async jobs / queues)            │
└────────────────┴────────────────┴───────────────────────────────────┘
```

---

## Project Structure

```
ghostrescue/
├── app/
│   ├── core/
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── database.py         # SQLAlchemy async engine
│   │   ├── graph_db.py         # Neo4j driver
│   │   ├── cache.py            # Redis client
│   │   └── logging.py
│   ├── models/
│   │   ├── entity.py           # Entity, EntityAlias, EntityMergeLog
│   │   ├── signal.py           # Signal
│   │   ├── case.py             # Case
│   │   ├── alert.py            # Alert
│   │   └── schemas.py          # Pydantic I/O schemas
│   ├── services/
│   │   ├── entity_resolution/
│   │   │   ├── fuzzy_matcher.py   # RapidFuzz multi-strategy matcher
│   │   │   ├── merger.py          # Entity merge logic + audit log
│   │   │   └── resolver.py        # Main resolver orchestrator
│   │   ├── nlp/
│   │   │   ├── pattern_rules.py   # Signal detection rules
│   │   │   └── classifier.py      # NLP classifier
│   │   ├── scoring/
│   │   │   └── risk_scorer.py     # Multi-factor risk scorer
│   │   ├── ingestion/
│   │   │   ├── base_connector.py
│   │   │   └── public_records_connector.py
│   │   └── graph/
│   │       └── graph_service.py   # Neo4j graph queries
│   ├── api/
│   │   ├── routes_ingest.py
│   │   ├── routes_entities.py
│   │   ├── routes_analyze.py
│   │   ├── routes_graph.py
│   │   ├── routes_alerts.py
│   │   └── routes_health.py
│   ├── workers/
│   │   ├── celery_app.py
│   │   └── tasks.py
│   └── main.py
├── tests/
│   ├── conftest.py
│   ├── test_entity_resolution.py
│   ├── test_nlp_and_scoring.py
│   └── test_api.py
├── sample_data/
│   └── sample_records.json      # Synthetic test records
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/ingest` | Ingest entity records (runs entity resolution) |
| `GET` | `/api/v1/entities` | List resolved entities (paginated) |
| `GET` | `/api/v1/entities/{entity_id}` | Get single entity with aliases |
| `GET` | `/api/v1/entities/{entity_id}/timeline` | Entity event timeline (temporal memory) |
| `GET` | `/api/v1/entities/{entity_id}/correlations` | Cross-source correlation features |
| `POST` | `/api/v1/analyze` | NLP classification + risk scoring on text |
| `GET` | `/api/v1/graph/{entity_id}` | Knowledge graph neighborhood |
| `GET` | `/api/v1/graph/{entity_id}/analytics` | Graph intelligence metrics |
| `GET` | `/api/v1/alerts` | List alerts (filterable) |
| `PATCH` | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge an alert |
| `POST` | `/api/v1/cases/evaluate` | Evaluate entity text and create/update case |
| `GET` | `/api/v1/cases` | List cases |
| `GET` | `/api/v1/cases/clusters` | Semantic clustering of related cases |
| `GET` | `/api/v1/cases/{case_id}` | Get case detail |
| `GET` | `/api/v1/cases/{case_id}/summary` | Analyst narrative summary |
| `GET` | `/api/v1/cases/{case_id}/explainability` | Explainability breakdown (JSON) |
| `GET` | `/api/v1/cases/{case_id}/explainability/html` | Explainability visualization (HTML) |
| `GET` | `/api/v1/cases/{case_id}/explainability/feedback` | Feedback history for case |
| `GET` | `/api/v1/trust/config` | Get trust and bias-control thresholds |
| `PATCH` | `/api/v1/trust/config` | Update trust thresholds |
| `POST` | `/api/v1/trust/feedback` | Submit analyst feedback (FP/corrections) |
| `GET` | `/api/v1/trust/feedback` | List analyst feedback |
| `GET` | `/api/v1/trust/stats` | False-positive rate + adaptive penalty |

---

## Entity Resolution Engine

**Flow:** `normalize → fuzzy match → merge / link / create`

**Strategies (weighted):**
- `token_sort_ratio` (0.35) — word-order-independent
- `token_set_ratio` (0.35) — subset / superset names  
- `partial_ratio` (0.15) — abbreviations / partial names
- `WRatio` (0.15) — weighted fallback

**Thresholds:**
- score ≥ 92 → **merge** (high confidence, absorb aliases, log audit event)
- score ≥ 85 → **link** (mid confidence, add as alias)
- score < 85 → **create** new entity

All merge events are recorded in `entity_merge_logs` and in the entity's `audit_log` JSON field.

---

## NLP Signal Types

| Signal Type | Description | Base Confidence | Weight |
|---|---|---|---|
| `coercion_language` | Forced, debt bondage, no choice | 0.80 | 0.35 |
| `minor_risk_language` | Underage, juvenile, barely legal | 0.90 | 0.40 |
| `recruitment_language` | Easy money, come with me, DM me | 0.65 | 0.20 |
| `commercial_sex_indicators` | Escort, incall, book now | 0.70 | 0.25 |
| `off_platform_contact` | Telegram, WhatsApp, Wickr | 0.55 | 0.10 |
| `transient_location_pattern` | Hotel, motel, new in town | 0.50 | 0.10 |

---

## Risk Score Bands

| Band | Score Range |
|------|-------------|
| `low` | 0–34 |
| `medium` | 35–59 |
| `high` | 60–79 |
| `critical` | 80–100 |

---

## Quick Start

```bash
# Development (SQLite, no external services required)
cd ghostrescue
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload

# Run tests
pytest -q

# Full stack (PostgreSQL + Redis + Neo4j)
docker compose up
```

## Adding a Data Source

1. Subclass `BaseConnector` in `app/services/ingestion/`
2. Implement `fetch()` (must query only public/permitted sources) and `transform()`
3. Call `.run(query)` to produce an `IngestRequest`
4. POST the result to `/api/v1/ingest`

## NamUs Source Integration

NamUs is now supported through local export ingestion.

Why local export: the public search page is interactive and does not expose a stable open API contract in the page HTML, so GhostRescue ingests from your downloaded NamUs data file (JSON/CSV) in a compliant, auditable way.

1. Export/download records from https://www.namus.gov/MissingPersons/Search
2. Save file as JSON or CSV (recommended fields):
  - `namus_case`
  - `first_name`
  - `last_name`
  - `alias`
  - `age`
  - `sex`
  - `last_contact_date`
  - `last_city`
  - `last_state`
  - `circumstances`
  - `source_url`
3. Run ingestion with:

```bash
NAMUS_DATA_FILE=sample_data/namus_missing_persons.json python scripts/populate_live_data.py
```

If `NAMUS_DATA_FILE` is not set, GhostRescue defaults to `sample_data/namus_missing_persons.json`.

---

## Compliance

- ✅ Public/permitted data sources only
- ✅ No explicit content stored or processed
- ✅ Full audit trail on all entity merges
- ✅ Compliance disclaimer on every API response
- ✅ PII masking flag (`is_pii_masked`) on entity records
- ✅ No accusations generated — triage leads only
- ✅ Human review required before any enforcement action

## Analyst-Grade Intelligence Added

- Entity memory timeline via `entity_events` (ingestion, analysis, case evaluation)
- Cross-source correlation metrics (source diversity, shared identifiers, temporal burst)
- Semantic case clustering using embedding-style token vectors and cosine similarity
- Compound escalation policy with runtime trust thresholds:
  - `critical`: risk ≥ configured critical threshold + minor-risk signal + multi-source reinforcement
  - `high`: risk ≥ configured high threshold with compound signals
  - `medium`: risk ≥ configured medium threshold
- Adaptive scoring penalty based on analyst false-positive feedback loop
- Confidence propagation on outputs (`confidence_score` and `system_confidence`)
- Case lifecycle integration with alerts (`under_review` / `escalated`)
- Narrative case summary endpoint with evidence activity over time
- Trust layer endpoints for threshold governance, feedback, and calibration stats

## Explainability & Transparency Layer

**Purpose:** Analysts can audit the system's reasoning for each case decision. No black boxes.

**Endpoints:**
- `GET /api/v1/cases/{case_id}/explainability` — JSON breakdown of:
  - Per-signal confidence contributions and weight percentages
  - Confidence composition (signal avg × 0.7 + entity confidence × 0.25 + diversity bonus × 0.05 − calibration penalty)
  - Feedback summary (FP count, FP rate, corrected scores)
  - Current trust config context (thresholds, penalties)
  
- `GET /api/v1/cases/{case_id}/explainability/html` — Interactive HTML page with:
  - Signal contribution bar chart (visual weight breakdown)
  - Confidence composition breakdown (pie-like visual)
  - Analyst feedback history table (recent comments, corrections)
  - System settings snapshot
  - Disclaimer and audit trail metadata
  
- `GET /api/v1/cases/{case_id}/explainability/feedback` — Feedback history API (JSON):
  - Timestamped analyst corrections
  - False-positive acknowledgments
  - Corrected risk scores
  - Notes and reasoning

**Design:** All outputs include compliance disclaimer. All confidence scores pinned to 0–1 range. All feedback is immutable for audit compliance.

## Analyst Dashboard

**URL:** `http://localhost:8000/` (or `/dashboard`)

A professional, real-time SaaS-style dashboard for case management and system monitoring.

**Features:**

**Overview Tab:**
- Live metrics: Total entities, active cases, unacknowledged alerts, system confidence
- Risk distribution chart (Low/Medium/High/Critical bands)
- Signal types detected (bar chart)
- Recent critical cases table (Risk > 70)

**Cases Tab:**
- Full case registry with filtering (search, status filter)
- Per-case stats: risk score, confidence, entity/signal count
- "View" button opens detailed case modal with:
  - Case summary tab (NLP narrative)
  - Explainability tab (signal breakdown + confidence recipe)
  - Feedback tab (analyst corrections + calibration history)
- Case modal embedded explainability viewer

**Alerts Tab:**
- Real-time alert list
- Severity filter (Critical/High/Medium/Low)
- Unacknowledged-only toggle
- Acknowledge action for each alert

**Entities Tab:**
- Entity registry search
- Per-entity stats: type, confidence, source count
- Timeline button for viewing entity event history

**Trust Settings Tab:**
- Risk threshold configuration (medium/high/critical cutoffs)
- False positive penalty editor
- Feedback statistics: FP count, FP rate, adaptive penalty
- Recent feedback table (analyst ID, type, corrected score, date)
- Save configuration button (persists to TrustConfig table)

**Design:**
- **Dark theme** with professional color scheme (slate/blue/emerald/red)
- **Responsive layout** (desktop, tablet, mobile)
- **Sidebar navigation** with collapsible menu on mobile
- **Real-time charts** (Chart.js for doughnut and bar charts)
- **Live stats** (dashboard refreshes every 30 seconds)
- **Modal case detail viewer** with tabbed explainability
- **No external CDN required** (except Chart.js, configurable)
- **WCAG-compliant** for accessibility

**Static Files:**
- `/app/static/dashboard.html` — Main UI page
- `/app/static/dashboard.css` — Styling (dark theme, responsive)
- `/app/static/dashboard.js` — Dashboard logic (API integration, charts, filtering)
