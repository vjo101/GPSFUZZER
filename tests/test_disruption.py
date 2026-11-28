import unittest

from gpsfuzzer.disruption import compare_disruption, disruption_rank


class DisruptionRankingTests(unittest.TestCase):
    def test_outcome_precedence_matches_configured_disruption_order(self):
        route_deviation = disruption_rank({
            "category": "failure",
            "reason": "route_deviation",
            "termination_reason": "crash_detected",
            "first_deviation": {"distance_m": 30.0},
        }, {"maximum_deviation_m": 30.0, "iae_m_s": 150.0})
        crash = disruption_rank({
            "category": "failure", "reason": "crash_detected",
            "safety_events": [{"category": "crash"}],
        })
        timeout = disruption_rank({
            "category": "failure", "reason": "waypoint_progress_timeout",
        })
        ekf = disruption_rank({
            "category": "failure", "reason": "ekf_failsafe",
            "safety_events": [{"category": "ekf_failsafe"}],
        })
        success = disruption_rank({"category": "success", "reason": "landed"})
        incomplete = disruption_rank({"category": "incomplete", "reason": "user_interrupted"})

        ordered = [route_deviation, crash, timeout, ekf, success, incomplete]
        for more_disruptive, less_disruptive in zip(ordered, ordered[1:]):
            self.assertEqual(compare_disruption(more_disruptive, less_disruptive), 1)

    def test_route_deviation_compares_maximum_then_integrated_error(self):
        high_peak = disruption_rank(
            {"reason": "route_deviation", "first_deviation": {"distance_m": 25}},
            {"maximum_deviation_m": 25, "iae_m_s": 50},
        )
        lower_peak_more_sustained = disruption_rank(
            {"reason": "route_deviation", "first_deviation": {"distance_m": 22}},
            {"maximum_deviation_m": 22, "iae_m_s": 300},
        )
        same_peak_more_sustained = disruption_rank(
            {"reason": "route_deviation", "first_deviation": {"distance_m": 25}},
            {"maximum_deviation_m": 25, "iae_m_s": 60},
        )

        self.assertEqual(compare_disruption(high_peak, lower_peak_more_sustained), 1)
        self.assertEqual(compare_disruption(same_peak_more_sustained, high_peak), 1)

    def test_rank_serialization_preserves_evidence_fields(self):
        rank = disruption_rank(
            {"reason": "route_deviation", "first_deviation": {"distance_m": 18}},
            {"maximum_deviation_m": 24.5, "iae_m_s": 92.0},
        )

        self.assertEqual(rank.to_dict(), {
            "category": "route_deviation",
            "class_rank": 5,
            "maximum_route_deviation_m": 24.5,
            "route_iae_m_s": 92.0,
            "ordering": "outcome_class_then_max_deviation_then_iae",
        })


if __name__ == "__main__":
    unittest.main()
