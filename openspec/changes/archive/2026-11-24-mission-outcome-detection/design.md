# Design

## Context

See proposal.md for motivation and `specs/gps-sitl-fuzzing/spec.md` for the behavior contract. `ExperimentRunner` currently records MAVLink telemetry but only ends a run when its duration expires or an existing startup/hook error occurs. `upload_and_start_mission` already loads the WPL mission, uploads it, enters AUTO, and confirms the takeoff gate. During the run loop, telemetry is drained into JSONL without mission outcome evaluation.

IMUFuzzer's `src/crashChecker.py` provides reference logic for mission sequence progress, a 90 second no-progress timeout, and EKF failsafe status text. Its `src/euc_dist_finder.py` uses a 15 metre deviation threshold. Those files are reference material, not imported runtime dependencies. ArduCopter emits `STATUSTEXT` containing `EKF Failsafe` and `Crash: Disarming` for the relevant safety events.

## Goals / Non-Goals

**Goals:**
- Add a mission outcome observer that consumes the same MAVLink messages the runner already records.
- Determine the active mission leg and final mission coordinate from the loaded mission.
- Classify a run as successful only after final mission progress and confirmed landed state within the endpoint radius.
- Detect crash, EKF failsafe, route deviation, and lack of waypoint progress, and preserve the reason and supporting evidence.
- Preserve current duration-based completion for runs without a mission.

**Non-Goals:**
- Generate or mutate missions, iterate automatically over multiple experiments, or compute IMUFuzzer-style resiliency scores.
- Change ArduPilot source, flight parameters, or the GPS mutation hook.
- Treat a final waypoint reached while still airborne as mission success.

## Decisions

### Adapt the checker as a GPSFuzzer monitor

Add a small Python outcome monitor owned by the GPSFuzzer repository and feed it MAVLink messages as they are consumed by the runner. Keep telemetry serialization independent, so every message continues to be retained even when it triggers a terminal outcome. Do not import `imufuzzer/src/crashChecker.py`: it depends on IMUFuzzer commander/configuration APIs, reads only the latest status text, and its mission sequence assumptions do not match GPSFuzzer's runner callbacks.

### Use mission progress and MAVLink vehicle state

Use `MISSION_CURRENT` and `MISSION_ITEM_REACHED` to track progress, `SIMSTATE` as ArduCopter SITL ground truth for route deviation and endpoint checks, and `GLOBAL_POSITION_INT` as the reported EKF position and fallback when simulator truth is unavailable. Use `EXTENDED_SYS_STATE` for confirmed landing when available, `HEARTBEAT` armed state as a fallback landing signal, and `STATUSTEXT` for crash and EKF failsafe events. Treat `EKF Failsafe` text as a failsafe even if the configured ArduPilot action is report-only or does not switch to LAND. Treat ArduCopter's `Crash: Disarming` text as a crash indication and retain the original text and severity in the result. Do not infer a crash merely from an ordinary disarm after landing.

Resolve mission navigation items and their coordinates from the loaded WPL mission, ignoring non-navigation commands when constructing the route. Use the current mission sequence to select the active leg. Use the home coordinate as the horizontal origin after a `NAV_TAKEOFF` item because ArduCopter may climb at home even when the WPL takeoff item's x/y differs. Calculate horizontal distance from the reported position to that leg in a local geographic projection (including latitude scaling), rather than copying the IMUFuzzer helper's raw latitude/longitude Euclidean calculation.

### Set provisional limits from IMUFuzzer

Use 15 metres as the initial horizontal deviation limit, matching the threshold in IMUFuzzer's distance analysis. Use 90 seconds without mission sequence progress as the initial waypoint timeout, matching `crashChecker.missionChecker`. Apply the progress timeout to the final landing leg as well. Store both effective thresholds in each mission result. Keep them as named settings/constants in GPSFuzzer so they can be tuned later without changing the outcome model.

Use the same 15 metre horizontal radius for confirming the final landing coordinate. Success requires the final mission item to be active or reached, confirmed landing, and the vehicle's ground-truth horizontal position within that radius of the final mission coordinate when `SIMSTATE` is available. Prefer `MAV_LANDED_STATE_ON_GROUND`; when ArduCopter omits `EXTENDED_SYS_STATE`, accept a disarmed heartbeat only after the monitor observed the vehicle armed, the final item became active, and position is within 1 metre relative altitude and 15 metres of the endpoint. Record which position and landing signals confirmed the outcome. If simulator truth is unavailable, use `GLOBAL_POSITION_INT` and record that fallback source. If the endpoint is reached but landing is not confirmed within 90 seconds of final-item progress, classify the run as failed with a landing timeout or endpoint deviation reason.

### Classify outcomes and retain evidence

The monitor returns a terminal outcome and reason to the runner. Crash, EKF failsafe, route deviation, and waypoint/landing timeout are failures. SITL exit, loss of required telemetry, or experiment duration expiring before a terminal mission result is incomplete. A successful landing is the only mission success condition. Continue writing telemetry and hook events through cleanup, then include the classification, reason, final/current mission sequence, target coordinate, observed landed state and position, endpoint distance, maximum observed route deviation, thresholds, and triggering MAVLink messages in `experiment.json`.

If multiple terminal signals arrive in one polling batch, preserve all observed safety events and use this precedence for the primary reason: crash, EKF failsafe, route deviation, timeout, then success. A success result must never override a failure signal observed in that same batch.

## Risks / Trade-offs

- [MAVLink mission sequence fields can differ around home items and non-navigation commands] -> Build a navigation-item index from the exact uploaded mission and add focused cases for home, skipped commands, and terminal LAND items.
- [STATUSTEXT wording can change across ArduPilot versions] -> Match stable crash/EKF phrases case-insensitively, retain raw text, and report unknown critical messages in the evidence rather than classifying every critical message as a crash.
- [GPS position can be noisy near the 15 metre boundary] -> Keep the initial threshold explicit in results and test boundary behavior; allow later tuning based on SITL evidence.
- [MAVLink telemetry can be missing while SITL is still running] -> Treat absence of required position/progress messages as incomplete when it prevents classification, and preserve the telemetry and console logs collected so far.
- [A timeout can end an experiment before a later landing or safety event] -> Use the documented 90 second per-leg timeout and record the last observed state and sequence for diagnosis.

## Migration Plan

No data migration is needed. Existing result fields remain, with mission outcome fields added to mission-run records. Non-mission runs keep their current duration behavior. Run focused monitor/runner tests, then a SITL mission that lands at its final waypoint and controlled SITL cases for timeout, deviation, crash/failsafe evidence where feasible. Do not modify IMUFuzzer; do not require an ArduPilot source change.
