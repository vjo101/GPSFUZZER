# Proposal

## Why

GPSFuzzer currently samples each run's GPS drift independently, so campaign results do not guide later attacks toward more disruptive cases. Add a resilience-guided search that measures mission route deviation and uses prior outcomes to adjust coherent spoof parameters across reproducible runs.

## What Changes

- Add feedback-guided GPS spoofing that prioritizes large route deviations, followed by crashes, timeouts, EKF failures, and successful missions.
- Begin with coherent drift and adjust drift speed while evaluating eight fixed bearings, 45 degrees apart.
- Keep the mission fixed while tuning a bearing target, then start a fresh seeded mission and reset the target search for a new sweep.
- Record the score, prior result, chosen adjustment, attack parameters, sweep/target identity, and seeds so adaptive campaigns can be inspected and replayed.
- On campaign stop, report the best disruptive attack and its record; add `--replay-record` to rerun a saved attack with its effective drift settings and exact mission artifact.
- Retain position-based disruption as the initial feedback signal; record velocity and spoof exposure separately until a reliable desired-velocity reference is defined.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gps-sitl-fuzzing`: Add a reproducible resilience-guided campaign mode that ranks outcomes and adjusts coherent GPS drift speed across fixed bearing targets and fresh mission sweeps.

## Impact

This affects campaign orchestration, drift configuration/sampling, route and outcome scoring, experiment/campaign records, replay CLI behavior, tests, and architecture documentation in `gpsfuzzer/`. It uses existing SITL telemetry, `SIMSTATE`, saved mission artifacts, and the GPS mutation hook; no new dependency or ArduPilot modification is expected.
