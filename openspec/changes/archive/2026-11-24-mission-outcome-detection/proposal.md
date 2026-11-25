# Proposal

## Why

GPSFuzzer currently marks a mission run completed when its configured duration expires, without determining whether the vehicle completed the route, landed at the intended endpoint, crashed, entered a failsafe, deviated too far, or stalled. Adding mission outcome detection will make each SITL run produce a useful and reproducible success or failure classification.

## What Changes

- Monitor mission progress and vehicle state while a mission runs, and classify terminal outcomes as success, failure, or incomplete.
- Define mission success as reaching the last mission waypoint and confirming the vehicle has landed within the endpoint tolerance.
- Detect and record ArduCopter crash and EKF failsafe indications, excessive route deviation, and mission progress timeouts.
- Start with a 15 m deviation threshold and a 90 second per-waypoint progress timeout, matching values found in the IMUFuzzer reference; record them as provisional defaults.
- Preserve telemetry, logs, and provenance when an outcome terminates the run.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gps-sitl-fuzzing`: Specify mission outcome detection, completion criteria, failure classification, and outcome provenance.

## Impact

This changes `gpsfuzzer/runner.py` and likely adds a GPSFuzzer mission outcome monitor and focused tests. Mission coordinates and progress come from the uploaded WPL mission and MAVLink telemetry. IMUFuzzer's `src/crashChecker.py` and distance analysis provide behavioral references only; the GPSFuzzer implementation will adapt the logic to its telemetry flow and use ArduCopter's crash and EKF failsafe messages. No ArduPilot source change or new dependency is expected.
