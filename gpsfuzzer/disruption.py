"""Outcome ranking used by feedback-guided GPS fuzzing campaigns."""

from dataclasses import dataclass
import math
from typing import Mapping


_CLASS_RANK = {
    "unclassified": 0,
    "success": 1,
    "ekf_failure": 2,
    "timeout": 3,
    "crash": 4,
    "route_deviation": 5,
}


@dataclass(frozen=True)
class DisruptionRank:
    """Serializable ranking evidence and an ordering key for one run."""

    category: str
    class_rank: int
    maximum_route_deviation_m: float | None = None
    route_iae_m_s: float | None = None

    def sort_key(self) -> tuple[float, float, float]:
        if self.category == "route_deviation":
            return (
                float(self.class_rank),
                _finite_or_floor(self.maximum_route_deviation_m),
                _finite_or_floor(self.route_iae_m_s),
            )
        return (float(self.class_rank), 0.0, 0.0)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "class_rank": self.class_rank,
            "maximum_route_deviation_m": self.maximum_route_deviation_m,
            "route_iae_m_s": self.route_iae_m_s,
            "ordering": "outcome_class_then_max_deviation_then_iae",
        }


def _finite_or_floor(value: float | None) -> float:
    if value is None:
        return -1.0
    numeric = float(value)
    return numeric if math.isfinite(numeric) else -1.0


def _event_categories(outcome: Mapping) -> set[str]:
    events = outcome.get("safety_events", ()) or ()
    return {
        str(event.get("category", "")).casefold()
        for event in events
        if isinstance(event, Mapping)
    }


def disruption_rank(
    outcome: Mapping | None,
    route_score: Mapping | None = None,
) -> DisruptionRank:
    """Rank a mission result according to the project's disruption priority.

    Route deviation is a persistent finding and outranks a later terminal
    event. Other categories are derived from the outcome and all safety-event
    evidence. Incomplete or otherwise unknown runs rank below success.
    """
    outcome = outcome or {}
    reason = str(outcome.get("reason", "")).casefold()
    termination = str(outcome.get("termination_reason", "")).casefold()
    evidence = outcome.get("first_deviation")
    has_deviation = bool(evidence) or reason == "route_deviation"
    event_categories = _event_categories(outcome)
    searchable = " ".join((reason, termination))

    if has_deviation:
        score = route_score or outcome.get("route_deviation_score") or {}
        maximum = score.get("maximum_deviation_m")
        if maximum is None and isinstance(evidence, Mapping):
            maximum = evidence.get("distance_m")
        iae = score.get("iae_m_s")
        return DisruptionRank(
            "route_deviation", _CLASS_RANK["route_deviation"],
            _optional_finite(maximum), _optional_finite(iae),
        )

    if "crash" in event_categories or "crash" in searchable:
        category = "crash"
    elif "timeout" in searchable:
        category = "timeout"
    elif "ekf_failsafe" in event_categories or "ekf failsafe" in searchable or "ekf_failsafe" in searchable:
        category = "ekf_failure"
    elif str(outcome.get("category", "")).casefold() == "success":
        category = "success"
    else:
        category = "unclassified"
    return DisruptionRank(category, _CLASS_RANK[category])


def _optional_finite(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def compare_disruption(left: DisruptionRank, right: DisruptionRank) -> int:
    """Return 1 when left is more disruptive, -1 when right is, else 0."""
    left_key = left.sort_key()
    right_key = right.sort_key()
    return (left_key > right_key) - (left_key < right_key)
