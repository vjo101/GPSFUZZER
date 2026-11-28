import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpsfuzzer import ExperimentConfig, FeedbackSearchConfig, MissionMutationConfig
from gpsfuzzer.campaign import (
    FEEDBACK_BEARINGS_DEG,
    CampaignRunner,
    _generate_unique_mission,
    derive_run_seed,
)
from gpsfuzzer.drift import sample_drift
from gpsfuzzer.runner import RunResult


class FakeExperimentRunner:
    def __init__(self, results_dir: Path, statuses=None, outcomes=None):
        self.results_dir = results_dir
        self.statuses = list(statuses or ["completed"])
        self.outcomes = list(outcomes or [])
        self.calls = []

    def run(self, config, **kwargs):
        metadata = kwargs["campaign"]
        self.calls.append((config, kwargs))
        run_id = f"fake-run-{metadata['iteration']:04d}"
        run_dir = self.results_dir / metadata["campaign_id"] / "runs" / run_id
        run_dir.mkdir(parents=True)
        record_path = run_dir / "experiment.json"
        record = {"campaign": metadata, "seed": config.seed}
        if self.outcomes:
            record["mission"] = {"outcome": self.outcomes.pop(0)}
        record_path.write_text(json.dumps(record))
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
            simulation_speedup=config.simulation_speedup,
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

    def test_feedback_campaign_reuses_mission_across_ordered_bearings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            results = root / "results"
            fake = FakeExperimentRunner(results)
            campaign = CampaignRunner(root / "ap", results, experiment_runner=fake).run(
                ExperimentConfig(
                    seed=215,
                    feedback=FeedbackSearchConfig(max_attempts_per_bearing=1),
                ),
                iterations=1,
                mission_file=template,
                feedback_guided=True,
            )

            self.assertEqual(campaign.mode, "feedback_guided")
            self.assertEqual(campaign.completed_attempts, 8)
            self.assertEqual(
                [call[1]["campaign"]["bearing_deg"] for call in fake.calls],
                list(FEEDBACK_BEARINGS_DEG),
            )
            mission_paths = [Path(call[1]["mission_file"]) for call in fake.calls]
            self.assertEqual(len({path.resolve() for path in mission_paths}), 1)
            self.assertTrue(all(path.is_file() for path in mission_paths))
            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(summary["completed_sweeps"], 1)
            self.assertEqual(summary["completed_attempts"], 8)

    def test_feedback_campaign_resets_speed_search_for_each_bearing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            results = root / "results"
            fake = FakeExperimentRunner(results)
            CampaignRunner(root / "ap", results, experiment_runner=fake).run(
                ExperimentConfig(
                    seed=216,
                    feedback=FeedbackSearchConfig(max_attempts_per_bearing=2),
                ),
                iterations=1,
                mission_file=template,
                feedback_guided=True,
            )

            self.assertEqual(len(fake.calls), 16)
            for bearing_index, bearing in enumerate(FEEDBACK_BEARINGS_DEG):
                calls = fake.calls[bearing_index * 2:bearing_index * 2 + 2]
                speeds = [call[0].drift.horizontal_speed_mps.minimum for call in calls]
                self.assertEqual([call[1]["campaign"]["bearing_deg"] for call in calls], [bearing, bearing])
                self.assertEqual(speeds, [1.25, 1.625])
                self.assertEqual(len({call[1]["campaign"]["target_seed"] for call in calls}), 1)

    def test_feedback_campaign_starts_fresh_mission_each_sweep_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            results = root / "results"
            fake = FakeExperimentRunner(results)
            campaign = CampaignRunner(root / "ap", results, experiment_runner=fake).run(
                ExperimentConfig(
                    seed=217,
                    feedback=FeedbackSearchConfig(max_attempts_per_bearing=1),
                ),
                iterations=2,
                mission_file=template,
                feedback_guided=True,
            )
            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(campaign.completed_attempts, 16)
            self.assertEqual(summary["completed_sweeps"], 2)
            self.assertEqual(len(summary["runs"]), 16)
            missions = [Path(call[1]["mission_file"]) for call in fake.calls]
            self.assertEqual(len({path.resolve() for path in missions[:8]}), 1)
            self.assertEqual(len({path.resolve() for path in missions[8:]}), 1)
            self.assertNotEqual(missions[0].read_bytes(), missions[8].read_bytes())
            self.assertTrue(all(entry["feedback_decision"]["attempt"] == 1 for entry in summary["runs"]))

    def test_feedback_campaign_interruption_preserves_active_target_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            results = root / "results"
            fake = FakeExperimentRunner(results, ["user_interrupted"])
            campaign = CampaignRunner(root / "ap", results, experiment_runner=fake).run(
                ExperimentConfig(seed=218),
                iterations=1,
                mission_file=template,
                feedback_guided=True,
            )
            summary = json.loads(campaign.record_path.read_text())
            self.assertEqual(campaign.status, "interrupted")
            self.assertEqual(summary["completed_attempts"], 1)
            self.assertEqual(summary["completed_sweeps"], 0)
            self.assertEqual(summary["active_target"]["search_state"]["attempts_completed"], 1)
            self.assertEqual(summary["active_target"]["bearing_deg"], FEEDBACK_BEARINGS_DEG[0])

    def test_feedback_campaign_records_best_disruptive_run_and_mission_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            results = root / "results"
            outcomes = [
                {
                    "reason": "route_deviation",
                    "first_deviation": {"distance_m": distance},
                    "route_deviation_score": {
                        "maximum_deviation_m": distance,
                        "iae_m_s": float(distance),
                    },
                }
                for distance in range(10, 18)
            ]
            fake = FakeExperimentRunner(results, outcomes=outcomes)
            campaign = CampaignRunner(root / "ap", results, experiment_runner=fake).run(
                ExperimentConfig(
                    seed=219,
                    feedback=FeedbackSearchConfig(max_attempts_per_bearing=1),
                ),
                iterations=1,
                mission_file=template,
                feedback_guided=True,
            )
            best = json.loads(campaign.record_path.read_text())["best_attack"]
            self.assertEqual(best["rank"]["maximum_route_deviation_m"], 17.0)
            self.assertEqual(best["effective_drift"]["bearing_deg"], 315.0)
            mission_artifact = campaign.record_path.parent / best["mission"]["path"]
            self.assertTrue(mission_artifact.is_file())
            import hashlib
            self.assertEqual(
                hashlib.sha256(mission_artifact.read_bytes()).hexdigest(),
                best["mission"]["sha256"],
            )

    def test_feedback_campaign_uses_recorded_outcome_to_change_next_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._write_mission_template(template)
            results = root / "results"
            deviation = {
                "reason": "route_deviation",
                "first_deviation": {"distance_m": 25},
                "route_deviation_score": {
                    "maximum_deviation_m": 25,
                    "iae_m_s": 90,
                },
            }
            success = {"category": "success", "reason": "landed_at_final_waypoint"}
            fake = FakeExperimentRunner(results, outcomes=[deviation, success, success] * 8)
            campaign = CampaignRunner(root / "ap", results, experiment_runner=fake).run(
                ExperimentConfig(
                    seed=220,
                    feedback=FeedbackSearchConfig(max_attempts_per_bearing=3),
                ),
                iterations=1,
                mission_file=template,
                feedback_guided=True,
            )
            first_target = [
                entry for entry in json.loads(campaign.record_path.read_text())["runs"]
                if entry["bearing_index"] == 0
            ]
            self.assertEqual(first_target[0]["rank"]["category"], "route_deviation")
            self.assertEqual(first_target[1]["rank"]["category"], "success")
            self.assertTrue(first_target[0]["feedback_decision"]["is_new_best"])
            self.assertFalse(first_target[1]["feedback_decision"]["is_new_best"])
            self.assertEqual(
                first_target[1]["feedback_decision"]["next_speed_mps"],
                1.4375,
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

    def test_campaign_records_explicit_one_x_reference_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeExperimentRunner(root / "results")
            campaign = CampaignRunner(
                root / "ap", root / "results", experiment_runner=fake,
            ).run(ExperimentConfig(seed=13, simulation_speedup=1.0))
            summary = json.loads(campaign.record_path.read_text())
        self.assertEqual(summary["simulation_speedup"], 1.0)
        self.assertEqual(summary["runs"][0]["simulation_speedup"], {
            "requested": 1.0,
            "effective": 1.0,
        })

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
            self.assertEqual(summary["simulation_speedup"], 2.0)
            self.assertEqual(summary["requested_iterations"], 3)
            self.assertEqual([run["iteration"] for run in summary["runs"]], [1, 2, 3])
            self.assertEqual([run["status"] for run in summary["runs"]], ["failed", "incomplete", "completed"])
            self.assertEqual(len({run["run_seed"] for run in summary["runs"]}), 3)
            for entry in summary["runs"]:
                self.assertEqual(entry["simulation_speedup"], {
                    "requested": 2.0,
                    "effective": 2.0,
                })
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
                    captured["feedback_guided"] = kwargs["feedback_guided"]
                    completed = kwargs["iterations"] if kwargs["iterations"] is not None else 2
                    return type("Result", (), {
                        "status": "completed",
                        "completed_attempts": completed,
                        "requested_iterations": kwargs["iterations"],
                        "record_path": Path(tmp) / "campaign.json",
                        "best_attack": None,
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
                    "--mission", str(Path(tmp) / "mission.wpl"), "--feedback-guided",
                ],
            ):
                self.assertEqual(cli.main(), 0)
            self.assertTrue(captured["feedback_guided"])

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
