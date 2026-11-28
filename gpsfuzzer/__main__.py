"""Command-line interface for GPSFuzzer experiments."""

import argparse
import json
from pathlib import Path

from .config import (
    DriftConfig,
    DriftMode,
    ExperimentConfig,
    FeedbackSearchConfig,
    MissionMutationConfig,
    NumericRange,
)
from .campaign import CampaignRunner
from .replay import load_replay_inputs
from .runner import ExperimentRunner


def _configuration(path: Path) -> ExperimentConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    drift = raw.get("drift", {})
    mission_mutation = raw.get("mission_mutation", {})
    feedback = raw.get("feedback", {})
    return ExperimentConfig(
        seed=raw["seed"],
        duration_s=raw.get("duration_s", 300.0),
        simulation_speedup=raw.get("simulation_speedup", 2.0),
        drift=DriftConfig(
            start_delay_s=NumericRange(*drift.get("start_delay_s", [30, 60])),
            horizontal_speed_mps=NumericRange(*drift.get("horizontal_speed_mps", [0.5, 2])),
            bearing_deg=NumericRange(*drift.get("bearing_deg", [0, 360])),
            mode=DriftMode(drift.get("mode", "coherent")),
        ),
        mission_mutation=MissionMutationConfig(
            waypoint_count=tuple(mission_mutation.get("waypoint_count", [3, 6])),
            leg_distance_m=NumericRange(*mission_mutation.get("leg_distance_m", [60, 240])),
            bearing_deg=NumericRange(*mission_mutation.get("bearing_deg", [0, 360])),
            altitude_m=NumericRange(*mission_mutation.get("altitude_m", [10, 30])),
        ),
        feedback=FeedbackSearchConfig(
            max_attempts_per_bearing=feedback.get("max_attempts_per_bearing", 10),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a GPSFuzzer ArduCopter SITL experiment")
    parser.add_argument("config", type=Path, nargs="?", help="JSON experiment configuration")
    parser.add_argument(
        "--replay-record",
        type=Path,
        help="replay one saved run's attack inputs and mission artifact",
    )
    parser.add_argument("--ardupilot", type=Path, required=True, help="ArduPilot checkout")
    parser.add_argument("--results", type=Path, default=Path("results"))
    campaign_mode = parser.add_mutually_exclusive_group()
    campaign_mode.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="number of independent SITL experiments to run in this campaign",
    )
    campaign_mode.add_argument(
        "--until-stopped",
        action="store_true",
        help="keep running independent experiments until interrupted with Ctrl-C",
    )
    parser.add_argument("--baseline", action="store_true", help="run with GPS mutation disabled")
    parser.add_argument(
        "--feedback-guided",
        action="store_true",
        help="run adaptive speed searches across bearing targets and seeded mission sweeps",
    )
    parser.add_argument("--frame", default="quad")
    parser.add_argument("--mission", type=Path, help="optional QGroundControl WPL mission to execute")
    parser.add_argument(
        "--no-mission-mutation",
        action="store_true",
        help="execute the supplied WPL mission unchanged instead of generating a route per iteration",
    )
    parser.add_argument("--location", help="optional LAT,LON,ALT,HEADING for SITL")
    parser.add_argument(
        "--map",
        action="store_true",
        help="launch MAVProxy's live map with GPS, simulator truth, and AHRS/EKF overlays",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="launch MAVProxy's live console alongside SITL",
    )
    parser.add_argument(
        "--drop-heartbeat-after",
        type=float,
        help="stop refreshing the shared-memory command after N seconds; for fault testing",
    )
    args = parser.parse_args()
    if args.replay_record is not None:
        if args.config is not None:
            parser.error("provide either CONFIG or --replay-record, not both")
        if args.baseline or args.feedback_guided or args.until_stopped or args.iterations != 1:
            parser.error("--replay-record runs one non-adaptive experiment")
        if args.mission is not None or args.no_mission_mutation:
            parser.error("--replay-record uses the mission artifact saved in its source record")
        try:
            replay = load_replay_inputs(args.replay_record)
        except ValueError as exc:
            parser.error(str(exc))
        replay_result = ExperimentRunner(args.ardupilot, args.results).run(
            replay.config,
            baseline=False,
            frame=replay.frame,
            mission_file=replay.mission_file,
            location=replay.location,
            heartbeat_stop_after_s=args.drop_heartbeat_after,
            show_map=args.map,
            show_console=args.console,
            campaign={
                "campaign_mode": "replay",
                "replay_of": {
                    "record": str(replay.source_record),
                    "run_id": replay.source_run_id,
                },
                "mission_generation": replay.mission_generation,
            },
        )
        print(
            f"replay {replay_result.status}: source={replay.source_record} "
            f"new_record={replay_result.record_path}"
        )
        return 0 if replay_result.status == "completed" else 1
    if args.config is None:
        parser.error("CONFIG is required unless --replay-record is used")
    config = _configuration(args.config)
    result = CampaignRunner(args.ardupilot, args.results).run(
        config,
        iterations=None if args.until_stopped else args.iterations,
        baseline=args.baseline,
        frame=args.frame,
        mission_file=args.mission,
        mutate_mission=not args.no_mission_mutation,
        location=args.location,
        heartbeat_stop_after_s=args.drop_heartbeat_after,
        show_map=args.map,
        show_console=args.console,
        feedback_guided=args.feedback_guided,
    )
    if args.feedback_guided:
        sweeps = (
            f"requested_sweeps={result.requested_iterations}"
            if result.requested_iterations is not None
            else "sweeps=until_stopped"
        )
        attempts = f"{result.completed_attempts} attempts; {sweeps}"
    else:
        attempts = (
            f"{result.completed_attempts}/{result.requested_iterations} attempts"
            if result.requested_iterations is not None
            else f"{result.completed_attempts} attempts (until stopped)"
        )
    print(f"campaign {result.status}: {attempts}; record={result.record_path}")
    if args.feedback_guided:
        best = result.best_attack
        if best is None:
            print("best attack: no scored disruptive result")
        else:
            print(
                "best attack: "
                f"run={best['run_id']} category={best['rank']['category']} "
                f"bearing={best['effective_drift']['bearing_deg']} deg "
                f"speed={best['effective_drift']['horizontal_speed_mps']} m/s "
                f"record={result.record_path.parent / best['record']} "
                f"mission={result.record_path.parent / best['mission']['path']} "
                f"sha256={best['mission']['sha256']}"
            )
    if result.status == "completed" or (
        result.status == "interrupted" and (args.until_stopped or args.feedback_guided)
    ):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
