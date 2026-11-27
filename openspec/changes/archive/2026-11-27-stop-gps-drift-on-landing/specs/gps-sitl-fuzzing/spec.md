# Spec Delta

## MODIFIED Requirements

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
