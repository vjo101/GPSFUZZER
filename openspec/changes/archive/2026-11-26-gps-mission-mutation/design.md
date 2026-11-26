# Design

## Context

`CampaignRunner` already derives a stable seed for every iteration and passes that seed into `ExperimentRunner`. It currently passes the same `mission_file` path on every run. `MissionRoute` and the experiment outcome monitor parse the uploaded WPL file, so the route used for upload and evaluation must remain identical. The IMUFuzzer reference generates bounded relative waypoint paths, but its generator relies on global randomness and includes assumptions and defects that are unsuitable to copy directly.

## Goals / Non-Goals

**Goals:**
- Generate a distinct, replayable WPL route for each mission-enabled campaign iteration.
- Keep mission generation local to GPSFuzzer and use the existing mission parser, upload, outcome, and per-run record flows.
- Preserve static mission execution as an explicit compatibility option.

**Non-Goals:**
- Change GPS drift mutation, outcome thresholds, or ArduPilot C++/SITL code.
- Randomly select arbitrary MAVLink mission commands; generated routes use a constrained takeoff, waypoint, land sequence.

## Decisions

- **Use the derived per-iteration seed with an isolated RNG.** The generator accepts a run seed and uses a local `random.Random` instance. It does not use module-global random state, so mission sampling cannot perturb GPS drift sampling. A repeated campaign therefore produces the same route at each iteration.
- **Mutate leg spacing directly.** Starting at home, sample a horizontal distance and bearing for each successive waypoint, then derive its coordinate from the previous point. Per-leg horizontal distance and bearing are the primary mutation dimensions; vary altitude secondarily within configured limits. This follows the IMUFuzzer generator's distance/bearing/vertical-angle route construction while avoiding its global RNG and unrelated command-generation assumptions. Use configurable distance bounds with a provisional default of 60–240 m: the lower end is four times GPSFuzzer's current 15 m route-deviation threshold, and the upper end is near the roughly 200–240 m legs in `waypoints.txt`. These bounds remain tunable because the deviation threshold and SITL speed affect useful spacing.
- **Derive segment duration instead of randomizing it.** The initial generator emits no waypoint dwell/delay. Time spent on a leg emerges from its distance, vehicle behavior, and mission progress; this keeps the first iteration focused on route geometry and makes the existing 90 second no-progress timeout the relevant limit. Explicit dwell-time mutation can be considered after observing generated SITL runs.
- **Use the provided WPL mission as a location template.** Read and validate its home coordinate, then sample waypoint count, per-leg distance/bearing, and bounded altitudes from mission-generation settings. Generate standard WPL rows for home, takeoff, navigation waypoints, and terminal LAND. Put the landing coordinate at the final generated waypoint so the existing endpoint success criterion remains coherent. Reject unsupported or invalid templates and settings before SITL starts.
- **Enable generation for mission campaigns, with an explicit static opt-out.** The CLI will expose an opt-out for users who need the current exact WPL behavior. Mission-less runs remain unchanged. Document defaults and allow the count and geographic/altitude bounds to be configured; choose conservative defaults informed by the IMUFuzzer reference and the existing SITL home, and record the effective values.
- **Generate once and pass one artifact through the run.** Before each attempt, write the generated WPL under that attempt's result directory. Pass that path to `ExperimentRunner`; its existing upload and `MissionRoute` parsing then consume the same artifact. Store the artifact path, generation settings, and seed in the experiment record and campaign index. Generation errors should create the normal failed-attempt record without launching SITL.
- **Avoid collisions within one campaign.** Compare generated route content against earlier iterations and deterministically resample from a seed-derived retry stream if a route repeats. This makes the “different routes” behavior an enforced campaign property rather than a probabilistic expectation.

## Risks / Trade-offs

- **Long legs may exceed the 90 second progress timeout at low SITL speeds, while short legs may be too close to the 15 m deviation threshold.** Keep leg-distance bounds configurable, start with the documented 60–240 m range, and tune from observed SITL progress and deviation records.
- **Random geometry may exceed the useful SITL operating area or challenge mission completion.** Validate coordinate/altitude ranges and keep defaults bounded; expose settings for later tuning.
- **A route can be reproducible but not safe for a real vehicle.** The feature is scoped to SITL and emits only a constrained navigation mission; document the SITL scope.
- **Writing a mission before `ExperimentRunner` creates its own run directory requires stable attempt paths.** Place each artifact in a per-iteration directory owned by `CampaignRunner` and pass it through as an ordinary mission path; include it in the experiment record.
