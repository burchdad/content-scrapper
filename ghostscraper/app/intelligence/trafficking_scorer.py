import re
from collections.abc import Iterable

from app.models.records import ScrapedRecord
from app.models.safety import SafetySignal


_SIGNAL_RULES: list[tuple[str, float, list[str]]] = [
    ("coercion_terms", 0.30, ["forced", "coerced", "no choice", "locked", "captivity", "pimp"]),
    ("minor_risk_terms", 0.35, ["underage", "young girl", "teen", "minor", "schoolgirl", "barely legal"]),
    ("commercial_sex_terms", 0.25, ["escort", "incall", "outcall", "full service", "hourly", "book now"]),
    ("contact_off_platform", 0.15, ["telegram", "whatsapp", "snapchat", "kik", "signal", "dm for details"]),
    ("travel_control_terms", 0.20, ["new in town", "passport", "transport", "driver", "hotel room"]),
]

_LOCATION_RE = re.compile(r"\b(?:hotel|motel|room\s*\d+|airport|truck stop|rest area)\b", re.IGNORECASE)


def risk_signal_weights() -> dict[str, float]:
    weights = {name: weight for name, weight, _ in _SIGNAL_RULES}
    weights["transient_location_pattern"] = 0.12
    return weights


def _flatten_record_text(record: ScrapedRecord) -> str:
    chunks: list[str] = [record.source_url or "", record.title or ""]
    for value in record.data.values():
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict, str)):
            for item in value:
                if isinstance(item, str):
                    chunks.append(item)
    return " ".join(chunks).lower()


def score_record_risk(record: ScrapedRecord) -> tuple[float, list[SafetySignal]]:
    text = _flatten_record_text(record)
    signals: list[SafetySignal] = []

    for name, weight, terms in _SIGNAL_RULES:
        for term in terms:
            if term in text:
                signals.append(SafetySignal(name=name, weight=weight, evidence=term))
                break

    if _LOCATION_RE.search(text):
        signals.append(SafetySignal(name="transient_location_pattern", weight=0.12, evidence="location pattern"))

    score = sum(signal.weight for signal in signals)
    return max(0.0, min(1.0, round(score, 3))), signals
