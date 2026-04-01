from datetime import datetime

from pydantic import BaseModel, Field

from app.models.requests import ScrapeRequest


class AgentPreset(BaseModel):
    preset_id: str
    user_id: str
    name: str
    request: ScrapeRequest
    created_at: datetime
    updated_at: datetime


class AgentHistoryItem(BaseModel):
    history_id: str
    user_id: str
    label: str
    request: ScrapeRequest
    run_async: bool = True
    created_at: datetime
    last_run_at: datetime
    job_id: str | None = None


class AgentSubmitRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1)
    label: str | None = None
    request: ScrapeRequest
    run_async: bool = True


class AgentSubmitResponse(BaseModel):
    history_id: str
    job_id: str
    run_async: bool


class AgentPresetCreateRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1)
    name: str = Field(min_length=1, max_length=120)
    request: ScrapeRequest


class AgentSafetyPresetRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    include_mature_content: bool = False
    run_async: bool = True
