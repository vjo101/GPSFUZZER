"""ArduCopter SITL lifecycle, telemetry capture, and provenance records."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable

from .config import ExperimentConfig
from .drift import EffectiveDrift, sample_drift
from .ipc import (
    STATE_READY,
    STATE_STALE,
    SystemVGPSBlock,
    encode_command,
)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    termination_reason: str
    duration_s: float
    effective_drift: EffectiveDrift | None
    record_path: Path


class ExperimentRunner:
    """Run one baseline or open-loop drift experiment against ArduCopter SITL."""

    def __init__(
        self,
        ardupilot_dir: str | Path,
        results_dir: str | Path,
        *,
        process_factory: Callable = subprocess.Popen,
        mavlink_factory: Callable | None = None,
        block_factory: Callable = SystemVGPSBlock,
        process_stopper: Callable | None = None,
        ready_timeout_s: float = 45.0,
        poll_interval_s: float = 0.05,
        heartbeat_interval_s: float = 0.5,
    ) -> None:
        self.ardupilot_dir = Path(ardupilot_dir).resolve()
        self.results_dir = Path(results_dir).resolve()
        self.process_factory = process_factory
        self.mavlink_factory = mavlink_factory
        self.block_factory = block_factory
        self.process_stopper = process_stopper or self._stop_process
        self.ready_timeout_s = ready_timeout_s
        self.poll_interval_s = poll_interval_s
        self.heartbeat_interval_s = heartbeat_interval_s

    def _open_mavlink(self):
        if self.mavlink_factory is not None:
            return self.mavlink_factory()
        from pymavlink import mavutil

        return mavutil.mavlink_connection(
            "udpin:127.0.0.1:5760", autoreconnect=True
        )

    @staticmethod
    def _revision(repository: Path) -> dict | None:
        try:
            commit = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
            diff = subprocess.check_output(
                ["git", "-C", str(repository), "diff", "HEAD", "--binary"],
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            untracked = subprocess.check_output(
                ["git", "-C", str(repository), "ls-files", "--others", "--exclude-standard", "-z"],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).split(b"\0")
            digest = hashlib.sha256(diff)
            has_untracked = False
            for encoded_path in sorted(filter(None, untracked)):
                path = repository / os.fsdecode(encoded_path)
                if path.is_file():
                    has_untracked = True
                    digest.update(encoded_path)
                    digest.update(path.read_bytes())
            status = subprocess.check_output(
                ["git", "-C", str(repository), "status", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            dirty = bool(status.strip())
            return {
                "commit": commit,
                "dirty": dirty,
                "worktree_sha256": digest.hexdigest() if dirty else None,
                "untracked_files_present": has_untracked,
            }
        except (OSError, subprocess.SubprocessError):
            return None

    def _sitl_command(self, run_dir: Path, frame: str, location: str | None) -> list[str]:
        command = [
            sys.executable,
            str(self.ardupilot_dir / "Tools/autotest/sim_vehicle.py"),
            "-v", "ArduCopter", "-f", frame,
            "--no-rebuild", "--no-mavproxy", "--udp", "--no-extra-ports",
            "--use-dir", str(run_dir / "sitl"),
            "-S", "1",
        ]
        if location is not None:
            command.extend(["--custom-location", location])
        return command

    @staticmethod
    def _validate_location(location: str | None) -> None:
        if location is None:
            return
        try:
            latitude, longitude, altitude, heading = (float(value) for value in location.split(","))
        except (TypeError, ValueError) as exc:
            raise ValueError("location must be LAT,LON,ALT,HEADING") from exc
        if not all(map(math.isfinite, (latitude, longitude, altitude, heading))):
            raise ValueError("location values must be finite")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 <= heading <= 360):
            raise ValueError("location latitude, longitude, or heading is out of range")

    @staticmethod
    def _stop_process(process) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, AttributeError):
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, AttributeError):
                process.kill()
            process.wait(timeout=5)

    @staticmethod
    def _write_telemetry_message(stream, message) -> bool:
        kind = message.get_type()
        if kind in {"BAD_DATA", "UNKNOWN"}:
            return False
        stream.write(json.dumps({
            "host_monotonic_ns": time.monotonic_ns(),
            "type": kind,
            "data": message.to_dict(),
        }, default=str) + "\n")
        return True

    @classmethod
    def _drain_telemetry(cls, connection, stream) -> int:
        count = 0
        if connection is None:
            return count
        while True:
            message = connection.recv_match(blocking=False)
            if message is None:
                break
            count += cls._write_telemetry_message(stream, message)
        stream.flush()
        return count

    @staticmethod
    def _request_telemetry_streams(connection) -> bool:
        """Ask ArduPilot for its normal data streams after a heartbeat arrives."""
        if connection is None or not getattr(connection, "target_system", 0):
            return False
        mav = getattr(connection, "mav", None)
        request = getattr(mav, "request_data_stream_send", None)
        if request is None:
            return False
        request(
            connection.target_system,
            connection.target_component,
            0,  # MAV_DATA_STREAM_ALL
            4,
            1,
        )
        return True

    def run(
        self,
        config: ExperimentConfig,
        *,
        baseline: bool = False,
        frame: str = "quad",
        mission_file: str | Path | None = None,
        location: str | None = None,
        heartbeat_stop_after_s: float | None = None,
    ) -> RunResult:
        """Run SITL, fail on unavailable/stale hook, and retain partial outputs."""
        self._validate_location(location)
        if heartbeat_stop_after_s is not None and (
            not math.isfinite(heartbeat_stop_after_s) or heartbeat_stop_after_s < 0
        ):
            raise ValueError("heartbeat_stop_after_s must be non-negative and finite")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_dir = self.results_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        sitl_dir = run_dir / "sitl"
        sitl_dir.mkdir()
        console_path = run_dir / "sitl_console.log"
        telemetry_path = run_dir / "telemetry.jsonl"
        record_path = run_dir / "experiment.json"
        gps_root = Path(__file__).resolve().parents[1]
        effective = None if baseline else sample_drift(config.drift, config.seed)
        experiment_id = time.time_ns() & ((1 << 63) - 1)
        sequence = 1
        process = None
        connection = None
        block = None
        started_at = time.monotonic()
        ready_at = None
        termination_reason = "not_started"
        run_status = "failed"
        telemetry_count = 0
        telemetry_requested = False
        hook_events: list[dict] = []
        last_publish = 0.0
        command = self._sitl_command(run_dir, frame, location)
        effective_config = {
            "seed": config.seed,
            "duration_s": config.duration_s,
            "start_delay_s": config.drift.start_delay_s.__dict__,
            "horizontal_speed_mps": config.drift.horizontal_speed_mps.__dict__,
            "bearing_deg": config.drift.bearing_deg.__dict__,
            "velocity_mode": config.drift.mode.value,
        }

        try:
            block = self.block_factory()
            connection = self._open_mavlink()
            console = console_path.open("w", encoding="utf-8")
            try:
                process = self.process_factory(
                    command,
                    cwd=self.ardupilot_dir,
                    stdout=console,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                while time.monotonic() - started_at < self.ready_timeout_s:
                    if process.poll() is not None:
                        termination_reason = f"sitl_exited_before_ready:{process.returncode}"
                        break
                    now = time.monotonic()
                    if now - last_publish >= self.heartbeat_interval_s:
                        block.write_command(encode_command(
                            sequence, experiment_id, effective,
                            published_monotonic_ns=time.monotonic_ns(),
                        ))
                        last_publish = now
                    with telemetry_path.open("a", encoding="utf-8") as telemetry:
                        telemetry_count += self._drain_telemetry(connection, telemetry)
                    if not telemetry_requested:
                        telemetry_requested = self._request_telemetry_streams(connection)
                    try:
                        status = block.read_status()
                    except ValueError:
                        status = None
                    if status is not None:
                        hook_events.append({
                            "monotonic_ns": time.monotonic_ns(),
                            "state": status.state,
                            "acknowledged_sequence": status.acknowledged_sequence,
                            "error_code": status.error_code,
                            "simulation_time_us": status.simulation_time_us,
                        })
                        if status.state == STATE_READY and status.acknowledged_sequence == sequence:
                            ready_at = time.monotonic()
                            break
                    time.sleep(self.poll_interval_s)
                if ready_at is None:
                    if termination_reason == "not_started":
                        termination_reason = "hook_unavailable_or_not_ready"
                    run_status = "failed"
                else:
                    mission_count = None
                    mission_failed = False
                    if mission_file is not None:
                        try:
                            from .mission import upload_and_start_mission

                            def record_mission_message(message):
                                nonlocal telemetry_count, last_publish
                                if message is not None:
                                    with telemetry_path.open("a", encoding="utf-8") as telemetry:
                                        telemetry_count += self._write_telemetry_message(telemetry, message)
                                now = time.monotonic()
                                if now - last_publish >= self.heartbeat_interval_s:
                                    block.write_command(encode_command(
                                        sequence, experiment_id, effective,
                                        published_monotonic_ns=time.monotonic_ns(),
                                    ))
                                    last_publish = now

                            mission_count = upload_and_start_mission(
                                connection, mission_file, on_message=record_mission_message
                            )
                            ready_at = time.monotonic()
                        except Exception as exc:
                            termination_reason = f"mission_start_failed:{type(exc).__name__}:{exc}"
                            mission_failed = True
                    if not mission_failed:
                        termination_reason = "duration_elapsed"
                        run_status = "completed"
                    while not mission_failed and time.monotonic() - ready_at < config.duration_s:
                        if process.poll() is not None:
                            termination_reason = f"sitl_exited:{process.returncode}"
                            run_status = "incomplete"
                            break
                        now = time.monotonic()
                        if (
                            heartbeat_stop_after_s is None
                            or now - ready_at < heartbeat_stop_after_s
                        ) and now - last_publish >= self.heartbeat_interval_s:
                            block.write_command(encode_command(
                                sequence, experiment_id, effective,
                                published_monotonic_ns=time.monotonic_ns(),
                            ))
                            last_publish = now
                        try:
                            status = block.read_status()
                            if status.state != STATE_READY or status.acknowledged_sequence != sequence:
                                hook_events.append({
                                    "monotonic_ns": time.monotonic_ns(),
                                    "state": status.state,
                                    "acknowledged_sequence": status.acknowledged_sequence,
                                    "error_code": status.error_code,
                                    "simulation_time_us": status.simulation_time_us,
                                })
                                termination_reason = (
                                    "hook_command_stale" if status.state == STATE_STALE
                                    else "hook_invalid_or_ack_lost"
                                )
                                run_status = "incomplete"
                                break
                            if not block.is_fresh():
                                termination_reason = "hook_status_stale"
                                run_status = "incomplete"
                                break
                        except ValueError:
                            termination_reason = "hook_status_invalid"
                            run_status = "incomplete"
                            break
                        with telemetry_path.open("a", encoding="utf-8") as telemetry:
                            telemetry_count += self._drain_telemetry(connection, telemetry)
                        if not telemetry_requested:
                            telemetry_requested = self._request_telemetry_streams(connection)
                        time.sleep(self.poll_interval_s)
            finally:
                console.close()
        except Exception as exc:
            termination_reason = f"runner_error:{type(exc).__name__}:{exc}"
            run_status = "failed" if ready_at is None else "incomplete"
        finally:
            if block is not None:
                try:
                    disable_sequence = sequence + 1
                    block.disable(disable_sequence, experiment_id)
                    deadline = time.monotonic() + 0.5
                    while process is not None and process.poll() is None and time.monotonic() < deadline:
                        try:
                            status = block.read_status()
                            if status.acknowledged_sequence == disable_sequence:
                                hook_events.append({
                                    "monotonic_ns": time.monotonic_ns(),
                                    "state": status.state,
                                    "acknowledged_sequence": status.acknowledged_sequence,
                                    "error_code": status.error_code,
                                    "simulation_time_us": status.simulation_time_us,
                                })
                                break
                        except ValueError:
                            pass
                        time.sleep(self.poll_interval_s)
                except Exception:
                    pass
            self.process_stopper(process)
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            if block is not None:
                block.close(remove=True)

        ended_at = time.monotonic()
        sitl_log_files = sorted(str(path) for path in sitl_dir.rglob("*.BIN"))
        record = {
            "run_id": run_id,
            "status": run_status,
            "termination_reason": termination_reason,
            "seed": config.seed,
            "configuration": effective_config,
            "effective_drift": None if effective is None else {
                "start_delay_s": effective.start_delay_s,
                "horizontal_speed_mps": effective.horizontal_speed_mps,
                "bearing_deg": effective.bearing_deg,
                "velocity_mode": effective.mode.value,
            },
            "source_revisions": {
                "gpsfuzzer": self._revision(gps_root),
                "ardupilot": self._revision(self.ardupilot_dir),
            },
            "sitl": {
                "command": command,
                "cwd": str(self.ardupilot_dir),
                "frame": frame,
                "custom_location": location,
            },
            "mission": {
                "path": None if mission_file is None else str(Path(mission_file).resolve()),
                "items_uploaded": locals().get("mission_count"),
            },
            "communication_fault_injection": {
                "heartbeat_stop_after_s": heartbeat_stop_after_s,
            },
            "duration_s": round(ended_at - started_at, 3),
            "telemetry_messages": telemetry_count,
            "hook_status_events": hook_events,
            "log_paths": {
                "console": str(console_path),
                "telemetry": str(telemetry_path),
                "dataflash": sitl_log_files,
            },
        }
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return RunResult(
            run_id, run_status, termination_reason,
            round(ended_at - started_at, 3), effective, record_path,
        )
