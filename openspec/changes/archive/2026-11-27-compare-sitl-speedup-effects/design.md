# Design

## Context

See proposal.md for motivation. `ExperimentConfig` currently contains the drift and mission-generation settings but no SITL speedup. The runner starts SITL, connects over MAVLink, performs mission readiness and takeoff gates, and records wall-clock run duration plus telemetry; the shared-memory GPS hook reports simulation time. The speedup must be in effect before flight starts, while retaining the existing default behavior.

## Goals / Non-Goals

**Goals:**
- Make the speedup an explicit, validated experiment input and use 2× when the setting is omitted.
- Pass the requested speedup to SITL at process startup, before telemetry routing or flight begins.
- Make run records sufficient to identify and compare speedup conditions and their timing/outcome evidence.
- Document a controlled 1×/2×/3× mission comparison using the same seed, mission template, drift settings, and route-generation settings.

**Non-Goals:**
- Change GPS mutation algorithms, mission geometry, or ArduPilot source.
- Automatically tune speedup or select a “safe” maximum based on CPU capacity.
- Claim that speedup is behavior-preserving solely because a campaign completes.

## Decisions

- Add a top-level `simulation_speedup` field to the experiment configuration, defaulting to `2.0`. Validate that it is a positive whole number because `sim_vehicle.py -S` accepts integers. The 1×, 2×, and 3× settings are comparison values, not an exclusive allowlist; other positive whole numbers remain supported.
- Pass the configured value through `sim_vehicle.py -S` when launching SITL. ArduPilot's startup path maps this option to its `SIM_SPEEDUP` setting. Applying it at startup works consistently with direct MAVLink and MAVProxy map/console modes; a runtime `PARAM_SET` and acknowledgment wait depends on the active MAVLink route and prevented the map/console configuration from reaching mission startup.
- Record the requested value, the value passed to the SITL startup command, and whether the SITL process started in experiment and campaign results. Preserve all existing timing fields and make the comparison instructions use simulation timestamps and mission outcomes alongside wall-clock duration; speedup intentionally changes the relationship between those clocks.
- Keep comparison orchestration simple: use separately recorded campaigns at 1×, 2×, and 3× with a fixed seed and identical inputs. Deterministic route generation then reproduces the same mission, and per-run seed derives the same GPS drift sample. Compare outcome category/reason, route deviation evidence, landing evidence, telemetry completeness, simulated elapsed time, and host elapsed time. Do not combine different speedups in a single campaign configuration.

Alternatives considered: changing ArduPilot's startup flags or parameter files would require extra SITL-specific process plumbing and could vary initialization behavior; runtime MAVLink configuration fits the current runner. A single comparison command could automate three campaigns, but separate campaigns make each condition's configuration explicit and results independently reproducible.

## Risks / Trade-offs

- [SITL process may fail before initialization] → Record the requested speedup and startup command, but mark it applied only after process creation succeeds; retain the startup console log for diagnosis.
- [Higher speedup can outrun host telemetry polling or hook processing] → Include telemetry counts and hook acknowledgements in comparison evidence; treat missing data or command-stale outcomes as an invalid comparison, not as equivalent behavior.
- [Host-based duration and timeout checks do not scale with simulated time] → Preserve both host and simulation timing evidence and scope the initial comparison to matched mission runs; evaluate timer normalization separately if results show timeout behavior is driving differences.
- [Same seed does not guarantee equivalent wall-clock scheduling] → Compare route and drift parameters and align behavioral traces by simulation time, while reporting timing variance.
