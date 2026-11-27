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
class MissionMutationConfig:
    """Seeded mission geometry bounds used by mission-based campaigns."""

    waypoint_count: tuple[int, int] = (3, 6)
    leg_distance_m: NumericRange = NumericRange(60.0, 240.0)
    bearing_deg: NumericRange = NumericRange(0.0, 360.0)
    altitude_m: NumericRange = NumericRange(10.0, 30.0)

    def __post_init__(self) -> None:
        if not isinstance(self.waypoint_count, (tuple, list)) or len(self.waypoint_count) != 2:
            raise ValueError("waypoint_count must contain minimum and maximum values")
        minimum, maximum = self.waypoint_count
        if (
            isinstance(minimum, bool) or isinstance(maximum, bool)
            or not isinstance(minimum, int) or not isinstance(maximum, int)
            or minimum < 1 or minimum > maximum or maximum > 100
        ):
            raise ValueError("waypoint_count must be an ordered integer range within 1..100")
        if self.leg_distance_m.minimum <= 0:
            raise ValueError("mission leg distance must be positive metres")
        if self.bearing_deg.minimum < 0 or self.bearing_deg.maximum > 360:
            raise ValueError("mission bearing must be within 0..360 degrees clockwise from north")
        if self.altitude_m.minimum <= 0 or self.altitude_m.maximum > 120:
            raise ValueError("mission relative altitude must be within (0, 120] metres")

    @property
    def has_variability(self) -> bool:
        return (
            self.waypoint_count[0] != self.waypoint_count[1]
            or self.leg_distance_m.minimum != self.leg_distance_m.maximum
            or self.bearing_deg.minimum != self.bearing_deg.maximum
            or self.altitude_m.minimum != self.altitude_m.maximum
        )


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
    mission_mutation: MissionMutationConfig = MissionMutationConfig()
    simulation_speedup: float = 2.0

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("duration must be a positive finite number of seconds")
        if (
            isinstance(self.simulation_speedup, bool)
            or not isinstance(self.simulation_speedup, (int, float))
            or not math.isfinite(self.simulation_speedup)
            or self.simulation_speedup <= 0
        ):
            raise ValueError("simulation_speedup must be a positive finite number")
        if not float(self.simulation_speedup).is_integer():
            raise ValueError("simulation_speedup must be a whole number supported by sim_vehicle.py")
        if not isinstance(self.mission_mutation, MissionMutationConfig):
            raise ValueError("mission_mutation must be MissionMutationConfig")
