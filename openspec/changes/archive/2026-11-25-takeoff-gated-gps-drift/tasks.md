# Tasks

## 1. Gate mission drift on airborne state

- [x] 1.1 Keep the initial shared-memory command inactive for mission experiments and publish active drift with a new sequence only after takeoff; verify command flags and sequence transitions with focused runner tests.
- [x] 1.2 Wait for EKF/GPS readiness, perform GUIDED takeoff, and wait for `EXTENDED_SYS_STATE` or a 10 m `GLOBAL_POSITION_INT` climb before uploading the static mission and entering AUTO; verify drift remains disabled through preflight.
- [x] 1.3 Add a 120-second takeoff timeout after the GUIDED takeoff command that returns an incomplete result with the hook inactive; verify timeout and retained run metadata using a controlled test clock.
- [x] 1.4 Preserve current hook-readiness-relative activation when no mission is supplied; verify existing non-mission behavior remains unchanged.

## 2. Record takeoff gate and document behavior

- [x] 2.1 Record takeoff command time, AUTO confirmation time, takeoff detection time, takeoff wait duration, active command sequence, and hook acknowledgment simulation time; verify these fields are present for successful and timed-out mission records.
- [x] 2.2 Document the takeoff-gated timing, timeout behavior, and non-mission behavior in the architecture guide; verify the example matches the implemented CLI and recorded fields.

## 3. End-to-end verification

- [x] 3.1 Run a mission SITL experiment and confirm native GPS remains unchanged before reported takeoff, the configured delay starts at the gate, drift follows the delay, and the resulting telemetry/provenance is retained.
