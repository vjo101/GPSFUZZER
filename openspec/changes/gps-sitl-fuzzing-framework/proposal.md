# Proposal

## Why

GPSFuzzer currently has prototype scripts for sending MAVLink GPS data and managing a mission, but no reproducible, modular GPS fuzzing workflow. This change adapts IMUFuzzer's Python-to-ArduPilot SITL pattern to explore gradual GPS position drift and its effects on navigation and estimation.

## What Changes

- Define a GPS SITL fuzzing capability for configuring, running, and recording reproducible experiments.
- Implement gradual horizontal position drift from simulator truth, with configurable start delay, speed, and bearing selected reproducibly from user-provided ranges.
- Provide a per-experiment toggle between coherent drift, which also offsets reported velocity, and position-only drift, which leaves reported velocity unchanged.
- Control a narrow ArduPilot SITL GPS mutation hook from Python through a GPS-specific System V shared-memory command and status contract.
- Base the integration on the available IMUFuzzer Python and patched ArduPilot source, while documenting where the GPS-specific behavior differs.

## Capabilities

### New Capabilities
- `gps-sitl-fuzzing`: Configure and run reproducible SITL experiments that apply gradual GPS position drift, choose velocity behavior, and collect outcomes.

### Modified Capabilities
- None.

## Impact

The change affects the GPSFuzzer Python framework, its experiment configuration and documentation, and ArduPilot's SITL GPS simulation path, expected to be localized to `libraries/SITL/SIM_GPS.cpp`. ArduPilot already implements coherent drift through `SIM_GPS1_GLTV`; the new hook will add experiment-timed activation and a position-only mode while retaining shared-memory control for greater configurability. The current MAVLink `GPS_INPUT` prototype remains a reference/fallback. The IMUFuzzer reference source is available in `../imufuzzer/data/ardupilot`, including `SensorFuzzer_Bridge.h/.cpp` and the SITL sensor integration in `AP_InertialSensor_SITL.cpp`. IMUFuzzer remains read-only.
