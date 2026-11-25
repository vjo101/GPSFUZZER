"""Command-line interface for GPSFuzzer experiments."""

import argparse
import json
from pathlib import Path

from .config import DriftConfig, DriftMode, ExperimentConfig, NumericRange
from .runner import ExperimentRunner


def _configuration(path: Path) -> ExperimentConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    drift = raw.get("drift", {})
    return ExperimentConfig(
        seed=raw["seed"],
        duration_s=raw.get("duration_s", 300.0),
        drift=DriftConfig(
            start_delay_s=NumericRange(*drift.get("start_delay_s", [30, 60])),
            horizontal_speed_mps=NumericRange(*drift.get("horizontal_speed_mps", [0.5, 2])),
            bearing_deg=NumericRange(*drift.get("bearing_deg", [0, 360])),
            mode=DriftMode(drift.get("mode", "coherent")),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a GPSFuzzer ArduCopter SITL experiment")
    parser.add_argument("config", type=Path, help="JSON experiment configuration")
    parser.add_argument("--ardupilot", type=Path, required=True, help="ArduPilot checkout")
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--baseline", action="store_true", help="run with GPS mutation disabled")
    parser.add_argument("--frame", default="quad")
    parser.add_argument("--mission", type=Path, help="optional QGroundControl WPL mission to execute")
    parser.add_argument("--location", help="optional LAT,LON,ALT,HEADING for SITL")
    parser.add_argument(
        "--drop-heartbeat-after",
        type=float,
        help="stop refreshing the shared-memory command after N seconds; for fault testing",
    )
    args = parser.parse_args()
    config = _configuration(args.config)
    result = ExperimentRunner(args.ardupilot, args.results).run(
        config,
        baseline=args.baseline,
        frame=args.frame,
        mission_file=args.mission,
        location=args.location,
        heartbeat_stop_after_s=args.drop_heartbeat_after,
    )
    print(f"{result.status}: {result.termination_reason}; record={result.record_path}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
