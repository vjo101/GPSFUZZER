# Proposal

## Why

Campaign iterations currently reuse the same supplied WPL mission, so changing GPS drift seeds alone does not explore different routes. GPSFuzzer should generate a reproducible route for each iteration so mission geometry varies alongside the GPS attack.

## What Changes

- Add seeded random mission generation for campaign runs, producing a distinct deterministic route for each iteration from its derived run seed. Sample each leg's horizontal distance and bearing as the primary route mutations, with altitude as a secondary value.
- Derive segment duration from the generated geometry and SITL flight behavior rather than randomizing waypoint delays in this change.
- Keep the generated route compatible with the existing QGroundControl WPL upload, outcome monitoring, and experiment record flow.
- Make route generation configurable and record the generated mission and effective generation settings with each run.
- Use the IMUFuzzer mission generator as a reference for bounded relative waypoint generation, while implementing GPSFuzzer-specific parsing, validation, seeding, and campaign integration.

## Capabilities

### New Capabilities

### Modified Capabilities
- `gps-sitl-fuzzing`: campaign iterations can generate and execute seeded, varying missions while preserving reproducibility and recording the effective route.

## Impact

Affected areas include the campaign and mission modules, CLI/configuration, experiment provenance, and tests. The existing `--mission` WPL file will provide the mission home and compatibility baseline; route generation will preserve a safe takeoff-to-waypoints-to-land structure. IMUFuzzer remains a read-only reference, and no ArduPilot changes or new dependencies are anticipated.
