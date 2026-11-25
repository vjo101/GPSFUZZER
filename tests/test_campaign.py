import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpsfuzzer import ExperimentConfig
from gpsfuzzer.campaign import CampaignRunner, derive_run_seed
from gpsfuzzer.drift import sample_drift
from gpsfuzzer.runner import RunResult


class FakeExperimentRunner:
    def __init__(self, results_dir: Path, statuses=None):
        self.results_dir = results_dir
        self.statuses = list(statuses or ["completed"])
        self.calls = []

    def run(self, config, **kwargs):
        metadata = kwargs["campaign"]
        self.calls.append((config, kwargs))
        run_id = f"fake-run-{metadata['iteration']:04d}"
        run_dir = self.results_dir / metadata["campaign_id"] / "runs" / run_id
        run_dir.mkdir(parents=True)
        record_path = run_dir / "experiment.json"
        record_path.write_text(json.dumps({"campaign": metadata, "seed": config.seed}))
        status = self.statuses.pop(0) if self.statuses else "completed"
        reason = "user_interrupted" if status == "user_interrupted" else "test_outcome"
        if status == "user_interrupted":
            status = "incomplete"
        return RunResult(
            run_id,
            status,
            reason,
            1.0,
            sample_drift(config.drift, config.seed),
            record_path,
        )


class CampaignTests(unittest.TestCase):
    def test_run_seeds_are_stable_and_distinct(self):
        first = [derive_run_seed(91, index) for index in range(32)]
        second = [derive_run_seed(91, index) for index in range(32)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))
        self.assertNotEqual(first, [derive_run_seed(92, index) for index in range(32)])

    def test_campaign_groups_runs_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "results"
            fake = FakeExperimentRunner(results_dir, ["failed", "incomplete", "completed"])
            campaign = CampaignRunner(
                Path(tmp) / "ardupilot",
                results_dir,
                experiment_runner=fake,
            ).run(ExperimentConfig(seed=17), iterations=3)

            self.assertEqual(campaign.status, "completed")
            self.assertEqual(campaign.completed_attempts, 3)
            campaign_dir = campaign.record_path.parent
            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(summary["campaign_seed"], 17)
            self.assertEqual(summary["requested_iterations"], 3)
            self.assertEqual([run["iteration"] for run in summary["runs"]], [1, 2, 3])
            self.assertEqual([run["status"] for run in summary["runs"]], ["failed", "incomplete", "completed"])
            self.assertEqual(len({run["run_seed"] for run in summary["runs"]}), 3)
            for entry in summary["runs"]:
                run_record = campaign_dir / entry["record"]
                self.assertTrue(run_record.is_file())
                self.assertEqual(run_record.parent.parent.name, "runs")
            self.assertTrue(all(call[1]["campaign"]["campaign_id"] == campaign.campaign_id for call in fake.calls))

    def test_campaign_repeats_seeded_attack_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_fake = FakeExperimentRunner(root / "first")
            second_fake = FakeExperimentRunner(root / "second")
            first = CampaignRunner(root / "ap", root / "first", experiment_runner=first_fake).run(
                ExperimentConfig(seed=101), iterations=3
            )
            second = CampaignRunner(root / "ap", root / "second", experiment_runner=second_fake).run(
                ExperimentConfig(seed=101), iterations=3
            )
            first_values = [sample_drift(ExperimentConfig(seed=call[0].seed).drift, call[0].seed) for call in first_fake.calls]
            second_values = [sample_drift(ExperimentConfig(seed=call[0].seed).drift, call[0].seed) for call in second_fake.calls]
            self.assertEqual(first_values, second_values)
            self.assertEqual(first.completed_attempts, second.completed_attempts)

    def test_campaign_rejects_non_positive_iteration_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            campaign = CampaignRunner(Path(tmp) / "ap", Path(tmp) / "results")
            with self.assertRaisesRegex(ValueError, "positive integer"):
                campaign.run(ExperimentConfig(seed=1), iterations=0)

    def test_campaign_stops_after_user_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeExperimentRunner(root / "results", ["completed", "user_interrupted", "completed"])
            campaign = CampaignRunner(
                root / "ap",
                root / "results",
                experiment_runner=fake,
            ).run(ExperimentConfig(seed=6), iterations=3)
            self.assertEqual(campaign.status, "interrupted")
            self.assertEqual(campaign.completed_attempts, 2)
            self.assertEqual(len(fake.calls), 2)

    def test_until_stopped_campaign_records_partial_run_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeExperimentRunner(
                root / "results",
                ["completed", "completed", "user_interrupted", "completed"],
            )
            campaign = CampaignRunner(
                root / "ap",
                root / "results",
                experiment_runner=fake,
            ).run(ExperimentConfig(seed=33), iterations=None)

            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(campaign.status, "interrupted")
            self.assertIsNone(campaign.requested_iterations)
            self.assertIsNone(summary["requested_iterations"])
            self.assertEqual(summary["mode"], "until_stopped")
            self.assertEqual(summary["completed_attempts"], 3)
            self.assertEqual(len(fake.calls), 3)
            self.assertTrue(all(call[1]["campaign"]["campaign_mode"] == "until_stopped" for call in fake.calls))
            self.assertTrue(all(run["requested_iterations"] is None for run in summary["runs"]))
            first_record = json.loads((campaign.record_path.parent / summary["runs"][0]["record"]).read_text())
            self.assertEqual(first_record["campaign"]["campaign_mode"], "until_stopped")
            self.assertIsNone(first_record["campaign"]["requested_iterations"])

    def test_until_stopped_campaign_records_interrupt_between_runs(self):
        class InterruptBetweenRuns(FakeExperimentRunner):
            def run(self, config, **kwargs):
                if len(self.calls) == 1:
                    raise KeyboardInterrupt
                return super().run(config, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = InterruptBetweenRuns(root / "results")
            campaign = CampaignRunner(
                root / "ap",
                root / "results",
                experiment_runner=fake,
            ).run(ExperimentConfig(seed=71), iterations=None)
            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(campaign.status, "interrupted")
            self.assertEqual(campaign.completed_attempts, 1)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(summary["completed_attempts"], 1)

    def test_cli_accepts_iteration_count_and_rejects_non_integer(self):
        from gpsfuzzer import __main__ as cli

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"seed": 4}))
            captured = {}

            class FakeCampaign:
                def __init__(self, *args):
                    pass

                def run(self, config, **kwargs):
                    captured["iterations"] = kwargs["iterations"]
                    completed = kwargs["iterations"] if kwargs["iterations"] is not None else 2
                    return type("Result", (), {
                        "status": "completed",
                        "completed_attempts": completed,
                        "requested_iterations": kwargs["iterations"],
                        "record_path": Path(tmp) / "campaign.json",
                    })()

            with patch.object(cli, "CampaignRunner", FakeCampaign), patch(
                "sys.argv",
                ["gpsfuzzer", str(config_path), "--ardupilot", tmp, "--results", tmp, "--iterations", "2"],
            ):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(captured["iterations"], 2)

            with patch.object(cli, "CampaignRunner", FakeCampaign), patch(
                "sys.argv",
                ["gpsfuzzer", str(config_path), "--ardupilot", tmp, "--until-stopped"],
            ):
                self.assertEqual(cli.main(), 0)
            self.assertIsNone(captured["iterations"])

            with patch.object(cli, "CampaignRunner", FakeCampaign), patch(
                "sys.argv",
                ["gpsfuzzer", str(config_path), "--ardupilot", tmp, "--iterations", "many"],
            ):
                with self.assertRaises(SystemExit):
                    cli.main()

            with patch.object(cli, "CampaignRunner", FakeCampaign), patch(
                "sys.argv",
                ["gpsfuzzer", str(config_path), "--ardupilot", tmp, "--iterations", "2", "--until-stopped"],
            ):
                with self.assertRaises(SystemExit):
                    cli.main()

            with patch.object(cli, "CampaignRunner", FakeCampaign), patch(
                "sys.argv",
                ["gpsfuzzer", str(config_path), "--ardupilot", tmp],
            ):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(captured["iterations"], 1)


if __name__ == "__main__":
    unittest.main()
