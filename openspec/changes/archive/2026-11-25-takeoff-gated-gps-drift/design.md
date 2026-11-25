# Design

## Context

See proposal.md and specs/gps-sitl-fuzzing/spec.md. Mission experiments must wait for navigation readiness and actual takeoff before activating GPS drift. IMUFuzzer provides a reference mission sequence: wait for GPS/EKF readiness, take off in GUIDED, upload the static mission while airborne, then enter AUTO.

## Goals / Non-Goals

**Goals:**
- Keep GPS mutation disabled through navigation setup and until ArduPilot reports the vehicle airborne.
- Start the hook's delay clock from a newly activated command at the takeoff transition.
- Upload the static mission after takeoff and enter AUTO before the timed experiment loop.
- Preserve non-mission experiment timing and capture gate timestamps.

**Non-Goals:**
- Change how non-mission runs activate drift.
- Infer takeoff from an elapsed time when ArduPilot does not report airborne state.
- Change the drift model, velocity modes, or map overlays.

## Decisions

### Follow IMUFuzzer's mission startup order

Keep the initial hook command disabled. Wait for the EKF status `EKF3 IMU0 is using GPS`, settle for two seconds, enter GUIDED, arm, and command takeoff. Detect airborne state from `EXTENDED_SYS_STATE.landed_state == IN_AIR` or a 10 m relative-altitude climb in `GLOBAL_POSITION_INT`; the latter is needed because this SITL setup does not reliably send extended system state. This mirrors IMUFuzzer's sequence and avoids uploading while ArduCopter is initializing mission storage. At the airborne transition, publish the active drift command with a new sequence; the hook anchors the configured delay when it consumes that sequence. Then upload the static mission and enter AUTO. Wait for AUTO confirmation and for the hook to acknowledge the active sequence before starting the experiment-duration clock.

### Bound the takeoff wait

After the GUIDED takeoff command, wait up to 120 seconds for the airborne state. If no airborne report arrives, leave the hook disabled and finish as `incomplete` with a takeoff-timeout reason.

### Record gate timing

Record host monotonic timestamps for takeoff command, airborne detection, and AUTO confirmation, the elapsed takeoff wait, the active command sequence, and the hook's simulation-time acknowledgment for that sequence. The acknowledgment simulation time is the origin used for the configured drift delay.

## Risks / Trade-offs

- [A MAVLink stream may omit `EXTENDED_SYS_STATE`] → Request the required stream and report a takeoff timeout without activating drift if no in-air report arrives.
- [The status acknowledgment may lag the takeoff report] → Refresh the disabled command before takeoff, publish one new active sequence at the gate, and wait for its acknowledgment before entering the run-duration loop.
- [A future MAVLink dialect may use different landed-state symbols] → Use the `pymavlink` enum when available and validate the expected `IN_AIR` value against the selected dialect.

## Migration Plan

No persistent data migration is needed. Existing mission configs gain the takeoff gate automatically; non-mission configs retain their current behavior. Older experiment records remain readable because the new timing metadata is additive.
