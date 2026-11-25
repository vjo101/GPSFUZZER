import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from gpsfuzzer.mission import upload_and_start_mission


class FakeLoader:
    def __init__(self):
        self.loaded = None

    def load(self, path):
        self.loaded = path

    def count(self):
        return 2

    def wp(self, sequence):
        return ("waypoint", sequence)


class FakeMav:
    def __init__(self):
        self.messages = []

    def mission_count_send(self, *args):
        self.messages.append(("count", args))

    def send(self, message):
        self.messages.append(("item", message))

    def set_mode_send(self, *args):
        self.messages.append(("mode", args))

    def command_long_send(self, *args):
        self.messages.append(("command", args))


class FakeMissionConnection:
    target_system = 1
    target_component = 1

    def __init__(self):
        self.mav = FakeMav()
        self.responses = [
            types.SimpleNamespace(
                text="EKF3 IMU0 is using GPS",
                get_type=lambda: "STATUSTEXT",
            ),
            types.SimpleNamespace(custom_mode=4, base_mode=81, get_type=lambda: "HEARTBEAT"),
            types.SimpleNamespace(base_mode=128, custom_mode=4, get_type=lambda: "HEARTBEAT"),
            types.SimpleNamespace(landed_state=2, get_type=lambda: "EXTENDED_SYS_STATE"),
            types.SimpleNamespace(type=0, get_type=lambda: "MISSION_ACK"),
            types.SimpleNamespace(seq=0, get_type=lambda: "MISSION_REQUEST_INT"),
            types.SimpleNamespace(seq=1, get_type=lambda: "MISSION_REQUEST"),
            types.SimpleNamespace(type=0, get_type=lambda: "MISSION_ACK"),
            types.SimpleNamespace(custom_mode=3, get_type=lambda: "HEARTBEAT"),
        ]
        self.cleared = False
        self.armed = False
        self.auto = False

    def waypoint_clear_all_send(self):
        self.cleared = True

    def recv_match(self, **kwargs):
        return self.responses.pop(0) if self.responses else None

    def arducopter_arm(self):
        self.armed = True

    def set_mode_auto(self):
        self.auto = True

    def mode_mapping(self):
        return {"GUIDED": 4, "AUTO": 3}


class MissionWorkflowTests(unittest.TestCase):
    def test_guided_takeoff_precedes_mission_upload_and_auto(self):
        fake_mavwp = types.SimpleNamespace(MAVWPLoader=FakeLoader)
        fake_mavutil = types.SimpleNamespace(
            mavlink=types.SimpleNamespace(
                MAV_LANDED_STATE_IN_AIR=2,
                MAV_CMD_NAV_TAKEOFF=22,
                MAV_MODE_FLAG_CUSTOM_MODE_ENABLED=1,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            mission_path = Path(tmp) / "mission.txt"
            mission_path.write_text("QGC WPL 110\n")
            connection = FakeMissionConnection()
            callbacks = {}
            with patch.dict(sys.modules, {"pymavlink": types.SimpleNamespace(
                mavwp=fake_mavwp, mavutil=fake_mavutil
            )}), patch("gpsfuzzer.mission.time.sleep"):
                count = upload_and_start_mission(
                    connection,
                    mission_path,
                    on_auto_confirmed=lambda value: callbacks.setdefault("auto", value),
                    on_takeoff=lambda value: callbacks.setdefault("takeoff", value),
                )
        self.assertEqual(count, 2)
        self.assertTrue(connection.cleared)
        self.assertTrue(connection.armed)
        self.assertTrue(connection.auto)
        self.assertLess(callbacks["takeoff"], callbacks["auto"])
        command_index = next(i for i, event in enumerate(connection.mav.messages) if event[0] == "command")
        count_index = next(i for i, event in enumerate(connection.mav.messages) if event[0] == "count")
        self.assertLess(command_index, count_index)
        self.assertEqual(
            [entry for entry in connection.mav.messages if entry[0] == "item"],
            [("item", ("waypoint", 0)), ("item", ("waypoint", 1))],
        )

    def test_times_out_when_guided_takeoff_never_reports_airborne(self):
        fake_mavwp = types.SimpleNamespace(MAVWPLoader=FakeLoader)
        fake_mavutil = types.SimpleNamespace(mavlink=types.SimpleNamespace())

        class FakeClock:
            def __init__(self):
                self.value = 0.0

            def monotonic(self):
                value = self.value
                self.value += 0.1
                return value

        with tempfile.TemporaryDirectory() as tmp:
            mission_path = Path(tmp) / "mission.txt"
            mission_path.write_text("QGC WPL 110\n")
            connection = FakeMissionConnection()
            connection.responses = connection.responses[:3]
            takeoff_events = []
            clock = FakeClock()
            with patch.dict(sys.modules, {"pymavlink": types.SimpleNamespace(
                mavwp=fake_mavwp, mavutil=fake_mavutil
            )}), patch("gpsfuzzer.mission.time.sleep"):
                with patch("gpsfuzzer.mission.time.monotonic", clock.monotonic):
                    with self.assertRaisesRegex(TimeoutError, "IN_AIR"):
                        upload_and_start_mission(
                            connection,
                            mission_path,
                            timeout_s=30,
                            takeoff_timeout_s=0.5,
                            on_takeoff=takeoff_events.append,
                        )
            self.assertFalse(connection.auto)
            self.assertEqual(takeoff_events, [])


if __name__ == "__main__":
    unittest.main()
