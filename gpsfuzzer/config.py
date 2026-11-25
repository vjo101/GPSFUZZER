"""Typed, unit-explicit experiment configuration and validation."""

from dataclasses import dataclass
from enum import Enum
import math


@dataclass(frozen=True)
class NumericRange:
    """Inclusive numeric range used for seeded sampling."""

    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.minimum) or not math.isfinite(self.maximum):
            raise ValueError("range bounds must be finite")
        if self.minimum > self.maximum:
            raise ValueError("range minimum must not exceed maximum")


class DriftMode(str, Enum):
    COHERENT = "coherent"
    POSITION_ONLY = "position_only"


@dataclass(frozen=True)
class DriftConfig:
    """Drift bounds: delay in seconds, speed in m/s, bearing in degrees."""

    start_delay_s: NumericRange = NumericRange(30.0, 60.0)
    horizontal_speed_mps: NumericRange = NumericRange(0.5, 2.0)
    bearing_deg: NumericRange = NumericRange(0.0, 360.0)
    mode: DriftMode = DriftMode.COHERENT

    def __post_init__(self) -> None:
        if self.start_delay_s.minimum < 0:
            raise ValueError("start delay must be non-negative seconds")
        if self.horizontal_speed_mps.minimum < 0:
            raise ValueError("horizontal speed must be non-negative metres per second")
        if self.bearing_deg.minimum < 0 or self.bearing_deg.maximum > 360:
            raise ValueError("bearing must be within 0..360 degrees clockwise from north")
        if not isinstance(self.mode, DriftMode):
            raise ValueError("mode must be DriftMode.COHERENT or DriftMode.POSITION_ONLY")


@dataclass(frozen=True)
class ExperimentConfig:
    """Reproducibility inputs for one experiment."""

    seed: int
    drift: DriftConfig = DriftConfig()
    duration_s: float = 300.0

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("duration must be a positive finite number of seconds")
