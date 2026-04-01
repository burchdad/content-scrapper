# Import all models here so SQLAlchemy mapper registry is populated
# before create_tables() calls Base.metadata.create_all
from app.models.alert import Alert
from app.models.case import Case
from app.models.entity import Entity, EntityAlias, EntityMergeLog
from app.models.entity_event import EntityEvent
from app.models.feedback import AnalystFeedback
from app.models.signal import Signal
from app.models.staged_signal import StagedSignal
from app.models.trust import TrustConfig

__all__ = [
    "Alert",
    "AnalystFeedback",
    "Case",
    "Entity",
    "EntityAlias",
    "EntityEvent",
    "EntityMergeLog",
    "Signal",
    "StagedSignal",
    "TrustConfig",
]
