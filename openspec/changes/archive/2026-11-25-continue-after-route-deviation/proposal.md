# Proposal

## Why

GPSFuzzer currently stops the SITL run as soon as route deviation crosses its threshold. That captures the first detection but hides whether continued GPS drift leads to recovery, later waypoint progress, landing, a crash, or an EKF failsafe.

## What Changes

- Treat route deviation as a recorded, non-terminal finding and continue mission observation after the first threshold crossing.
- Keep GPS drift active after deviation until the run reaches its existing terminal condition.
- Continue to stop observation on crash, EKF failsafe, waypoint/landing timeout, configured experiment-duration timeout, SITL exit, user interruption, and normal mission completion/landing.
- Record the first deviation time and distance, the maximum observed deviation, and the terminal event separately. A run with any detected deviation remains classified as a deviation failure even if the aircraft later lands; the termination reason identifies what actually ended observation.

## Capabilities

### New Capabilities

### Modified Capabilities
- `gps-sitl-fuzzing`: route deviation no longer stops observation immediately; deviation findings, final outcome, and observation termination are recorded separately while GPS drift remains active.

## Impact

Affected areas include mission outcome monitoring, the experiment runner's termination loop, experiment record fields, mission outcome and runner tests, and the architecture guide. No ArduPilot changes or new dependencies are expected. IMUFuzzer is a behavioral reference for continuing a mission after its fuzzing window; this change does not add a GPS drift cutoff or disable the GPS hook at deviation.
