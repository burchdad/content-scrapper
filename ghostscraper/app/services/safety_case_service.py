import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.intelligence.trafficking_scorer import score_record_risk
from app.models.records import ScrapedRecord
from app.models.responses import ScrapeResponse
from app.models.safety import (
    SafetyCase,
    SafetyCaseBulkWorkflowUpdateResult,
    SafetyCaseCreateFromJobRequest,
    SafetyCaseRecord,
    SafetyCaseReportChecklistItem,
    SafetyCaseReportChecklistUpdate,
    SafetyCaseReportEvidenceItem,
    SafetyCaseReportPackage,
    SafetyCaseReportSignoff,
    SafetyCaseReportSignoffUpdate,
    SafetyCaseReportSummary,
    SafetyCaseReportWorkflowUpdateRequest,
    SafetyCaseSummary,
)
from app.services.job_service import create_job_id


class SafetyCaseService:
    def __init__(self, root: str) -> None:
        self.cases_dir = Path(root) / "cases"
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def create_case_from_job(self, job: ScrapeResponse, request: SafetyCaseCreateFromJobRequest) -> SafetyCase:
        selected_records = job.records[: request.record_limit]
        flagged: list[SafetyCaseRecord] = []
        all_scores: list[float] = []

        for index, record in enumerate(selected_records):
            score, signals = score_record_risk(record)
            all_scores.append(score)
            if score < request.min_risk_score:
                continue
            flagged.append(
                SafetyCaseRecord(
                    record_index=index,
                    source_url=record.source_url,
                    title=record.title,
                    risk_score=score,
                    risk_band=self._risk_band_for_score(score),
                    signals=signals,
                    media_hashes=self._hash_media(record),
                )
            )

        avg_score = round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0
        max_score = max(all_scores) if all_scores else 0.0
        case_id = create_job_id()
        case = SafetyCase(
            case_id=case_id,
            status="open",
            job_id=job.job_id,
            title=request.title or f"Safety case for job {job.job_id}",
            notes=request.notes,
            created_at=datetime.now(UTC),
            total_records_evaluated=len(selected_records),
            flagged_records_count=len(flagged),
            average_risk_score=avg_score,
            highest_risk_band=self._risk_band_for_score(max_score),
            submission_checklist=self._default_submission_checklist(),
            signoff=self._default_signoff(),
            records=flagged,
        )
        self.save_case(case)
        return case

    def save_case(self, case: SafetyCase) -> None:
        path = self.cases_dir / f"{case.case_id}.json"
        path.write_text(case.model_dump_json(indent=2), encoding="utf-8")

    def get_case(self, case_id: str) -> SafetyCase | None:
        path = self.cases_dir / f"{case_id}.json"
        if not path.exists():
            return None
        return SafetyCase.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_cases(
        self,
        limit: int = 20,
        signoff_approved: bool | None = None,
        destination_channel: str | None = None,
    ) -> list[SafetyCaseSummary]:
        files = sorted(self.cases_dir.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        summaries: list[SafetyCaseSummary] = []
        normalized_channel = destination_channel.strip().lower() if destination_channel else None
        for path in files:
            case = SafetyCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
            checklist = case.submission_checklist or self._default_submission_checklist()
            checklist_completed = sum(1 for item in checklist if item.completed)
            signoff = case.signoff or self._default_signoff()

            if signoff_approved is not None and signoff.approved != signoff_approved:
                continue
            if normalized_channel and (signoff.destination_channel or "").strip().lower() != normalized_channel:
                continue

            summaries.append(
                SafetyCaseSummary(
                    case_id=case.case_id,
                    status=case.status,
                    job_id=case.job_id,
                    title=case.title,
                    created_at=case.created_at,
                    flagged_records_count=case.flagged_records_count,
                    average_risk_score=case.average_risk_score,
                    highest_risk_band=case.highest_risk_band,
                    checklist_completed_count=checklist_completed,
                    checklist_total_count=len(checklist),
                    signoff_approved=signoff.approved,
                    signoff_reviewer_id=signoff.reviewer_id,
                    destination_channel=signoff.destination_channel,
                    signoff_approved_at=signoff.approved_at,
                )
            )
            if len(summaries) >= limit:
                break
        return summaries

    def build_case_report_package(self, case: SafetyCase, reviewer: str | None = None) -> SafetyCaseReportPackage:
        summary = SafetyCaseReportSummary(
            case_id=case.case_id,
            job_id=case.job_id,
            title=case.title,
            status=case.status,
            created_at=case.created_at,
            flagged_records_count=case.flagged_records_count,
            average_risk_score=case.average_risk_score,
            highest_risk_band=case.highest_risk_band,
        )
        evidence = [
            SafetyCaseReportEvidenceItem(
                record_index=record.record_index,
                source_url=record.source_url,
                title=record.title,
                risk_score=record.risk_score,
                risk_band=record.risk_band,
                signal_names=[signal.name for signal in record.signals],
                evidence_terms=[signal.evidence for signal in record.signals],
                media_hashes=record.media_hashes,
            )
            for record in case.records
        ]
        submission_checklist = case.submission_checklist or self._default_submission_checklist()
        signoff = case.signoff or self._default_signoff()
        if reviewer and not signoff.reviewer_id:
            signoff = signoff.model_copy(update={"reviewer_id": reviewer})
        return SafetyCaseReportPackage(
            report_id=f"report-{case.case_id}",
            generated_at=datetime.now(UTC),
            reviewer=reviewer or signoff.reviewer_id,
            case_summary=summary,
            legal_notice=(
                "This report contains automated risk indicators for triage only. "
                "It is not a legal determination and requires human review before enforcement action."
            ),
            chain_of_custody=[
                "Case loaded from immutable storage record.",
                "Evidence manifest generated from stored signal and media hash fields.",
                "Report reviewed and approved by authorized safety personnel before external submission.",
            ],
            submission_checklist=submission_checklist,
            signoff=signoff,
            evidence_manifest=evidence,
        )

    def report_package_json(self, package: SafetyCaseReportPackage) -> str:
        return package.model_dump_json(indent=2)

    def update_case_report_workflow(
        self,
        case_id: str,
        request: SafetyCaseReportWorkflowUpdateRequest,
    ) -> SafetyCase | None:
        case = self.get_case(case_id)
        if not case:
            return None

        checklist = case.submission_checklist or self._default_submission_checklist()
        by_id = {item.item_id: item for item in checklist}

        for update in request.checklist_updates:
            self._apply_checklist_update(by_id=by_id, checklist=checklist, update=update)

        signoff = case.signoff or self._default_signoff()
        if request.signoff:
            signoff = self._apply_signoff_update(signoff=signoff, update=request.signoff)

        case.submission_checklist = checklist
        case.signoff = signoff
        self.save_case(case)
        return case

    def bulk_update_case_report_workflow(
        self,
        case_ids: list[str],
        request: SafetyCaseReportWorkflowUpdateRequest,
    ) -> SafetyCaseBulkWorkflowUpdateResult:
        updated_case_ids: list[str] = []
        missing_case_ids: list[str] = []

        for case_id in case_ids:
            updated = self.update_case_report_workflow(case_id=case_id, request=request)
            if not updated:
                missing_case_ids.append(case_id)
                continue
            updated_case_ids.append(case_id)

        return SafetyCaseBulkWorkflowUpdateResult(
            updated_case_ids=updated_case_ids,
            missing_case_ids=missing_case_ids,
        )

    @staticmethod
    def case_summaries_csv(summaries: list[SafetyCaseSummary]) -> str:
        rows = [
            "case_id,status,job_id,title,created_at,flagged_records_count,average_risk_score,highest_risk_band,"
            "checklist_completed_count,checklist_total_count,signoff_approved,signoff_reviewer_id,destination_channel,signoff_approved_at"
        ]
        for item in summaries:
            rows.append(
                ",".join(
                    [
                        SafetyCaseService._csv_escape(item.case_id),
                        SafetyCaseService._csv_escape(item.status),
                        SafetyCaseService._csv_escape(item.job_id),
                        SafetyCaseService._csv_escape(item.title),
                        SafetyCaseService._csv_escape(item.created_at.isoformat()),
                        str(item.flagged_records_count),
                        str(item.average_risk_score),
                        SafetyCaseService._csv_escape(item.highest_risk_band),
                        str(item.checklist_completed_count),
                        str(item.checklist_total_count),
                        str(item.signoff_approved).lower(),
                        SafetyCaseService._csv_escape(item.signoff_reviewer_id),
                        SafetyCaseService._csv_escape(item.destination_channel),
                        SafetyCaseService._csv_escape(item.signoff_approved_at.isoformat() if item.signoff_approved_at else None),
                    ]
                )
            )
        return "\n".join(rows) + "\n"

    @staticmethod
    def _risk_band_for_score(score: float) -> str:
        if score >= 0.7:
            return "critical"
        if score >= 0.45:
            return "high"
        if score >= 0.25:
            return "moderate"
        return "low"

    @staticmethod
    def _hash_media(record: ScrapedRecord) -> list[str]:
        hashes: list[str] = []
        for value in [record.source_url, *record.images, *record.videos]:
            if not value:
                continue
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            hashes.append(f"sha256:{digest}")
        return hashes

    @staticmethod
    def _csv_escape(value: str | None) -> str:
        if value is None:
            return ""
        text = str(value).replace('"', '""')
        return f'"{text}"'

    @staticmethod
    def _default_submission_checklist() -> list[SafetyCaseReportChecklistItem]:
        return [
            SafetyCaseReportChecklistItem(
                item_id="human-review",
                label="Primary human reviewer completed full case review.",
                completed=False,
            ),
            SafetyCaseReportChecklistItem(
                item_id="second-review",
                label="Secondary reviewer confirmed escalation recommendation.",
                completed=False,
            ),
            SafetyCaseReportChecklistItem(
                item_id="evidence-integrity",
                label="Evidence links, terms, and media hashes verified.",
                completed=False,
            ),
            SafetyCaseReportChecklistItem(
                item_id="submission-channel",
                label="Submission destination selected (platform trust/safety or legal channel).",
                completed=False,
            ),
        ]

    @staticmethod
    def _default_signoff(reviewer_id: str | None = None) -> SafetyCaseReportSignoff:
        return SafetyCaseReportSignoff(
            reviewer_id=reviewer_id,
            approved=False,
            approved_at=None,
            destination_channel=None,
        )

    @staticmethod
    def _apply_checklist_update(
        by_id: dict[str, SafetyCaseReportChecklistItem],
        checklist: list[SafetyCaseReportChecklistItem],
        update: SafetyCaseReportChecklistUpdate,
    ) -> None:
        item = by_id.get(update.item_id)
        if not item:
            item = SafetyCaseReportChecklistItem(
                item_id=update.item_id,
                label=update.item_id.replace("-", " ").title(),
                completed=False,
            )
            checklist.append(item)
            by_id[update.item_id] = item
        if update.completed is not None:
            item.completed = update.completed
        if update.notes is not None:
            item.notes = update.notes

    @staticmethod
    def _apply_signoff_update(
        signoff: SafetyCaseReportSignoff,
        update: SafetyCaseReportSignoffUpdate,
    ) -> SafetyCaseReportSignoff:
        if update.reviewer_id is not None:
            signoff.reviewer_id = update.reviewer_id
        if update.destination_channel is not None:
            signoff.destination_channel = update.destination_channel
        if update.approved is not None:
            if update.approved and not signoff.approved:
                signoff.approved_at = datetime.now(UTC)
            if not update.approved:
                signoff.approved_at = None
            signoff.approved = update.approved
        return signoff
