# Spec Delta

## ADDED Requirements

### Requirement: Run a resilience-guided coherent GPS spoofing search
GPSFuzzer SHALL provide a campaign mode that uses the recorded vehicle response to choose later coherent GPS drift speed values, within configured bounds, in an effort to find highly disruptive spoofing cases.

#### Scenario: Start a feedback-guided target
- **WHEN** a user starts a feedback-guided campaign with a valid configuration and seed
- **THEN** GPSFuzzer begins a reproducible target search using coherent GPS drift and records the campaign configuration

#### Scenario: Adjust drift speed from a completed run
- **WHEN** a target run completes with a score and outcome evidence
- **THEN** GPSFuzzer uses the configured feedback policy and that result to select the next bounded drift speed, and records the previous result and adjustment decision

#### Scenario: Reach a speed bound or target run limit
- **WHEN** the next adjustment would exceed the configured speed bounds or the target reaches its configured attempt limit
- **THEN** GPSFuzzer ends that target search without starting an out-of-bounds or over-limit run

### Requirement: Prioritize disruptive outcomes in feedback
GPSFuzzer SHALL rank route deviation above crash, crash above timeout, timeout above EKF failure, and EKF failure above successful mission completion when comparing feedback-guided runs; within route-deviation runs, larger and more sustained deviation SHALL rank as more disruptive.

#### Scenario: Compare runs with different primary outcomes
- **WHEN** two feedback-guided runs have different primary outcome categories
- **THEN** the run in the higher-priority category ranks as more disruptive, and all observed outcome evidence remains recorded

#### Scenario: Compare route-deviation runs
- **WHEN** two runs both have route-deviation findings
- **THEN** the run with greater route-deviation magnitude and duration ranks as more disruptive according to the configured score definition

#### Scenario: Successful mission has no disruption finding
- **WHEN** a mission succeeds without a route-deviation finding or higher-priority terminal event
- **THEN** its outcome ranks below route-deviation, crash, timeout, and EKF-failure outcomes

### Requirement: Measure route deviation over time for feedback
GPSFuzzer SHALL calculate a time-based horizontal route-deviation metric from SITL ground-truth position and the active mission route using simulation timestamps, and SHALL retain velocity error and spoof exposure as separate measurements.

#### Scenario: Score a mission telemetry interval
- **WHEN** timestamped `SIMSTATE` position and active-route data are available during a mission
- **THEN** GPSFuzzer accumulates route-deviation error over simulation time and records the resulting per-run metric and duration

#### Scenario: Ground-truth position is unavailable
- **WHEN** a mission run lacks usable `SIMSTATE` position samples
- **THEN** GPSFuzzer records that the primary route-deviation score is unavailable and does not silently substitute spoof displacement for vehicle response

#### Scenario: Record velocity and spoof exposure
- **WHEN** reported GPS velocity, reported position, and simulator truth are available
- **THEN** GPSFuzzer records velocity and spoof-exposure metrics separately from the route-deviation feedback score

### Requirement: Search coherent drift speed across fixed bearing targets
Feedback-guided campaigns SHALL search drift speed separately for each of eight fixed bearings spaced 45 degrees apart, keep the bearing fixed while adjusting speed for a target, and keep the mission fixed during that target search.

#### Scenario: Evaluate a bearing target
- **WHEN** a feedback-guided target is assigned one of the eight configured bearings
- **THEN** every run in that target uses the same bearing while drift speed is adjusted within its configured bounds

#### Scenario: Advance to the next bearing
- **WHEN** a bearing target ends because its attempt limit or speed range is exhausted
- **THEN** GPSFuzzer advances to the next fixed bearing target and records its target identity

### Requirement: Start reproducible fresh mission and target sweeps
After completing the configured bearing targets, GPSFuzzer SHALL start a fresh seeded mission sweep, reset per-target speed-search state to configured initial values, and preserve campaign-wide results and the best disruptive run.

#### Scenario: Begin a fresh sweep
- **WHEN** every bearing target in a sweep has ended and the campaign continues
- **THEN** GPSFuzzer generates a new reproducible mission, resets target search state, and records the new sweep and mission identity

#### Scenario: Reproduce a feedback-guided campaign
- **WHEN** a campaign is rerun with the same seed, configuration, and deterministic feedback policy
- **THEN** it reproduces the same mission and target order, initial attack parameters, and feedback decisions for equivalent recorded outcomes

### Requirement: Record feedback decisions and campaign provenance
GPSFuzzer SHALL record every target run's mission, bearing, effective speed, score components, outcome evidence, attempt number, feedback input, selected next value, and campaign/sweep/target seeds so the adaptive search can be audited and replayed.

#### Scenario: Target adjustment is recorded
- **WHEN** the feedback policy selects a new drift speed
- **THEN** the campaign record identifies the prior run and score that informed the selection and the resulting speed

#### Scenario: Campaign stops during a target search
- **WHEN** the user interrupts a feedback-guided campaign
- **THEN** GPSFuzzer preserves completed run records, current sweep and target state, and the best disruptive result found so far

### Requirement: Report the best attack when an adaptive campaign stops
When a feedback-guided campaign stops, GPSFuzzer SHALL report the best disruptive attack found, its run record, effective drift settings, and saved mission artifact, while retaining all attempted run records.

#### Scenario: Campaign ends with a best attack
- **WHEN** a feedback-guided campaign completes its configured work or is interrupted after at least one scored run
- **THEN** its final summary identifies the best run, disruption ranking evidence, effective drift parameters, and mission artifact path

#### Scenario: Campaign stops before producing a scored run
- **WHEN** a feedback-guided campaign stops before any run has a usable disruption result
- **THEN** its final summary reports that no best attack is available and preserves setup or incomplete-run records

### Requirement: Replay a saved feedback-guided attack
GPSFuzzer SHALL provide a `--replay-record` option that reruns the effective coherent drift settings and exact mission artifact referenced by a saved feedback-guided experiment record as one independent experiment.

#### Scenario: Replay a valid saved attack
- **WHEN** a user supplies a valid feedback-guided `experiment.json` to `--replay-record`
- **THEN** GPSFuzzer validates and loads the recorded drift parameters and mission artifact, launches one non-adaptive experiment, and writes a new result record linked to the source record

#### Scenario: Replay record or mission artifact is unavailable
- **WHEN** the replay record is invalid or its referenced mission artifact is missing or does not match its recorded digest
- **THEN** GPSFuzzer reports the replay input error before launching SITL

#### Scenario: Replay reproduces inputs but SITL behavior varies
- **WHEN** a replay uses the same recorded attack inputs but SITL produces a different vehicle response
- **THEN** GPSFuzzer records the same attack and mission provenance with the new outcome without claiming outcome identity
