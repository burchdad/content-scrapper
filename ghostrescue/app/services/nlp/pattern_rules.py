import re
from dataclasses import dataclass, field


@dataclass
class PatternRule:
    signal_type: str
    label: str
    patterns: list[str]
    base_confidence: float
    weight: float  # contribution to raw risk score (0–1 scale before ×100)
    compiled: list[re.Pattern] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.patterns]


PATTERN_RULES: list[PatternRule] = [
    PatternRule(
        signal_type="coercion_language",
        label="Coercion or control indicators",
        patterns=[
            r"\b(forced|coerced|no\s+choice|locked\s+up|captive|captivity|pimp|controlled|owned|trafficked)\b",
            r"\b(can'?t\s+(leave|go|refuse|say\s+no))\b",
            r"\b(debt\s+bondage|owes|paying\s+off|work\s+it\s+off)\b",
        ],
        base_confidence=0.80,
        weight=0.35,
    ),
    PatternRule(
        signal_type="minor_risk_language",
        label="Minor or vulnerable person risk indicators",
        patterns=[
            r"\b(underage|minor\b|juvenile|teen\b|teenager|schoolgirl|schoolboy|barely\s+legal"
            r"|young\s+(girl|boy|woman|man))\b",
        ],
        base_confidence=0.90,
        weight=0.40,
    ),
    PatternRule(
        signal_type="recruitment_language",
        label="Recruitment or luring patterns",
        patterns=[
            r"\b(easy\s+money|fast\s+cash|good\s+pay|model(ing)?\s+opportunity|work\s+from\s+home\s+job)\b",
            r"\b(dm\s+me|message\s+me|contact\s+privately|don'?t\s+tell|keep\s+it\s+quiet|our\s+little\s+secret)\b",
            r"\b(come\s+with\s+me|pick\s+you\s+up|you('re|\s+are)\s+special|i\s+can\s+help\s+you)\b",
        ],
        base_confidence=0.65,
        weight=0.20,
    ),
    PatternRule(
        signal_type="commercial_sex_indicators",
        label="Commercial sexual services indicators",
        patterns=[
            r"\b(escort\b|incall|outcall|full\s+service|hourly\s+rate|book\s+now|available\s+now|gfe)\b",
            r"\b(donation\s+based|tribute\s+required|rates\s+on\s+request)\b",
        ],
        base_confidence=0.70,
        weight=0.25,
    ),
    PatternRule(
        signal_type="off_platform_contact",
        label="Off-platform contact diversion",
        patterns=[
            r"\b(telegram|whatsapp|snapchat|kik|wickr|dm\s+for\s+details|text\s+only|no\s+calls)\b",
        ],
        base_confidence=0.55,
        weight=0.10,
    ),
    PatternRule(
        signal_type="transient_location_pattern",
        label="Transient or controlled location indicators",
        patterns=[
            r"\b(hotel\b|motel\b|room\s*\d+|truck\s+stop|rest\s+area|new\s+in\s+town|just\s+arrived)\b",
            r"\b(passport\s+held|transport\s+arranged|driver\s+provided|travel\s+arranged)\b",
        ],
        base_confidence=0.50,
        weight=0.10,
    ),
]
