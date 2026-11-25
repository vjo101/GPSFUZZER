"""Raw mission upload and start workflow shared by baseline and drift runs."""

from pathlib import Path
import time
from typing import Callable


def upload_and_start_mission(
    connection,
    mission_path: str | Path,
    *,
    timeout_s: float = 30.0,
    on_message: Callable | None = None,
) -> int:
    """Upload a QGroundControl WPL mission, wait for GPS, arm, and enter AUTO."""
    from pymavlink import mavwp

    loader = mavwp.MAVWPLoader()
    loader.load(str(mission_path))
    count = loader.count()
    if count < 1:
        raise ValueError("mission file contains no mission items")

    connection.waypoint_clear_all_send()
    clear_deadline = time.monotonic() + timeout_s
    cleared = False
    while time.monotonic() < clear_deadline:
        message = connection.recv_match(blocking=True, timeout=0.25)
        if message is None:
            if on_message is not None:
                on_message(None)
            continue
        if on_message is not None:
            on_message(message)
        if message.get_type() == "MISSION_ACK":
            if getattr(message, "type", 0) != 0:
                raise RuntimeError(f"mission clear rejected with result {message.type}")
            cleared = True
            break
    if not cleared:
        raise TimeoutError("autopilot did not acknowledge mission clear")

    connection.mav.mission_count_send(
        connection.target_system, connection.target_component, count
    )
    deadline = time.monotonic() + timeout_s
    requested: set[int] = set()
    accepted = False
    while time.monotonic() < deadline:
        message = connection.recv_match(
            blocking=True,
            timeout=max(0.01, min(0.25, deadline - time.monotonic())),
        )
        if message is None:
            if on_message is not None:
                on_message(None)
            continue
        if on_message is not None:
            on_message(message)
        kind = message.get_type()
        if kind == "MISSION_ACK":
            if getattr(message, "type", 0) != 0:
                raise RuntimeError(f"mission upload rejected with result {message.type}")
            if len(requested) == count:
                accepted = True
                break
            continue
        sequence = message.seq
        if sequence < 0 or sequence >= count:
            raise RuntimeError(f"autopilot requested invalid mission sequence {sequence}")
        connection.mav.send(loader.wp(sequence))
        requested.add(sequence)
    if not accepted:
        raise TimeoutError("autopilot did not acknowledge mission upload")

    request_streams = getattr(connection.mav, "request_data_stream_send", None)
    if request_streams is not None:
        request_streams(
            connection.target_system,
            connection.target_component,
            0,
            4,
            1,
        )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        message = connection.recv_match(blocking=True, timeout=0.25)
        if on_message is not None:
            on_message(message)
        if (
            message is not None
            and message.get_type() == "GPS_RAW_INT"
            and message.fix_type >= 3
        ):
            break
    else:
        raise TimeoutError("GPS fix was not available before mission start")

    connection.arducopter_arm()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        heartbeat = connection.recv_match(blocking=True, timeout=0.25)
        if on_message is not None:
            on_message(heartbeat)
        if (
            heartbeat is not None
            and heartbeat.get_type() == "HEARTBEAT"
            and heartbeat.base_mode & 128
        ):
            break
    else:
        raise TimeoutError("ArduCopter did not arm before mission start")
    connection.set_mode_auto()
    return count
