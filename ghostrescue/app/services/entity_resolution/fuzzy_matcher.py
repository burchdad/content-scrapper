from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass
class MatchCandidate:
    entity_id: str
    canonical_name: str
    score: float
    match_strategy: str
    matched_alias: str | None = None


class FuzzyMatcher:
    """
    Multi-strategy fuzzy name matcher using RapidFuzz.

    Strategies applied and weighted:
      - token_sort_ratio (0.35) — word-order-independent comparison
      - token_set_ratio  (0.35) — handles subset / superset names
      - partial_ratio    (0.15) — handles abbreviations / partial names
      - WRatio           (0.15) — weighted combination fallback

    Returns candidates whose best alias score >= threshold, sorted by score desc.
    """

    _WEIGHTS = [0.35, 0.35, 0.15, 0.15]

    def __init__(self, threshold: float = 85.0) -> None:
        self.threshold = threshold

    def match(
        self,
        query_name: str,
        candidates: list[tuple[str, str, list[str]]],  # (entity_id, canonical_name, aliases)
    ) -> list[MatchCandidate]:
        """
        Returns all candidate entities whose name-or-alias score >= threshold.

        candidates: list of (entity_id, canonical_name, [alias_str, ...])
        """
        normalized_query = self._normalize(query_name)
        results: list[MatchCandidate] = []

        for entity_id, canonical_name, aliases in candidates:
            hit = self._best_score(normalized_query, canonical_name, aliases)
            if hit:
                results.append(
                    MatchCandidate(
                        entity_id=entity_id,
                        canonical_name=hit["canonical_name"],
                        score=hit["score"],
                        match_strategy=hit["match_strategy"],
                        matched_alias=hit["matched_alias"],
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _best_score(
        self,
        query: str,
        canonical: str,
        aliases: list[str],
    ) -> dict | None:
        best_score = 0.0
        best_label = canonical
        is_alias = False

        for text in [canonical, *aliases]:
            score = self._multi_strategy_score(query, self._normalize(text))
            if score > best_score:
                best_score = score
                best_label = text
                is_alias = text != canonical

        if best_score < self.threshold:
            return None

        return {
            "canonical_name": canonical,
            "score": round(best_score, 2),
            "match_strategy": "fuzzy_multi",
            "matched_alias": best_label if is_alias else None,
        }

    @classmethod
    def _multi_strategy_score(cls, a: str, b: str) -> float:
        scores = [
            fuzz.token_sort_ratio(a, b),
            fuzz.token_set_ratio(a, b),
            fuzz.partial_ratio(a, b),
            fuzz.WRatio(a, b),
        ]
        return sum(s * w for s, w in zip(scores, cls._WEIGHTS))

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().strip().split())
