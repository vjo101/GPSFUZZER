import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from gpsfuzzer import DriftConfig, DriftMode, ExperimentConfig, NumericRange
from gpsfuzzer.ipc import HookStatus, STATE_READY, STATE_STARTING, COMMAND_FORMAT
from gpsfuzzer.runner import ExperimentRunner


class FakeBlock:
    def __init__(self, state=STATE_READY, fresh=True, ack=1):
        self.state = state
        self.fresh = fresh
        self.ack = ack
        self.commands = []
        self.removed = False

    def write_command(self, data):
        command = COMMAND_FORMAT.unpack(data)
        self.commands.append(command)
        self.ack = command[3]

    def read_status(self):
        return HookStatus(self.ack, self.state, 0, 1000, 1000, 1)

    def is_fresh(self):
        return self.fresh

    def disable(self, sequence, experiment_id):
        self.ack = sequence
        self.commands.append((0, 0, 0, sequence, experiment_id, 0))

    def close(self, remove=False):
        self.removed = remove


class FakeProcess:
    pid = 0
    returncode = None

    def poll(self):
        return None


class FakeConnection:
    target_system = 1
    target_component = 1

    class Mav:
        def request_data_stream_send(self, *args):
            self.last_request = args

    def __init__(self):
        self.mav = self.Mav()
        self.mission_messages = []
        self.mission_started = False

    def recv_match(self, blocking=False):
        if self.mission_started and self.mission_messages:
            return self.mission_messages.pop(0)
        return None

    def close(self):
        pass


class RunnerTests(unittest.TestCase):
    def test_stopper_terminates_entire_sitl_process_group(self):
        child_script = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "time.sleep(60)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", child_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ExperimentRunner._stop_process(process)
        self.assertIsNotNone(process.poll())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            self.fail("SITL process group still exists after cleanup")

    def test_validates_and_records_custom_simulation_location(self):
        ExperimentRunner._validate_location("60.0,24.0,100,0")
        with self.assertRaisesRegex(ValueError, "LAT,LON,ALT,HEADING"):
            ExperimentRunner._validate_location("60,24,100")
        with self.assertRaisesRegex(ValueError, "out of range"):
            ExperimentRunner._validate_location("91,24,100,0")

    def test_gui_mavproxy_command_keeps_process_alive_without_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ExperimentRunner(Path(tmp) / "ap", Path(tmp) / "results")
            command = runner._sitl_command(
                Path(tmp) / "run",
                "quad",
                None,
                show_map=True,
                show_console=True,
            )
            args = command[command.index("--mavproxy-args") + 1]
            self.assertIn("--non-interactive", args)
            self.assertIn("--cmd", args)
            self.assertIn("--map", command)
            self.assertIn("--console", command)

    def _runner(
        self,
        root,
        block,
        timeout=5.0,
        mavlink_factory=FakeConnection,
        process_stopper=None,
    ):
        return ExperimentRunner(
            root / "ardupilot",
            root / "results",
            process_factory=lambda *args, **kwargs: FakeProcess(),
            mavlink_factory=mavlink_factory,
            block_factory=lambda: block,
            process_stopper=process_stopper or (lambda process: None),
            ready_timeout_s=timeout,
            poll_interval_s=0.001,
            heartbeat_interval_s=0.01,
        )

    @staticmethod
    def _write_mission(path):
        path.write_text(
            "QGC WPL 110\n"
            "0\t1\t0\t16\t0\t0\t0\t0\t60.0\t24.0\t100\t1\n"
            "1\t0\t3\t21\t0\t0\t0\t0\t60.0\t24.0\t0\t1\n",
            encoding="utf-8",
        )

    def test_baseline_disables_hook_and_records_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = FakeBlock()
            result = self._runner(root, block).run(
                ExperimentConfig(seed=17, duration_s=0.02), baseline=True
            )
            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "completed")
            self.assertIsNone(record["effective_drift"])
            self.assertEqual(record["status"], "completed")
            self.assertTrue(record["log_paths"]["telemetry"].endswith("telemetry.jsonl"))
            self.assertTrue(block.removed)
            self.assertTrue(any(command[5] == 0 for command in block.commands))

    def test_coherent_and_position_only_modes_are_selectable(self):
        for mode in (DriftMode.COHERENT, DriftMode.POSITION_ONLY):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                block = FakeBlock()
                config = ExperimentConfig(
                    seed=5,
                    duration_s=0.005,
                    drift=DriftConfig(
                        start_delay_s=NumericRange(0, 0),
                        horizontal_speed_mps=NumericRange(1, 1),
                        bearing_deg=NumericRange(90, 90),
                        mode=mode,
                    ),
                )
                result = self._runner(root, block).run(config)
                record = json.loads(result.record_path.read_text())
                self.assertEqual(record["effective_drift"]["velocity_mode"], mode.value)
                first_command = next(command for command in block.commands if len(command) == 12)
                self.assertEqual(first_command[3], 1)
                self.assertEqual(first_command[5], 1)

    def test_mission_command_stays_inactive_until_takeoff_then_uses_new_sequence(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()
            connection = FakeConnection()

            class TelemetryMessage:
                def __init__(self, kind, **fields):
                    self.kind = kind
                    self.__dict__.update(fields)

                def get_type(self):
                    return self.kind

                def to_dict(self):
                    return {key: value for key, value in self.__dict__.items() if key != "kind"}

            uploaded_paths = []

            def upload_and_fly(connection, path, **callbacks):
                uploaded_paths.append(Path(path).resolve())
                callbacks["on_takeoff_started"](150)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](250)
                connection.mission_messages = [
                    TelemetryMessage("MISSION_CURRENT", seq=1),
                    TelemetryMessage("MISSION_ITEM_REACHED", seq=1),
                    TelemetryMessage("EXTENDED_SYS_STATE", landed_state=1),
                    TelemetryMessage(
                        "GLOBAL_POSITION_INT", lat=600_000_000, lon=240_000_000,
                        relative_alt=0,
                    ),
                ]
                connection.mission_started = True
                return 2

            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = self._runner(
                    root, block, mavlink_factory=lambda: connection,
                ).run(
                    ExperimentConfig(
                        seed=5,
                        duration_s=0.005,
                        drift=DriftConfig(
                            start_delay_s=NumericRange(2, 2),
                            horizontal_speed_mps=NumericRange(1, 1),
                            bearing_deg=NumericRange(90, 90),
                        ),
                    ),
                    mission_file=mission_path,
                    campaign={
                        "mission_generation": {
                            "enabled": True,
                            "path": "missions/iteration-0001.waypoints",
                            "generation_seed": 5,
                            "settings": {"leg_distance_m": {"minimum": 60, "maximum": 240}},
                        }
                    },
                )

            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "completed")
            self.assertEqual(record["mission"]["outcome"]["category"], "success")
            self.assertEqual(record["mission"]["outcome"]["reason"], "landed_at_final_waypoint")
            self.assertEqual(uploaded_paths, [mission_path.resolve()])
            self.assertEqual(record["mission"]["path"], str(uploaded_paths[0]))
            self.assertEqual(
                record["mission"]["generation"],
                record["campaign"]["mission_generation"],
            )
            self.assertEqual(
                record["configuration"]["mission_mutation"]["leg_distance_m"],
                {"minimum": 60.0, "maximum": 240.0},
            )
            self.assertEqual(record["mission"]["thresholds"]["deviation_limit_m"], 15.0)
            self.assertEqual(record["mission"]["thresholds"]["progress_timeout_s"], 90.0)
            self.assertEqual(record["telemetry_messages"], 4)
            commands = [command for command in block.commands if len(command) == 12]
            self.assertEqual(commands[0][5], 0)
            self.assertEqual(commands[0][3], 1)
            self.assertEqual(commands[1][5], 1)
            self.assertEqual(commands[1][3], 2)
            gate = record["mission"]["takeoff_gate"]
            self.assertEqual(gate["auto_confirmed_monotonic_ns"], 250)
            self.assertEqual(gate["takeoff_detected_monotonic_ns"], 200)
            self.assertEqual(gate["takeoff_wait_s"], 0.0)
            self.assertEqual(gate["takeoff_started_monotonic_ns"], 150)
            self.assertEqual(gate["command_sequence"], 3)
            self.assertEqual(gate["drift_command_sequence"], 2)
            self.assertEqual(gate["hook_ack_simulation_time_us"], 1000)
            self.assertTrue(gate["landing_drift_disable"]["acknowledged"])
            self.assertEqual(gate["landing_drift_disable"]["command_sequence"], 3)

    def test_landing_disable_stops_drift_before_later_crash(self):
        from unittest.mock import patch

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        class BatchedConnection(FakeConnection):
            def __init__(self):
                super().__init__()
                self.batches = []

            def recv_match(self, blocking=False):
                if not self.mission_started or not self.batches:
                    return None
                batch = self.batches[0]
                if batch:
                    return batch.pop(0)
                self.batches.pop(0)
                time.sleep(0.015)
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()
            connection = BatchedConnection()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                connection.batches = [
                    [
                        TelemetryMessage("MISSION_CURRENT", seq=1),
                        TelemetryMessage("SIMSTATE", lat=600_002_000, lng=240_000_000),
                    ],
                    [TelemetryMessage("STATUSTEXT", text="Crash: Disarming", severity=0)],
                ]
                connection.mission_started = True
                return 2

            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = self._runner(
                    root, block, mavlink_factory=lambda: connection,
                ).run(
                    ExperimentConfig(
                        seed=5,
                        duration_s=1,
                        drift=DriftConfig(
                            start_delay_s=NumericRange(0, 0),
                            horizontal_speed_mps=NumericRange(1, 1),
                            bearing_deg=NumericRange(90, 90),
                        ),
                    ),
                    mission_file=mission_path,
                )

            record = json.loads(result.record_path.read_text())
            outcome = record["mission"]["outcome"]
            self.assertEqual(result.termination_reason, "crash_detected")
            self.assertEqual(outcome["category"], "failure")
            self.assertEqual(outcome["reason"], "route_deviation")
            self.assertEqual(outcome["termination_reason"], "crash_detected")
            self.assertIsNotNone(outcome["first_deviation"])
            self.assertGreater(outcome["maximum_deviation_m"], 15)
            enabled_commands = [
                command for command in block.commands
                if len(command) == 12 and command[5] == 1
            ]
            self.assertEqual(len(enabled_commands), 1)
            disabled = record["mission"]["landing_drift_disable"]
            self.assertTrue(disabled["acknowledged"])
            self.assertEqual(disabled["command_sequence"], 3)

    def test_unacknowledged_landing_disable_keeps_capturing_until_landing(self):
        from unittest.mock import patch

        class NoDisableAckBlock(FakeBlock):
            def write_command(self, data):
                command = COMMAND_FORMAT.unpack(data)
                self.commands.append(command)
                if command[3] < 3 or command[5] != 0:
                    self.ack = command[3]

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = NoDisableAckBlock()
            connection = FakeConnection()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                connection.mission_messages = [
                    TelemetryMessage("MISSION_CURRENT", seq=1),
                    TelemetryMessage("EXTENDED_SYS_STATE", landed_state=1),
                    TelemetryMessage(
                        "GLOBAL_POSITION_INT", lat=600_000_000, lon=240_000_000,
                        relative_alt=0,
                    ),
                ]
                connection.mission_started = True
                return 2

            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = self._runner(
                    root, block, timeout=0.03, mavlink_factory=lambda: connection,
                ).run(
                    ExperimentConfig(seed=5, duration_s=1),
                    mission_file=mission_path,
                )

            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(result.termination_reason, "landing_disable_unacknowledged")
            self.assertEqual(record["mission"]["outcome"]["reason"], "landing_disable_unacknowledged")
            self.assertEqual(
                record["mission"]["outcome"]["mission_terminal_reason"],
                "landed_at_final_waypoint",
            )
            self.assertEqual(record["telemetry_messages"], 3)
            self.assertFalse(record["mission"]["landing_drift_disable"]["acknowledged"])
            active_sequences = [
                command[3] for command in block.commands
                if len(command) == 12 and command[5] == 1
            ]
            self.assertEqual(active_sequences, [2])

    def test_deviation_then_endpoint_landing_records_both_events(self):
        from unittest.mock import patch

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        class BatchedConnection(FakeConnection):
            def __init__(self):
                super().__init__()
                self.batches = []

            def recv_match(self, blocking=False):
                if not self.mission_started or not self.batches:
                    return None
                batch = self.batches[0]
                if batch:
                    return batch.pop(0)
                self.batches.pop(0)
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()
            connection = BatchedConnection()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                connection.batches = [
                    [
                        TelemetryMessage("MISSION_CURRENT", seq=1),
                        TelemetryMessage("SIMSTATE", lat=600_002_000, lng=240_000_000),
                    ],
                    [
                        TelemetryMessage("MISSION_ITEM_REACHED", seq=1),
                        TelemetryMessage("EXTENDED_SYS_STATE", landed_state=1),
                        TelemetryMessage("SIMSTATE", lat=600_000_000, lng=240_000_000),
                    ],
                ]
                connection.mission_started = True
                return 2

            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = self._runner(
                    root, block, mavlink_factory=lambda: connection,
                ).run(
                    ExperimentConfig(seed=5, duration_s=1), mission_file=mission_path,
                )

            record = json.loads(result.record_path.read_text())
            outcome = record["mission"]["outcome"]
            self.assertEqual(result.termination_reason, "landed_at_final_waypoint")
            self.assertEqual(outcome["category"], "failure")
            self.assertEqual(outcome["reason"], "route_deviation")
            self.assertEqual(outcome["termination_reason"], "landed_at_final_waypoint")
            self.assertIsNotNone(outcome["landing_confirmation"])

    def test_duration_expiry_after_deviation_retains_finding_and_stop_cause(self):
        from unittest.mock import patch

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()
            connection = FakeConnection()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                connection.mission_messages = [
                    TelemetryMessage("MISSION_CURRENT", seq=1),
                    TelemetryMessage("SIMSTATE", lat=600_002_000, lng=240_000_000),
                ]
                connection.mission_started = True
                return 2

            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = self._runner(
                    root, block, mavlink_factory=lambda: connection,
                ).run(
                    ExperimentConfig(
                        seed=5,
                        duration_s=0.04,
                        drift=DriftConfig(
                            start_delay_s=NumericRange(0, 0),
                            horizontal_speed_mps=NumericRange(1, 1),
                            bearing_deg=NumericRange(90, 90),
                        ),
                    ),
                    mission_file=mission_path,
                )

            record = json.loads(result.record_path.read_text())
            outcome = record["mission"]["outcome"]
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(result.termination_reason, "mission_duration_expired")
            self.assertEqual(outcome["category"], "failure")
            self.assertEqual(outcome["reason"], "route_deviation")
            self.assertEqual(outcome["termination_reason"], "mission_duration_expired")
            self.assertEqual(
                sum(1 for command in block.commands if len(command) == 12 and command[5] == 1),
                1,
            )
            self.assertTrue(record["mission"]["landing_drift_disable"]["acknowledged"])

    def test_sitl_exit_after_deviation_is_recorded_as_stop_cause(self):
        from unittest.mock import patch

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        class ExitAfterTelemetryProcess(FakeProcess):
            def __init__(self):
                self.poll_count = 0
                self.returncode = None

            def poll(self):
                self.poll_count += 1
                if self.poll_count >= 4:
                    self.returncode = 7
                return self.returncode

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()
            connection = FakeConnection()
            process = ExitAfterTelemetryProcess()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                connection.mission_messages = [
                    TelemetryMessage("MISSION_CURRENT", seq=1),
                    TelemetryMessage("SIMSTATE", lat=600_002_000, lng=240_000_000),
                ]
                connection.mission_started = True
                return 2

            runner = ExperimentRunner(
                root / "ardupilot",
                root / "results",
                process_factory=lambda *args, **kwargs: process,
                mavlink_factory=lambda: connection,
                block_factory=lambda: block,
                process_stopper=lambda proc: None,
                ready_timeout_s=1,
                poll_interval_s=0.001,
                heartbeat_interval_s=0.001,
            )
            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = runner.run(
                    ExperimentConfig(seed=5, duration_s=1), mission_file=mission_path,
                )

            outcome = json.loads(result.record_path.read_text())["mission"]["outcome"]
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(result.termination_reason, "sitl_exited:7")
            self.assertEqual(outcome["category"], "failure")
            self.assertEqual(outcome["reason"], "route_deviation")
            self.assertEqual(outcome["termination_reason"], "sitl_exited:7")
            self.assertTrue(json.loads(result.record_path.read_text())[
                "mission"]["landing_drift_disable"]["acknowledged"])

    def test_user_interruption_after_deviation_keeps_finding_and_stop_cause(self):
        from unittest.mock import patch

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()
            connection = FakeConnection()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                connection.mission_messages = [
                    TelemetryMessage("MISSION_CURRENT", seq=1),
                    TelemetryMessage("SIMSTATE", lat=600_002_000, lng=240_000_000),
                ]
                connection.mission_started = True
                return 2

            with (
                patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly),
                patch("gpsfuzzer.runner.time.sleep", side_effect=KeyboardInterrupt),
            ):
                result = self._runner(
                    root, block, mavlink_factory=lambda: connection,
                ).run(
                    ExperimentConfig(seed=5, duration_s=1), mission_file=mission_path,
                )

            outcome = json.loads(result.record_path.read_text())["mission"]["outcome"]
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(result.termination_reason, "user_interrupted")
            self.assertEqual(outcome["category"], "failure")
            self.assertEqual(outcome["reason"], "route_deviation")
            self.assertEqual(outcome["termination_reason"], "user_interrupted")

    def test_progress_and_landing_timeouts_after_deviation_end_observation(self):
        from unittest.mock import patch
        from gpsfuzzer.outcome import MissionOutcomeMonitor

        class TelemetryMessage:
            def __init__(self, kind, **fields):
                self.kind = kind
                self.__dict__.update(fields)

            def get_type(self):
                return self.kind

            def to_dict(self):
                return {key: value for key, value in self.__dict__.items() if key != "kind"}

        for terminal_reason, include_current in (
            ("waypoint_progress_timeout", False),
            ("landing_timeout", True),
        ):
            with self.subTest(terminal_reason=terminal_reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mission_path = root / "mission.txt"
                self._write_mission(mission_path)
                block = FakeBlock()
                connection = FakeConnection()

                def upload_and_fly(connection, path, **callbacks):
                    callbacks["on_takeoff_started"](100)
                    callbacks["on_takeoff"](200)
                    callbacks["on_auto_confirmed"](300)
                    telemetry = []
                    if include_current:
                        telemetry.append(TelemetryMessage("MISSION_CURRENT", seq=1))
                    telemetry.append(
                        TelemetryMessage("SIMSTATE", lat=600_002_000, lng=240_000_000)
                    )
                    connection.mission_messages = telemetry
                    connection.mission_started = True
                    return 2

                def short_timeout_monitor(route, **kwargs):
                    return MissionOutcomeMonitor(route, progress_timeout_s=0.01, **kwargs)

                with (
                    patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly),
                    patch("gpsfuzzer.runner.MissionOutcomeMonitor", side_effect=short_timeout_monitor),
                ):
                    result = self._runner(
                        root, block, mavlink_factory=lambda: connection,
                    ).run(
                        ExperimentConfig(seed=5, duration_s=0.2), mission_file=mission_path,
                    )

                outcome = json.loads(result.record_path.read_text())["mission"]["outcome"]
                self.assertEqual(result.termination_reason, terminal_reason)
                self.assertEqual(outcome["category"], "failure")
                self.assertEqual(outcome["reason"], "route_deviation")
                self.assertEqual(outcome["termination_reason"], terminal_reason)

    def test_mission_takeoff_timeout_is_incomplete_and_keeps_hook_inactive(self):
        from unittest.mock import patch
        from gpsfuzzer.mission import MissionTakeoffTimeout

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()

            def never_takes_off(connection, path, **callbacks):
                callbacks["on_takeoff_started"](time.monotonic_ns())
                raise MissionTakeoffTimeout("test timeout")

            with patch("gpsfuzzer.mission.upload_and_start_mission", never_takes_off):
                result = self._runner(root, block).run(
                    ExperimentConfig(seed=8, duration_s=0.005),
                    mission_file=mission_path,
                )

            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "incomplete")
            self.assertTrue(record["termination_reason"].startswith("mission_takeoff_timeout:"))
            self.assertIsNone(record["mission"]["takeoff_gate"]["auto_confirmed_monotonic_ns"])
            self.assertIsNone(record["mission"]["takeoff_gate"]["takeoff_detected_monotonic_ns"])
            self.assertGreaterEqual(record["mission"]["takeoff_gate"]["takeoff_wait_s"], 0)
            self.assertIsNone(record["mission"]["takeoff_gate"]["command_sequence"])
            self.assertIsNone(record["mission"]["takeoff_gate"]["drift_command_sequence"])
            self.assertIsNone(record["mission"]["takeoff_gate"]["hook_ack_simulation_time_us"])
            self.assertTrue(all(command[5] == 0 for command in block.commands if len(command) == 12))
            self.assertTrue(Path(record["log_paths"]["telemetry"]).exists())

    def test_mission_duration_expiry_without_an_outcome_is_incomplete(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission_path = root / "mission.txt"
            self._write_mission(mission_path)
            block = FakeBlock()

            def upload_and_fly(connection, path, **callbacks):
                callbacks["on_takeoff_started"](100)
                callbacks["on_takeoff"](200)
                callbacks["on_auto_confirmed"](300)
                return 2

            with patch("gpsfuzzer.mission.upload_and_start_mission", upload_and_fly):
                result = self._runner(root, block).run(
                    ExperimentConfig(seed=9, duration_s=0.005),
                    mission_file=mission_path,
                )

            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(result.termination_reason, "mission_duration_expired")
            self.assertEqual(record["mission"]["outcome"]["category"], "incomplete")
            self.assertEqual(record["mission"]["thresholds"]["landing_radius_m"], 15.0)
            self.assertTrue(Path(record["log_paths"]["telemetry"]).exists())

    def test_unavailable_hook_is_failed_and_record_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = FakeBlock(state=STATE_STARTING)
            result = self._runner(root, block, timeout=0.02).run(
                ExperimentConfig(seed=3, duration_s=1)
            )
            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "failed")
            self.assertEqual(record["termination_reason"], "hook_unavailable_or_not_ready")
            self.assertTrue(result.record_path.exists())
            self.assertTrue(Path(record["log_paths"]["telemetry"]).exists())
            self.assertTrue(block.removed)

    def test_midrun_stale_hook_is_incomplete_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = FakeBlock(fresh=False)
            result = self._runner(root, block).run(
                ExperimentConfig(seed=3, duration_s=1)
            )
            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(record["termination_reason"], "hook_status_stale")
            self.assertIn("source_revisions", record)
            self.assertIn("telemetry", record["log_paths"])

    def test_user_interruption_records_and_cleans_gui_enabled_sitl(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = FakeBlock()
            stopped = []
            runner = self._runner(
                root,
                block,
                process_stopper=lambda process: stopped.append(process),
            )
            with patch("gpsfuzzer.runner.time.sleep", side_effect=KeyboardInterrupt):
                result = runner.run(
                    ExperimentConfig(seed=12, duration_s=2),
                    show_map=True,
                    show_console=True,
                )
            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.termination_reason, "user_interrupted")
            self.assertTrue(result.cleanup_complete)
            self.assertEqual(len(stopped), 1)
            self.assertTrue(record["sitl"]["map_enabled"])
            self.assertTrue(record["sitl"]["console_enabled"])
            self.assertTrue(record["cleanup"]["complete"])
            self.assertTrue(Path(record["log_paths"]["telemetry"]).exists())

    def test_startup_error_still_runs_process_cleanup_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = FakeBlock()
            stopped = []
            result = self._runner(
                root,
                block,
                mavlink_factory=lambda: (_ for _ in ()).throw(RuntimeError("startup error")),
                process_stopper=lambda process: stopped.append(process),
            ).run(ExperimentConfig(seed=12, duration_s=1))
            record = json.loads(result.record_path.read_text())
            self.assertEqual(result.status, "failed")
            self.assertTrue(result.cleanup_complete)
            self.assertEqual(stopped, [None])
            self.assertEqual(record["cleanup"]["errors"], [])


if __name__ == "__main__":
    unittest.main()
