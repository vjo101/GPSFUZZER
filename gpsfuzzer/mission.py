"""Raw mission upload and start workflow shared by baseline and drift runs."""

from pathlib import Path
import time
from typing import Callable


class MissionTakeoffTimeout(TimeoutError):
    """Raised when a guided takeoff does not reach the airborne state."""


def upload_and_start_mission(
    connection,
    mission_path: str | Path,
    *,
    timeout_s: float = 30.0,
    takeoff_timeout_s: float = 120.0,
    on_message: Callable | None = None,
    on_auto_confirmed: Callable[[int], None] | None = None,
    on_takeoff_started: Callable[[int], None] | None = None,
    on_takeoff: Callable[[int], None] | None = None,
) -> int:
    """Guided takeoff, upload a static WPL mission, then start AUTO."""
    from pymavlink import mavutil, mavwp

    loader = mavwp.MAVWPLoader()
    loader.load(str(mission_path))
    count = loader.count()
    if count < 1:
        raise ValueError("mission file contains no mission items")

    request_streams = getattr(connection.mav, "request_data_stream_send", None)
    if request_streams is not None:
        request_streams(connection.target_system, connection.target_component, 0, 4, 1)

    # Match IMUFuzzer's startup sequence: wait until EKF/GPS is ready, allow
    # it to settle, take off in GUIDED, then upload the mission and enter AUTO.
    ready_deadline = time.monotonic() + takeoff_timeout_s
    navigation_ready = False
    while time.monotonic() < ready_deadline:
        message = connection.recv_match(blocking=True, timeout=0.25)
        if message is None:
            if on_message is not None:
                on_message(None)
            continue
        if on_message is not None:
            on_message(message)
        kind = message.get_type()
        status_text = getattr(message, "text", "") if kind == "STATUSTEXT" else ""
        if isinstance(status_text, bytes):
            status_text = status_text.decode("utf-8", errors="replace")
        if kind == "STATUSTEXT" and "EKF3 IMU0 is using GPS" in str(status_text):
            navigation_ready = True
            break
    if not navigation_ready:
        raise TimeoutError(
            f"EKF did not report GPS use within {takeoff_timeout_s:g} seconds"
        )

    time.sleep(2.0)

    guided_mode = connection.mode_mapping().get("GUIDED")
    if guided_mode is None:
        raise RuntimeError("autopilot does not advertise a GUIDED mode")
    connection.mav.set_mode_send(
        connection.target_system,
        getattr(mavutil.mavlink, "MAV_MODE_FLAG_CUSTOM_MODE_ENABLED", 1),
        guided_mode,
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        heartbeat = connection.recv_match(blocking=True, timeout=0.25)
        if on_message is not None:
            on_message(heartbeat)
        if (
            heartbeat is not None
            and heartbeat.get_type() == "HEARTBEAT"
            and heartbeat.custom_mode == guided_mode
        ):
            break
    else:
        raise TimeoutError("ArduCopter did not confirm GUIDED mode")

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
        raise TimeoutError("ArduCopter did not arm for GUIDED takeoff")

    takeoff_started_ns = time.monotonic_ns()
    takeoff_altitude_m = 10
    if on_takeoff_started is not None:
        on_takeoff_started(takeoff_started_ns)
    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        getattr(mavutil.mavlink, "MAV_CMD_NAV_TAKEOFF", 22),
        0,
        0, 0, 0, 0, 0, 0, takeoff_altitude_m,
    )
    in_air_state = getattr(mavutil.mavlink, "MAV_LANDED_STATE_IN_AIR", 2)
    takeoff_deadline = time.monotonic() + takeoff_timeout_s
    while time.monotonic() < takeoff_deadline:
        message = connection.recv_match(
            blocking=True,
            timeout=max(0.01, min(0.25, takeoff_deadline - time.monotonic())),
        )
        if on_message is not None:
            on_message(message)
        airborne = (
            message is not None
            and (
                (
                    message.get_type() == "EXTENDED_SYS_STATE"
                    and message.landed_state == in_air_state
                )
                or (
                    message.get_type() == "GLOBAL_POSITION_INT"
                    and getattr(message, "relative_alt", 0) >= takeoff_altitude_m * 1000
                )
            )
        )
        if airborne:
            takeoff_detected_ns = time.monotonic_ns()
            if on_takeoff is not None:
                on_takeoff(takeoff_detected_ns)
            break
    else:
        raise MissionTakeoffTimeout(
            f"ArduCopter did not report IN_AIR within {takeoff_timeout_s:g} seconds of GUIDED takeoff"
        )

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
    status_texts: list[str] = []
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
        if kind == "STATUSTEXT":
            status = getattr(message, "text", "")
            if isinstance(status, bytes):
                status = status.decode("utf-8", errors="replace")
            if status:
                status_texts.append(str(status).rstrip("\x00"))
        if kind == "MISSION_ACK":
            if getattr(message, "type", 0) != 0:
                # ArduPilot sends the explanatory STATUSTEXT just after the
                # rejection ACK. Drain briefly so the error can identify the
                # advertised mission limit instead of exposing only enum 4.
                status_deadline = time.monotonic() + 0.5
                while time.monotonic() < status_deadline:
                    status_message = connection.recv_match(
                        type="STATUSTEXT", blocking=True,
                        timeout=max(0.01, status_deadline - time.monotonic()),
                    )
                    if status_message is None:
                        break
                    if on_message is not None:
                        on_message(status_message)
                    status = getattr(status_message, "text", "")
                    if isinstance(status, bytes):
                        status = status.decode("utf-8", errors="replace")
                    if status:
                        status_texts.append(str(status).rstrip("\x00"))
                detail = "; ".join(status_texts[-3:])
                suffix = f" ({detail})" if detail else ""
                raise RuntimeError(
                    f"mission upload rejected with result {message.type}{suffix}"
                )
            if len(requested) == count:
                accepted = True
                break
            continue
        if kind not in ("MISSION_REQUEST", "MISSION_REQUEST_INT"):
            continue
        sequence = message.seq
        if sequence < 0 or sequence >= count:
            raise RuntimeError(f"autopilot requested invalid mission sequence {sequence}")
        connection.mav.send(loader.wp(sequence))
        requested.add(sequence)
    if not accepted:
        raise TimeoutError("autopilot did not acknowledge mission upload")

    auto_mode = connection.mode_mapping().get("AUTO")
    if auto_mode is None:
        raise RuntimeError("autopilot does not advertise an AUTO mode")
    connection.set_mode_auto()

    deadline = time.monotonic() + timeout_s
    auto_confirmed = False
    while time.monotonic() < deadline:
        heartbeat = connection.recv_match(
            blocking=True,
            timeout=max(0.01, min(0.25, deadline - time.monotonic())),
        )
        if on_message is not None:
            on_message(heartbeat)
        if (
            heartbeat is not None
            and heartbeat.get_type() == "HEARTBEAT"
            and heartbeat.custom_mode == auto_mode
        ):
            auto_confirmed = True
            auto_confirmed_ns = time.monotonic_ns()
            if on_auto_confirmed is not None:
                on_auto_confirmed(auto_confirmed_ns)
            break
    if not auto_confirmed:
        raise TimeoutError("ArduCopter did not confirm AUTO mode")
    return count
