# Tasks

## 1. Seeded WPL mission generator

- [x] 1.1 Add a GPSFuzzer mission-generation module that validates the template home and generation bounds, samples each horizontal leg distance and bearing from a local RNG initialized with the run seed, varies altitude secondarily, and emits a QGC WPL takeoff/waypoint/land route without random dwell time; verify WPL parsing and same-seed output with focused unit tests.
- [x] 1.2 Add generator tests for per-leg distance/bearing bounds, altitude bounds, invalid templates, terminal LAND placement, and deterministic distinct outputs for representative different seeds; verify with the mission unit-test suite.
- [x] 1.3 Document the generation defaults, including the provisional 60–240 m leg-distance range, setting units, derived segment duration, and SITL-only scope in the architecture guide; verify the documented configuration matches the implementation.

## 2. Mission mutation configuration and CLI

- [x] 2.1 Add validated mission-generation settings for waypoint count, per-leg distance and bearing, and altitude bounds; use a configurable provisional 60–240 m horizontal leg-distance default based on the current mission and 15 m deviation threshold, and verify valid and invalid values through configuration unit tests.
- [x] 2.2 Add a CLI opt-out for mission mutation while keeping mission-less runs unchanged; verify parser behavior for enabled-by-default mission runs and static-mission opt-out.
- [x] 2.3 Document the command-line opt-out and configuration fields; verify the examples match CLI help and accepted configuration keys.

## 3. Campaign integration and provenance

- [x] 3.1 Generate a mission artifact for each mission-enabled iteration using its derived run seed, deterministically resampling on an in-campaign duplicate, and pass that same file to `ExperimentRunner`; verify mocked campaign runs receive distinct, reproducible WPL paths and contents.
- [x] 3.2 Preserve the original static mission path when mutation is disabled and turn mission-generation errors into a recorded failed attempt without starting SITL; verify both behaviors with campaign tests.
- [x] 3.3 Record the per-run mission artifact path, generation seed, and effective settings in experiment and campaign records, and retain the WPL artifact beside campaign run data; verify JSON records and artifact contents in campaign tests.

## 4. End-to-end regression

- [x] 4.1 Run the relevant mission, campaign, and CLI test suites and verify generated mission upload/outcome evaluation share the recorded WPL artifact while existing static mission and mission-less flows remain covered.
