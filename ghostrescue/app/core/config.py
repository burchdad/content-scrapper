from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "GhostRescue AI"
    debug: bool = False

    # Database (defaults to in-process SQLite for development)
    database_url: str = "sqlite+aiosqlite:///./ghostrescue.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "ghostrescue"

    # External APIs
    newsapi_key: str = ""
    courtlistener_api_token: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    x_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    # Entity resolution thresholds (RapidFuzz score range: 0–100)
    entity_match_threshold: float = 85.0   # consider as potential match
    entity_merge_threshold: float = 92.0   # high-confidence auto-merge

    # Risk scoring bands
    risk_high_threshold: float = 65.0
    risk_critical_threshold: float = 80.0

    # Compliance disclaimer — must appear on all output
    disclaimer: str = (
        "Outputs are intelligence leads, not verified conclusions. "
        "All data is sourced from public, legally permitted records only. "
        "This system does not generate accusations or legal determinations. "
        "Human review is required before any action is taken."
    )

    # Audit retention for exported Tier 4 proof reports
    tier4_audit_export_root: str = "./audit_exports/tier4"

    # Tier 4 archive (daily immutable-style retention)
    tier4_archive_root: str = "./app/data/tier4_reports"
    tier4_archive_auto_trigger: bool = True

    # Optional real-time notifications for newly archived Tier 4 cases
    tier4_archive_webhook_url: str = ""
    tier4_archive_webhook_timeout_seconds: float = 5.0
    tier4_archive_webhook_bearer_token: str = ""

    # Secure temporary investigation chat (non-persistent)
    temporary_chat_enabled: bool = True
    temporary_chat_access_key: str = ""
    temporary_chat_max_messages: int = 12
    temporary_chat_max_context_chars: int = 24000
    temporary_session_ttl_minutes: int = 90
    temporary_sensitive_allowed_roles: str = "trusted_operator,senior_analyst"


def get_settings() -> Settings:
    return Settings()
