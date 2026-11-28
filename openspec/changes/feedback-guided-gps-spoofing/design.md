# Design

## Context

See proposal.md for motivation and the spec delta for required behavior. The existing campaign runner samples each run independently, while `MissionOutcomeMonitor` already tracks route deviation, terminal mission outcomes, and simulator truth. The architecture guide documents coherent drift as a GPS position and velocity offset along a configured bearing.

IMUFuzzer's outer loop reuses a generated mission through a parameter sweep, then creates a new mission and parameter-manager state. In the checked-in A2 path, however, the value advances linearly by 0.25 and the resilience score is not used to choose that adjustment. Its generic count limit is not applied to A2. GPSFuzzer will adopt the sweep structure but use the disruption ranking to guide speed changes and a bounded per-bearing attempt count.

## Goals / Non-Goals

**Goals:**
- Add an opt-in adaptive campaign mode while preserving current open-loop campaigns.
- Rank disruption using explicit outcome precedence and time-based route-deviation measurements.
- Make each adaptive choice, mission, target, and result reproducible and auditable.
- Search coherent drift speed independently at eight fixed bearings, then begin a new mission sweep with reset search state.

**Non-Goals:**
- Search position-only drift, GPS velocity mutation separately, or multiple numeric attack parameters in the initial mode.
- Adjust spoofing during a flight; decisions apply between independent SITL runs.
- Replace the existing mission outcome classifier or use spoof displacement as a vehicle-resilience score.
- Use velocity error in the initial combined feedback ranking without a validated desired-velocity reference.

## Decisions

### Reuse the mission and target sweep structure

Generate one mission per sweep and use that same route for all speed attempts at all eight bearing targets in the sweep. The targets use bearings 0, 45, 90, 135, 180, 225, 270, and 315 degrees clockwise from north. After all eight targets finish, generate the next seeded mission, reset each target's search state, and preserve campaign-wide history and best result. This matches IMUFuzzer's mission-level sweep pattern and makes speed results across bearings comparable on the same route. A fresh mission per attempt was rejected because it would confound parameter feedback with route difficulty.

### Use a bounded score-guided hill climb

For each bearing, initialize speed at the midpoint of the configured speed interval, with a positive initial step equal to one quarter of the interval width. Keep the bearing, mission, and other attack settings fixed during that target. After each run, compare its disruption rank with the best result seen for that target. On improvement, retain the result and continue in the same direction with the current step. On a tie or regression, reverse direction and halve the step. Clamp candidate values to the configured speed interval. Stop after 10 attempts for the bearing or when the next candidate would be outside the interval; record the stop reason. The attempt limit is configurable, defaulting to 10.

This is a practical local search, not a guarantee of finding a global maximum. Copying IMUFuzzer's active constant-step A2 behavior was rejected because it neither uses resilience scores to choose the next value nor has a fixed A2 run budget. Binary search was rejected because the objective is maximizing disruption, which may be non-monotonic in speed, rather than finding a single monotonic threshold.

### Rank outcomes lexicographically and retain the evidence vector

Compare runs first by the highest-priority applicable class: route deviation, crash, timeout, EKF failure, then successful mission. A run with a route-deviation finding remains in the route-deviation class even if it later crashes or reaches another terminal event; preserve both the deviation finding and terminal cause. Among route-deviation runs, compare maximum horizontal route deviation first, then time-integrated route deviation (IAE) as a measure of magnitude sustained over simulation time. Keep mission outcome and every safety event in the record even when only one class determines comparison. This avoids opaque arbitrary weights and reflects the requested priority that large deviations dominate.

Use `SIMSTATE` to measure physical vehicle distance from the active route leg, and integrate horizontal error over simulation timestamps. Keep per-leg/window metrics for within-run trends and aggregate samples once into a whole-run IAE for between-run feedback. Do not divide by the mean error or invert the score: those transforms are unstable near zero and unnecessary for ordinal comparison. Report duration-normalized IAE as a supplementary metric when run durations differ. Record reported GPS position and velocity versus simulator truth as spoof exposure, separate from route response. Record vehicle velocity as a diagnostic until a reliable desired-velocity reference is defined.

When `SIMSTATE` is unavailable or insufficient, mark the primary feedback score unavailable; do not silently substitute the spoofed GPS estimate. The run remains in campaign history but cannot steer the speed search using a fabricated route score; outcome class can still be retained and the missing-score decision recorded.

### Preserve deterministic inputs and decision history

Derive mission, sweep, and run seeds deterministically from the campaign seed and stable sweep/target/attempt indices. Record the effective mission artifact and route, bearing, speed, target attempt, outcome category, maximum deviation, IAE components, prior best result, chosen direction/step, next speed, and stop reason. Keep the best disruptive run and all per-run records even after target state resets. Replaying from the campaign seed regenerates initial inputs; replaying the recorded decision history reproduces adaptive choices without requiring SITL to reproduce bit-for-bit outcomes.

### Report and replay the best attack

At normal completion or interruption, include a `best_attack` entry in `campaign.json` with the source experiment record, disruption rank, effective drift fields, and saved mission artifact path and digest. Print a concise best-attack summary and the record path in the CLI result. If no scored attack exists, report that explicitly. Continue retaining all attempted runs, not only the best one.

Add `--replay-record <experiment.json>` as an alternate CLI invocation to load one recorded adaptive run and launch a single non-adaptive experiment. Resolve the exact generated mission artifact from the saved campaign/run metadata, verify its digest, and load the run's effective drift values plus its experiment duration, simulation speedup, frame, and location. Write the replay as a new result with a link to the source record and current source revisions. Reject malformed records, records missing required replay fields, or missing/mismatched mission artifacts before SITL starts. Do not promise identical flight outcomes: replay guarantees the selected inputs and route, while SITL scheduling or source revisions can change behavior.

An explicit replay flag was chosen over requiring users to copy values into a new JSON configuration because adaptive records include a generated mission and effective values sampled from ranges; manually reconstructing both is error-prone. The replay path runs one experiment rather than resuming or rerunning the entire adaptive campaign.

### Keep adaptive search opt-in

Add a distinct campaign mode so existing fixed-count and until-stopped open-loop campaigns keep their current semantics. Adaptive mode owns its sweep and target loop, uses the existing runner and outcome evidence, and records the policy name/version with campaign provenance. No ArduPilot hook or shared-memory ABI change is needed.

## Risks / Trade-offs

- [A hill climb can miss a disruptive speed region separated by a local dip] → Run eight direction targets independently, retain the full result history, and use a bounded configurable attempt limit; later work can compare alternative search policies.
- [Mission difficulty can dominate between-sweep comparisons] → Keep the mission fixed within a sweep, record route geometry, and preserve per-sweep metrics rather than treating scores across missions as directly paired.
- [SITL outcomes may vary despite identical inputs] → Record actual adaptive decisions and outcomes; seed replay recreates inputs, while decision-history replay reproduces choices.
- [Telemetry gaps can bias time-integrated route error] → Record sample coverage and missing-score status; exclude invalid metrics from score comparisons while retaining outcome evidence.
- [Outcome precedence hides secondary terminal events in a single ranking label] → Preserve all findings and terminal events in the evidence record; use precedence only for ordering.
- [A saved record may outlive or become separated from its generated mission] → Store a campaign-relative mission artifact path and digest, validate both before replay, and report an actionable error without starting SITL.
- [A replay run may not reproduce the original outcome] → Preserve exact inputs and route, link the new record to its source, and state that the replay is input-reproducible rather than outcome-identical.

## Migration Plan

This is an additive campaign mode and record extension. Existing open-loop campaign configuration and records remain valid. Users can return to the prior behavior by selecting the existing campaign mode; adaptive campaign outputs include a policy version so future ranking or search-policy changes can be distinguished.
