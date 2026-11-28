# Tasks

## 1. Add route-disruption metrics and ranking

- [x] 1.1 Add per-route-leg and whole-run horizontal IAE and maximum route-deviation metrics using simulation timestamps and `SIMSTATE`; verify known trajectories, time integration, mission-leg boundaries, and missing-ground-truth behavior in focused unit tests.
- [x] 1.2 Add the lexicographic disruption comparator for route deviation, crash, timeout, EKF failure, and success, retaining secondary event evidence; verify category precedence and route-deviation magnitude ordering in unit tests.
- [x] 1.3 Record velocity error and spoof exposure separately from vehicle-response scoring; verify serialized metrics identify their source and never substitute spoof offset for route error.

## 2. Implement reproducible speed feedback

- [x] 2.1 Add validated feedback settings for speed bounds and per-bearing attempt limit (default 10), deriving the initial speed and step from the configured interval; verify invalid ranges and limits fail before SITL launch.
- [x] 2.2 Implement a deterministic score-guided hill-climb policy that starts at the speed-range midpoint, advances on improvement, reverses and halves its step on tie/regression, and respects bounds; verify transitions, ties, reversals, and exhausted bounds with policy unit tests.
- [x] 2.3 Record each adjustment's prior best run, ranking evidence, direction, step, candidate speed, and target stop reason; verify policy decision records are JSON serializable and sufficient to replay choices.
- [x] 2.4 Document the score fields, ranking order, search policy, and configuration in the architecture guide; verify examples match accepted configuration keys and generated record fields.

## 3. Add adaptive mission and bearing sweeps

- [x] 3.1 Add an opt-in feedback-guided campaign mode that generates one seeded mission per sweep and holds it fixed across eight bearing targets (0 through 315 degrees in 45 degree increments); verify mission reuse and target ordering in campaign tests.
- [x] 3.2 Run the speed policy for each bearing with coherent drift only, a fresh per-target search state, and at most the configured number of runs; verify each runner invocation receives the expected mission, bearing, bounded speed, and deterministic seed.
- [x] 3.3 Start a fresh seeded mission after all bearing targets finish, reset only target search state, and retain campaign history and best disruptive result; verify successive sweeps and resume/interruption records in campaign tests.
- [x] 3.4 Extend CLI/configuration and campaign records for the opt-in mode, sweep/target seeds, target attempt limit, and best-attack summary printed on completion or interruption; verify the summary includes the best run, attack values, and mission artifact or explicitly reports no scored result.
- [x] 3.5 Add `--replay-record` to launch one non-adaptive run from a saved experiment record, validate required values and the mission artifact digest before SITL startup, and link the new record to its source; verify valid replay, malformed record, missing artifact, digest mismatch, and single-run behavior in CLI tests.
- [x] 3.6 Document best-attack lookup and the `--replay-record` workflow, including that input replay does not guarantee an identical SITL outcome; verify the documented command runs against a saved campaign artifact.

## 4. Verify end-to-end adaptive behavior

- [x] 4.1 Add runner/campaign integration tests covering telemetry scoring, feedback-driven speed changes, all bearing targets, fresh mission sweeps, stop conditions, interrupted campaigns, and best-attack reporting; verify existing open-loop campaign modes remain unchanged.
- [x] 4.2 Run a seeded SITL feedback-guided campaign, then replay its best recorded attack; inspect both records for matching attack inputs and mission digest, expected source-record linkage, outcome evidence, and process cleanup, and document observed outcome variance in the SITL validation guide.
