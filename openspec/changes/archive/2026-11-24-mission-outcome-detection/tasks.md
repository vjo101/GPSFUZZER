# Tasks

## 1. Build mission outcome tracking

- [x] 1.1 Add mission parsing helpers that identify navigation items, active legs, and the final mission coordinate from the uploaded WPL file; verify home items and non-navigation commands do not corrupt the route index.
- [x] 1.2 Add a mission outcome monitor for mission progress, GPS position, landed state, crash and EKF failsafe status text; verify each event produces the expected terminal outcome and evidence in focused unit tests.
- [x] 1.3 Implement horizontal point-to-leg and endpoint distance calculations with latitude-aware geographic scaling; verify known distances, the 15 metre boundary, and representative latitudes.
- [x] 1.4 Add the 15 metre deviation/landing radius and 90 second no-progress timeout defaults and document their IMUFuzzer provenance; verify both values are included in mission result records.

## 2. Integrate outcome tracking with experiments

- [x] 2.1 Feed received MAVLink messages to the mission monitor without changing telemetry JSONL capture; verify message capture continues through terminal classification.
- [x] 2.2 Stop mission observation on success, crash, EKF failsafe, deviation, waypoint/landing timeout, SITL exit, or duration expiry and map each to success, failed, or incomplete; verify precedence and termination reasons with runner tests.
- [x] 2.3 Extend `experiment.json` with outcome, reason, mission progress, endpoint and vehicle position, landing state, maximum deviation, thresholds, and triggering event evidence; verify complete and interrupted records retain telemetry and logs.
- [x] 2.4 Preserve duration-based completion for non-mission runs; verify existing baseline and non-mission tests continue to pass.

## 3. Validate and document SITL outcomes

- [x] 3.1 Add focused tests for final waypoint plus landing success, endpoint miss, no-progress timeout, route deviation, crash, EKF failsafe, missing telemetry, and simultaneous event precedence; verify all expected classifications.
- [x] 3.2 Run a SITL mission that lands at its final waypoint and controlled SITL cases for available failure signals; verify outcome records, telemetry, console logs, and DataFlash logs are retained.
- [x] 3.3 Document the outcome categories, provisional thresholds, evidence fields, and how to tune the thresholds in the GPSFuzzer architecture and validation guides; verify the documented result schema matches implementation.
