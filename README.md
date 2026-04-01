# content-scrapper

Monorepo for intelligence tooling focused on compliant public-record analysis workflows.

## Repositories In This Workspace

- `ghostrescue/`: FastAPI-based intelligence platform with dashboard, ingestion pipelines, explainability, trust controls, archive lifecycle, and secure temporary investigation workflows.
- `ghostscraper/`: Supporting scraper-oriented application and related service code.

## What GhostRescue Can Do

GhostRescue is an analyst-assist intelligence platform designed to ingest permitted-source data, detect risk signals, correlate events, and produce explainable, auditable outputs for human review.

It is built for triage and decision support, not autonomous enforcement. Every output is intended to be reviewed by an operator.

## Core Features

- Real-time dashboard with operations tabs for Cases, Alerts, Entities, Trust, Archive, and Staging.
- Tier 4 proof lifecycle with archive retention, integrity verification, and optional webhook notifications.
- Document intake and case-file access from the dashboard.
- Temporary drag-and-drop document analysis that does not persist evidence by default.
- Secure temporary investigation chat with no-store response behavior.
- Sensitive mode controls with analyst role allowlisting and analyst identity checks.

## Platform Capabilities

- Multi-source ingestion orchestration for public/permitted records.
- Entity resolution and cross-source linkage to reduce duplicate identities and improve correlation quality.
- NLP-assisted signal classification and weighted risk scoring.
- Governance and trust controls (feedback loops, thresholds, explainability, analyst-decision telemetry).
- Operational packaging: API routes, dashboard workflows, archival exports, and verification endpoints.
- Security-oriented temporary workflows for sensitive investigations where persistence is optional and controlled.

## Use Case Scenarios

- Investigative Triage: Quickly analyze inbound text/documents to prioritize leads by risk and confidence.
- Case Enrichment: Attach new documents or source findings to existing cases and review explainability context.
- Command-Center Monitoring: Track active alerts, unresolved cases, and analyst actions in one dashboard.
- Audit and Oversight: Verify report integrity, review archived records, and preserve chain-of-trust metadata.
- Sensitive Operations: Run temporary, non-persistent analysis/chat sessions with role and identity enforcement before conversion to a permanent case.

## Industry Integration Guidance

GhostRescue can be integrated as a decision-support layer in industries that rely on high-volume record review, incident triage, and human-governed escalation workflows.

- Public Safety and Investigations: Lead prioritization, cross-source correlation, and analyst review workflows.
- Compliance and Risk Operations: Intake triage, pattern detection, escalation support, and auditable case tracking.
- Enterprise Security and Trust Teams: Incident enrichment, investigation collaboration, and explainable scoring.
- NGO / Humanitarian Intelligence Programs: Signal aggregation from permitted public sources with transparent review controls.

Across industries, the best fit is where teams need:

- faster triage without losing human control,
- explainable outputs for defensibility,
- and a clear audit path from detection to action.

## Quick Start (GhostRescue)

```bash
cd ghostrescue
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open:

- API docs: `http://localhost:8000/docs`
- Dashboard: `http://localhost:8000/dashboard`

## Environment Notes

In `ghostrescue/.env`, configure sensitive-mode access as needed:

- `TEMPORARY_CHAT_ACCESS_KEY`
- `TEMPORARY_SENSITIVE_ALLOWED_ROLES` (default: `trusted_operator,senior_analyst`)

Recommended for production-style deployment:

- Configure API keys/tokens only for approved data providers.
- Restrict sensitive-mode roles to senior operators.
- Use network controls and secrets management for runtime credentials.
- Enable archival + integrity verification for regulated workflows.

## Tests

```bash
cd ghostrescue
pytest -q
```

## Deployment

For containerized deployment:

```bash
cd ghostrescue
docker compose up --build
```

Use `ghostrescue/README.md` for detailed API and architecture documentation.