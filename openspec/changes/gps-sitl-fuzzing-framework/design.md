# Design

## Context

See proposal.md for motivation and specs/gps-sitl-fuzzing/spec.md for the behavior contract. IMUFuzzer's Python implementation separates sensor mutators, a fuzzing engine, mission and parameter management, SITL lifecycle, and result analysis. Its Python-to-C++ path uses System V shared memory: `src/sensorMutator.py` writes fixed-layout type/count/float parameter structures at fixed keys; `libraries/AP_InertialSensor/SensorFuzzer_Bridge.h/.cpp` in `../imufuzzer/data/ardupilot` attaches to those segments, reads mutation commands, mutates SITL samples, and detaches; `AP_InertialSensor_SITL.cpp` calls the bridge during sample generation. The checked-out reference tree is accessible and patched, though its changes include local edits and should be treated as a research reference rather than a pristine upstream diff.

In the current ArduPilot checkout, `libraries/SITL/SIM_GPS.cpp` builds a `GPS_Data` sample from simulator truth in `GPS::update()`, applies configured simulator effects, then calls `backend->publish(&d)`. The existing `SIM_GPS1_GLTV` parameter applies a north/east/down velocity offset, integrates that offset into reported position, and adds it to reported velocity. Its `GPSGlitchVelocity` autotest verifies coherent position/velocity drift. GPSFuzzer's `gpsSpoofingProto.py` uses MAVLink `GPS_INPUT`, but that source reconstructs only part of a baseline sample and is not the selected mutation interface.

## Goals / Non-Goals

**Goals:**
- Adapt IMUFuzzer's modular Python orchestration and Python-to-SITL shared-memory command pattern using a GPS-specific contract.
- Generate gradual horizontal drift from native simulator truth with seeded start delay, speed, and bearing.
- Let each experiment choose coherent drift or position-only drift.
- Keep the ArduPilot change in SITL GPS simulation and make the hook inert when no valid active command is available.
- Record the effective mutation parameters, velocity mode, source revisions, SITL settings, outcome, and logs.

**Non-Goals:**
- Implement sudden position jumps, altitude drift, fix/satellite mutation, GPS dropouts, or receiver/RF-level spoofing in the first version.
- Copy IMUFuzzer's IMU waveform modes or resiliency score without a GPS-specific justification.
- Modify IMUFuzzer or general hardware GPS backends.

## Decisions

### Use a GPS-specific System V shared-memory command and status block

Follow the reference bridge pattern in `SensorFuzzer_Bridge.h/.cpp`, but do not copy its GPS-inappropriate vector structs or implicit `count` behavior. Define a fixed-width GPS command block with a version, active flag, experiment identifier/sequence, drift start time, speed, bearing, and velocity mode. Include a status/acknowledgment sequence and last-consumed simulation timestamp so Python can establish hook readiness and detect stale consumption. Choose a GPS-specific key that does not collide with the reference keys. Initialize to inactive; on missing, invalid, or stale commands, leave GPS output unchanged and expose a failure status.

### Apply the hook to generated GPS data before backend publication

Add the narrow hook in `libraries/SITL/SIM_GPS.cpp` after native `GPS_Data` generation and before `backend->publish(&d)`. Use simulation time rather than wall-clock time so timing and seeded runs are repeatable under SITL speed changes. Convert horizontal speed and bearing into north/east velocity components. Once drift starts, integrate the vector over elapsed simulation time into position using local geographic scaling. In coherent mode, add the same north/east vector to `d.speedN`/`d.speedE`; in position-only mode, leave speed fields unchanged. Keep altitude/down velocity outside the first-version drift model.

The existing `SIM_GPS1_GLTV` parameter is a useful behavior reference and can support comparison tests, but it does not replace the shared-memory hook: the selected interface needs an explicit delayed start, per-run sampled parameters, and a velocity-mode toggle.

### Generate and record drift parameters in Python

Python validates configuration, samples configured delay/speed/bearing ranges from the experiment seed, chooses the velocity mode, and publishes the effective command. Configuration uses explicit units (seconds, metres per second, degrees clockwise from north) and validated ranges. Preserve those effective values in the experiment record so a run can be reproduced without re-sampling.

### Keep experiment responsibilities modular

Use separate components for experiment configuration and seed handling, drift parameter selection, shared-memory command/status communication, SITL lifecycle and readiness, and telemetry/log collection. Start with baseline and open-loop drift experiments; defer feedback-guided exploration and scoring until vehicle outcomes are characterized.

## Risks / Trade-offs

- [A shared-memory ABI mismatch could corrupt values or silently disable mutation] -> Define fixed-width fields, version/size checks, shared constants/documentation, and serialization tests on the Python side plus layout checks in C++.
- [Stale commands could continue a drift after Python exits] -> Add command freshness and sequence acknowledgment; define a bounded stale timeout that disables mutation, and test abrupt fuzzer termination.
- [Position and velocity semantics can be confused by EKF/GPS checks] -> Make the two modes explicit in config and records; test both against native GPS telemetry and describe their exact measurement effects.
- [Degree conversion becomes inaccurate near the poles] -> Use a bounded local scale with a documented latitude limit or robust geodesic conversion; test longitude scaling at representative latitudes.
- [ArduPilot source divergence from IMUFuzzer's fork can invalidate copied assumptions] -> Treat the patched reference as evidence for communication patterns only and trace the hook against the active `../ardupilot` source before editing it.

## Migration Plan

No persistent data migration is needed. Keep the existing toy MAVLink scripts available as reference while introducing the shared-memory drift path. The SITL hook defaults to inactive and must first pass an unmutated baseline comparison. Document each ArduPilot source file changed and record its revision alongside each GPSFuzzer experiment. If the hook fails readiness or freshness checks, stop or mark the run incomplete and disable mutation.

## Open Questions

- What practical bounds should the initial configuration support for drift start delay, horizontal speed, and bearing? Keep them user-configurable and agree concrete defaults during implementation using the experiment's physical assumptions.
- Which vehicle behavior signals should later drive feedback-guided exploration beyond raw telemetry and logs (mission deviation, EKF/failsafe events, crash, or a combination)?
