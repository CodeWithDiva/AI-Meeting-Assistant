"""Semantic search and similarity ranking service for transcripts."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass
class SearchResult:
    segment_id: int
    text: str
    speaker_label: str | None
    start_time: float
    end_time: float
    score: float


class SemanticSearchService:
    """Semantic and lexical ranking for meeting transcripts."""

    def _tokenize(self, text: str) -> list[str]:
        return [w.lower() for w in re.findall(r"\b\w{2,}\b", text)]

    def _cosine_similarity(self, vec1: Counter, vec2: Counter) -> float:
        intersection = set(vec1.keys()) & set(vec2.keys())
        numerator = sum(vec1[x] * vec2[x] for x in intersection)
        sum1 = sum(vec1[x] ** 2 for x in vec1.keys())
        sum2 = sum(vec2[x] ** 2 for x in vec2.keys())
        denominator = math.sqrt(sum1) * math.sqrt(sum2)
        if not denominator:
            return 0.0
        return float(numerator) / denominator

    def search_segments(
        self,
        query: str,
        segments: list[Any],
        limit: int = 5,
    ) -> list[SearchResult]:
        """Rank and return the most relevant segments for a query."""
        if not query.strip() or not segments:
            return []

        query_tokens = self._tokenize(query)
        query_vec = Counter(query_tokens)
        query_lower = query.lower()

        results: list[SearchResult] = []

        for seg in segments:
            text = getattr(seg, "text", "")
            seg_tokens = self._tokenize(text)
            seg_vec = Counter(seg_tokens)

            # Cosine lexical similarity
            sim = self._cosine_similarity(query_vec, seg_vec)

            # Exact substring match bonus
            if query_lower in text.lower():
                sim += 0.5

            if sim > 0.05:
                results.append(
                    SearchResult(
                        segment_id=getattr(seg, "id", 0),
                        text=text,
                        speaker_label=getattr(seg, "speaker_label", None),
                        start_time=getattr(seg, "start_time", 0.0),
                        end_time=getattr(seg, "end_time", 0.0),
                        score=round(sim, 3),
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]
