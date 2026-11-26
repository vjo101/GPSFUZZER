"""Sequential, reproducible campaigns of independent SITL experiments."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from .config import ExperimentConfig
from .mission_mutation import MissionGenerationResult, generate_mission
from .runner import ExperimentRunner, RunResult


class MissionGenerationError(ValueError):
    """Raised when a campaign cannot create a valid per-run WPL route."""


def derive_run_seed(campaign_seed: int, iteration_index: int) -> int:
    """Return a stable 64-bit seed for a zero-based campaign iteration."""
    if isinstance(campaign_seed, bool) or not isinstance(campaign_seed, int):
        raise ValueError("campaign_seed must be an integer")
    if isinstance(iteration_index, bool) or not isinstance(iteration_index, int) or iteration_index < 0:
        raise ValueError("iteration_index must be a non-negative integer")
    payload = f"gpsfuzzer-campaign-v1:{campaign_seed}:{iteration_index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _derive_mission_retry_seed(run_seed: int, retry_index: int) -> int:
    payload = f"gpsfuzzer-mission-retry-v1:{run_seed}:{retry_index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _mission_settings_dict(settings) -> dict:
    return {
        "waypoint_count": {"minimum": settings.waypoint_count[0], "maximum": settings.waypoint_count[1]},
        "leg_distance_m": {
            "minimum": settings.leg_distance_m.minimum,
            "maximum": settings.leg_distance_m.maximum,
        },
        "bearing_deg": {"minimum": settings.bearing_deg.minimum, "maximum": settings.bearing_deg.maximum},
        "altitude_m": {"minimum": settings.altitude_m.minimum, "maximum": settings.altitude_m.maximum},
    }


def _generate_unique_mission(
    template_path: str | Path,
    output_path: Path,
    run_seed: int,
    settings,
    used_digests: set[str],
) -> tuple[MissionGenerationResult, int, int, str]:
    for retry_index in range(1024):
        generation_seed = (
            run_seed if retry_index == 0
            else _derive_mission_retry_seed(run_seed, retry_index)
        )
        generated = generate_mission(
            template_path, output_path, generation_seed, settings=settings
        )
        digest = hashlib.sha256(generated.path.read_bytes()).hexdigest()
        if digest not in used_digests:
            used_digests.add(digest)
            return generated, generation_seed, retry_index, digest
    raise ValueError("mission settings could not produce a route distinct from prior campaign iterations")


@dataclass(frozen=True)
class CampaignResult:
    campaign_id: str
    status: str
    requested_iterations: int | None
    completed_attempts: int
    record_path: Path
    runs: tuple[RunResult, ...]


class CampaignRunner:
    """Run experiments sequentially and maintain a campaign-level index."""

    def __init__(
        self,
        ardupilot_dir: str | Path,
        results_dir: str | Path,
        *,
        experiment_runner: ExperimentRunner | None = None,
        **runner_options: Any,
    ) -> None:
        self.ardupilot_dir = Path(ardupilot_dir).resolve()
        self.results_dir = Path(results_dir).resolve()
        self.experiment_runner = experiment_runner
        self.runner_options = runner_options

    @staticmethod
    def _new_campaign_id() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")

    @staticmethod
    def _write_summary(path: Path, summary: dict) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _effective_drift(result: RunResult) -> dict | None:
        drift = result.effective_drift
        if drift is None:
            return None
        return {
            "start_delay_s": drift.start_delay_s,
            "horizontal_speed_mps": drift.horizontal_speed_mps,
            "bearing_deg": drift.bearing_deg,
            "velocity_mode": drift.mode.value,
        }

    def run(
        self,
        config: ExperimentConfig,
        *,
        iterations: int | None = 1,
        baseline: bool = False,
        frame: str = "quad",
        mission_file: str | Path | None = None,
        mutate_mission: bool = True,
        location: str | None = None,
        heartbeat_stop_after_s: float | None = None,
        show_map: bool = False,
        show_console: bool = False,
    ) -> CampaignResult:
        if iterations is not None and (
            isinstance(iterations, bool) or not isinstance(iterations, int) or iterations <= 0
        ):
            raise ValueError("iterations must be a positive integer or None for until-stopped mode")
        if (
            mission_file is not None
            and mutate_mission
            and (iterations is None or iterations > 1)
            and not config.mission_mutation.has_variability
        ):
            raise ValueError("mission mutation needs at least one non-degenerate setting for multiple iterations")
        campaign_mode = "until_stopped" if iterations is None else "fixed_count"

        self.results_dir.mkdir(parents=True, exist_ok=True)
        campaign_id = self._new_campaign_id()
        campaign_dir = self.results_dir / campaign_id
        campaign_dir.mkdir(parents=False, exist_ok=False)
        runs_dir = campaign_dir / "runs"
        runs_dir.mkdir()
        missions_dir = campaign_dir / "missions"
        used_mission_digests: set[str] = set()
        summary_path = campaign_dir / "campaign.json"
        summary = {
            "campaign_id": campaign_id,
            "status": "running",
            "mode": campaign_mode,
            "campaign_seed": config.seed,
            "mission_mutation": {
                "enabled": mission_file is not None and mutate_mission,
                "template_path": None if mission_file is None else str(Path(mission_file).resolve()),
                "settings": _mission_settings_dict(config.mission_mutation),
            },
            "requested_iterations": iterations,
            "completed_attempts": 0,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "runs": [],
        }
        self._write_summary(summary_path, summary)

        runner = self.experiment_runner or ExperimentRunner(
            self.ardupilot_dir,
            runs_dir,
            **self.runner_options,
        )
        results: list[RunResult] = []
        used_seeds: set[int] = set()
        interrupted = False
        cleanup_failed = False
        index = 0
        try:
            while iterations is None or index < iterations:
                run_seed = derive_run_seed(config.seed, index)
                if run_seed in used_seeds:
                    raise RuntimeError(f"derived duplicate run seed at iteration {index + 1}")
                used_seeds.add(run_seed)
                iteration = index + 1
                run_config = replace(config, seed=run_seed)
                run_metadata = {
                    "campaign_id": campaign_id,
                    "campaign_mode": campaign_mode,
                    "campaign_seed": config.seed,
                    "iteration": iteration,
                    "iteration_index": index,
                    "requested_iterations": iterations,
                    "run_seed": run_seed,
                }
                index += 1
                try:
                    effective_mission_file = mission_file
                    if mission_file is not None and mutate_mission:
                        missions_dir.mkdir(exist_ok=True)
                        mission_path = missions_dir / f"iteration-{iteration:04d}.waypoints"
                        run_metadata["mission_generation"] = {
                            "enabled": True,
                            "path": str(mission_path.relative_to(campaign_dir)),
                            "run_seed": run_seed,
                            "generation_seed": None,
                            "retry_count": None,
                            "sha256": None,
                            "settings": _mission_settings_dict(run_config.mission_mutation),
                        }
                        try:
                            generated, generation_seed, retry_count, digest = _generate_unique_mission(
                                mission_file,
                                mission_path,
                                run_seed,
                                run_config.mission_mutation,
                                used_mission_digests,
                            )
                        except Exception as exc:
                            raise MissionGenerationError(str(exc)) from exc
                        run_metadata["mission_generation"].update({
                            "generation_seed": generation_seed,
                            "retry_count": retry_count,
                            "sha256": digest,
                            "settings": generated.settings,
                        })
                        effective_mission_file = generated.path
                    elif mission_file is not None:
                        run_metadata["mission_generation"] = {
                            "enabled": False,
                            "path": str(Path(mission_file).resolve()),
                            "run_seed": run_seed,
                            "generation_seed": None,
                            "retry_count": 0,
                            "sha256": None,
                            "settings": None,
                        }
                    result = runner.run(
                        run_config,
                        baseline=baseline,
                        frame=frame,
                        mission_file=effective_mission_file,
                        location=location,
                        heartbeat_stop_after_s=heartbeat_stop_after_s,
                        show_map=show_map,
                        show_console=show_console,
                        campaign=run_metadata,
                    )
                except KeyboardInterrupt:
                    interrupted = True
                    summary["completed_attempts"] = len(summary["runs"])
                    break
                except Exception as exc:
                    # Preserve an attempt record even when setup fails before
                    # ExperimentRunner can produce its normal RunResult.
                    failed_dir = runs_dir / f"iteration-{iteration:04d}-setup-error"
                    failed_dir.mkdir(exist_ok=True)
                    record_path = failed_dir / "experiment.json"
                    if isinstance(exc, MissionGenerationError):
                        termination_reason = f"mission_generation_error:{exc.__cause__ or exc}"
                    else:
                        termination_reason = f"campaign_runner_error:{type(exc).__name__}:{exc}"
                    error_record = {
                        **run_metadata,
                        "run_id": failed_dir.name,
                        "seed": run_seed,
                        "status": "failed",
                        "termination_reason": termination_reason,
                    }
                    record_path.write_text(json.dumps(error_record, indent=2) + "\n", encoding="utf-8")
                    entry = {
                        **run_metadata,
                        "status": "failed",
                        "termination_reason": termination_reason,
                        "record": str(record_path.relative_to(campaign_dir)),
                        "effective_drift": None,
                    }
                    summary["runs"].append(entry)
                    summary["completed_attempts"] = len(summary["runs"])
                    self._write_summary(summary_path, summary)
                    continue

                results.append(result)
                entry = {
                    **run_metadata,
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "record": str(result.record_path.relative_to(campaign_dir)),
                    "effective_drift": self._effective_drift(result),
                }
                summary["runs"].append(entry)
                summary["completed_attempts"] = len(summary["runs"])
                self._write_summary(summary_path, summary)
                if result.termination_reason == "user_interrupted":
                    interrupted = True
                    break
                if not result.cleanup_complete:
                    cleanup_failed = True
                    break
        except KeyboardInterrupt:
            interrupted = True

        summary["status"] = (
            "interrupted" if interrupted
            else "cleanup_failed" if cleanup_failed
            else "completed"
        )
        summary["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        self._write_summary(summary_path, summary)
        return CampaignResult(
            campaign_id=campaign_id,
            status=summary["status"],
            requested_iterations=iterations,
            completed_attempts=summary["completed_attempts"],
            record_path=summary_path,
            runs=tuple(results),
        )
