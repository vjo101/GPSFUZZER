# Spec Delta

## Purpose

GPS SITL fuzzing lets researchers run reproducible experiments that gradually drift the GPS-reported position away from simulator truth. It provides controls for drift timing, speed, direction, and whether reported velocity remains consistent with that drift.

## ADDED Requirements

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
