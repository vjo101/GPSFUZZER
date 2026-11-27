# Proposal

## Why

Mission campaigns currently run at ArduPilot SITL's default 1× simulation speed, which makes repeated experiments slow. We want to measure whether 2× and 3× simulation speed reduce wall-clock time while preserving comparable GPS spoofing and vehicle outcomes.

## What Changes

- Add a configurable SITL simulation speedup, defaulting to 2× based on the initial comparison, and apply it consistently to experiment runs.
- Record the requested and effective speedup in each experiment and campaign record.
- Provide a reproducible comparison procedure for 1×, 2×, and 3× using matched seeds, mission routes, and GPS drift parameters, comparing runtime, telemetry completeness, and flight/outcome evidence.
- Keep 1× available as an explicit reference condition, with 3× available for comparison.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gps-sitl-fuzzing`: Configure, apply, and record SITL simulation speedup and support meaningful comparison of speedup conditions.

## Impact

- `gpsfuzzer/config.py`, `gpsfuzzer/__main__.py`, `gpsfuzzer/runner.py`, and campaign/experiment record generation.
- GPS SITL fuzzing configuration files and documentation for the controlled 1×/2×/3× comparison.
- ArduPilot SITL parameter handling for `SIM_SPEEDUP`; no ArduPilot source changes are expected.
