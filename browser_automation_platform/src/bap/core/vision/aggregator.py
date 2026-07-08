"""Transforms raw observations into a PageState.

Analyzers are independent, so two of them may report the same logical field
(e.g. OCR and an AI analyzer both reading "header_region.text"). The
aggregator's single job is resolving that into one Observation per field.
"""

from __future__ import annotations

from collections.abc import Iterable

from bap.core.domain.models import Observation, PageState


class Aggregator:
    """Keeps, per field name, the observation with the highest confidence;
    on equal confidence the most recently observed wins."""

    def build_page_state(
        self, profile_id: str, observations: Iterable[Observation]
    ) -> PageState:
        best: dict[str, Observation] = {}
        for obs in observations:
            current = best.get(obs.name)
            if current is None or self._beats(obs, current):
                best[obs.name] = obs
        return PageState(profile_id=profile_id, fields=best)

    @staticmethod
    def _beats(candidate: Observation, incumbent: Observation) -> bool:
        return (candidate.confidence, candidate.observed_at) > (
            incumbent.confidence,
            incumbent.observed_at,
        )


__all__ = ["Aggregator"]
