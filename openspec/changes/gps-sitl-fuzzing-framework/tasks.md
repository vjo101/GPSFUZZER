# Tasks

## 1. Document reference implementation and GPS integration

- [x] 1.1 Write `docs/IMUFUZZER_ANALYSIS.md` tracing Python orchestration/mutators in `src/sensorFuzzingEngine.py`, `src/sensorMutator.py`, and `main_module.py` to System V communication and the patched ArduPilot bridge in `../imufuzzer/data/ardupilot/libraries/AP_InertialSensor/SensorFuzzer_Bridge.h/.cpp` and `AP_InertialSensor_SITL.cpp`; verify each claim against those accessible source files and distinguish reference-tree local edits from upstream behavior.
- [x] 1.2 Write `docs/ARDUPILOT_GPS_ANALYSIS.md` tracing `GPS::update()` in `../ardupilot/libraries/SITL/SIM_GPS.cpp` through `GPS_Data` generation, existing `SIM_GPS1_GLTV` drift, and backend publication; verify the proposed hook point and document every ArduPilot file changed.
- [x] 1.3 Write `docs/GPSFUZZER_ARCHITECTURE.md` defining Python/C++ responsibilities, GPS shared-memory command and acknowledgment layout, field units, drift timing/integration, both velocity modes, freshness and cleanup behavior, and experiment provenance; verify the documented layout against both language declarations.

## 2. Implement reproducible drift configuration and mutation logic

- [x] 2.1 Add typed experiment/drift configuration for start-delay, horizontal-speed, and bearing ranges plus the coherent/position-only toggle; verify unit handling and invalid-range rejection with focused tests.
- [x] 2.2 Add seeded sampling for effective start delay, speed, and bearing and record the sampled values; verify identical outputs for repeated runs with the same seed and configuration.
- [x] 2.3 Add Python System V shared-memory command/status serialization using fixed-width, versioned fields and a GPS-specific key; verify layout, sequence acknowledgment, readiness, freshness, disable, and cleanup behavior with isolated tests, and document any dependency added.

## 3. Implement the ArduPilot SITL GPS drift hook

- [x] 3.1 Add the inactive-by-default hook in the common `GPS::update()` measurement path in `../ardupilot/libraries/SITL/SIM_GPS.cpp` before backend publication; verify the SITL target builds and output matches native GPS when no active command exists.
- [x] 3.2 Read and validate shared-memory commands, acknowledge consumed sequences, and disable mutation on invalid or stale commands; verify startup, abrupt Python exit, stale timeout, and repeated SITL lifecycle behavior with focused checks and document source modifications.
- [x] 3.3 Implement delayed, simulation-time-based horizontal drift using configured speed and bearing; verify position changes at expected rates and remains unchanged before the start delay using unit or SITL checks.
- [x] 3.4 Implement coherent mode (add drift vector to reported horizontal velocity) and position-only mode (leave reported velocity unchanged); verify both modes against GPS telemetry and test position integration at representative latitudes.

## 4. Build experiment orchestration and result capture

- [x] 4.1 Implement the modular runner for ArduCopter SITL startup, hook readiness, baseline/mutation control, termination, and process cleanup; verify lifecycle and unavailable-hook handling with mocked process/interface tests and document the run command.
- [x] 4.2 Collect configured telemetry and ArduPilot logs and store seed, effective delay/speed/bearing, velocity mode, source revisions, SITL settings, duration, termination reason, and log paths; verify complete and interrupted experiment records with tests.
- [x] 4.3 Add baseline and drift mission workflows that preserve raw outcomes without copying IMUFuzzer's IMU-specific feedback scoring; verify baseline disables the hook and both drift modes are selectable from configuration.

## 5. Verify the end-to-end SITL workflow

- [x] 5.1 Run an unmutated ArduCopter SITL baseline and compare GPS telemetry/log output with native simulation; document launch settings and observed equivalence.
- [x] 5.2 Run seeded coherent and position-only drift experiments and verify sampled delay/speed/bearing, field behavior, hook acknowledgments, captured telemetry/logs, and provenance.
- [x] 5.3 Exercise unavailable-hook and mid-run communication-loss cases and verify each run is reported as failed or incomplete with available logs retained.
