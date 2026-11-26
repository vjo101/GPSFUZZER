import json
import unittest
import os
import tempfile
import time
from pathlib import Path

from gpsfuzzer import (
    DriftConfig, DriftMode, ExperimentConfig, MissionMutationConfig, NumericRange, sample_drift,
)
from gpsfuzzer.ipc import (
    COMMAND_FORMAT,
    GPS_SHM_KEY,
    SEGMENT_SIZE,
    STATE_READY,
    STATUS_FORMAT,
    SystemVGPSBlock,
    WIRE_MAGIC,
    WIRE_VERSION,
    encode_command,
)


class DriftConfigurationTests(unittest.TestCase):
    def test_ranges_are_sampled_with_explicit_units_and_mode(self):
        config = DriftConfig(
            start_delay_s=NumericRange(2, 4),
            horizontal_speed_mps=NumericRange(1, 3),
            bearing_deg=NumericRange(90, 180),
            mode=DriftMode.POSITION_ONLY,
        )
        result = sample_drift(config, 42)
        self.assertGreaterEqual(result.start_delay_s, 2)
        self.assertLessEqual(result.start_delay_s, 4)
        self.assertGreaterEqual(result.horizontal_speed_mps, 1)
        self.assertLessEqual(result.horizontal_speed_mps, 3)
        self.assertGreaterEqual(result.bearing_deg, 90)
        self.assertLessEqual(result.bearing_deg, 180)
        self.assertEqual(result.mode, DriftMode.POSITION_ONLY)

    def test_rejects_invalid_ranges_and_experiment_values(self):
        with self.assertRaisesRegex(ValueError, "minimum"):
            NumericRange(2, 1)
        with self.assertRaisesRegex(ValueError, "finite"):
            NumericRange(0, float("inf"))
        with self.assertRaisesRegex(ValueError, "delay"):
            DriftConfig(start_delay_s=NumericRange(-1, 2))
        with self.assertRaisesRegex(ValueError, "speed"):
            DriftConfig(horizontal_speed_mps=NumericRange(-0.1, 2))
        with self.assertRaisesRegex(ValueError, "bearing"):
            DriftConfig(bearing_deg=NumericRange(0, 361))
        with self.assertRaisesRegex(ValueError, "integer"):
            ExperimentConfig(seed=True)
        with self.assertRaisesRegex(ValueError, "duration"):
            ExperimentConfig(seed=1, duration_s=0)

    def test_same_seed_and_configuration_produce_same_recorded_values(self):
        config = DriftConfig()
        first = sample_drift(config, 2026)
        second = sample_drift(config, 2026)
        self.assertEqual(first, second)

    def test_mission_mutation_configuration_defaults_and_validation(self):
        defaults = MissionMutationConfig()
        self.assertEqual(defaults.waypoint_count, (3, 6))
        self.assertEqual(defaults.leg_distance_m, NumericRange(60, 240))
        self.assertEqual(defaults.bearing_deg, NumericRange(0, 360))
        self.assertEqual(defaults.altitude_m, NumericRange(10, 30))
        with self.assertRaisesRegex(ValueError, "waypoint_count"):
            MissionMutationConfig(waypoint_count=(4, 3))
        with self.assertRaisesRegex(ValueError, "distance"):
            MissionMutationConfig(leg_distance_m=NumericRange(0, 100))
        with self.assertRaisesRegex(ValueError, "bearing"):
            MissionMutationConfig(bearing_deg=NumericRange(0, 361))
        with self.assertRaisesRegex(ValueError, "altitude"):
            MissionMutationConfig(altitude_m=NumericRange(10, 121))

    def test_experiment_json_parses_mission_mutation_settings(self):
        from gpsfuzzer.__main__ import _configuration

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "seed": 42,
                "mission_mutation": {
                    "waypoint_count": [2, 4],
                    "leg_distance_m": [80, 180],
                    "bearing_deg": [45, 270],
                    "altitude_m": [12, 26],
                },
            }), encoding="utf-8")
            config = _configuration(path)
        self.assertEqual(config.mission_mutation.waypoint_count, (2, 4))
        self.assertEqual(config.mission_mutation.leg_distance_m, NumericRange(80, 180))
        self.assertEqual(config.mission_mutation.bearing_deg, NumericRange(45, 270))
        self.assertEqual(config.mission_mutation.altitude_m, NumericRange(12, 26))


class SharedMemoryTests(unittest.TestCase):
    def test_wire_layout_ack_readiness_freshness_disable_and_cleanup(self):
        self.assertEqual(GPS_SHM_KEY, 0x47505346)
        self.assertEqual(COMMAND_FORMAT.size + STATUS_FORMAT.size, SEGMENT_SIZE)
        config = DriftConfig()
        effective = sample_drift(config, 12)
        command = encode_command(7, 99, effective, published_monotonic_ns=1234)
        decoded = COMMAND_FORMAT.unpack(command)
        self.assertEqual(decoded[0:3], (WIRE_MAGIC, WIRE_VERSION, COMMAND_FORMAT.size))
        self.assertEqual(decoded[3:5], (7, 99))

        key = 0x47500000 | (os.getpid() & 0xFFFF)
        block = SystemVGPSBlock(key)
        try:
            self.assertEqual(block.read_status().state, 0)
            block.write_command(command)
            heartbeat = time.monotonic_ns()
            block.write_status(STATUS_FORMAT.pack(
                WIRE_MAGIC, WIRE_VERSION, STATUS_FORMAT.size, 7,
                STATE_READY, 0, 1_250_000, heartbeat, 1,
            ))
            self.assertTrue(block.is_ready(7))
            self.assertTrue(block.is_fresh(now_monotonic_ns=heartbeat + 10))
            self.assertFalse(block.is_fresh(now_monotonic_ns=heartbeat + 3_000_000_000))
            block.disable(8, 99)
            disabled = COMMAND_FORMAT.unpack(block.read_command())
            self.assertEqual(disabled[3], 8)
            self.assertEqual(disabled[5], 0)
        finally:
            block.close(remove=True)


if __name__ == "__main__":
    unittest.main()
