import json
from pathlib import Path
import tempfile
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
        self.commands.append(COMMAND_FORMAT.unpack(data))

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

    def recv_match(self, blocking=False):
        return None

    def close(self):
        pass


class RunnerTests(unittest.TestCase):
    def test_validates_and_records_custom_simulation_location(self):
        ExperimentRunner._validate_location("60.0,24.0,100,0")
        with self.assertRaisesRegex(ValueError, "LAT,LON,ALT,HEADING"):
            ExperimentRunner._validate_location("60,24,100")
        with self.assertRaisesRegex(ValueError, "out of range"):
            ExperimentRunner._validate_location("91,24,100,0")

    def _runner(self, root, block, timeout=5.0):
        return ExperimentRunner(
            root / "ardupilot",
            root / "results",
            process_factory=lambda *args, **kwargs: FakeProcess(),
            mavlink_factory=FakeConnection,
            block_factory=lambda: block,
            process_stopper=lambda process: None,
            ready_timeout_s=timeout,
            poll_interval_s=0.001,
            heartbeat_interval_s=0.01,
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


if __name__ == "__main__":
    unittest.main()
