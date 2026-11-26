"""Seeded generation of bounded QGroundControl WPL mission routes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import random

from .config import MissionMutationConfig

EARTH_RADIUS_M = 6_371_000.0
MAX_GENERATED_WAYPOINTS = 100


@dataclass(frozen=True)
class MissionGenerationResult:
    path: Path
    seed: int
    waypoint_count: int
    settings: dict


def _validate_range(name: str, bounds: tuple[float, float]) -> tuple[float, float]:
    if len(bounds) != 2:
        raise ValueError(f"{name} must contain minimum and maximum values")
    minimum, maximum = (float(value) for value in bounds)
    if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum > maximum:
        raise ValueError(f"{name} must have finite ordered bounds")
    return minimum, maximum


def _load_template(path: str | Path) -> tuple[list[str], list[str], float, float, float]:
    template = Path(path)
    try:
        lines = template.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read mission template {template}: {exc}") from exc
    if not lines or lines[0].strip() != "QGC WPL 110":
        raise ValueError("mission template must use QGC WPL 110 format")

    rows = [line.split() for line in lines[1:] if line.strip()]
    if any(len(row) != 12 for row in rows):
        raise ValueError("each mission item must contain 12 QGC WPL fields")
    home = next((row for row in rows if row[0] == "0" and row[1] == "1"), None)
    if home is None:
        raise ValueError("mission template must contain a current sequence-zero home item")
    if not any(row[3] == "22" for row in rows):
        raise ValueError("mission template must contain a NAV_TAKEOFF item")

    try:
        latitude, longitude, altitude = (float(home[index]) for index in (8, 9, 10))
        frame = int(home[2])
    except (ValueError, IndexError) as exc:
        raise ValueError("mission template home item has invalid coordinates or frame") from exc
    if not all(math.isfinite(value) for value in (latitude, longitude, altitude)):
        raise ValueError("mission template home coordinates must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("mission template home latitude/longitude is out of range")
    if frame not in (0, 3, 5, 6, 10, 11):
        raise ValueError("mission template home must use a global coordinate frame")
    return rows, home, latitude, longitude, altitude


def _coordinate_at_distance(
    latitude: float,
    longitude: float,
    distance_m: float,
    bearing_deg: float,
) -> tuple[float, float]:
    angular_distance = distance_m / EARTH_RADIUS_M
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    longitude_deg = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return math.degrees(lat2), longitude_deg


def _wpl_row(
    sequence: int,
    command: int,
    frame: int,
    latitude: float,
    longitude: float,
    altitude_m: float,
    *,
    current: int = 0,
) -> str:
    return "\t".join((
        str(sequence), str(current), str(frame), str(command),
        "0", "0", "0", "0",
        f"{latitude:.9f}", f"{longitude:.9f}", f"{altitude_m:.3f}", "1",
    ))


def generate_mission(
    template_path: str | Path,
    output_path: str | Path,
    seed: int,
    *,
    settings: MissionMutationConfig | None = None,
) -> MissionGenerationResult:
    """Generate a deterministic home-relative route and write it as QGC WPL."""
    settings = settings or MissionMutationConfig()
    waypoint_count = settings.waypoint_count
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("mission generation seed must be an integer")
    if (
        len(waypoint_count) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in waypoint_count)
        or waypoint_count[0] < 1
        or waypoint_count[0] > waypoint_count[1]
        or waypoint_count[1] > MAX_GENERATED_WAYPOINTS
    ):
        raise ValueError(f"waypoint_count must be an ordered integer range within 1..{MAX_GENERATED_WAYPOINTS}")

    distance_bounds = _validate_range(
        "leg_distance_m", (settings.leg_distance_m.minimum, settings.leg_distance_m.maximum)
    )
    bearing_bounds = _validate_range(
        "bearing_deg", (settings.bearing_deg.minimum, settings.bearing_deg.maximum)
    )
    altitude_bounds = _validate_range(
        "altitude_m", (settings.altitude_m.minimum, settings.altitude_m.maximum)
    )
    if distance_bounds[0] <= 0:
        raise ValueError("leg_distance_m must be positive")
    if bearing_bounds[0] < 0 or bearing_bounds[1] > 360:
        raise ValueError("bearing_deg must be within 0..360 degrees clockwise from north")
    if altitude_bounds[0] <= 0:
        raise ValueError("altitude_m must be positive")

    template_rows, home_row, home_lat, home_lon, home_alt = _load_template(template_path)
    takeoff_row = next(row for row in template_rows if row[3] == "22")
    try:
        takeoff_alt = float(takeoff_row[10])
    except ValueError as exc:
        raise ValueError("mission template takeoff altitude must be numeric") from exc
    if not math.isfinite(takeoff_alt) or takeoff_alt <= 0:
        raise ValueError("mission template takeoff altitude must be positive and finite")

    rng = random.Random(seed)
    count = rng.randint(*waypoint_count)
    current_lat, current_lon = home_lat, home_lon
    rows = ["QGC WPL 110"]
    rows.append("\t".join(home_row))
    rows.append(_wpl_row(1, 22, 3, home_lat, home_lon, takeoff_alt))
    for sequence in range(2, count + 2):
        distance = rng.uniform(*distance_bounds)
        bearing = rng.uniform(*bearing_bounds)
        altitude = rng.uniform(*altitude_bounds)
        current_lat, current_lon = _coordinate_at_distance(
            current_lat, current_lon, distance, bearing
        )
        if not -90 <= current_lat <= 90:
            raise ValueError("generated waypoint latitude is out of range")
        rows.append(_wpl_row(sequence, 16, 3, current_lat, current_lon, altitude))
    rows.append(_wpl_row(count + 2, 21, 3, current_lat, current_lon, 0.0))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return MissionGenerationResult(
        output,
        seed,
        count,
        {
            "waypoint_count": {"minimum": waypoint_count[0], "maximum": waypoint_count[1]},
            "leg_distance_m": {"minimum": distance_bounds[0], "maximum": distance_bounds[1]},
            "bearing_deg": {"minimum": bearing_bounds[0], "maximum": bearing_bounds[1]},
            "altitude_m": {"minimum": altitude_bounds[0], "maximum": altitude_bounds[1]},
            "sampled_waypoint_count": count,
            "home": {"latitude": home_lat, "longitude": home_lon, "altitude_m": home_alt},
            "segment_duration": "derived_from_route_and_vehicle_behavior",
        },
    )
