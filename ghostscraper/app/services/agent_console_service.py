import json
from datetime import UTC, datetime
from pathlib import Path

from app.models.agent_console import (
    AgentHistoryItem,
    AgentPreset,
    AgentPresetCreateRequest,
    AgentSafetyPresetRequest,
    AgentSubmitRequest,
)
from app.models.requests import ScrapeRequest
from app.services.job_service import create_job_id


class AgentConsoleService:
    def __init__(self, root: str) -> None:
        self.root = Path(root) / "agent_console"
        self.root.mkdir(parents=True, exist_ok=True)

    def list_presets(self, user_id: str) -> list[AgentPreset]:
        data = self._read_json(self._presets_path(user_id), default=[])
        return [AgentPreset.model_validate(item) for item in data]

    def create_preset(self, request: AgentPresetCreateRequest) -> AgentPreset:
        presets = self.list_presets(request.user_id)
        now = datetime.now(UTC)
        preset = AgentPreset(
            preset_id=create_job_id(),
            user_id=request.user_id,
            name=request.name,
            request=request.request,
            created_at=now,
            updated_at=now,
        )
        presets.append(preset)
        self._write_json(self._presets_path(request.user_id), [p.model_dump(mode="json") for p in presets])
        return preset

    def create_safety_monitoring_preset(self, request: AgentSafetyPresetRequest) -> AgentPreset:
        preset_request = AgentPresetCreateRequest(
            user_id=request.user_id,
            name=request.name or "Safety Monitoring Preset",
            request=ScrapeRequest(
                query=request.query
                or "Monitor public posts and comments for grooming, coercion, and off-platform contact cues",
                mode="auto",
                max_pages=10,
                include_images=True,
                include_videos=True,
                include_mature_content=request.include_mature_content,
                use_search_discovery=True,
                source_pack_ids=[
                    "social-discussion",
                    "short-video-viral",
                    "livestream-clips",
                ],
                desired_fields=[
                    "title",
                    "source_url",
                    "social_links",
                    "hashtags",
                    "image_urls",
                    "video_urls",
                ],
            ),
        )
        return self.create_preset(preset_request)

    def delete_preset(self, user_id: str, preset_id: str) -> bool:
        presets = self.list_presets(user_id)
        filtered = [p for p in presets if p.preset_id != preset_id]
        if len(filtered) == len(presets):
            return False
        self._write_json(self._presets_path(user_id), [p.model_dump(mode="json") for p in filtered])
        return True

    def list_history(self, user_id: str, limit: int = 50, offset: int = 0) -> list[AgentHistoryItem]:
        data = self._read_json(self._history_path(user_id), default=[])
        items = [AgentHistoryItem.model_validate(item) for item in data]
        items.sort(key=lambda item: item.last_run_at, reverse=True)
        return items[offset : offset + limit]

    def create_history_item(self, submit: AgentSubmitRequest, job_id: str) -> AgentHistoryItem:
        history = self.list_history(submit.user_id, limit=5000)
        now = datetime.now(UTC)
        item = AgentHistoryItem(
            history_id=create_job_id(),
            user_id=submit.user_id,
            label=submit.label or submit.request.query,
            request=submit.request,
            run_async=submit.run_async,
            created_at=now,
            last_run_at=now,
            job_id=job_id,
        )
        history.append(item)
        self._write_json(self._history_path(submit.user_id), [h.model_dump(mode="json") for h in history])
        return item

    def update_history_run(self, user_id: str, history_id: str, job_id: str, run_async: bool) -> AgentHistoryItem | None:
        history = self.list_history(user_id, limit=5000)
        for item in history:
            if item.history_id == history_id:
                item.last_run_at = datetime.now(UTC)
                item.job_id = job_id
                item.run_async = run_async
                self._write_json(self._history_path(user_id), [h.model_dump(mode="json") for h in history])
                return item
        return None

    def get_history_item(self, user_id: str, history_id: str) -> AgentHistoryItem | None:
        history = self.list_history(user_id, limit=5000)
        for item in history:
            if item.history_id == history_id:
                return item
        return None

    def delete_history_item(self, user_id: str, history_id: str) -> bool:
        history = self.list_history(user_id, limit=5000)
        filtered = [item for item in history if item.history_id != history_id]
        if len(filtered) == len(history):
            return False
        self._write_json(self._history_path(user_id), [h.model_dump(mode="json") for h in filtered])
        return True

    def _presets_path(self, user_id: str) -> Path:
        user_dir = self._user_dir(user_id)
        return user_dir / "presets.json"

    def _history_path(self, user_id: str) -> Path:
        user_dir = self._user_dir(user_id)
        return user_dir / "history.json"

    def _user_dir(self, user_id: str) -> Path:
        safe = "".join(ch for ch in user_id if ch.isalnum() or ch in {"-", "_"}) or "default"
        user_dir = self.root / safe
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    @staticmethod
    def _read_json(path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
