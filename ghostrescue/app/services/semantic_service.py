import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


class SemanticService:
    @staticmethod
    def embedding(text: str) -> dict[str, float]:
        tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
        if not tokens:
            return {}
        counts = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
        return {k: v / norm for k, v in counts.items()}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        shared = set(a).intersection(b)
        if not shared:
            return 0.0
        return round(sum(a[k] * b[k] for k in shared), 4)

    def similarity(self, left: str, right: str) -> float:
        return self.cosine(self.embedding(left), self.embedding(right))
