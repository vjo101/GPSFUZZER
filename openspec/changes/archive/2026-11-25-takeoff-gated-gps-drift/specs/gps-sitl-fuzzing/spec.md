# Spec Delta

## Purpose

GPS SITL fuzzing supports reproducible mission experiments that begin GPS drift only after ArduPilot reports the vehicle airborne, so ground handling and mission preparation remain unmodified.

## ADDED Requirements

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
