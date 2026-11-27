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
from .mission import MAV_CMD_NAV_LAND, MissionRoute
from .outcome import (
    DEFAULT_DEVIATION_LIMIT_M,
    DEFAULT_PROGRESS_TIMEOUT_S,
    LANDED_RELATIVE_ALTITUDE_M,
    MissionOutcomeMonitor,
)
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
    cleanup_complete: bool = True
    simulation_speedup: float | None = None


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

    def _open_mavlink(self, port: int = 5760):
        if self.mavlink_factory is not None:
            return self.mavlink_factory()
        from pymavlink import mavutil

        return mavutil.mavlink_connection(
            f"udpin:127.0.0.1:{port}", autoreconnect=True
        )

    @staticmethod
    def _mission_outcome_record(
        monitor: MissionOutcomeMonitor | None,
        category: str,
        reason: str,
        termination_reason: str,
    ) -> dict:
        """Serialize a finding separately from the event ending observation."""
        evidence = {} if monitor is None else monitor.evidence()
        if monitor is not None and monitor.first_deviation is not None:
            category = "failure"
            reason = "route_deviation"
        return {
            "category": category,
            "reason": reason,
            "termination_reason": termination_reason,
            **evidence,
        }

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

    def _sitl_command(
        self,
        run_dir: Path,
        frame: str,
        location: str | None,
        *,
        simulation_speedup: float = 2.0,
        show_map: bool = False,
        show_console: bool = False,
    ) -> list[str]:
        mavproxy_enabled = show_map or show_console
        command = [
            sys.executable,
            str(self.ardupilot_dir / "Tools/autotest/sim_vehicle.py"),
            "-v", "ArduCopter", "-f", frame,
            "--no-rebuild", "--udp", "--no-extra-ports",
            "--use-dir", str(run_dir / "sitl"),
            "-S", str(int(simulation_speedup)),
        ]
        if not mavproxy_enabled:
            command.append("--no-mavproxy")
        else:
            # Keep MAVProxy's SITL input on UDP 5760 and send a second copy to
            # GPSFuzzer. --no-extra-ports suppresses default GCS ports, so add
            # this explicit output for the runner's independent telemetry link.
            # The runner has no interactive stdin; keeping MAVProxy's shell in
            # its default mode would make it exit on EOF and stop SITL.
            command.extend(["--out", "127.0.0.1:14550"])
            mavproxy_args = ["--non-interactive"]
            if show_map:
                mavproxy_args.append(
                    '--cmd "map set showgpspos 1; map set showsimpos 1; '
                    'map set showahrspos 1"'
                )
                command.append("--map")
            if show_console:
                command.append("--console")
            command.extend(["--mavproxy-args", " ".join(mavproxy_args)])
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
        if process is None:
            return
        process_group = process.pid
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            if process.poll() is None:
                process.terminate()
        except (OSError, AttributeError):
            if process.poll() is None:
                process.terminate()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                break
            except (OSError, AttributeError):
                if process.poll() is not None:
                    break
            if process.poll() is not None:
                try:
                    process.wait(timeout=0)
                except (subprocess.TimeoutExpired, ChildProcessError):
                    pass
            time.sleep(0.05)

        try:
            os.killpg(process_group, 0)
        except (ProcessLookupError, OSError, AttributeError):
            pass
        else:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except (OSError, AttributeError):
                if process.poll() is None:
                    process.kill()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
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
    def _drain_telemetry(cls, connection, stream, observer=None) -> int:
        count = 0
        if connection is None:
            return count
        while True:
            message = connection.recv_match(blocking=False)
            if message is None:
                break
            count += cls._write_telemetry_message(stream, message)
            if observer is not None:
                observer.consume(message)
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
        show_map: bool = False,
        show_console: bool = False,
        campaign: dict | None = None,
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
        mission_run = mission_file is not None
        initial_drift = None if baseline or mission_run else effective
        mission_gate = {
            "takeoff_started_monotonic_ns": None,
            "auto_confirmed_monotonic_ns": None,
            "takeoff_detected_monotonic_ns": None,
            "takeoff_wait_s": None,
            "command_sequence": None,
            "drift_command_sequence": None,
            "hook_ack_simulation_time_us": None,
            "landing_drift_disable": None,
        }
        mission_count = None
        mission_route = None
        outcome_monitor = None
        mission_outcome = None
        effective_simulation_speedup = None
        simulation_speedup_applied_monotonic_ns = None
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
        cleanup_errors: list[str] = []
        cleanup_complete = True
        last_publish = 0.0
        drift_disabled = False
        landing_disable_failed = False
        mission_auto_confirmed = False
        pending_outcome_messages = []
        mavproxy_enabled = show_map or show_console
        mavlink_port = 14550 if mavproxy_enabled else 5760
        command = self._sitl_command(
            run_dir,
            frame,
            location,
            simulation_speedup=config.simulation_speedup,
            show_map=show_map,
            show_console=show_console,
        )

        def disable_drift_for_landing(trigger_at=None, *, wait_for_ack=True) -> None:
            nonlocal sequence, last_publish, drift_disabled, landing_disable_failed
            nonlocal telemetry_count
            if mission_gate["landing_drift_disable"] is not None:
                return
            if trigger_at is None and outcome_monitor is not None:
                trigger_at = outcome_monitor.terminal_land_active_at
            if trigger_at is None:
                return
            sequence += 1
            mission_gate["command_sequence"] = sequence
            disabled = {
                "triggered_monotonic_ns": round(trigger_at * 1_000_000_000),
                "command_sequence": sequence,
                "acknowledged": False,
                "acknowledged_monotonic_ns": None,
                "hook_ack_simulation_time_us": None,
                "hook_state": None,
                "failure_reason": None,
            }
            mission_gate["landing_drift_disable"] = disabled
            block.write_command(encode_command(
                sequence,
                experiment_id,
                None,
                published_monotonic_ns=time.monotonic_ns(),
            ))
            drift_disabled = True
            last_publish = time.monotonic()
            if not wait_for_ack:
                return

            deadline = last_publish + self.ready_timeout_s
            while time.monotonic() < deadline:
                if process is not None and process.poll() is not None:
                    disabled["failure_reason"] = "sitl_exited_before_disable_ack"
                    break
                try:
                    status = block.read_status()
                except ValueError:
                    status = None
                if status is not None:
                    hook_events.append({
                        "monotonic_ns": time.monotonic_ns(),
                        "event": "landing_drift_disable",
                        "state": status.state,
                        "acknowledged_sequence": status.acknowledged_sequence,
                        "error_code": status.error_code,
                        "simulation_time_us": status.simulation_time_us,
                    })
                    disabled["hook_state"] = status.state
                    if (
                        status.state == STATE_READY
                        and status.acknowledged_sequence == sequence
                    ):
                        disabled["acknowledged"] = True
                        disabled["acknowledged_monotonic_ns"] = time.monotonic_ns()
                        disabled["hook_ack_simulation_time_us"] = status.simulation_time_us
                        break
                with telemetry_path.open("a", encoding="utf-8") as telemetry:
                    telemetry_count_delta = self._drain_telemetry(
                        connection,
                        telemetry,
                        outcome_monitor,
                    )
                telemetry_count += telemetry_count_delta
                time.sleep(self.poll_interval_s)
            if not disabled["acknowledged"]:
                landing_disable_failed = True
                if disabled["failure_reason"] is None:
                    disabled["failure_reason"] = "landing_disable_unacknowledged"
        effective_config = {
            "seed": config.seed,
            "duration_s": config.duration_s,
            "simulation_speedup": config.simulation_speedup,
            "start_delay_s": config.drift.start_delay_s.__dict__,
            "horizontal_speed_mps": config.drift.horizontal_speed_mps.__dict__,
            "bearing_deg": config.drift.bearing_deg.__dict__,
            "velocity_mode": config.drift.mode.value,
            "mission_mutation": {
                "waypoint_count": {
                    "minimum": config.mission_mutation.waypoint_count[0],
                    "maximum": config.mission_mutation.waypoint_count[1],
                },
                "leg_distance_m": config.mission_mutation.leg_distance_m.__dict__,
                "bearing_deg": config.mission_mutation.bearing_deg.__dict__,
                "altitude_m": config.mission_mutation.altitude_m.__dict__,
            },
        }

        try:
            if mission_file is not None:
                mission_route = MissionRoute.from_file(mission_file)
            block = self.block_factory()
            connection = self._open_mavlink(mavlink_port)
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
                            sequence, experiment_id, initial_drift,
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
                    effective_simulation_speedup = config.simulation_speedup
                    simulation_speedup_applied_monotonic_ns = time.monotonic_ns()
                    mission_failed = False
                    if mission_file is not None:
                        try:
                            from .mission import MissionTakeoffTimeout, upload_and_start_mission

                            def record_mission_message(message):
                                nonlocal telemetry_count, last_publish
                                if message is not None:
                                    with telemetry_path.open("a", encoding="utf-8") as telemetry:
                                        telemetry_count += self._write_telemetry_message(telemetry, message)
                                    observed_at = time.monotonic()
                                    if mission_auto_confirmed:
                                        pending_outcome_messages.append((message, observed_at))
                                        if (
                                            mission_route.final_waypoint.command == MAV_CMD_NAV_LAND
                                            and message.get_type() in {"MISSION_CURRENT", "MISSION_ITEM_REACHED"}
                                            and int(message.seq) >= mission_route.final_waypoint.sequence
                                        ):
                                            disable_drift_for_landing(
                                                observed_at,
                                                wait_for_ack=False,
                                            )
                                now = time.monotonic()
                                if now - last_publish >= self.heartbeat_interval_s:
                                    command_drift = (
                                        effective
                                        if (
                                            mission_gate["takeoff_detected_monotonic_ns"] is not None
                                            and not drift_disabled
                                        )
                                        else None
                                    )
                                    block.write_command(encode_command(
                                        sequence, experiment_id, command_drift,
                                        published_monotonic_ns=time.monotonic_ns(),
                                    ))
                                    last_publish = now

                            def record_auto_confirmation(monotonic_ns):
                                nonlocal mission_auto_confirmed
                                mission_gate["auto_confirmed_monotonic_ns"] = monotonic_ns
                                mission_auto_confirmed = True

                            def record_takeoff_started(monotonic_ns):
                                mission_gate["takeoff_started_monotonic_ns"] = monotonic_ns

                            def activate_after_takeoff(monotonic_ns):
                                nonlocal sequence, last_publish
                                mission_gate["takeoff_detected_monotonic_ns"] = monotonic_ns
                                mission_gate["takeoff_wait_s"] = round(
                                    (monotonic_ns - mission_gate["takeoff_started_monotonic_ns"])
                                    / 1_000_000_000,
                                    6,
                                )
                                sequence += 1
                                mission_gate["command_sequence"] = sequence
                                command_drift = None if baseline else effective
                                if command_drift is not None:
                                    mission_gate["drift_command_sequence"] = sequence
                                block.write_command(encode_command(
                                    sequence,
                                    experiment_id,
                                    command_drift,
                                    published_monotonic_ns=time.monotonic_ns(),
                                ))
                                last_publish = time.monotonic()

                            mission_count = upload_and_start_mission(
                                connection,
                                mission_file,
                                takeoff_timeout_s=120.0,
                                on_message=record_mission_message,
                                on_auto_confirmed=record_auto_confirmation,
                                on_takeoff_started=record_takeoff_started,
                                on_takeoff=activate_after_takeoff,
                            )
                            # The hook starts its simulation-time delay when it
                            # consumes a fresh sequence, so wait for that ack
                            # before starting the experiment duration clock.
                            ack_deadline = time.monotonic() + self.ready_timeout_s
                            while time.monotonic() < ack_deadline:
                                if process.poll() is not None:
                                    if mission_gate["landing_drift_disable"] is not None:
                                        mission_gate["landing_drift_disable"]["failure_reason"] = (
                                            "sitl_exited_before_disable_ack"
                                        )
                                        landing_disable_failed = True
                                        break
                                    raise RuntimeError("SITL exited before acknowledging takeoff command")
                                with telemetry_path.open("a", encoding="utf-8") as telemetry:
                                    while True:
                                        message = connection.recv_match(blocking=False)
                                        if message is None:
                                            break
                                        telemetry_count += self._write_telemetry_message(
                                            telemetry, message,
                                        )
                                        observed_at = time.monotonic()
                                        pending_outcome_messages.append((message, observed_at))
                                        if (
                                            mission_auto_confirmed
                                            and mission_route.final_waypoint.command == MAV_CMD_NAV_LAND
                                            and message.get_type() in {"MISSION_CURRENT", "MISSION_ITEM_REACHED"}
                                            and int(message.seq) >= mission_route.final_waypoint.sequence
                                        ):
                                            disable_drift_for_landing(
                                                observed_at,
                                                wait_for_ack=False,
                                            )
                                status = block.read_status()
                                if (
                                    status.state == STATE_READY
                                    and status.acknowledged_sequence == mission_gate["command_sequence"]
                                ):
                                    mission_gate["hook_ack_simulation_time_us"] = status.simulation_time_us
                                    landing_disable = mission_gate["landing_drift_disable"]
                                    if (
                                        landing_disable is not None
                                        and landing_disable["command_sequence"] == status.acknowledged_sequence
                                    ):
                                        landing_disable["acknowledged"] = True
                                        landing_disable["acknowledged_monotonic_ns"] = time.monotonic_ns()
                                        landing_disable["hook_ack_simulation_time_us"] = status.simulation_time_us
                                        landing_disable["hook_state"] = status.state
                                    hook_events.append({
                                        "monotonic_ns": time.monotonic_ns(),
                                        "state": status.state,
                                        "acknowledged_sequence": status.acknowledged_sequence,
                                        "error_code": status.error_code,
                                        "simulation_time_us": status.simulation_time_us,
                                    })
                                    break
                                if status.state in (STATE_STALE,):
                                    if mission_gate["landing_drift_disable"] is not None:
                                        mission_gate["landing_drift_disable"]["failure_reason"] = (
                                            "landing_disable_hook_stale"
                                        )
                                        landing_disable_failed = True
                                        break
                                    raise RuntimeError("GPS mutation hook became stale at takeoff")
                                time.sleep(self.poll_interval_s)
                            else:
                                if mission_gate["landing_drift_disable"] is not None:
                                    mission_gate["landing_drift_disable"]["failure_reason"] = (
                                        "landing_disable_unacknowledged"
                                    )
                                    landing_disable_failed = True
                                else:
                                    raise TimeoutError("GPS mutation hook did not acknowledge takeoff command")
                            ready_at = time.monotonic()
                            outcome_monitor = MissionOutcomeMonitor(
                                mission_route,
                                started_at=ready_at,
                            )
                            for message, observed_at in pending_outcome_messages:
                                outcome_monitor.consume(message, now=observed_at)
                            if outcome_monitor.terminal_land_active_at is not None:
                                disable_drift_for_landing()
                        except MissionTakeoffTimeout as exc:
                            if mission_gate["takeoff_started_monotonic_ns"] is not None:
                                mission_gate["takeoff_wait_s"] = round(
                                    (time.monotonic_ns() - mission_gate["takeoff_started_monotonic_ns"])
                                    / 1_000_000_000,
                                    6,
                                )
                            termination_reason = f"mission_takeoff_timeout:{exc}"
                            run_status = "incomplete"
                            mission_outcome = {
                                "category": "incomplete",
                                "reason": "mission_takeoff_timeout",
                            }
                            mission_failed = True
                        except Exception as exc:
                            termination_reason = f"mission_start_failed:{type(exc).__name__}:{exc}"
                            mission_outcome = {
                                "category": "failed",
                                "reason": "mission_start_failed",
                            }
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
                                sequence, experiment_id, None if drift_disabled else effective,
                                published_monotonic_ns=time.monotonic_ns(),
                            ))
                            last_publish = now
                        try:
                            status = block.read_status()
                            if not landing_disable_failed and (
                                status.state != STATE_READY
                                or status.acknowledged_sequence != sequence
                            ):
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
                            if not landing_disable_failed and not block.is_fresh():
                                termination_reason = "hook_status_stale"
                                run_status = "incomplete"
                                break
                        except ValueError:
                            if not landing_disable_failed:
                                termination_reason = "hook_status_invalid"
                                run_status = "incomplete"
                                break
                        with telemetry_path.open("a", encoding="utf-8") as telemetry:
                            telemetry_count += self._drain_telemetry(
                                connection,
                                telemetry,
                                outcome_monitor if mission_run else None,
                            )
                        if outcome_monitor is not None:
                            if outcome_monitor.terminal_land_active_at is not None:
                                disable_drift_for_landing()
                            detected = outcome_monitor.evaluate(now=time.monotonic())
                            if detected is not None:
                                termination_reason = detected.termination_reason or detected.reason
                                mission_outcome = self._mission_outcome_record(
                                    outcome_monitor,
                                    detected.category,
                                    detected.reason,
                                    termination_reason,
                                )
                                run_status = "completed" if detected.category == "success" else "failed"
                                if landing_disable_failed:
                                    mission_outcome["mission_terminal_reason"] = termination_reason
                                    mission_outcome["category"] = "incomplete"
                                    mission_outcome["reason"] = "landing_disable_unacknowledged"
                                    termination_reason = "landing_disable_unacknowledged"
                                    run_status = "incomplete"
                                break
                        if not telemetry_requested:
                            telemetry_requested = self._request_telemetry_streams(connection)
                        time.sleep(self.poll_interval_s)
                    if mission_run and mission_outcome is None and not mission_failed:
                        if run_status == "completed" and termination_reason == "duration_elapsed":
                            run_status = "incomplete"
                            termination_reason = "mission_duration_expired"
                        mission_outcome = self._mission_outcome_record(
                            outcome_monitor, "incomplete", termination_reason,
                            termination_reason,
                        )
                        if landing_disable_failed:
                            mission_outcome["mission_terminal_reason"] = termination_reason
                            mission_outcome["category"] = "incomplete"
                            mission_outcome["reason"] = "landing_disable_unacknowledged"
                            termination_reason = "landing_disable_unacknowledged"
                            run_status = "incomplete"
            finally:
                console.close()
        except KeyboardInterrupt:
            termination_reason = "user_interrupted"
            run_status = "incomplete"
            if mission_run and mission_outcome is None:
                mission_outcome = self._mission_outcome_record(
                    outcome_monitor, "incomplete", "user_interrupted", "user_interrupted",
                )
        except Exception as exc:
            termination_reason = f"runner_error:{type(exc).__name__}:{exc}"
            run_status = "failed" if ready_at is None else "incomplete"
            if mission_run and mission_outcome is None:
                mission_outcome = self._mission_outcome_record(
                    outcome_monitor,
                    "incomplete" if ready_at is not None else "failed",
                    "runner_error",
                    termination_reason,
                )
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
            try:
                self.process_stopper(process)
            except Exception as exc:
                cleanup_complete = False
                cleanup_errors.append(f"process_group_cleanup:{type(exc).__name__}:{exc}")
            if connection is not None:
                try:
                    connection.close()
                except Exception as exc:
                    cleanup_complete = False
                    cleanup_errors.append(f"mavlink_close:{type(exc).__name__}:{exc}")
            if block is not None:
                try:
                    block.close(remove=True)
                except Exception as exc:
                    cleanup_complete = False
                    cleanup_errors.append(f"shared_memory_cleanup:{type(exc).__name__}:{exc}")

        ended_at = time.monotonic()
        if mission_run and mission_outcome is None:
            mission_outcome = self._mission_outcome_record(
                outcome_monitor,
                "incomplete" if run_status == "incomplete" else "failed",
                termination_reason,
                termination_reason,
            )
        if mission_run and landing_disable_failed:
            if mission_outcome is None:
                mission_outcome = self._mission_outcome_record(
                    outcome_monitor,
                    "incomplete",
                    "landing_disable_unacknowledged",
                    termination_reason,
                )
            else:
                mission_outcome["mission_terminal_reason"] = mission_outcome.get(
                    "termination_reason", termination_reason,
                )
            mission_outcome["category"] = "incomplete"
            mission_outcome["reason"] = "landing_disable_unacknowledged"
            run_status = "incomplete"
            termination_reason = "landing_disable_unacknowledged"
        sitl_log_files = sorted(str(path) for path in sitl_dir.rglob("*.BIN"))
        if cleanup_errors:
            run_status = "failed"
            termination_reason = f"{termination_reason};cleanup_failed"
        record = {
            "run_id": run_id,
            "campaign": campaign,
            "status": run_status,
            "termination_reason": termination_reason,
            "cleanup": {
                "complete": cleanup_complete,
                "errors": cleanup_errors,
            },
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
                "mavproxy_enabled": mavproxy_enabled,
                "map_enabled": show_map,
                "console_enabled": show_console,
                "telemetry_port": mavlink_port,
                "simulation_speedup": {
                    "requested": config.simulation_speedup,
                    "effective": effective_simulation_speedup,
                    "applied": effective_simulation_speedup is not None,
                    "application": "sim_vehicle_-S",
                    "applied_monotonic_ns": simulation_speedup_applied_monotonic_ns,
                },
            },
            "mission": {
                "path": None if mission_file is None else str(Path(mission_file).resolve()),
                "generation": None if campaign is None else campaign.get("mission_generation"),
                "items_uploaded": mission_count,
                "takeoff_gate": None if not mission_run else mission_gate,
                "landing_drift_disable": (
                    None if not mission_run else mission_gate["landing_drift_disable"]
                ),
                "outcome": mission_outcome,
                "thresholds": None if not mission_run else {
                    "deviation_limit_m": DEFAULT_DEVIATION_LIMIT_M,
                    "landing_radius_m": DEFAULT_DEVIATION_LIMIT_M,
                    "progress_timeout_s": DEFAULT_PROGRESS_TIMEOUT_S,
                    "disarmed_landing_altitude_limit_m": LANDED_RELATIVE_ALTITUDE_M,
                },
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
            cleanup_complete, effective_simulation_speedup,
        )
