# Tasks

## 1. Configure and record simulation speedup

- [x] 1.1 Set the validated `simulation_speedup` default to 2× in typed and JSON configuration; verify omitted values default to 2× and invalid-value tests still pass.
- [x] 1.2 Pass `SIM_SPEEDUP` through the SITL startup speedup option; verify runner tests cover the 2× default and explicit 1×/3× values in the command.
- [x] 1.3 Record requested and startup-applied speedup in per-run and campaign JSON; verify campaign records default to 2× and explicit 1× remains selectable.

## 2. Compare 1×, 2×, and 3× SITL behavior

- [x] 2.1 Document repeatable commands for three matched mission campaigns and a comparison procedure covering same generated route and drift sample, wall-clock duration, simulation time, telemetry completeness, mission outcomes, route deviation, and landing evidence.
- [x] 2.2 Run the same seeded mission experiment at 1×, 2×, and 3× in SITL; verify each record shows the requested/effective speedup and retains complete telemetry and hook acknowledgements.
- [x] 2.3 Compare the three result sets and document whether 2× and 3× preserve comparable vehicle behavior while reducing wall-clock runtime, including any timing or telemetry limitations observed.
