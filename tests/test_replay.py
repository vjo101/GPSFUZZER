import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpsfuzzer.__main__ import main
from gpsfuzzer.replay import load_replay_inputs


class ReplayTests(unittest.TestCase):
    def _write_record(self, root: Path) -> Path:
        mission = root / "sweep-0001.waypoints"
        mission.write_text("QGC WPL 110\nmission bytes\n", encoding="utf-8")
        digest = hashlib.sha256(mission.read_bytes()).hexdigest()
        record = {
            "run_id": "original-run-1",
            "seed": 123,
            "configuration": {
                "duration_s": 45,
                "simulation_speedup": 2,
            },
            "effective_drift": {
                "start_delay_s": 12,
                "horizontal_speed_mps": 1.25,
                "bearing_deg": 90,
                "velocity_mode": "coherent",
            },
            "sitl": {"frame": "quad", "custom_location": "1,2,3,4"},
            "mission": {
                "path": str(mission),
                "generation": {"sha256": digest, "path": "missions/sweep-0001.waypoints"},
            },
        }
        record_path = root / "experiment.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        return record_path

    def test_loads_exact_inputs_and_checks_mission_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_record(Path(tmp))
            replay = load_replay_inputs(path)
            self.assertEqual(replay.config.seed, 123)
            self.assertEqual(replay.config.duration_s, 45)
            self.assertEqual(replay.config.drift.start_delay_s.minimum, 12)
            self.assertEqual(replay.config.drift.horizontal_speed_mps.minimum, 1.25)
            self.assertEqual(replay.config.drift.bearing_deg.minimum, 90)
            self.assertEqual(replay.mission_file.name, "sweep-0001.waypoints")
            self.assertEqual(replay.frame, "quad")
            self.assertEqual(replay.location, "1,2,3,4")

    def test_rejects_malformed_record_missing_artifact_and_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot read replay record"):
                load_replay_inputs(malformed)

            path = self._write_record(root)
            record = json.loads(path.read_text())
            record["mission"]["path"] = str(root / "missing.waypoints")
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact is missing"):
                load_replay_inputs(path)

            record["mission"]["path"] = str(root / "sweep-0001.waypoints")
            record["mission"]["generation"]["sha256"] = "0" * 64
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                load_replay_inputs(path)

    def test_cli_replay_starts_exactly_one_run_and_links_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = self._write_record(root)
            captured = []

            class FakeRunner:
                def __init__(self, *args):
                    pass

                def run(self, config, **kwargs):
                    captured.append((config, kwargs))
                    return type("Result", (), {
                        "status": "completed",
                        "record_path": root / "replay" / "experiment.json",
                    })()

            with patch("gpsfuzzer.__main__.ExperimentRunner", FakeRunner), patch(
                "sys.argv",
                ["gpsfuzzer", "--ardupilot", str(root), "--results", str(root / "results"),
                 "--replay-record", str(record)],
            ):
                self.assertEqual(main(), 0)

            self.assertEqual(len(captured), 1)
            config, kwargs = captured[0]
            self.assertEqual(config.seed, 123)
            self.assertEqual(kwargs["mission_file"], root / "sweep-0001.waypoints")
            self.assertEqual(kwargs["campaign"]["campaign_mode"], "replay")
            self.assertEqual(kwargs["campaign"]["replay_of"]["record"], str(record.resolve()))

    def test_cli_rejects_bad_replay_before_runner_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = self._write_record(root)
            contents = json.loads(record.read_text())
            contents["mission"]["generation"]["sha256"] = "bad"
            record.write_text(json.dumps(contents), encoding="utf-8")
            with patch("gpsfuzzer.__main__.ExperimentRunner") as runner, patch(
                "sys.argv",
                ["gpsfuzzer", "--ardupilot", str(root), "--replay-record", str(record)],
            ):
                with self.assertRaises(SystemExit):
                    main()
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
