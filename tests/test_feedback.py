import json
import unittest

from gpsfuzzer.config import NumericRange
from gpsfuzzer.disruption import disruption_rank
from gpsfuzzer.feedback import SpeedHillClimb


def deviation_rank(maximum_m, iae_m_s):
    return disruption_rank(
        {"category": "failure", "reason": "route_deviation",
         "first_deviation": {"distance_m": maximum_m}},
        {"maximum_deviation_m": maximum_m, "iae_m_s": iae_m_s},
    )


class SpeedHillClimbTests(unittest.TestCase):
    def test_starts_at_midpoint_and_keeps_direction_when_rank_improves(self):
        policy = SpeedHillClimb(NumericRange(0.5, 2.0), max_attempts=10)
        self.assertEqual(policy.current_speed_mps, 1.25)
        self.assertEqual(policy.step_mps, 0.375)
        first = policy.observe_result(deviation_rank(20, 80), run_id="run-1")
        second = policy.observe_result(deviation_rank(24, 90), run_id="run-2")

        self.assertEqual(first.next_speed_mps, 1.625)
        self.assertTrue(first.is_new_best)
        self.assertEqual(second.next_speed_mps, 2.0)
        self.assertTrue(second.is_new_best)
        self.assertEqual(policy.best_run_id, "run-2")
        self.assertEqual(policy.best_speed_mps, 1.625)

    def test_regression_and_tie_reverse_direction_and_halve_step(self):
        for second_rank in (disruption_rank({"category": "success"}), deviation_rank(20, 80)):
            with self.subTest(second_rank=second_rank):
                policy = SpeedHillClimb(NumericRange(0.5, 2.0))
                policy.observe_result(deviation_rank(20, 80), run_id="best")
                decision = policy.observe_result(second_rank, run_id="other")
                self.assertEqual(decision.direction, -1)
                self.assertEqual(decision.step_mps, 0.1875)
                self.assertEqual(decision.next_speed_mps, 1.4375)
                self.assertFalse(decision.is_new_best)

    def test_stops_at_attempt_limit_and_rejects_extra_observations(self):
        policy = SpeedHillClimb(NumericRange(0.5, 2.0), max_attempts=2)
        policy.observe_result(deviation_rank(20, 80))
        last = policy.observe_result(deviation_rank(22, 90))
        self.assertEqual(last.stop_reason, "attempt_limit_reached")
        self.assertIsNone(last.next_speed_mps)
        with self.assertRaisesRegex(RuntimeError, "attempt limit"):
            policy.observe_result(deviation_rank(23, 100))

    def test_clamps_to_bound_then_stops_when_no_new_speed_is_available(self):
        policy = SpeedHillClimb(NumericRange(0.0, 1.0), max_attempts=5)
        first = policy.observe_result(deviation_rank(10, 10))
        second = policy.observe_result(deviation_rank(11, 12))
        at_bound = policy.observe_result(deviation_rank(12, 14))
        self.assertEqual(first.next_speed_mps, 0.75)
        self.assertEqual(second.next_speed_mps, 1.0)
        self.assertEqual(at_bound.stop_reason, "speed_bound_reached")
        self.assertIsNone(at_bound.next_speed_mps)

    def test_decisions_and_target_state_are_json_serializable(self):
        policy = SpeedHillClimb(NumericRange(0.5, 2.0))
        first = policy.observe_result(deviation_rank(20, 80), run_id="r1")
        second = policy.observe_result(deviation_rank(22, 90), run_id="r2")
        encoded = json.dumps({
            "decisions": [first.to_dict(), second.to_dict()],
            "state": policy.state(),
        })
        decoded = json.loads(encoded)
        self.assertEqual(decoded["decisions"][0]["speed_mps"], 1.25)
        self.assertEqual(decoded["decisions"][1]["speed_mps"], 1.625)
        self.assertEqual(decoded["decisions"][1]["prior_best_run_id"], "r1")
        self.assertEqual(decoded["decisions"][1]["prior_best_speed_mps"], 1.25)
        self.assertEqual(decoded["decisions"][1]["direction_before"], 1)
        self.assertEqual(decoded["decisions"][1]["step_before_mps"], 0.375)
        self.assertEqual(decoded["decisions"][1]["next_speed_mps"], 2.0)
        self.assertEqual(decoded["state"]["best_run_id"], "r2")
        self.assertEqual(decoded["state"]["best_speed_mps"], 1.625)

    def test_rejects_invalid_search_intervals_and_limits(self):
        with self.assertRaisesRegex(ValueError, "positive width"):
            SpeedHillClimb(NumericRange(1.0, 1.0))
        with self.assertRaisesRegex(ValueError, "positive integer"):
            SpeedHillClimb(NumericRange(0.0, 1.0), max_attempts=0)


if __name__ == "__main__":
    unittest.main()
