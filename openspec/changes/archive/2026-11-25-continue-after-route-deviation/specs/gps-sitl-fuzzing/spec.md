# Spec Delta

## MODIFIED Requirements

### Requirement: Record experiment outcomes and provenance
The fuzzer SHALL collect configured SITL telemetry and logs and associate them with the experiment configuration, seed, source revisions, SITL settings, duration, and termination reason when available. Mission runs SHALL also record their classified outcome, outcome evidence, thresholds used for route deviation and mission progress timeout, and any deviation finding separately from the event that ended observation.

#### Scenario: Experiment completes
- **WHEN** an experiment reaches its configured end condition
- **THEN** the fuzzer stores the outcome and collected logs with its provenance record

#### Scenario: Experiment is interrupted
- **WHEN** an experiment ends because of a detected failure or interruption
- **THEN** the fuzzer records the termination reason and retains available telemetry and logs

#### Scenario: Mission outcome is classified
- **WHEN** a mission experiment is classified as successful, failed, or incomplete
- **THEN** its record includes the outcome category, reason, relevant mission and vehicle state evidence, and the applied 15 metre deviation and 90 second progress timeout thresholds

#### Scenario: Deviation is followed by another terminal event
- **WHEN** a mission crosses the deviation threshold and later reaches another terminal event
- **THEN** the record retains the deviation finding and its evidence separately from the termination reason that ended observation

### Requirement: Classify mission outcomes
For mission experiments, GPSFuzzer SHALL monitor mission progress, vehicle state, and reported safety events, and SHALL end mission observation on a terminal condition while recording any route deviation finding independently of that condition.

#### Scenario: Mission succeeds after landing at its endpoint
- **WHEN** the final mission item is active or reported reached, and ArduPilot confirms the vehicle is landed within 15 metres of the final mission coordinate, with no deviation finding
- **THEN** GPSFuzzer classifies the mission as successful and records the endpoint distance and landing evidence

#### Scenario: Terminal LAND item omits an item-reached or landed-state message
- **WHEN** the final LAND item is active, the vehicle was observed armed and then reports disarmed, and its relative altitude is at most 1 metre within 15 metres of the final mission coordinate
- **THEN** GPSFuzzer treats the disarm and position evidence as landing confirmation and records the evidence source

#### Scenario: Vehicle exceeds the route deviation limit
- **WHEN** the SITL ground-truth position (`SIMSTATE`) is more than the provisional 15 metre threshold from the active mission leg, or `GLOBAL_POSITION_INT` exceeds it when simulator truth is unavailable
- **THEN** GPSFuzzer records the first deviation time and distance and updates the observed maximum deviation, continues observation without ending the run for deviation alone, and keeps configured GPS drift active

#### Scenario: Deviating mission later lands at its endpoint
- **WHEN** a mission has a deviation finding and later confirms landing within 15 metres of its final mission coordinate
- **THEN** GPSFuzzer ends observation with a deviation failure outcome, records landed-at-endpoint as the termination reason, and retains landing evidence

#### Scenario: GPS mutation shifts the reported position away from simulator truth
- **WHEN** GPSFuzzer changes reported GPS/EKF position during SITL
- **THEN** GPSFuzzer retains both reported and `SIMSTATE` positions and uses simulator truth for route and endpoint outcome checks

#### Scenario: Mission makes no waypoint progress
- **WHEN** the active mission item does not advance for 90 seconds
- **THEN** GPSFuzzer ends observation with a waypoint-timeout failure and records the timeout as the termination reason

#### Scenario: Vehicle reports a crash
- **WHEN** ArduPilot reports a crash during a mission experiment
- **THEN** GPSFuzzer ends observation with a crash failure and records the crash as the termination reason

#### Scenario: Vehicle reports an EKF failsafe
- **WHEN** ArduPilot reports an EKF failsafe during a mission experiment
- **THEN** GPSFuzzer ends observation with an EKF-failsafe failure and records the failsafe as the termination reason

#### Scenario: Mission reaches its final item but does not land at the endpoint
- **WHEN** the final mission item is reached but the vehicle does not confirm landing within 90 seconds or lands more than 15 metres from the final mission coordinate
- **THEN** GPSFuzzer ends observation with a failure and records whether landing confirmation or endpoint proximity failed

#### Scenario: Mission outcome cannot be determined
- **WHEN** SITL exits, telemetry is interrupted, or the configured experiment duration expires before a terminal mission condition is observed
- **THEN** GPSFuzzer classifies the mission as incomplete and records the termination reason

#### Scenario: Run without a mission
- **WHEN** an experiment runs without a mission file
- **THEN** GPSFuzzer retains the existing duration-based completion behavior and does not apply mission outcome classification
