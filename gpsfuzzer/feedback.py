"""Deterministic feedback policy for coherent GPS drift speed."""

from dataclasses import dataclass

from .config import NumericRange
from .disruption import DisruptionRank, compare_disruption


@dataclass(frozen=True)
class FeedbackDecision:
    """One serializable speed-search transition after a completed run."""

    attempt: int
    run_id: str | None
    speed_mps: float
    rank: dict
    prior_best_run_id: str | None
    prior_best_speed_mps: float | None
    prior_best_rank: dict | None
    is_new_best: bool
    direction_before: int
    step_before_mps: float
    direction: int
    step_mps: float
    next_speed_mps: float | None
    stop_reason: str | None

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "run_id": self.run_id,
            "speed_mps": self.speed_mps,
            "rank": self.rank,
            "prior_best_run_id": self.prior_best_run_id,
            "prior_best_speed_mps": self.prior_best_speed_mps,
            "prior_best_rank": self.prior_best_rank,
            "is_new_best": self.is_new_best,
            "direction_before": self.direction_before,
            "step_before_mps": self.step_before_mps,
            "direction": self.direction,
            "step_mps": self.step_mps,
            "next_speed_mps": self.next_speed_mps,
            "stop_reason": self.stop_reason,
        }


class SpeedHillClimb:
    """Bounded local search over one fixed coherent-drift bearing."""

    def __init__(self, speed_bounds: NumericRange, max_attempts: int = 10) -> None:
        if not isinstance(speed_bounds, NumericRange):
            raise ValueError("speed_bounds must be NumericRange")
        if speed_bounds.maximum <= speed_bounds.minimum:
            raise ValueError("speed_bounds must have a positive width")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts <= 0
        ):
            raise ValueError("max_attempts must be a positive integer")
        self.speed_bounds = speed_bounds
        self.max_attempts = max_attempts
        self.current_speed_mps = (speed_bounds.minimum + speed_bounds.maximum) / 2.0
        self.direction = 1
        self.step_mps = (speed_bounds.maximum - speed_bounds.minimum) / 4.0
        self.attempts_completed = 0
        self.best_rank: DisruptionRank | None = None
        self.best_run_id: str | None = None
        self.best_speed_mps: float | None = None

    def observe_result(
        self,
        rank: DisruptionRank,
        *,
        run_id: str | None = None,
    ) -> FeedbackDecision:
        """Record a result and choose the next in-range speed, if any."""
        if not isinstance(rank, DisruptionRank):
            raise ValueError("rank must be DisruptionRank")
        if self.attempts_completed >= self.max_attempts:
            raise RuntimeError("target attempt limit has already been reached")

        self.attempts_completed += 1
        scored_speed = self.current_speed_mps
        direction_before = self.direction
        step_before = self.step_mps
        prior_best_rank = self.best_rank
        prior_best_run_id = self.best_run_id
        prior_best_speed = self.best_speed_mps
        improved = (
            prior_best_rank is None
            or compare_disruption(rank, prior_best_rank) > 0
        )
        if improved:
            self.best_rank = rank
            self.best_run_id = run_id
            self.best_speed_mps = self.current_speed_mps
        else:
            self.direction *= -1
            self.step_mps /= 2.0

        next_speed = None
        stop_reason = None
        if self.attempts_completed >= self.max_attempts:
            stop_reason = "attempt_limit_reached"
        else:
            candidate = self.current_speed_mps + self.direction * self.step_mps
            candidate = min(
                self.speed_bounds.maximum,
                max(self.speed_bounds.minimum, candidate),
            )
            if candidate == self.current_speed_mps:
                stop_reason = "speed_bound_reached"
            else:
                next_speed = candidate
                self.current_speed_mps = candidate

        return FeedbackDecision(
            attempt=self.attempts_completed,
            run_id=run_id,
            speed_mps=scored_speed,
            rank=rank.to_dict(),
            prior_best_run_id=prior_best_run_id,
            prior_best_speed_mps=prior_best_speed,
            prior_best_rank=None if prior_best_rank is None else prior_best_rank.to_dict(),
            is_new_best=improved,
            direction_before=direction_before,
            step_before_mps=step_before,
            direction=self.direction,
            step_mps=self.step_mps,
            next_speed_mps=next_speed,
            stop_reason=stop_reason,
        )

    def state(self) -> dict:
        """Return target-search state for campaign and interruption records."""
        return {
            "speed_bounds_mps": {
                "minimum": self.speed_bounds.minimum,
                "maximum": self.speed_bounds.maximum,
            },
            "max_attempts": self.max_attempts,
            "attempts_completed": self.attempts_completed,
            "current_speed_mps": self.current_speed_mps,
            "direction": self.direction,
            "step_mps": self.step_mps,
            "best_speed_mps": self.best_speed_mps,
            "best_run_id": self.best_run_id,
            "best_rank": None if self.best_rank is None else self.best_rank.to_dict(),
        }
