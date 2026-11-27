# Design

## Context

See proposal.md for motivation and the delta spec for observable behavior. The runner republishes the active drift command while observing a mission. `MissionOutcomeMonitor` already tracks when the final route item becomes active, and `MissionRoute` retains each item's MAVLink command. The shared-memory hook accepts an explicit disabled command and acknowledges command sequences. `SIMSTATE` is separately emitted simulator truth; the GPS mutation hook modifies the GPS measurement and does not rewrite `SIMSTATE`.

## Goals / Non-Goals

**Goals:**
- Detect activation of the terminal mission item only when it is a LAND command.
- Publish a new disabled hook command once, prevent later heartbeats from re-enabling drift, and record the trigger and acknowledgment.
- Continue telemetry capture and outcome evaluation until the existing mission terminal condition.

**Non-Goals:**
- Freeze or rewrite the simulator's physical position or `SIMSTATE` telemetry.
- Change GPS drift behavior for missions without a terminal LAND item or runs without a mission.
- Change the landing confirmation, deviation, or outcome classification thresholds.

## Decisions

- Use the route's final item sequence and command to distinguish a terminal LAND item from an ordinary final waypoint. Do not disable drift merely because the final item is active when it is not a LAND command.
- On the first observed activation of the terminal LAND item, advance the hook command sequence and publish an explicit disabled command. Update the runner's active sequence and latch the disabled state so heartbeat refreshes and telemetry callbacks cannot republish the sampled drift command.
- Wait for the hook status to acknowledge the disable sequence and record the trigger timestamp, sequence, acknowledgment, and hook status in the mission record. Continue observing mission telemetry after acknowledgment. If acknowledgment fails or becomes stale, retain a specific hook-disable failure/incomplete reason while still running normal cleanup.
- Let the SITL GPS hook return to unmutated GPS samples through its existing disabled-command behavior. Keep simulator position telemetry untouched and continue using it for route and endpoint checks when available.
- Confirm touchdown from `EXTENDED_SYS_STATE` when available, or from an armed-to-disarmed transition after the final item is active when low relative altitude and a vehicle position are available. Do not require endpoint proximity to recognize touchdown; use the measured endpoint distance to classify an off-endpoint landing as a failure immediately. Preserve route-deviation classification when one was already recorded, and record the off-endpoint landing as the termination cause.

Alternatives considered:
- Disable only after landed confirmation: rejected because it leaves drift active through the descent and does not meet the selected landing-phase trigger.
- Rely on command TTL expiry: rejected because drift would continue for the TTL interval and the result would not show an explicit, acknowledged transition.
- Stop mission observation when LAND becomes active: rejected because landing evidence and post-LAND safety outcomes still need to be captured.

## Risks / Trade-offs

- [The runner can observe LAND activation after a short telemetry polling interval] → Issue the disable immediately after processing the activating progress message, before the next active-command heartbeat, and record the observation time.
- [A hook acknowledgment can be delayed or lost] → Record the disable-specific sequence and failure, prevent accidental active-command republishing, and preserve the existing cleanup disable as a final safeguard.
- [The vehicle may continue moving during descent or touchdown] → Keep `SIMSTATE` as physical simulator truth; disabling spoofing removes injected measurement drift but does not claim to stop real simulated motion.
- [A disarmed low-altitude message could arrive before the vehicle is fully settled] → Require that the vehicle was previously observed armed, the final mission item is active, low altitude and position evidence are available, and retain all landing evidence and raw telemetry.

## Migration Plan

No configuration or wire-format migration is expected. Existing missions without a terminal LAND item and non-mission runs retain current behavior.
