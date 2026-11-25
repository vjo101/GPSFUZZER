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


class FakeMissionConnection:
    target_system = 1
    target_component = 1

    def __init__(self):
        self.mav = FakeMav()
        self.responses = [
            types.SimpleNamespace(type=0, get_type=lambda: "MISSION_ACK"),
            types.SimpleNamespace(seq=0, get_type=lambda: "MISSION_REQUEST_INT"),
            types.SimpleNamespace(seq=1, get_type=lambda: "MISSION_REQUEST"),
            types.SimpleNamespace(type=0, get_type=lambda: "MISSION_ACK"),
            types.SimpleNamespace(fix_type=3, get_type=lambda: "GPS_RAW_INT"),
            types.SimpleNamespace(base_mode=128, get_type=lambda: "HEARTBEAT"),
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


class MissionWorkflowTests(unittest.TestCase):
    def test_uploads_mission_waits_for_fix_and_starts_auto(self):
        fake_mavwp = types.SimpleNamespace(MAVWPLoader=FakeLoader)
        with tempfile.TemporaryDirectory() as tmp:
            mission_path = Path(tmp) / "mission.txt"
            mission_path.write_text("QGC WPL 110\n")
            connection = FakeMissionConnection()
            with patch.dict(sys.modules, {"pymavlink": types.SimpleNamespace(mavwp=fake_mavwp)}):
                count = upload_and_start_mission(connection, mission_path)
        self.assertEqual(count, 2)
        self.assertTrue(connection.cleared)
        self.assertTrue(connection.armed)
        self.assertTrue(connection.auto)
        self.assertEqual(
            [entry for entry in connection.mav.messages if entry[0] == "item"],
            [("item", ("waypoint", 0)), ("item", ("waypoint", 1))],
        )


if __name__ == "__main__":
    unittest.main()
