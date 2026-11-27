# Proposal

## Why

Mission runs currently keep sending the active GPS drift command after the terminal LAND mission item becomes active. That can continue influencing the vehicle's GPS/EKF estimate during landing, even though the mission is already in its landing phase.

## What Changes

- Disable GPS drift for mission runs as soon as the final LAND item becomes active.
- For every mission run, treat an armed-to-disarmed transition at low relative altitude after the final item becomes active as landing evidence, even when the vehicle is outside the endpoint radius.
- End observation on an off-endpoint touchdown and classify it as an endpoint-miss failure, preserving route-deviation failure precedence when a deviation was already recorded.
- Keep collecting reported position and SITL `SIMSTATE` telemetry through landing; disabling the injection must not fabricate or freeze simulator ground truth.
- Record the landing-phase trigger and the disable command sequence and hook acknowledgment in the experiment record.
- Preserve current drift behavior for missions without a terminal LAND item and for runs without a mission.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gps-sitl-fuzzing`: Stop mission GPS drift at activation of the terminal LAND item and record evidence that the mutation hook accepted the disable command.

## Impact

The mission outcome monitor and SITL runner in `gpsfuzzer/` need to coordinate detection of the terminal LAND item with a fresh disabled command to the existing GPS mutation hook. The ArduPilot SITL hook already accepts disabled commands through the shared-memory interface; no new dependency or wire format is expected. Mission telemetry and outcome classification continue through landing. `SIMSTATE` remains an observation of simulated vehicle motion, not a spoofed GPS field.
