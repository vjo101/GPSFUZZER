# Design

## Context

See proposal.md for motivation and the spec delta for externally visible behavior. The current mission monitor returns `route_deviation` once the maximum deviation crosses its threshold, and the experiment runner ends the run on any returned outcome. GPS drift is refreshed while the runner remains active. IMUFuzzer provides a useful precedent for continuing mission observation after an injection window, but this change does not introduce an injection cutoff.

## Goals / Non-Goals

**Goals:**
- Preserve deviation as a finding while allowing mission observation and GPS drift to continue.
- Preserve a distinct terminal reason and evidence for the event that ends observation.
- Keep crash, EKF failsafe, progress/landing timeout, experiment duration, SITL exit, interruption, and normal mission completion as observation endpoints.

**Non-Goals:**
- Change deviation, waypoint-progress, or landing thresholds.
- Add a GPS drift duration or stop drift when deviation is detected.
- Change ArduPilot or IMUFuzzer.

## Decisions

1. **Separate deviation evidence from terminal outcome.** The monitor should latch the first threshold crossing (time and distance) and continue updating maximum deviation, without returning deviation as a stop signal. This avoids losing subsequent telemetry and flight behavior. A deviation finding remains a failure classification even if the aircraft later lands; the terminal reason records what actually stopped observation.

2. **Keep existing terminal checks in the runner loop.** Continue evaluating crash, EKF failsafe, mission/landing timeouts, endpoint landing, configured duration, SITL lifecycle, and interruption after deviation. The GPS hook remains refreshed for the life of the run, so the active mutation is unaffected by the deviation finding. Add regression coverage that checks the runner does not break at deviation but does stop on terminal events.

3. **Record both finding and stop cause.** Extend mission outcome evidence/experiment serialization with first deviation evidence, maximum deviation, terminal event/reason, and mission outcome category. If deviation precedes crash, failsafe, timeout, or landing, retain both the deviation finding and the later terminal cause. Existing non-mission duration behavior remains unchanged.

4. **Use IMUFuzzer as a behavioral reference only.** Its crash checker can disable fuzzing at a configured waypoint while allowing the mission loop to continue. GPSFuzzer instead keeps its configured GPS drift active through the run, because there is no requested fuzz cutoff waypoint.

## Risks / Trade-offs

- [Longer runs retain SITL and viewer processes after deviation] → Existing progress, landing, and experiment-duration timeouts still bound observation; preserve normal cleanup on every terminal path.
- [Outcome fields may be interpreted as a single status by existing consumers] → Keep the failure classification, deviation evidence, and terminal reason explicit and update record documentation/tests together.

## Migration Plan

No configuration migration is expected. Existing records remain readable; new records add deviation finding and terminal-event evidence. Validate consumers that read experiment JSON against optional/new fields.
