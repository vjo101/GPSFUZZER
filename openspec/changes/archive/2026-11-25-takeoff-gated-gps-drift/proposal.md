# Proposal

## Why

Mission runs currently activate GPS drift when the SITL hook becomes ready, before the vehicle has taken off. This can spoof the GPS fix while the vehicle is still on the ground and makes configured drift delays unrelated to the mission's flight phase.

## What Changes

- Keep GPS mutation disabled until navigation is ready and a GUIDED takeoff is reported airborne.
- Follow the IMUFuzzer mission order: take off, upload the static mission while airborne, then enter AUTO.
- Activate the drift command only after ArduPilot reports takeoff, measure the configured delay from that transition, and record takeoff-gate timing in experiment results.
- Mark a mission run incomplete without activating drift if takeoff is not reported within 120 seconds after the GUIDED takeoff command.
- Preserve the current startup-relative behavior for runs without a mission.

## Capabilities

### New Capabilities

- `gps-sitl-fuzzing`: Add mission takeoff gating to the existing GPS drift experiment behavior.

### Modified Capabilities

None. The current capability only exists as a delta in the completed `gps-sitl-fuzzing-framework` change; this change will define its durable spec.

## Impact

This affects `gpsfuzzer/runner.py`, `gpsfuzzer/mission.py`, experiment provenance, and the ArduPilot GPSFuzzer command timing contract if activation requires a new command sequence. It uses MAVLink flight state to distinguish arming/AUTO from actual airborne state. No new runtime dependency is anticipated.
