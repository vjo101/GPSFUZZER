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
The fuzzer SHALL collect configured SITL telemetry and logs and associate them with the experiment configuration, seed, source revisions, SITL settings, duration, and termination reason when available.

#### Scenario: Experiment completes
- **WHEN** an experiment reaches its configured end condition
- **THEN** the fuzzer stores the outcome and collected logs with its provenance record

#### Scenario: Experiment is interrupted
- **WHEN** an experiment ends because of a detected failure or interruption
- **THEN** the fuzzer records the termination reason and retains available telemetry and logs
