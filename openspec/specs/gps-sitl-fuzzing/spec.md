# gps-sitl-fuzzing Specification

## Purpose

GPS SITL fuzzing supports reproducible mission experiments that begin GPS drift only after ArduPilot reports the vehicle airborne, so ground handling and mission preparation remain unmodified.

## Requirements

### Requirement: Gate mission GPS drift on takeoff
For an experiment with a mission, GPSFuzzer SHALL wait for EKF/GPS navigation readiness, enter GUIDED, arm, and wait until ArduPilot reports the vehicle airborne through `EXTENDED_SYS_STATE` or a 10 m relative-altitude climb before uploading the static mission and switching to AUTO. GPS mutation SHALL remain inactive until the airborne report, then activate with a new command sequence so the configured drift delay starts at takeoff. The experiment SHALL record takeoff start and detection, AUTO confirmation, the active command sequence, and its hook acknowledgment.

#### Scenario: Mission preparation does not apply drift
- **WHEN** a mission experiment is initializing navigation, arming, or taking off in GUIDED
- **THEN** reported GPS position and velocity remain unmutated

#### Scenario: Drift starts after takeoff and its configured delay
- **WHEN** ArduPilot reports the vehicle airborne during a mission experiment
- **THEN** GPSFuzzer starts the configured drift delay from that takeoff gate and applies drift only after the delay elapses

#### Scenario: Mission does not take off
- **WHEN** ArduPilot does not report the vehicle airborne within 120 seconds after GUIDED takeoff is commanded
- **THEN** GPSFuzzer marks the experiment incomplete, records a takeoff-timeout termination reason, and leaves GPS mutation inactive

#### Scenario: Run without a mission
- **WHEN** an experiment runs without a mission file
- **THEN** its drift activation and delay retain the existing hook-readiness-relative behavior

### Requirement: Configure a reproducible GPS drift experiment
The fuzzer SHALL accept an experiment configuration and random seed, and SHALL record the effective configuration and seed with the resulting experiment data.

#### Scenario: Start a configured experiment
- **WHEN** a user starts an experiment with a valid configuration and seed
- **THEN** the fuzzer runs using those values and records them with the experiment results

#### Scenario: Reject an invalid experiment configuration
- **WHEN** the experiment configuration contains an unsupported or invalid value
- **THEN** the fuzzer reports the configuration error before starting the experiment

### Requirement: Apply gradual horizontal GPS position drift
The fuzzer SHALL support gradual horizontal drift from simulator truth with configurable drift start delay, horizontal speed, and direction, and SHALL allow configured ranges to be sampled reproducibly from the experiment seed.

#### Scenario: Drift begins after its configured delay
- **WHEN** simulation time reaches the configured drift start time
- **THEN** the reported GPS position begins moving away from simulator truth at the configured horizontal speed and direction

#### Scenario: Drift is not yet active
- **WHEN** simulation time is earlier than the configured drift start time
- **THEN** the reported GPS position remains at its unmutated simulated value

#### Scenario: Repeat an experiment with the same seed
- **WHEN** two experiments use the same configuration and random seed
- **THEN** their sampled start delay, speed, and direction are identical

### Requirement: Select GPS velocity behavior during position drift
The fuzzer SHALL provide a per-experiment choice between coherent drift, which adds the drift velocity to reported GPS velocity, and position-only drift, which leaves reported GPS velocity unchanged.

#### Scenario: Coherent drift mode
- **WHEN** coherent drift mode is selected and the drift is active
- **THEN** reported GPS position drifts and reported horizontal velocity includes the configured drift vector

#### Scenario: Position-only drift mode
- **WHEN** position-only drift mode is selected and the drift is active
- **THEN** reported GPS position drifts while reported GPS velocity remains equal to its unmutated simulated value

### Requirement: Control and monitor the SITL GPS mutation hook
The fuzzer SHALL initialize and control the ArduPilot SITL GPS mutation interface, and SHALL detect when the hook is unavailable or its commands become stale.

#### Scenario: Hook is ready for an experiment
- **WHEN** the SITL hook initializes and reports its readiness for the active experiment
- **THEN** the fuzzer begins the experiment and records that the hook is active

#### Scenario: Hook is unavailable or stale
- **WHEN** the hook does not acknowledge the active experiment or its status becomes stale
- **THEN** the fuzzer reports the interface failure and marks the experiment failed or incomplete

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
For mission experiments, GPSFuzzer SHALL monitor mission progress, vehicle state, and reported safety events, SHALL stop configured GPS drift when the terminal LAND mission item becomes active, and SHALL end mission observation on a terminal condition while recording any route deviation finding independently of that condition.

#### Scenario: Mission succeeds after landing at its endpoint
- **WHEN** the final mission item is active or reported reached, and ArduPilot confirms the vehicle is landed within 15 metres of the final mission coordinate, with no deviation finding
- **THEN** GPSFuzzer classifies the mission as successful and records the endpoint distance and landing evidence

#### Scenario: Terminal LAND item omits an item-reached or landed-state message
- **WHEN** the final LAND item is active, the vehicle was observed armed and then reports disarmed, its relative altitude is at most 1 metre, and its position is available
- **THEN** GPSFuzzer treats the disarm and low-altitude evidence as landing confirmation and records the evidence source and endpoint distance

#### Scenario: Vehicle exceeds the route deviation limit
- **WHEN** the SITL ground-truth position (`SIMSTATE`) is more than the provisional 15 metre threshold from the active mission leg, or `GLOBAL_POSITION_INT` exceeds it when simulator truth is unavailable
- **THEN** GPSFuzzer records the first deviation time and distance and updates the observed maximum deviation, continues observation without ending the run for deviation alone, and keeps configured GPS drift active only until the terminal LAND item becomes active

#### Scenario: Deviating mission later lands at its endpoint
- **WHEN** a mission has a deviation finding and later confirms landing within 15 metres of its final mission coordinate
- **THEN** GPSFuzzer ends observation with a deviation failure outcome, records landed-at-endpoint as the termination reason, and retains landing evidence

#### Scenario: Mission lands outside the endpoint radius without a prior deviation
- **WHEN** the final mission item is active, the vehicle was observed armed and then reports disarmed at a relative altitude of at most 1 metre, and its available position is more than 15 metres from the final mission coordinate
- **THEN** GPSFuzzer immediately ends observation with an endpoint-miss failure and records the disarm as the termination cause instead of waiting for the landing timeout

#### Scenario: Deviating mission lands outside the endpoint radius
- **WHEN** a mission has a route-deviation finding and the vehicle is observed armed then disarmed at a relative altitude of at most 1 metre after the final item becomes active, more than 15 metres from the final mission coordinate
- **THEN** GPSFuzzer immediately ends observation with a route-deviation failure, records the off-endpoint disarm as the termination cause, and retains landing evidence

#### Scenario: GPS mutation shifts the reported position away from simulator truth
- **WHEN** GPSFuzzer changes reported GPS/EKF position during SITL
- **THEN** GPSFuzzer retains both reported and `SIMSTATE` positions and uses simulator truth for route and endpoint outcome checks

#### Scenario: Terminal LAND item becomes active
- **WHEN** mission progress telemetry reports the final mission item active and that item is a LAND command
- **THEN** GPSFuzzer promptly sends a fresh disabled command to the GPS mutation hook, records the trigger and disable command sequence, verifies the hook acknowledgment, and continues collecting reported-position and `SIMSTATE` telemetry through landing

#### Scenario: GPS mutation hook does not acknowledge the landing disable
- **WHEN** the GPS mutation hook does not acknowledge the disabled command for the terminal LAND item
- **THEN** GPSFuzzer records an incomplete outcome with a landing-disable failure reason, does not republish an active drift command, and continues collecting telemetry through the mission's terminal condition

#### Scenario: Final mission item is not a LAND command
- **WHEN** the final mission item becomes active but is not a LAND command
- **THEN** GPSFuzzer leaves configured GPS drift active and continues normal mission outcome monitoring

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

### Requirement: Generate a reproducible mission for each campaign iteration
For each mutation-enabled campaign iteration with a mission template, GPSFuzzer SHALL use the iteration seed to generate a valid route, primarily sampling each leg's horizontal distance and bearing and secondarily its altitude. Segment duration SHALL emerge from route geometry and vehicle behavior, not randomized dwell. The route SHALL retain template home and takeoff/waypoints/land structure; record settings and exact WPL artifact.

#### Scenario: Campaign iterations explore different routes
- **WHEN** a campaign has mission mutation enabled and starts multiple iterations
- **THEN** each iteration executes a distinct generated route derived from its own run seed

#### Scenario: Campaign routes can be reproduced
- **WHEN** a campaign is repeated with the same seed, mission template, generation settings, and iteration order
- **THEN** each iteration generates the same WPL route as its corresponding prior run

#### Scenario: Leg spacing and heading are sampled within configured bounds
- **WHEN** GPSFuzzer generates a route with valid distance and bearing ranges
- **THEN** each waypoint is placed using a sampled horizontal leg distance and bearing within those ranges, with altitude sampled from its own configured bounds

#### Scenario: Segment duration follows route execution
- **WHEN** GPSFuzzer generates a mission route
- **THEN** it does not randomize waypoint dwell time, and observed time per leg depends on the generated distance and vehicle behavior

#### Scenario: Generated mission is used consistently
- **WHEN** a route is generated for an iteration
- **THEN** GPSFuzzer uploads that route, evaluates mission outcomes against that route, and stores the exact WPL artifact with the experiment record

#### Scenario: Mission mutation is disabled
- **WHEN** a user disables mission mutation for a run with a mission template
- **THEN** GPSFuzzer uploads and evaluates the supplied static mission as it does today

#### Scenario: Mission generation settings are invalid
- **WHEN** mission generation is enabled with invalid bounds or a waypoint count range that cannot produce a valid route
- **THEN** GPSFuzzer reports the configuration error before launching SITL
