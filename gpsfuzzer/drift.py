"""Seeded selection and recording of effective GPS drift parameters."""

from dataclasses import dataclass
import random

from .config import DriftConfig, DriftMode


@dataclass(frozen=True)
class EffectiveDrift:
    start_delay_s: float
    horizontal_speed_mps: float
    bearing_deg: float
    mode: DriftMode


def sample_drift(config: DriftConfig, seed: int) -> EffectiveDrift:
    """Sample one effective drift command without changing global RNG state."""
    rng = random.Random(seed)
    return EffectiveDrift(
        start_delay_s=rng.uniform(config.start_delay_s.minimum, config.start_delay_s.maximum),
        horizontal_speed_mps=rng.uniform(
            config.horizontal_speed_mps.minimum,
            config.horizontal_speed_mps.maximum,
        ),
        bearing_deg=rng.uniform(config.bearing_deg.minimum, config.bearing_deg.maximum),
        mode=config.mode,
    )
