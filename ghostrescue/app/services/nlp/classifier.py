from app.core.logging import get_logger
from app.models.schemas import SignalOut
from app.services.nlp.pattern_rules import PATTERN_RULES, PatternRule

logger = get_logger(__name__)


class NLPClassifier:
    """
    Rule-based NLP signal classifier.

    Detects trafficking-related language patterns in free text and returns
    structured SignalOut objects with confidence scores.

    Interface is designed to be swappable with a transformer-based model
    (spaCy / HuggingFace) without changing callers.
    """

    def classify(self, text: str) -> list[SignalOut]:
        """
        Run all pattern rules against text.
        Returns one signal per rule that matches (deduplicated by signal_type).
        """
        signals: list[SignalOut] = []
        for rule in PATTERN_RULES:
            evidence = self._first_match(text, rule)
            if evidence:
                signals.append(
                    SignalOut(
                        signal_type=rule.signal_type,
                        label=rule.label,
                        confidence=rule.base_confidence,
                        evidence=evidence,
                    )
                )
        logger.debug("NLP classified %d chars → %d signals", len(text), len(signals))
        return signals

    @staticmethod
    def _first_match(text: str, rule: PatternRule) -> str | None:
        for pattern in rule.compiled:
            m = pattern.search(text)
            if m:
                return m.group(0).strip()
        return None
