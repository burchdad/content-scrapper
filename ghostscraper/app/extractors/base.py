from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    data: dict[str, Any] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
