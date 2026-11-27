# Spec Delta

## ADDED Requirements

### Requirement: Configure and record SITL simulation speedup
GPSFuzzer SHALL allow a positive whole-number SITL simulation speedup to be configured, default it to 2×, apply it before flight begins, and record the requested and effective values in experiment and campaign results.

#### Scenario: Run at default simulation speed
- **WHEN** a user starts an experiment without a simulation speedup setting
- **THEN** GPSFuzzer runs SITL at 2× and records 2× as the requested and effective speedup

#### Scenario: Run at the 1× reference speed
- **WHEN** a user explicitly configures a speedup of 1×
- **THEN** GPSFuzzer runs SITL at 1× and records 1× as the requested and effective speedup

#### Scenario: Run with an explicit simulation speedup
- **WHEN** a user configures a supported speedup such as 2× or 3×
- **THEN** GPSFuzzer applies that value before takeoff and records the requested and effective speedup for the run

#### Scenario: Reject an invalid simulation speedup
- **WHEN** a user configures a non-finite, fractional, zero, or negative simulation speedup
- **THEN** GPSFuzzer reports a configuration error before launching SITL

#### Scenario: Compare simulation speed conditions
- **WHEN** a user runs otherwise matched experiments at 1×, 2×, and 3× using the same campaign seed, mission-generation settings, and GPS drift configuration
- **THEN** each run record identifies its speedup and retains the mission outcome, telemetry, and timing evidence needed to compare wall-clock duration and vehicle behavior
