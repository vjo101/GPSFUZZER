# Spec Delta

## ADDED Requirements

### Requirement: Run a fixed-size GPS fuzzing campaign
The fuzzer SHALL accept a positive campaign iteration count and attempt exactly that many independent SITL experiments when the campaign is not interrupted by the user.

#### Scenario: Campaign reaches its requested iteration count
- **WHEN** a campaign is started with an iteration count N and runs are not interrupted
- **THEN** the fuzzer starts N independent SITL experiments and records the requested and completed attempt counts

#### Scenario: Reject an invalid iteration count
- **WHEN** a campaign is configured with an iteration count that is not a positive integer
- **THEN** the fuzzer reports a configuration error before launching SITL

### Requirement: Run a GPS fuzzing campaign until stopped
The fuzzer SHALL support an opt-in unbounded campaign mode that runs independent SITL experiments sequentially until the user requests stop.

#### Scenario: Campaign continues after each result
- **WHEN** a campaign is started with `--until-stopped` and no stop is requested
- **THEN** the fuzzer starts another independent experiment after each result, including mission failure or incomplete outcomes

#### Scenario: User stops an active campaign
- **WHEN** the user presses Ctrl-C during an experiment or between experiments in an until-stopped campaign
- **THEN** the fuzzer stops launching new experiments, cleans up the active SITL process group, and records an interrupted campaign with the actual attempt count

#### Scenario: Until-stopped conflicts with an explicit fixed count
- **WHEN** the user supplies both `--until-stopped` and `--iterations N`
- **THEN** the fuzzer reports an option conflict before launching SITL

### Requirement: Sample a reproducible GPS attack for every campaign iteration
The fuzzer SHALL derive a distinct deterministic per-run seed from the campaign seed and iteration number, then sample that run's GPS drift parameters from the configured ranges using the per-run seed.

#### Scenario: Campaign iterations use distinct attack samples
- **WHEN** a campaign runs multiple iterations with non-degenerate drift ranges
- **THEN** each iteration uses its own per-run seed and samples its attack independently of the other iterations

#### Scenario: Campaign can be reproduced
- **WHEN** a campaign is rerun with the same campaign seed, configuration, and iteration count
- **THEN** each iteration receives the same per-run seed and effective GPS attack parameters as the corresponding iteration in the original campaign

### Requirement: Record campaign and iteration results independently
The fuzzer SHALL retain a separate experiment record and available telemetry and SITL logs for every attempted iteration, and SHALL associate each record with the campaign identifier, campaign mode, campaign seed, iteration number, requested iteration count (or null for an until-stopped campaign), per-run seed, effective GPS attack, and outcome.

#### Scenario: Iteration results are retained
- **WHEN** a campaign iteration ends
- **THEN** its experiment record and available telemetry and SITL logs are stored in a run-specific location and referenced by the campaign summary

#### Scenario: Mission failure does not stop later iterations
- **WHEN** a mission iteration ends with a failure or incomplete outcome
- **THEN** the fuzzer records that outcome and proceeds to the next iteration until the requested count is reached

### Requirement: Clean up all SITL processes after an experiment
After obtaining an experiment result, the fuzzer SHALL stop and reap the SITL process and every process it launched for that experiment, including MAVProxy map or console processes when enabled, before returning the result or starting another iteration.

#### Scenario: Experiment ends with a result
- **WHEN** an experiment completes with a success, failure, or incomplete outcome, with or without the map or console enabled
- **THEN** the fuzzer has stopped and reaped its SITL and MAVProxy processes before returning the result

#### Scenario: User interrupts an experiment
- **WHEN** the user interrupts an active experiment
- **THEN** the fuzzer stops and reaps all processes launched for that experiment before exiting, while retaining the available experiment records and logs
