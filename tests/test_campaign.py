import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpsfuzzer import ExperimentConfig, MissionMutationConfig
from gpsfuzzer.campaign import CampaignRunner, _generate_unique_mission, derive_run_seed
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
    @staticmethod
    def _write_mission_template(path: Path):
        path.write_text(
            "QGC WPL 110\n"
            "0\t1\t0\t16\t0\t0\t0\t0\t-35.363262\t149.165237\t584\t1\n"
            "1\t0\t3\t22\t0\t0\t0\t0\t-35.362491\t149.164780\t20\t1\n"
            "2\t0\t3\t16\t0\t0\t0\t0\t-35.360200\t149.168200\t20\t1\n"
            "3\t0\t3\t21\t0\t0\t0\t0\t-35.360200\t149.168200\t0\t1\n",
            encoding="utf-8",
        )

    def test_campaign_generates_distinct_reproducible_mission_per_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            first_fake = FakeExperimentRunner(root / "first-results")
            second_fake = FakeExperimentRunner(root / "second-results")
            config = ExperimentConfig(seed=991)

            first = CampaignRunner(
                root / "ap", root / "first-results", experiment_runner=first_fake,
            ).run(config, iterations=3, mission_file=template)
            second = CampaignRunner(
                root / "ap", root / "second-results", experiment_runner=second_fake,
            ).run(config, iterations=3, mission_file=template)

            first_paths = [Path(call[1]["mission_file"]) for call in first_fake.calls]
            second_paths = [Path(call[1]["mission_file"]) for call in second_fake.calls]
            first_routes = [path.read_bytes() for path in first_paths]
            second_routes = [path.read_bytes() for path in second_paths]
            self.assertEqual(len(set(first_routes)), 3)
            self.assertEqual(first_routes, second_routes)
            self.assertTrue(all(path.parent.name == "missions" for path in first_paths))
            self.assertTrue(all(path.is_file() for path in first_paths + second_paths))
            self.assertEqual(first.completed_attempts, 3)
            self.assertEqual(second.completed_attempts, 3)
            first_summary = json.loads(first.record_path.read_text())
            self.assertTrue(first_summary["mission_mutation"]["enabled"])
            for entry, mission_path in zip(first_summary["runs"], first_paths):
                generation = entry["mission_generation"]
                self.assertEqual(generation["generation_seed"], entry["run_seed"])
                self.assertEqual(
                    (first.record_path.parent / generation["path"]).read_bytes(),
                    mission_path.read_bytes(),
                )
                self.assertEqual(len(generation["sha256"]), 64)
                experiment = json.loads(
                    (first.record_path.parent / entry["record"]).read_text()
                )
                self.assertEqual(
                    experiment["campaign"]["mission_generation"], generation
                )

    def test_duplicate_route_uses_deterministic_seeded_retry(self):
        from gpsfuzzer.mission_mutation import MissionGenerationResult, generate_mission
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            prior = generate_mission(template, root / "prior.waypoints", 1)
            prior_bytes = prior.path.read_bytes()
            used = {hashlib.sha256(prior_bytes).hexdigest()}
            real_generate = generate_mission
            calls = []

            def repeat_once(template_path, output_path, seed, *, settings):
                calls.append(seed)
                if len(calls) == 1:
                    Path(output_path).write_bytes(prior_bytes)
                    return MissionGenerationResult(Path(output_path), seed, 3, {})
                return real_generate(template_path, output_path, seed, settings=settings)

            with patch("gpsfuzzer.campaign.generate_mission", side_effect=repeat_once):
                generated, generation_seed, retry_count, digest = _generate_unique_mission(
                    template,
                    root / "unique.waypoints",
                    2,
                    MissionMutationConfig(),
                    used,
                )
            self.assertEqual(retry_count, 1)
            self.assertEqual(generation_seed, calls[1])
            self.assertNotEqual(generated.path.read_bytes(), prior_bytes)
            self.assertIn(digest, used)

    def test_static_mission_opt_out_passes_original_path_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "static.waypoints"
            self._write_mission_template(template)
            fake = FakeExperimentRunner(root / "results")
            campaign = CampaignRunner(
                root / "ap", root / "results", experiment_runner=fake,
            ).run(
                ExperimentConfig(seed=13),
                iterations=2,
                mission_file=template,
                mutate_mission=False,
            )
            self.assertEqual(campaign.completed_attempts, 2)
            self.assertEqual([call[1]["mission_file"] for call in fake.calls], [template, template])
            self.assertFalse((campaign.record_path.parent / "missions").exists())
            entries = json.loads(campaign.record_path.read_text())["runs"]
            self.assertTrue(all(not entry["mission_generation"]["enabled"] for entry in entries))

    def test_invalid_template_is_recorded_without_starting_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "invalid.waypoints"
            template.write_text("QGC WPL 110\n", encoding="utf-8")
            fake = FakeExperimentRunner(root / "results")
            campaign = CampaignRunner(
                root / "ap", root / "results", experiment_runner=fake,
            ).run(ExperimentConfig(seed=14), mission_file=template)

            self.assertEqual(fake.calls, [])
            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(summary["completed_attempts"], 1)
            entry = summary["runs"][0]
            self.assertEqual(entry["status"], "failed")
            self.assertTrue(entry["termination_reason"].startswith("mission_generation_error:"))
            record = json.loads((campaign.record_path.parent / entry["record"]).read_text())
            self.assertTrue(record["mission_generation"]["enabled"])
            self.assertEqual(record["mission_generation"]["run_seed"], entry["run_seed"])

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
                    captured["mutate_mission"] = kwargs["mutate_mission"]
                    captured["mission_file"] = kwargs["mission_file"]
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
                ["gpsfuzzer", str(config_path), "--ardupilot", tmp, "--mission", str(Path(tmp) / "mission.wpl")],
            ):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(captured["iterations"], 1)
            self.assertTrue(captured["mutate_mission"])
            self.assertEqual(captured["mission_file"], Path(tmp) / "mission.wpl")

            with patch.object(cli, "CampaignRunner", FakeCampaign), patch(
                "sys.argv",
                [
                    "gpsfuzzer", str(config_path), "--ardupilot", tmp,
                    "--mission", str(Path(tmp) / "mission.wpl"), "--no-mission-mutation",
                ],
            ):
                self.assertEqual(cli.main(), 0)
            self.assertFalse(captured["mutate_mission"])


if __name__ == "__main__":
    unittest.main()
