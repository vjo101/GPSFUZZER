"""Mission outcome classification from the mission and MAVLink telemetry."""

from dataclasses import dataclass
import math
import time

from .mission import MissionRoute, MissionWaypoint

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_DEVIATION_LIMIT_M = 15.0
DEFAULT_PROGRESS_TIMEOUT_S = 90.0
LANDED_STATE_ON_GROUND = 1
HEARTBEAT_ARMED_FLAG = 128
LANDED_RELATIVE_ALTITUDE_M = 1.0


@dataclass(frozen=True)
class MissionOutcome:
    category: str
    reason: str
    termination_reason: str | None = None


def horizontal_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


def horizontal_distance_to_leg_m(
    latitude: float,
    longitude: float,
    start: MissionWaypoint,
    end: MissionWaypoint,
) -> float:
    """Distance from a GPS coordinate to a mission leg in a local NE plane."""
    mean_latitude = math.radians((latitude + start.latitude + end.latitude) / 3.0)
    longitude_scale = max(1.0e-6, abs(math.cos(mean_latitude)))

    def project(lat: float, lon: float) -> tuple[float, float]:
        north = EARTH_RADIUS_M * math.radians(lat - start.latitude)
        east = EARTH_RADIUS_M * longitude_scale * math.radians(lon - start.longitude)
        return east, north

    px, py = project(latitude, longitude)
    ex, ey = project(end.latitude, end.longitude)
    length_squared = ex * ex + ey * ey
    if length_squared == 0:
        return math.hypot(px, py)
    fraction = max(0.0, min(1.0, (px * ex + py * ey) / length_squared))
    return math.hypot(px - fraction * ex, py - fraction * ey)


class MissionOutcomeMonitor:
    """Track route progress, safety messages, deviation, landing and timeout."""

    def __init__(
        self,
        route: MissionRoute,
        *,
        deviation_limit_m: float = DEFAULT_DEVIATION_LIMIT_M,
        progress_timeout_s: float = DEFAULT_PROGRESS_TIMEOUT_S,
        started_at: float | None = None,
    ) -> None:
        if not math.isfinite(deviation_limit_m) or deviation_limit_m <= 0:
            raise ValueError("deviation_limit_m must be a positive finite value")
        if not math.isfinite(progress_timeout_s) or progress_timeout_s <= 0:
            raise ValueError("progress_timeout_s must be a positive finite value")
        self.route = route
        self.deviation_limit_m = deviation_limit_m
        self.progress_timeout_s = progress_timeout_s
        self.started_at = time.monotonic() if started_at is None else started_at
        self.last_progress_at = self.started_at
        self.last_progress_sequence: int | None = None
        self.current_sequence: int | None = None
        self.final_waypoint_active = False
        self.final_waypoint_active_at: float | None = None
        self.final_waypoint_reached = False
        self.final_waypoint_reached_at: float | None = None
        self.landed_state: int | None = None
        self.armed: bool | None = None
        self.armed_seen = False
        self.landing_confirmation: dict | None = None
        self.reported_position: dict | None = None
        self.simulator_truth_position: dict | None = None
        self.position_source: str | None = None
        self.vehicle_position: dict | None = None
        self.endpoint_distance_m: float | None = None
        self.maximum_deviation_m = 0.0
        self.maximum_reported_deviation_m = 0.0
        self.maximum_simulator_deviation_m = 0.0
        self.first_deviation: dict | None = None
        self.safety_events: list[dict] = []

    @staticmethod
    def _message_text(message) -> str:
        text = getattr(message, "text", "")
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        return str(text).rstrip("\x00")

    def consume(self, message, *, now: float | None = None) -> None:
        """Observe one MAVLink message; call evaluate after draining a batch."""
        if message is None:
            return
        observed_at = time.monotonic() if now is None else now
        kind = message.get_type()

        if kind == "STATUSTEXT":
            text = self._message_text(message)
            lowered = text.casefold()
            category = None
            if "crash:" in lowered and "disarm" in lowered:
                category = "crash"
            elif "ekf failsafe" in lowered:
                category = "ekf_failsafe"
            if category is not None:
                self.safety_events.append({
                    "category": category,
                    "text": text,
                    "severity": getattr(message, "severity", None),
                    "observed_monotonic_ns": round(observed_at * 1_000_000_000),
                })

        if kind == "MISSION_CURRENT":
            self._record_progress(int(message.seq), observed_at)
            self._update_geometry(observed_at)
        elif kind == "MISSION_ITEM_REACHED":
            sequence = int(message.seq)
            self._record_progress(sequence, observed_at, force=True)
            if sequence >= self.route.final_waypoint.sequence:
                self._record_final_reached(observed_at)
            self._update_geometry(observed_at)

        if kind == "EXTENDED_SYS_STATE":
            self.landed_state = int(message.landed_state)
            if self.landed_state == LANDED_STATE_ON_GROUND:
                self.landing_confirmation = {
                    "source": "extended_sys_state",
                    "observed_monotonic_ns": round(observed_at * 1_000_000_000),
                }

        if kind == "HEARTBEAT":
            self.armed = bool(int(message.base_mode) & HEARTBEAT_ARMED_FLAG)
            if self.armed:
                self.armed_seen = True
            self._confirm_disarmed_landing(observed_at)

        if kind == "GLOBAL_POSITION_INT":
            latitude = float(message.lat) / 1.0e7
            longitude = float(message.lon) / 1.0e7
            self.reported_position = {
                "latitude": latitude,
                "longitude": longitude,
                "relative_altitude_m": float(getattr(message, "relative_alt", 0)) / 1000.0,
            }
            self._update_geometry(observed_at)
            self._confirm_disarmed_landing(observed_at)

        if kind == "SIMSTATE":
            self.simulator_truth_position = {
                "latitude": float(message.lat) / 1.0e7,
                "longitude": float(message.lng) / 1.0e7,
                "relative_altitude_m": (
                    None if self.reported_position is None
                    else self.reported_position["relative_altitude_m"]
                ),
            }
            self._update_geometry(observed_at)
            self._confirm_disarmed_landing(observed_at)

    def _record_progress(self, sequence: int, observed_at: float, *, force: bool = False) -> None:
        # MAVLink can deliver an older MISSION_CURRENT after a newer sequence
        # (for example around mission completion). Keep the active route leg
        # from moving backwards; an explicit item-reached event may establish
        # a lower sequence when a mission intentionally loops.
        if (
            not force
            and self.current_sequence is not None
            and sequence < self.current_sequence
        ):
            return
        if force or self.last_progress_sequence is None or sequence > self.last_progress_sequence:
            self.last_progress_sequence = sequence
            self.last_progress_at = observed_at
        self.current_sequence = sequence
        if sequence >= self.route.final_waypoint.sequence:
            self._record_final_active(observed_at)
        if sequence > self.route.final_waypoint.sequence:
            self._record_final_reached(observed_at)

    def _record_final_active(self, observed_at: float) -> None:
        if not self.final_waypoint_active:
            self.final_waypoint_active = True
            self.final_waypoint_active_at = observed_at

    def _record_final_reached(self, observed_at: float) -> None:
        self._record_final_active(observed_at)
        if not self.final_waypoint_reached:
            self.final_waypoint_reached = True
            self.final_waypoint_reached_at = observed_at
            self.last_progress_at = observed_at

    def _confirm_disarmed_landing(self, observed_at: float) -> None:
        if self.landing_confirmation is not None:
            return
        position = self.vehicle_position
        if (
            self.armed_seen
            and self.armed is False
            and self.final_waypoint_active
            and position is not None
            and position["relative_altitude_m"] is not None
            and position["relative_altitude_m"] <= LANDED_RELATIVE_ALTITUDE_M
            and self.endpoint_distance_m is not None
            and self.endpoint_distance_m <= self.deviation_limit_m
        ):
            self.landing_confirmation = {
                "source": "disarmed_low_altitude_near_final_waypoint",
                "observed_monotonic_ns": round(observed_at * 1_000_000_000),
                "relative_altitude_m": position["relative_altitude_m"],
                "endpoint_distance_m": self.endpoint_distance_m,
            }

    def _update_geometry(self, observed_at: float) -> None:
        """Measure route and endpoint deviation against SITL truth when present."""
        if self.simulator_truth_position is not None:
            self.position_source = "simstate_truth"
            selected = self.simulator_truth_position
            if self.reported_position is not None:
                selected = {
                    **selected,
                    "relative_altitude_m": self.reported_position["relative_altitude_m"],
                }
        elif self.reported_position is not None:
            self.position_source = "global_position_int"
            selected = self.reported_position
        else:
            return

        self.vehicle_position = selected
        final = self.route.final_waypoint
        self.endpoint_distance_m = horizontal_distance_m(
            selected["latitude"], selected["longitude"],
            final.latitude, final.longitude,
        )
        sequence = (
            self.current_sequence
            if self.current_sequence is not None
            else self.route.waypoints[0].sequence
        )
        leg = self.route.active_leg(sequence)
        if leg is None:
            return

        selected_deviation = horizontal_distance_to_leg_m(
            selected["latitude"], selected["longitude"], *leg,
        )
        if self.simulator_truth_position is not None:
            self.maximum_simulator_deviation_m = max(
                self.maximum_simulator_deviation_m, selected_deviation,
            )
            self.maximum_deviation_m = self.maximum_simulator_deviation_m
            if self.reported_position is not None:
                reported_deviation = horizontal_distance_to_leg_m(
                    self.reported_position["latitude"],
                    self.reported_position["longitude"], *leg,
                )
                self.maximum_reported_deviation_m = max(
                    self.maximum_reported_deviation_m, reported_deviation,
                )
        else:
            self.maximum_reported_deviation_m = max(
                self.maximum_reported_deviation_m, selected_deviation,
            )
            self.maximum_deviation_m = self.maximum_reported_deviation_m

        if (
            selected_deviation > self.deviation_limit_m
            and self.first_deviation is None
        ):
            self.first_deviation = {
                "distance_m": selected_deviation,
                "threshold_m": self.deviation_limit_m,
                "observed_monotonic_ns": round(observed_at * 1_000_000_000),
                "position_source": self.position_source,
            }

    def _terminal_outcome(self, category: str, reason: str) -> MissionOutcome:
        """Keep a detected deviation as the finding while preserving stop cause."""
        if self.first_deviation is not None:
            return MissionOutcome("failure", "route_deviation", reason)
        return MissionOutcome(category, reason, reason)

    def evaluate(self, *, now: float | None = None) -> MissionOutcome | None:
        """Return a terminal classification; deviation alone is non-terminal."""
        current = time.monotonic() if now is None else now
        categories = {event["category"] for event in self.safety_events}
        if "crash" in categories:
            return self._terminal_outcome("failure", "crash_detected")
        if "ekf_failsafe" in categories:
            return self._terminal_outcome("failure", "ekf_failsafe")

        final_item_observed = self.final_waypoint_active or self.final_waypoint_reached
        if final_item_observed:
            if self.landing_confirmation is not None:
                if self.endpoint_distance_m is None:
                    return None
                if self.endpoint_distance_m <= self.deviation_limit_m:
                    return self._terminal_outcome("success", "landed_at_final_waypoint")
                return self._terminal_outcome("failure", "landing_outside_endpoint_radius")
            final_item_seen_at = self.final_waypoint_reached_at or self.final_waypoint_active_at
            if final_item_seen_at is not None and current - final_item_seen_at >= self.progress_timeout_s:
                return self._terminal_outcome("failure", "landing_timeout")

        if current - self.last_progress_at >= self.progress_timeout_s:
            return self._terminal_outcome("failure", "waypoint_progress_timeout")
        return None

    def evidence(self) -> dict:
        final = self.route.final_waypoint
        return {
            "current_sequence": self.current_sequence,
            "last_progress_sequence": self.last_progress_sequence,
            "final_waypoint_sequence": final.sequence,
            "final_waypoint_coordinate": {
                "latitude": final.latitude,
                "longitude": final.longitude,
                "altitude_m": final.altitude_m,
            },
            "final_waypoint_reached": self.final_waypoint_reached,
            "final_waypoint_active": self.final_waypoint_active,
            "landed_state": self.landed_state,
            "armed": self.armed,
            "landing_confirmation": self.landing_confirmation,
            "vehicle_position": self.vehicle_position,
            "reported_vehicle_position": self.reported_position,
            "simulator_truth_position": self.simulator_truth_position,
            "position_source": self.position_source,
            "endpoint_distance_m": self.endpoint_distance_m,
            "maximum_deviation_m": self.maximum_deviation_m,
            "first_deviation": self.first_deviation,
            "maximum_reported_deviation_m": self.maximum_reported_deviation_m,
            "maximum_simulator_deviation_m": self.maximum_simulator_deviation_m,
            "thresholds": {
                "deviation_limit_m": self.deviation_limit_m,
                "landing_radius_m": self.deviation_limit_m,
                "progress_timeout_s": self.progress_timeout_s,
                "disarmed_landing_altitude_limit_m": LANDED_RELATIVE_ALTITUDE_M,
            },
            "safety_events": list(self.safety_events),
        }
