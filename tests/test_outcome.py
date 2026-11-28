import tempfile
import types
import unittest
from pathlib import Path

from gpsfuzzer.mission import MissionRoute, MissionWaypoint
from gpsfuzzer.outcome import (
    DEFAULT_DEVIATION_LIMIT_M,
    DEFAULT_PROGRESS_TIMEOUT_S,
    MissionOutcomeMonitor,
    horizontal_distance_m,
    horizontal_distance_to_leg_m,
)


def message(kind, **fields):
    return types.SimpleNamespace(get_type=lambda: kind, **fields)


class MissionRouteTests(unittest.TestCase):
    def test_route_uses_home_as_origin_and_skips_non_navigation_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mission.waypoints"
            path.write_text(
                "QGC WPL 110\n"
                "0\t1\t0\t16\t0\t0\t0\t0\t60.0\t24.0\t100\t1\n"
                "1\t0\t3\t22\t0\t0\t0\t0\t60.0001\t24.0\t10\t1\n"
                "2\t0\t2\t178\t0\t5\t0\t0\t0\t0\t0\t1\n"
                "3\t0\t3\t16\t0\t0\t0\t0\t60.0002\t24.0002\t10\t1\n"
                "4\t0\t3\t21\t0\t0\t0\t0\t60.0003\t24.0003\t0\t1\n",
                encoding="utf-8",
            )
            route = MissionRoute.from_file(path)

        self.assertEqual([point.sequence for point in route.waypoints], [1, 3, 4])
        self.assertEqual(route.home_waypoint.sequence, 0)
        self.assertEqual(route.final_waypoint.command, 21)
        self.assertEqual(
            tuple(point.sequence for point in route.active_leg(1)),
            (0, 1),
        )
        self.assertEqual(
            tuple(point.sequence for point in route.active_leg(2)),
            (0, 3),
        )


class MissionOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.route = MissionRoute.from_file("waypoints.txt")

    def test_geographic_distance_and_route_distance_use_latitude_scaling(self):
        self.assertAlmostEqual(horizontal_distance_m(60, 24, 60, 24.001), 55.6, delta=0.5)
        start = MissionWaypoint(1, 16, 60.0, 24.0, 10)
        end = MissionWaypoint(2, 21, 60.0, 24.001, 0)
        deviation = horizontal_distance_to_leg_m(
            60.0001,
            24.0005,
            start,
            end,
        )
        self.assertAlmostEqual(deviation, 11.1, delta=0.5)
        self.assertEqual(DEFAULT_DEVIATION_LIMIT_M, 15.0)
        self.assertEqual(DEFAULT_PROGRESS_TIMEOUT_S, 90.0)

    def test_route_deviation_iae_uses_simulation_time_and_truth_position(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.0, 24.001, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=2), now=0)
        truth = {"lat": round(60.0001 * 1e7), "lng": round(24.0005 * 1e7)}
        monitor.consume(message("SYSTEM_TIME", time_boot_ms=1000), now=100)
        monitor.consume(message("SIMSTATE", **truth), now=100)
        monitor.consume(message("SYSTEM_TIME", time_boot_ms=3000), now=102)
        monitor.consume(message("SIMSTATE", **truth), now=102)

        score = monitor.evidence()["route_deviation_score"]
        expected_deviation = horizontal_distance_to_leg_m(
            60.0001, 24.0005, *route.active_leg(2),
        )
        self.assertTrue(score["available"])
        self.assertAlmostEqual(score["iae_m_s"], expected_deviation * 2, delta=0.1)
        self.assertAlmostEqual(score["duration_normalized_iae_m"], expected_deviation, delta=0.1)
        self.assertEqual(score["scored_duration_s"], 2.0)
        self.assertEqual(score["sample_count"], 2)
        self.assertEqual(score["interval_count"], 1)
        self.assertAlmostEqual(score["maximum_deviation_m"], expected_deviation, delta=0.1)
        self.assertEqual(score["by_leg"][0]["end_sequence"], 2)

    def test_route_deviation_score_does_not_integrate_across_leg_change(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 16, 60.0, 24.001, 10),
            MissionWaypoint(3, 21, 60.001, 24.001, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)

        def sample(sim_ms, lat, lon):
            monitor.consume(message("SYSTEM_TIME", time_boot_ms=sim_ms), now=sim_ms / 1000)
            monitor.consume(message(
                "SIMSTATE", lat=round(lat * 1e7), lng=round(lon * 1e7),
            ), now=sim_ms / 1000)

        monitor.consume(message("MISSION_CURRENT", seq=2), now=0)
        sample(1000, 60.0001, 24.0005)
        sample(3000, 60.0001, 24.0005)
        monitor.consume(message("MISSION_CURRENT", seq=3), now=4)
        sample(5000, 60.0005, 24.0011)
        sample(7000, 60.0005, 24.0011)

        score = monitor.evidence()["route_deviation_score"]
        self.assertEqual(score["interval_count"], 2)
        self.assertEqual(score["scored_duration_s"], 4.0)
        self.assertEqual(len(score["by_leg"]), 2)
        self.assertEqual([leg["interval_count"] for leg in score["by_leg"]], [1, 1])
        self.assertAlmostEqual(
            score["iae_m_s"],
            sum(leg["iae_m_s"] for leg in score["by_leg"]),
        )

    def test_route_deviation_score_is_unavailable_without_timestamped_truth(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.0, 24.001, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=2), now=1)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round(60.0001 * 1e7), lon=round(24.0005 * 1e7), relative_alt=10,
        ), now=2)
        score = monitor.evidence()["route_deviation_score"]
        self.assertFalse(score["available"])
        self.assertIsNone(score["iae_m_s"])
        self.assertIsNone(score["maximum_deviation_m"])

    def test_gps_exposure_and_velocity_diagnostics_are_separate_from_route_score(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.0, 24.01, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=2), now=0)
        monitor.consume(message("SYSTEM_TIME", time_boot_ms=1000), now=1)
        monitor.consume(message(
            "SIMSTATE", lat=round(60.0 * 1e7), lng=round(24.001 * 1e7),
        ), now=1)
        monitor.consume(message("SYSTEM_TIME", time_boot_ms=2000), now=2)
        monitor.consume(message(
            "SIMSTATE", lat=round(60.0 * 1e7), lng=round(24.0011 * 1e7),
        ), now=2)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round(60.002 * 1e7), lon=round(24.0011 * 1e7), relative_alt=20,
            vx=123, vy=-45, vz=10,
        ), now=2)
        monitor.consume(message(
            "GPS_RAW_INT",
            fix_type=3,
            lat=round(60.0002 * 1e7), lon=round(24.0011 * 1e7),
            vel=200, cog=9000,
        ), now=2)

        evidence = monitor.evidence()
        route_score = evidence["route_deviation_score"]
        exposure = evidence["gps_measurement_exposure"]
        self.assertAlmostEqual(route_score["maximum_deviation_m"], 0.0, delta=0.1)
        self.assertAlmostEqual(route_score["iae_m_s"], 0.0, delta=0.1)
        self.assertEqual(exposure["position"]["source"], "GPS_RAW_INT.lat_lon_vs_SIMSTATE")
        self.assertGreater(exposure["position"]["maximum_offset_m"], 20.0)
        self.assertEqual(
            exposure["velocity"]["source"],
            "GPS_RAW_INT.vel_cog_vs_finite_difference_SIMSTATE",
        )
        self.assertGreater(exposure["velocity"]["latest_error_mps"], 1.0)
        self.assertEqual(evidence["vehicle_velocity_diagnostic"], {
            "source": "GLOBAL_POSITION_INT.vx_vy_vz",
            "north_mps": 1.23,
            "east_mps": -0.45,
            "down_mps": 0.1,
        })

    def test_terminal_land_activation_is_one_shot_and_requires_land_command(self):
        land_route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.001, 24.0, 0),
        ))
        monitor = MissionOutcomeMonitor(land_route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=1), now=1)
        self.assertFalse(monitor.evidence()["terminal_land_active"])

        monitor.consume(message("MISSION_CURRENT", seq=2), now=2)
        monitor.consume(message("MISSION_CURRENT", seq=2), now=3)
        evidence = monitor.evidence()
        self.assertTrue(evidence["terminal_land_active"])
        self.assertEqual(evidence["terminal_land_active_at_monotonic_ns"], 2_000_000_000)

        non_land_route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 16, 60.001, 24.0, 10),
        ))
        non_land_monitor = MissionOutcomeMonitor(non_land_route, started_at=0)
        non_land_monitor.consume(message("MISSION_CURRENT", seq=2), now=4)
        self.assertFalse(non_land_monitor.evidence()["terminal_land_active"])

    def test_terminal_land_activation_responds_to_current_and_reached_messages(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.001, 24.0, 0),
        ))
        for kind in ("MISSION_CURRENT", "MISSION_ITEM_REACHED"):
            with self.subTest(kind=kind):
                monitor = MissionOutcomeMonitor(route, started_at=0)
                monitor.consume(message(kind, seq=route.final_waypoint.sequence), now=5)
                self.assertTrue(monitor.evidence()["terminal_land_active"])
                self.assertEqual(
                    monitor.evidence()["terminal_land_active_at_monotonic_ns"],
                    5_000_000_000,
                )

    def test_deviation_is_nonterminal_and_latches_first_and_maximum_evidence(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        start, end = self.route.waypoints[:2]
        midpoint_lat = (start.latitude + end.latitude) / 2
        midpoint_lon = (start.longitude + end.longitude) / 2
        monitor.consume(message("MISSION_CURRENT", seq=end.sequence), now=1)
        monitor.consume(message(
            "SIMSTATE",
            lat=round((midpoint_lat + 0.0002) * 1e7),
            lng=round(midpoint_lon * 1e7),
        ), now=2)
        first = monitor.evidence()["first_deviation"]
        self.assertGreater(first["distance_m"], DEFAULT_DEVIATION_LIMIT_M)
        self.assertEqual(first["observed_monotonic_ns"], 2_000_000_000)
        self.assertIsNone(monitor.evaluate(now=2))

        monitor.consume(message(
            "SIMSTATE",
            lat=round((midpoint_lat + 0.0003) * 1e7),
            lng=round(midpoint_lon * 1e7),
        ), now=3)
        evidence = monitor.evidence()
        self.assertEqual(evidence["first_deviation"], first)
        self.assertGreater(evidence["maximum_deviation_m"], first["distance_m"])
        self.assertIsNone(monitor.evaluate(now=3))

    def test_stale_current_sequence_does_not_move_active_leg_backward(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=3), now=1)
        monitor.consume(message("MISSION_CURRENT", seq=2), now=2)

        self.assertEqual(monitor.current_sequence, 3)
        self.assertEqual(monitor.last_progress_sequence, 3)

        # An explicit reached event can still report a lower sequence for a
        # mission loop and is treated as authoritative progress.
        monitor.consume(message("MISSION_ITEM_REACHED", seq=2), now=3)
        self.assertEqual(monitor.current_sequence, 2)

    def test_success_requires_final_item_landing_and_endpoint_proximity(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        final = self.route.final_waypoint
        monitor.consume(message("MISSION_ITEM_REACHED", seq=final.sequence), now=10)
        monitor.consume(message("EXTENDED_SYS_STATE", landed_state=1), now=10)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round(final.latitude * 1e7), lon=round(final.longitude * 1e7),
            relative_alt=0,
        ), now=10)

        outcome = monitor.evaluate(now=10)
        self.assertEqual((outcome.category, outcome.reason), ("success", "landed_at_final_waypoint"))
        self.assertEqual(monitor.evidence()["final_waypoint_sequence"], final.sequence)

    def test_terminal_land_success_uses_disarm_and_low_altitude_fallback(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        final = self.route.final_waypoint
        monitor.consume(message("MISSION_CURRENT", seq=final.sequence), now=1)
        monitor.consume(message("HEARTBEAT", base_mode=128), now=2)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round(final.latitude * 1e7), lon=round(final.longitude * 1e7),
            relative_alt=85,
        ), now=3)
        monitor.consume(message("HEARTBEAT", base_mode=0), now=4)

        outcome = monitor.evaluate(now=4)
        self.assertEqual((outcome.category, outcome.reason), ("success", "landed_at_final_waypoint"))
        self.assertFalse(monitor.final_waypoint_reached)
        self.assertEqual(
            monitor.evidence()["landing_confirmation"]["source"],
            "disarmed_low_altitude_after_final_item",
        )

    def test_disarm_away_from_endpoint_confirms_landing_and_fails_promptly(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.001, 24.0, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=route.final_waypoint.sequence), now=1)
        monitor.consume(message("HEARTBEAT", base_mode=128), now=2)
        previous = route.waypoints[0]
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round(previous.latitude * 1e7),
            lon=round(previous.longitude * 1e7),
            relative_alt=0,
        ), now=3)
        monitor.consume(message("HEARTBEAT", base_mode=0), now=4)

        outcome = monitor.evaluate(now=4)
        self.assertEqual(
            (outcome.category, outcome.reason, outcome.termination_reason),
            ("failure", "landing_outside_endpoint_radius", "landing_outside_endpoint_radius"),
        )
        self.assertEqual(
            monitor.evidence()["landing_confirmation"]["source"],
            "disarmed_low_altitude_after_final_item",
        )

    def test_off_endpoint_disarm_after_deviation_preserves_deviation_failure(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.001, 24.0, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=1), now=1)
        monitor.consume(message(
            "SIMSTATE", lat=round(60.0005 * 1e7), lng=round(24.0 * 1e7),
        ), now=2)
        self.assertIsNotNone(monitor.first_deviation)

        monitor.consume(message("MISSION_CURRENT", seq=2), now=3)
        monitor.consume(message("HEARTBEAT", base_mode=128), now=4)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round(60.0005 * 1e7), lon=round(24.0 * 1e7), relative_alt=0,
        ), now=5)
        monitor.consume(message("HEARTBEAT", base_mode=0), now=6)

        outcome = monitor.evaluate(now=6)
        self.assertEqual(
            (outcome.category, outcome.reason, outcome.termination_reason),
            ("failure", "route_deviation", "landing_outside_endpoint_radius"),
        )
        self.assertIsNotNone(monitor.evidence()["landing_confirmation"])

    def test_simulator_truth_controls_route_and_endpoint_outcome(self):
        route = MissionRoute((
            MissionWaypoint(1, 16, 60.0, 24.0, 10),
            MissionWaypoint(2, 21, 60.001, 24.0, 0),
        ))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        final = route.final_waypoint
        monitor.consume(message("MISSION_CURRENT", seq=final.sequence), now=1)
        monitor.consume(message("HEARTBEAT", base_mode=128), now=2)
        monitor.consume(message(
            "SIMSTATE",
            lat=round(final.latitude * 1e7),
            lng=round(final.longitude * 1e7),
        ), now=3)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round((final.latitude + 0.002) * 1e7),
            lon=round(final.longitude * 1e7),
            relative_alt=50,
        ), now=4)
        monitor.consume(message("HEARTBEAT", base_mode=0), now=5)

        outcome = monitor.evaluate(now=5)
        self.assertEqual(outcome.reason, "landed_at_final_waypoint")
        self.assertEqual(monitor.position_source, "simstate_truth")
        self.assertEqual(monitor.endpoint_distance_m, 0)
        self.assertGreater(monitor.maximum_reported_deviation_m, 15)
        self.assertEqual(monitor.maximum_simulator_deviation_m, 0)

    def test_endpoint_miss_fails_even_when_position_is_on_final_route_leg(self):
        previous = MissionWaypoint(1, 16, 60.0, 24.0, 10)
        final = MissionWaypoint(2, 21, 60.001, 24.0, 0)
        route = MissionRoute((previous, final))
        monitor = MissionOutcomeMonitor(route, started_at=0)
        latitude = (final.latitude + previous.latitude) / 2
        longitude = (final.longitude + previous.longitude) / 2
        monitor.consume(message("MISSION_CURRENT", seq=final.sequence), now=9)
        monitor.consume(message("MISSION_ITEM_REACHED", seq=final.sequence), now=10)
        monitor.consume(message("EXTENDED_SYS_STATE", landed_state=1), now=10)
        monitor.consume(message(
            "GLOBAL_POSITION_INT", lat=round(latitude * 1e7), lon=round(longitude * 1e7),
            relative_alt=0,
        ), now=10)

        outcome = monitor.evaluate(now=10)
        self.assertEqual(outcome.reason, "landing_outside_endpoint_radius")

    def test_waypoint_and_landing_timeouts_are_failures(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        self.assertEqual(monitor.evaluate(now=90).reason, "waypoint_progress_timeout")

        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        monitor.consume(
            message("MISSION_ITEM_REACHED", seq=self.route.final_waypoint.sequence),
            now=1,
        )
        self.assertEqual(monitor.evaluate(now=91).reason, "landing_timeout")

    def test_deviation_followed_by_landing_is_failure_with_landing_stop_cause(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        first, second = self.route.waypoints[:2]
        midpoint_lat = (first.latitude + second.latitude) / 2
        midpoint_lon = (first.longitude + second.longitude) / 2
        monitor.consume(message("MISSION_CURRENT", seq=second.sequence), now=1)
        monitor.consume(message(
            "SIMSTATE",
            lat=round((midpoint_lat + 0.0002) * 1e7),
            lng=round(midpoint_lon * 1e7),
        ), now=2)
        final = self.route.final_waypoint
        monitor.consume(message("MISSION_ITEM_REACHED", seq=final.sequence), now=3)
        monitor.consume(message("EXTENDED_SYS_STATE", landed_state=1), now=4)
        monitor.consume(message(
            "SIMSTATE",
            lat=round(final.latitude * 1e7),
            lng=round(final.longitude * 1e7),
        ), now=4)

        outcome = monitor.evaluate(now=4)
        self.assertEqual((outcome.category, outcome.reason), ("failure", "route_deviation"))
        self.assertEqual(outcome.termination_reason, "landed_at_final_waypoint")

    def test_deviation_followed_by_waypoint_or_landing_timeout_keeps_terminal_cause(self):
        first, second = self.route.waypoints[:2]
        midpoint_lat = (first.latitude + second.latitude) / 2
        midpoint_lon = (first.longitude + second.longitude) / 2

        monitor = MissionOutcomeMonitor(self.route, progress_timeout_s=5, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=second.sequence), now=1)
        monitor.consume(message(
            "SIMSTATE",
            lat=round((midpoint_lat + 0.0002) * 1e7),
            lng=round(midpoint_lon * 1e7),
        ), now=2)
        outcome = monitor.evaluate(now=7)
        self.assertEqual((outcome.category, outcome.reason), ("failure", "route_deviation"))
        self.assertEqual(outcome.termination_reason, "waypoint_progress_timeout")

        monitor = MissionOutcomeMonitor(self.route, progress_timeout_s=5, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=second.sequence), now=1)
        monitor.consume(message(
            "SIMSTATE",
            lat=round((midpoint_lat + 0.0002) * 1e7),
            lng=round(midpoint_lon * 1e7),
        ), now=2)
        monitor.consume(
            message("MISSION_ITEM_REACHED", seq=self.route.final_waypoint.sequence),
            now=3,
        )
        outcome = monitor.evaluate(now=8)
        self.assertEqual((outcome.category, outcome.reason), ("failure", "route_deviation"))
        self.assertEqual(outcome.termination_reason, "landing_timeout")

    def test_deviation_and_safety_events_classify_failure(self):
        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        first, second = self.route.waypoints[:2]
        monitor.consume(message("MISSION_CURRENT", seq=second.sequence), now=1)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round((first.latitude + second.latitude) / 2 * 1e7) + 3000,
            lon=round((first.longitude + second.longitude) / 2 * 1e7),
            relative_alt=10000,
        ), now=2)
        self.assertGreater(monitor.maximum_deviation_m, DEFAULT_DEVIATION_LIMIT_M)
        self.assertIsNone(monitor.evaluate(now=2))

        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        monitor.consume(message("STATUSTEXT", text="EKF Failsafe", severity=2), now=1)
        monitor.consume(message("STATUSTEXT", text="Crash: Disarming", severity=0), now=1)
        self.assertEqual(monitor.evaluate(now=1).reason, "crash_detected")
        self.assertEqual(len(monitor.safety_events), 2)

        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        monitor.consume(message("STATUSTEXT", text="EKF Failsafe", severity=2), now=1)
        self.assertEqual(monitor.evaluate(now=1).reason, "ekf_failsafe")

        monitor = MissionOutcomeMonitor(self.route, started_at=0)
        monitor.consume(message("MISSION_CURRENT", seq=second.sequence), now=1)
        monitor.consume(message(
            "GLOBAL_POSITION_INT",
            lat=round((first.latitude + second.latitude) / 2 * 1e7) + 3000,
            lon=round((first.longitude + second.longitude) / 2 * 1e7),
            relative_alt=10000,
        ), now=2)
        monitor.consume(message("STATUSTEXT", text="EKF Failsafe", severity=2), now=3)
        outcome = monitor.evaluate(now=3)
        self.assertEqual((outcome.category, outcome.reason), ("failure", "route_deviation"))
        self.assertEqual(outcome.termination_reason, "ekf_failsafe")


if __name__ == "__main__":
    unittest.main()
