# Tasks

## 1. Track route deviation as a finding

- [x] 1.1 Update mission outcome monitoring to latch first deviation time/distance and continue tracking maximum deviation without returning a terminal outcome; add unit tests for first crossing, repeated samples, and maximum tracking.
- [x] 1.2 Update outcome evidence and its documentation to expose first and maximum deviation independently of terminal outcome; verify serialized evidence in outcome tests.

## 2. Continue observation through terminal events

- [x] 2.1 Update runner outcome handling so a deviation finding does not break the run and GPS drift remains active; add runner tests showing telemetry/iteration continues after deviation.
- [x] 2.2 Add runner integration tests proving crash, EKF failsafe, waypoint/landing timeout, configured duration, SITL exit, interruption, and endpoint landing still end observation with the appropriate terminal reason, including when deviation was recorded first.
- [x] 2.3 Update architecture and experiment-record documentation to describe continued drift, deviation failure classification, and separate termination reason; verify documented record fields match serialized output.

## 3. Regression verification

- [x] 3.1 Run the focused outcome and runner test suites, then the full project test suite; confirm existing non-mission duration behavior and campaign iteration handling remain unchanged.
