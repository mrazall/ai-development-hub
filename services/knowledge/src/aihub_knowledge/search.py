from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedItem:
    key: str
    value: object
    score: float = 0.0


def reciprocal_rank_fusion(*rankings: Iterable[RankedItem], k: int = 60) -> list[RankedItem]:
    merged: dict[str, RankedItem] = {}
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item.key] = scores.get(item.key, 0.0) + 1 / (k + rank)
            merged.setdefault(item.key, item)
    return sorted(
        (RankedItem(item.key, item.value, scores[item.key]) for item in merged.values()),
        key=lambda x: (-x.score, x.key),
    )


def lexical_rank(query: str, items: Iterable[RankedItem]) -> list[RankedItem]:
    terms = {term.casefold() for term in query.split() if term}
    scored = []
    for item in items:
        text = str(item.value).casefold()
        score = sum(text.count(term) for term in terms)
        if score:
            scored.append(RankedItem(item.key, item.value, float(score)))
    return sorted(scored, key=lambda x: (-x.score, x.key))
