# GPSFuzzer SITL Architecture

## Responsibilities

The Python package validates experiment inputs, samples delay/speed/bearing
from the configured seed, publishes a GPS-specific shared-memory command,
checks hook status, and is responsible for experiment lifecycle and provenance
collection. `gpsfuzzer/config.py` defines typed ranges and the velocity mode;
`gpsfuzzer/drift.py` returns an immutable `EffectiveDrift` record. The
`gpsfuzzer/ipc.py` module owns serialization and System V segment lifecycle.
`gpsfuzzer/runner.py` starts ArduCopter SITL, monitors the hook, captures raw
MAVLink telemetry and DataFlash logs, and writes a provenance record. When a
mission file is supplied, `gpsfuzzer/mission.py` uploads it and starts AUTO
mode for baseline and drift runs. A custom `LAT,LON,ALT,HEADING` option lets
experiments validate geographic conversion at different latitudes.

Mission runs wait for `EKF3 IMU0 is using GPS`, settle for two seconds, then
follow IMUFuzzer's order: GUIDED, arm, take off, wait for `EXTENDED_SYS_STATE`
to report `IN_AIR` or for `GLOBAL_POSITION_INT` to show a 10 m climb, upload
the static mission, and enter AUTO. The heartbeat can arrive
before mission storage initialization has completed, so uploading immediately
after connection can be rejected with zero available mission slots. GPS drift
stays inactive until the airborne report, then a new hook command starts the
configured delay. A 120-second takeoff timeout records the run as incomplete.

ArduPilot's SITL GPS path remains responsible for constructing its native
`GPS_Data` sample. The hook in `libraries/SITL/SIM_GPS.cpp` reads the command
and adjusts that sample before backend publication. The hook applies to the
primary SITL GPS instance (instance 0); other simulated GPS instances remain
unchanged.

## Shared-memory ABI

The GPSFuzzer segment uses key `0x47505346` (ASCII `GPSF`), distinct from the
IMUFuzzer sensor keys. It consists of a 72-byte command followed by a 48-byte
status record. Both sides use packed little-endian fields, with no native
alignment padding. Python uses explicit `struct.Struct` formats, and C++ uses
packed declarations plus compile-time size assertions. The records currently
use ABI version 1.

| Command offset | Field | Type | Unit / meaning |
| ---: | --- | --- | --- |
| 0 | magic | u32 | `0x47505346` |
| 4 | version | u16 | ABI version, currently 1 |
| 6 | size | u16 | command size, 72 bytes |
| 8 | sequence | u64 | command sequence; positive and acknowledged by SITL |
| 16 | experiment_id | u64 | experiment identifier |
| 24 | flags | u32 | bit 0 enables mutation; zero disables |
| 28 | mode | u32 | 0 coherent, 1 position-only |
| 32 | start_delay | i64 | microseconds after command consumption in SITL simulation time |
| 40 | speed | f64 | horizontal drift speed, metres per second |
| 48 | bearing | f64 | degrees clockwise from north, inclusive range 0..360 |
| 56 | published_at | u64 | host monotonic nanoseconds, used for freshness |
| 64 | ttl | u64 | command freshness limit in nanoseconds |

The status record starts at byte 72:

| Status offset | Field | Type | Unit / meaning |
| ---: | --- | --- | --- |
| 0 | magic | u32 | `0x47505346` |
| 4 | version | u16 | ABI version, currently 1 |
| 6 | size | u16 | status size, 48 bytes |
| 8 | acknowledged_sequence | u64 | most recently consumed command sequence |
| 16 | state | u32 | 0 starting, 1 ready, 2 invalid, 3 stale |
| 20 | error_code | u32 | zero on ready, nonzero on interface/validation errors |
| 24 | simulation_time | u64 | last processed GPS simulation timestamp, microseconds |
| 32 | heartbeat | u64 | host monotonic nanoseconds when SITL last updated status |
| 40 | generation | u64 | status update counter |

These sizes and field offsets match `COMMAND_FORMAT` and `STATUS_FORMAT` in
`gpsfuzzer/ipc.py` and the packed `GPSFuzzerCommand` and `GPSFuzzerStatus`
declarations in `SIM_GPS.cpp`. Python's standard-library `ctypes` calls the
System V APIs; no third-party Python IPC dependency is added. `pymavlink` is
pinned in `requirements.txt` for telemetry capture and mission control; the
repository's existing MAVLink examples also use it.

## Drift timing and position conversion

Python samples and records the effective delay, speed, and bearing using a
private `random.Random(seed)` instance. It sends those values without further
sampling in C++. The start delay is measured from the simulation timestamp at
which SITL first consumes a fresh command sequence. Before that delay elapses,
position and velocity remain native. Thereafter, the hook integrates the
north/east drift vector using elapsed SITL simulation time, not wall-clock
time. North/east metres are converted to latitude/longitude degrees using an
Earth radius of 6,371,000 metres and a bounded local cosine scale; altitude is
unchanged.

In **coherent** mode the same north/east vector is added to reported horizontal
velocity, so position and velocity indicate the same drift. In
**position-only** mode only position changes; `speedN` and `speedE` retain
their native simulated values. Vertical velocity and altitude are outside this
initial drift model.

## Readiness, freshness, and cleanup

Python creates or attaches the GPSF segment with mutation inactive until a
command is published. SITL reports readiness only after validating the magic,
version, size, sequence, mode, units/ranges, and command freshness. It
acknowledges the sequence and updates its status heartbeat and simulation
timestamp on each GPS publication. Python starts a run only after the expected
sequence is acknowledged in ready state and checks that the heartbeat remains
fresh. A stale or invalid command disables drift and changes status to stale
or invalid; a missing shared-memory segment leaves the GPS measurement
unchanged.

The runner explicitly publishes a disabled command for baseline runs and
on normal shutdown. On communication loss, SITL's command TTL disables
mutation. Cleanup order is: publish disable if communication remains, stop
SITL, detach Python, then remove the System V segment. Removing the segment
while SITL is attached is safe at the kernel level but it remains mapped until
the SITL process exits.

## Experiment provenance

An experiment record should preserve the seed, original configuration,
effective sampled delay/speed/bearing, velocity mode, GPSFuzzer and ArduPilot
revisions, SITL launch/settings, duration, termination reason, telemetry and
DataFlash log paths, and hook status/acknowledgments. Raw telemetry and logs
are retained for both baseline and drift runs; this initial architecture does
not apply IMUFuzzer's IMU-specific feedback score.

The ArduPilot integration is currently localized to
`libraries/SITL/SIM_GPS.cpp`. The ArduCopter SITL target builds successfully
after configuring Waf for `--board sitl` and running `./waf copter` from the
ArduPilot checkout with the GPSFuzzer venv Python.

## Running an experiment

Create the project venv and install the runtime dependency with
`python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`. For
the ArduPilot Waf build, install its Python build tools into that same venv
with `.venv/bin/pip install empy==3.3.4 pexpect`. From `../ardupilot`, configure
and build with `../GPSFUZZER/.venv/bin/python ./waf configure --board sitl`
and `../GPSFUZZER/.venv/bin/python ./waf copter`. Then run:

```sh
./.venv/bin/python -m gpsfuzzer configs/sitl-example.json \
  --ardupilot ../ardupilot --results results
```

Use `--baseline` to run the same SITL workflow with mutation disabled and
`--mission path/to/mission.txt` to upload and execute a QGroundControl WPL
mission. Add `--map` to start ArduPilot's MAVProxy map with GPS, simulator
truth, and AHRS/EKF position overlays enabled. Add `--console` to launch the
MAVProxy console as well. With either GUI option, the runner leaves MAVProxy
connected to SITL and receives a telemetry copy on UDP port 14550; headless
runs continue to connect directly on port 5760. The selected UI options and
telemetry port are recorded in `experiment.json`. Each run writes
`experiment.json`, `telemetry.jsonl`, the SITL console log, and DataFlash BIN
paths under a unique results directory.

For a live mission map, run:

```sh
./.venv/bin/python -m gpsfuzzer configs/sitl-coherent.json \
  --ardupilot ../ardupilot --results results \
  --mission waypoints.txt --map --console
```

Use `--location 60,24,100,0` to place the simulator at 60° latitude for
longitude-scale checks. Use `--drop-heartbeat-after 5` to stop refreshing a
command five seconds after hook readiness and exercise the two-second command
TTL; that injected communication loss is expected to produce an incomplete
record with captured logs.

### Important changes to ardupilot
./.venv/bin/pip install MAVProxy
MAVPROXY_CMD="$PWD/.venv/bin/mavproxy.py" \
  ./.venv/bin/python -m gpsfuzzer configs/sitl-coherent.json \
  --ardupilot ../ardupilot --results results \
  --mission waypoints.txt --map --console

PYTHONPATH=/usr/lib/python3/dist-packages \
MAVPROXY_CMD="$PWD/.venv/bin/mavproxy.py" \
./.venv/bin/python -m gpsfuzzer configs/sitl-coherent.json \
  --ardupilot ../ardupilot --results results \
  --mission waypoints.txt --map --console
