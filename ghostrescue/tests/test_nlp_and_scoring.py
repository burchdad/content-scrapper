from app.models.schemas import SignalOut
from app.services.nlp.classifier import NLPClassifier
from app.services.scoring.risk_scorer import RiskScorer


class TestNLPClassifier:
    def setup_method(self):
        self.classifier = NLPClassifier()

    def test_detects_coercion_language(self):
        signals = self.classifier.classify("The victim said she was forced and had no choice to leave.")
        types = [s.signal_type for s in signals]
        assert "coercion_language" in types

    def test_detects_minor_risk_language(self):
        signals = self.classifier.classify("Underage individuals were identified at the location.")
        types = [s.signal_type for s in signals]
        assert "minor_risk_language" in types

    def test_detects_off_platform_contact(self):
        signals = self.classifier.classify("Reach me on telegram for more information.")
        types = [s.signal_type for s in signals]
        assert "off_platform_contact" in types

    def test_detects_recruitment_language(self):
        signals = self.classifier.classify("Easy money, just come with me and don't tell anyone.")
        types = [s.signal_type for s in signals]
        assert "recruitment_language" in types

    def test_detects_commercial_sex_indicators(self):
        signals = self.classifier.classify("Escort available now, incall only, book now.")
        types = [s.signal_type for s in signals]
        assert "commercial_sex_indicators" in types

    def test_no_false_positives_on_benign_text(self):
        signals = self.classifier.classify(
            "She went to the grocery store and bought milk. The weather was nice."
        )
        assert signals == []

    def test_multiple_signals_detected(self):
        signals = self.classifier.classify(
            "Young girl forced to work. Contact on telegram only. New in town."
        )
        types = {s.signal_type for s in signals}
        assert len(types) >= 3


class TestRiskScorer:
    def setup_method(self):
        self.scorer = RiskScorer()

    def test_empty_signals_returns_zero_score(self):
        result = self.scorer.score([])
        assert result.risk_score == 0.0
        assert result.risk_band == "low"
        assert result.confidence_score == 0.0
        assert result.disclaimer

    def test_coercion_signal_non_zero_score(self):
        signals = [SignalOut(signal_type="coercion_language", label="test", confidence=0.85, evidence="forced")]
        result = self.scorer.score(signals)
        assert result.risk_score > 0

    def test_minor_risk_signal_high_contribution(self):
        signals = [SignalOut(signal_type="minor_risk_language", label="test", confidence=0.90, evidence="underage")]
        result = self.scorer.score(signals)
        # weight=0.40 × confidence=0.90 × 100 = 36
        assert result.risk_score >= 30.0

    def test_critical_risk_band_on_stacked_signals(self):
        signals = [
            SignalOut(signal_type="coercion_language", label="t", confidence=1.0, evidence="forced"),
            SignalOut(signal_type="minor_risk_language", label="t", confidence=1.0, evidence="underage"),
            SignalOut(signal_type="commercial_sex_indicators", label="t", confidence=1.0, evidence="escort"),
        ]
        result = self.scorer.score(signals, entity_match_confidence=1.0, signal_frequency_bonus=3.0)
        assert result.risk_band in ("high", "critical")

    def test_explanation_always_present(self):
        result = self.scorer.score([])
        assert len(result.explanation) > 20

    def test_disclaimer_always_present(self):
        result = self.scorer.score(
            [SignalOut(signal_type="off_platform_contact", label="t", confidence=0.5, evidence="telegram")]
        )
        assert "intelligence leads" in result.disclaimer.lower()
