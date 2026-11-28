"""Validated reconstruction of a single saved experiment's input settings."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from .config import DriftConfig, DriftMode, ExperimentConfig, NumericRange


@dataclass(frozen=True)
class ReplayInputs:
    config: ExperimentConfig
    mission_file: Path
    frame: str
    location: str | None
    source_record: Path
    source_run_id: str
    mission_generation: dict


def load_replay_inputs(record_path: str | Path) -> ReplayInputs:
    """Load inputs from a run record and validate its preserved mission file."""
    source = Path(record_path).resolve()
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read replay record: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError("replay record must contain a JSON object")

    try:
        effective = record["effective_drift"]
        configuration = record["configuration"]
        sitl = record["sitl"]
        mission = record["mission"]
        generation = mission["generation"]
        seed = record["seed"]
        duration_s = configuration["duration_s"]
        speedup = configuration["simulation_speedup"]
        mission_path = Path(mission["path"]).resolve()
        frame = sitl["frame"]
        location = sitl.get("custom_location")
        delay = effective["start_delay_s"]
        speed = effective["horizontal_speed_mps"]
        bearing = effective["bearing_deg"]
        velocity_mode = effective["velocity_mode"]
        expected_digest = generation["sha256"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"replay record is missing required input field: {exc}") from exc

    if not isinstance(generation, dict) or not isinstance(expected_digest, str):
        raise ValueError("replay record has no valid generated-mission digest")
    if not mission_path.is_file():
        raise ValueError(f"replay mission artifact is missing: {mission_path}")
    actual_digest = hashlib.sha256(mission_path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError(
            f"replay mission digest mismatch: expected {expected_digest}, got {actual_digest}"
        )
    if velocity_mode != DriftMode.COHERENT.value:
        raise ValueError("replay currently supports coherent drift records only")
    if not isinstance(frame, str) or not frame:
        raise ValueError("replay record has an invalid SITL frame")

    try:
        values = (float(delay), float(speed), float(bearing), float(duration_s), float(speedup))
    except (TypeError, ValueError) as exc:
        raise ValueError("replay record contains non-numeric experiment values") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("replay record contains non-finite experiment values")
    delay, speed, bearing, duration_s, speedup = values
    if delay < 0 or speed < 0 or not 0 <= bearing <= 360:
        raise ValueError("replay record contains out-of-range drift values")

    config = ExperimentConfig(
        seed=seed,
        duration_s=duration_s,
        simulation_speedup=speedup,
        drift=DriftConfig(
            start_delay_s=NumericRange(delay, delay),
            horizontal_speed_mps=NumericRange(speed, speed),
            bearing_deg=NumericRange(bearing, bearing),
            mode=DriftMode.COHERENT,
        ),
    )
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("replay record has no run_id to link as its source")
    return ReplayInputs(
        config=config,
        mission_file=mission_path,
        frame=frame,
        location=location,
        source_record=source,
        source_run_id=run_id,
        mission_generation=generation,
    )
