# Spec Delta

## ADDED Requirements

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
