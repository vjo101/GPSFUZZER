import tempfile
import unittest
from pathlib import Path

from gpsfuzzer.mission import MissionRoute
from gpsfuzzer.mission_mutation import generate_mission
from gpsfuzzer.outcome import horizontal_distance_m
from gpsfuzzer.config import MissionMutationConfig, NumericRange


class MissionMutationTests(unittest.TestCase):
    @staticmethod
    def _template(path: Path, *, takeoff: bool = True, home: bool = True) -> None:
        rows = ["QGC WPL 110"]
        if home:
            rows.append("0\t1\t0\t16\t0\t0\t0\t0\t-35.363262\t149.165237\t584\t1")
        if takeoff:
            rows.append("1\t0\t3\t22\t0\t0\t0\t0\t-35.362491\t149.164780\t20\t1")
        rows.append("2\t0\t3\t21\t0\t0\t0\t0\t-35.360200\t149.168200\t0\t1")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def test_same_seed_reproduces_route_and_different_seed_changes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._template(template)
            settings = MissionMutationConfig(waypoint_count=(3, 3))
            first = generate_mission(template, root / "first.waypoints", 123, settings=settings)
            repeated = generate_mission(template, root / "repeat.waypoints", 123, settings=settings)
            other = generate_mission(template, root / "other.waypoints", 124, settings=settings)

            self.assertEqual(first.path.read_bytes(), repeated.path.read_bytes())
            self.assertNotEqual(first.path.read_bytes(), other.path.read_bytes())
            route = MissionRoute.from_file(first.path)
            self.assertEqual(route.home_waypoint.latitude, -35.363262)
            self.assertEqual(route.home_waypoint.longitude, 149.165237)
            self.assertEqual(len(route.waypoints), 5)  # takeoff + 3 waypoints + land
            self.assertEqual(route.waypoints[-1].command, 21)
            self.assertEqual(
                (route.waypoints[-1].latitude, route.waypoints[-1].longitude),
                (route.waypoints[-2].latitude, route.waypoints[-2].longitude),
            )

    def test_samples_leg_distance_bearing_and_altitude_within_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._template(template)
            generated = generate_mission(
                template,
                root / "generated.waypoints",
                91,
                settings=MissionMutationConfig(
                    waypoint_count=(4, 4),
                    leg_distance_m=NumericRange(120, 120),
                    bearing_deg=NumericRange(90, 90),
                    altitude_m=NumericRange(15, 25),
                ),
            )
            route = MissionRoute.from_file(generated.path)
            route_points = [route.home_waypoint, *route.waypoints[1:-1]]
            self.assertEqual(len(route_points), 5)
            for start, end in zip(route_points, route_points[1:]):
                self.assertAlmostEqual(
                    horizontal_distance_m(start.latitude, start.longitude, end.latitude, end.longitude),
                    120,
                    delta=0.02,
                )
                self.assertGreater(end.longitude, start.longitude)
                self.assertGreaterEqual(end.altitude_m, 15)
                self.assertLessEqual(end.altitude_m, 25)

            data_rows = generated.path.read_text(encoding="utf-8").splitlines()[1:]
            self.assertTrue(all(float(row.split()[4]) == 0 for row in data_rows))
            self.assertEqual(generated.settings["segment_duration"], "derived_from_route_and_vehicle_behavior")

    def test_rejects_templates_without_home_or_takeoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._template(template, home=False)
            with self.assertRaisesRegex(ValueError, "home"):
                generate_mission(template, root / "out.waypoints", 1)
            self._template(template, takeoff=False)
            with self.assertRaisesRegex(ValueError, "TAKEOFF"):
                generate_mission(template, root / "out.waypoints", 1)

    def test_rejects_invalid_ranges_and_waypoint_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.waypoints"
            self._template(template)
            with self.assertRaisesRegex(ValueError, "positive"):
                generate_mission(
                    template, root / "out.waypoints", 1,
                    settings=MissionMutationConfig(leg_distance_m=NumericRange(0, 100)),
                )
            with self.assertRaisesRegex(ValueError, "bearing"):
                generate_mission(
                    template, root / "out.waypoints", 1,
                    settings=MissionMutationConfig(bearing_deg=NumericRange(0, 361)),
                )
            with self.assertRaisesRegex(ValueError, "waypoint_count"):
                generate_mission(
                    template, root / "out.waypoints", 1,
                    settings=MissionMutationConfig(waypoint_count=(4, 3)),
                )


if __name__ == "__main__":
    unittest.main()
