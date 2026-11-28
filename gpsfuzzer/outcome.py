"""Mission outcome classification from the mission and MAVLink telemetry."""

from dataclasses import dataclass
import math
import time

from .mission import MAV_CMD_NAV_LAND, MissionRoute, MissionWaypoint

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_DEVIATION_LIMIT_M = 15.0
DEFAULT_PROGRESS_TIMEOUT_S = 90.0
LANDED_STATE_ON_GROUND = 1
HEARTBEAT_ARMED_FLAG = 128
LANDED_RELATIVE_ALTITUDE_M = 1.0
LANDED_TERRAIN_CLEARANCE_M = 1.0
TERRAIN_REPORT_MAX_AGE_S = 5.0


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
        self.terminal_land_active_at: float | None = None
        self.final_waypoint_reached = False
        self.final_waypoint_reached_at: float | None = None
        self.landed_state: int | None = None
        self.armed: bool | None = None
        self.armed_seen = False
        self.terrain_clearance_m: float | None = None
        self.terrain_report_at: float | None = None
        self.landing_confirmation: dict | None = None
        self.reported_position: dict | None = None
        self.simulator_truth_position: dict | None = None
        self.position_source: str | None = None
        self.vehicle_position: dict | None = None
        self.endpoint_distance_m: float | None = None
        self.maximum_deviation_m = 0.0
        self.maximum_reported_deviation_m = 0.0
        self.maximum_simulator_deviation_m = 0.0
        self.maximum_truth_route_deviation_m = 0.0
        self._simulation_time_ms: int | None = None
        self._previous_route_score_sample: tuple[int, int, float] | None = None
        self._route_iae_m_s = 0.0
        self._route_scored_duration_s = 0.0
        self._route_score_intervals = 0
        self._route_score_samples = 0
        self._route_score_legs: dict[str, dict] = {}
        self._previous_truth_motion_sample: tuple[int, float, float] | None = None
        self.truth_velocity_mps: dict | None = None
        self.raw_gps_position: dict | None = None
        self.raw_gps_velocity_mps: dict | None = None
        self.latest_gps_position_offset_m: float | None = None
        self.maximum_gps_position_offset_m: float | None = None
        self.gps_position_offset_sum_m = 0.0
        self.gps_position_offset_samples = 0
        self.latest_gps_velocity_error_mps: float | None = None
        self.maximum_gps_velocity_error_mps: float | None = None
        self.gps_velocity_error_samples = 0
        self.vehicle_velocity_diagnostic_mps: dict | None = None
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

        if kind == "SYSTEM_TIME":
            try:
                simulation_time_ms = int(message.time_boot_ms)
            except (AttributeError, TypeError, ValueError):
                simulation_time_ms = None
            if simulation_time_ms is not None and simulation_time_ms >= 0:
                self._simulation_time_ms = simulation_time_ms

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

        if kind == "TERRAIN_REPORT":
            clearance = float(getattr(message, "current_height", float("nan")))
            if math.isfinite(clearance):
                self.terrain_clearance_m = clearance
                self.terrain_report_at = observed_at
                self._confirm_disarmed_landing(observed_at)

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
            try:
                self.vehicle_velocity_diagnostic_mps = {
                    "source": "GLOBAL_POSITION_INT.vx_vy_vz",
                    "north_mps": float(message.vx) / 100.0,
                    "east_mps": float(message.vy) / 100.0,
                    "down_mps": float(message.vz) / 100.0,
                }
            except (AttributeError, TypeError, ValueError):
                self.vehicle_velocity_diagnostic_mps = None
            self._update_geometry(observed_at)
            self._confirm_disarmed_landing(observed_at)

        if kind == "GPS_RAW_INT":
            self._record_raw_gps_measurement(message)

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
            self._record_route_score_sample()
            self._update_truth_velocity()
            self._confirm_disarmed_landing(observed_at)

    def _record_raw_gps_measurement(self, message) -> None:
        """Keep raw GPS attack exposure distinct from vehicle route response."""
        try:
            fix_type = int(message.fix_type)
            latitude = float(message.lat) / 1.0e7
            longitude = float(message.lon) / 1.0e7
        except (AttributeError, TypeError, ValueError):
            return
        if (
            fix_type < 2
            or not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            return
        self.raw_gps_position = {
            "latitude": latitude,
            "longitude": longitude,
            "fix_type": fix_type,
        }
        if self.simulator_truth_position is not None:
            offset = horizontal_distance_m(
                latitude,
                longitude,
                self.simulator_truth_position["latitude"],
                self.simulator_truth_position["longitude"],
            )
            self.latest_gps_position_offset_m = offset
            self.maximum_gps_position_offset_m = max(
                offset,
                self.maximum_gps_position_offset_m
                if self.maximum_gps_position_offset_m is not None else 0.0,
            )
            self.gps_position_offset_sum_m += offset
            self.gps_position_offset_samples += 1

        try:
            speed_mps = float(message.vel) / 100.0
            course_deg = float(message.cog) / 100.0
        except (AttributeError, TypeError, ValueError):
            return
        if (
            not math.isfinite(speed_mps)
            or not math.isfinite(course_deg)
            or speed_mps < 0
            or course_deg < 0
            or course_deg >= 360
            or speed_mps >= 655.35
        ):
            return
        course_rad = math.radians(course_deg)
        self.raw_gps_velocity_mps = {
            "source": "GPS_RAW_INT.vel_cog",
            "north_mps": speed_mps * math.cos(course_rad),
            "east_mps": speed_mps * math.sin(course_rad),
            "speed_mps": speed_mps,
            "course_deg": course_deg,
        }
        if self.truth_velocity_mps is not None:
            north_error = (
                self.raw_gps_velocity_mps["north_mps"]
                - self.truth_velocity_mps["north_mps"]
            )
            east_error = (
                self.raw_gps_velocity_mps["east_mps"]
                - self.truth_velocity_mps["east_mps"]
            )
            error = math.hypot(north_error, east_error)
            self.latest_gps_velocity_error_mps = error
            self.maximum_gps_velocity_error_mps = max(
                error,
                self.maximum_gps_velocity_error_mps
                if self.maximum_gps_velocity_error_mps is not None else 0.0,
            )
            self.gps_velocity_error_samples += 1

    def _update_truth_velocity(self) -> None:
        """Estimate horizontal truth velocity from timestamped SIMSTATE samples."""
        if self._simulation_time_ms is None or self.simulator_truth_position is None:
            self._previous_truth_motion_sample = None
            return
        current = (
            self._simulation_time_ms,
            self.simulator_truth_position["latitude"],
            self.simulator_truth_position["longitude"],
        )
        previous = self._previous_truth_motion_sample
        if previous is not None:
            delta_s = (current[0] - previous[0]) / 1000.0
            if delta_s > 0:
                mean_latitude = math.radians((current[1] + previous[1]) / 2.0)
                north_m = EARTH_RADIUS_M * math.radians(current[1] - previous[1])
                east_m = (
                    EARTH_RADIUS_M * math.cos(mean_latitude)
                    * math.radians(current[2] - previous[2])
                )
                self.truth_velocity_mps = {
                    "source": "finite_difference_SIMSTATE",
                    "north_mps": north_m / delta_s,
                    "east_mps": east_m / delta_s,
                    "simulation_time_ms": current[0],
                }
        self._previous_truth_motion_sample = current

    def _record_route_score_sample(self) -> None:
        """Accumulate truth-to-route absolute error using SITL simulation time."""
        if self._simulation_time_ms is None or self.simulator_truth_position is None:
            self._previous_route_score_sample = None
            return
        sequence = (
            self.current_sequence
            if self.current_sequence is not None
            else self.route.waypoints[0].sequence
        )
        leg = self.route.active_leg(sequence)
        if leg is None:
            self._previous_route_score_sample = None
            return
        start, end = leg
        leg_key = f"{start.sequence}:{end.sequence}"
        position = self.simulator_truth_position
        deviation_m = horizontal_distance_to_leg_m(
            position["latitude"], position["longitude"], start, end,
        )
        self._route_score_samples += 1
        self.maximum_truth_route_deviation_m = max(
            self.maximum_truth_route_deviation_m, deviation_m,
        )
        leg_score = self._route_score_legs.setdefault(leg_key, {
            "start_sequence": start.sequence,
            "end_sequence": end.sequence,
            "iae_m_s": 0.0,
            "scored_duration_s": 0.0,
            "maximum_deviation_m": 0.0,
            "sample_count": 0,
            "interval_count": 0,
        })
        leg_score["maximum_deviation_m"] = max(
            leg_score["maximum_deviation_m"], deviation_m,
        )
        leg_score["sample_count"] += 1

        previous = self._previous_route_score_sample
        current_time = self._simulation_time_ms
        if previous is not None and previous[1] == end.sequence:
            previous_time, _previous_sequence, previous_deviation = previous
            delta_ms = current_time - previous_time
            if delta_ms > 0:
                delta_s = delta_ms / 1000.0
                interval_iae = (previous_deviation + deviation_m) * 0.5 * delta_s
                self._route_iae_m_s += interval_iae
                self._route_scored_duration_s += delta_s
                self._route_score_intervals += 1
                leg_score["iae_m_s"] += interval_iae
                leg_score["scored_duration_s"] += delta_s
                leg_score["interval_count"] += 1
        self._previous_route_score_sample = (
            current_time, end.sequence, deviation_m,
        )

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
            if self.route.final_waypoint.command == MAV_CMD_NAV_LAND:
                self.terminal_land_active_at = observed_at

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
        terrain_clearance_is_low = (
            self.terrain_clearance_m is not None
            and self.terrain_report_at is not None
            and observed_at - self.terrain_report_at <= TERRAIN_REPORT_MAX_AGE_S
            and self.terrain_clearance_m <= LANDED_TERRAIN_CLEARANCE_M
        )
        relative_altitude_is_low = (
            position is not None
            and position["relative_altitude_m"] is not None
            and position["relative_altitude_m"] <= LANDED_RELATIVE_ALTITUDE_M
        )
        if (
            self.armed_seen
            and self.armed is False
            and self.final_waypoint_active
            and (relative_altitude_is_low or terrain_clearance_is_low)
            and self.endpoint_distance_m is not None
        ):
            terrain_used = terrain_clearance_is_low and not relative_altitude_is_low
            self.landing_confirmation = {
                "source": (
                    "disarmed_low_terrain_clearance_after_final_item"
                    if terrain_used
                    else "disarmed_low_altitude_after_final_item"
                ),
                "observed_monotonic_ns": round(observed_at * 1_000_000_000),
                "relative_altitude_m": (
                    None if position is None else position["relative_altitude_m"]
                ),
                "terrain_clearance_m": (
                    self.terrain_clearance_m if terrain_used else None
                ),
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
            "terminal_land_active": self.terminal_land_active_at is not None,
            "terminal_land_active_at_monotonic_ns": (
                None if self.terminal_land_active_at is None
                else round(self.terminal_land_active_at * 1_000_000_000)
            ),
            "landed_state": self.landed_state,
            "armed": self.armed,
            "terrain_clearance_m": self.terrain_clearance_m,
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
            "route_deviation_score": {
                "source": "SIMSTATE",
                "clock": "SYSTEM_TIME.time_boot_ms",
                "method": "trapezoidal_integral_of_horizontal_distance_to_active_route_leg",
                "iae_m_s": (
                    self._route_iae_m_s if self._route_score_intervals else None
                ),
                "duration_normalized_iae_m": (
                    self._route_iae_m_s / self._route_scored_duration_s
                    if self._route_scored_duration_s > 0 else None
                ),
                "scored_duration_s": self._route_scored_duration_s,
                "sample_count": self._route_score_samples,
                "interval_count": self._route_score_intervals,
                "maximum_deviation_m": (
                    self.maximum_truth_route_deviation_m
                    if self._route_score_samples else None
                ),
                "available": self._route_score_intervals > 0,
                "by_leg": list(self._route_score_legs.values()),
            },
            "gps_measurement_exposure": {
                "position": {
                    "source": "GPS_RAW_INT.lat_lon_vs_SIMSTATE",
                    "latest_offset_m": self.latest_gps_position_offset_m,
                    "maximum_offset_m": self.maximum_gps_position_offset_m,
                    "mean_offset_m": (
                        self.gps_position_offset_sum_m / self.gps_position_offset_samples
                        if self.gps_position_offset_samples else None
                    ),
                    "sample_count": self.gps_position_offset_samples,
                    "latest_raw_gps_position": self.raw_gps_position,
                    "latest_simulator_truth_position": self.simulator_truth_position,
                },
                "velocity": {
                    "source": "GPS_RAW_INT.vel_cog_vs_finite_difference_SIMSTATE",
                    "latest_error_mps": self.latest_gps_velocity_error_mps,
                    "maximum_error_mps": self.maximum_gps_velocity_error_mps,
                    "sample_count": self.gps_velocity_error_samples,
                    "latest_raw_gps_velocity": self.raw_gps_velocity_mps,
                    "latest_truth_velocity": self.truth_velocity_mps,
                },
            },
            "vehicle_velocity_diagnostic": self.vehicle_velocity_diagnostic_mps,
            "thresholds": {
                "deviation_limit_m": self.deviation_limit_m,
                "landing_radius_m": self.deviation_limit_m,
                "progress_timeout_s": self.progress_timeout_s,
                "disarmed_landing_altitude_limit_m": LANDED_RELATIVE_ALTITUDE_M,
                "disarmed_landing_terrain_clearance_limit_m": LANDED_TERRAIN_CLEARANCE_M,
                "terrain_report_max_age_s": TERRAIN_REPORT_MAX_AGE_S,
            },
            "safety_events": list(self.safety_events),
        }
