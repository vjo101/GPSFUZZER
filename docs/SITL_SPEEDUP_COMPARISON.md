# Comparing SITL simulation speed

When `simulation_speedup` is omitted, GPSFuzzer now uses 2×. The speedup examples
set their values explicitly so the 1× reference remains reproducible. They use
the same seed and GPS drift ranges. With the same
mission template and mission-generation defaults, each one-run campaign should
generate the same route and effective drift sample. Only `simulation_speedup`
differs. Keep the ArduPilot checkout, frame, mission template, and runner
options the same across all three commands.

Run each condition from the GPSFuzzer repository root:

```bash
MAVPROXY_CMD="$(command -v mavproxy.py)" python -m gpsfuzzer configs/sitl-speedup-1x.json --ardupilot ../ardupilot --results results/speedup-comparison --iterations 1 --mission waypoints.txt
MAVPROXY_CMD="$(command -v mavproxy.py)" python -m gpsfuzzer configs/sitl-speedup-2x.json --ardupilot ../ardupilot --results results/speedup-comparison --iterations 1 --mission waypoints.txt
MAVPROXY_CMD="$(command -v mavproxy.py)" python -m gpsfuzzer configs/sitl-speedup-3x.json --ardupilot ../ardupilot --results results/speedup-comparison --iterations 1 --mission waypoints.txt
```

The commands create separate campaign directories beneath
`results/speedup-comparison/`. Compare `campaign.json` and each referenced
`experiment.json`:

1. Confirm each run's requested and effective speedup match 1×, 2×, or 3× and
   `applied` is true. The experiment record includes the exact `sim_vehicle.py`
   startup command and its `-S` value.
2. Confirm `campaign_seed`, run seed, generated mission SHA-256, and effective
   drift parameters match. If they do not, the runs are not a matched comparison.
3. Compare mission outcome category/reason, first and maximum route deviation,
   endpoint distance, landing evidence, crash/failsafe evidence, telemetry
   counts, and GPS hook acknowledgements. Inspect `telemetry.jsonl` to compare
   GPS/EKF and `SIMSTATE` traces; align by simulation timestamps where present,
   such as `GLOBAL_POSITION_INT.time_boot_ms`.
4. Compare `experiment.json` wall-clock `duration_s` to measure throughput.
   Report wall-clock and simulation-time evidence separately: `SIM_SPEEDUP`
   changes their relationship, and some current observation limits use
   wall-clock time.

One run per speed is an initial screening comparison, not evidence of statistical
equivalence. Repeat matched seeds before drawing conclusions about whether a
speedup preserves behavior. Keep speedup fixed within any resilience comparison.

## Initial SITL comparison

On 2026-11-27, one matched generated mission was run at each speed using the
commands above, the same GPSFuzzer and ArduPilot checkouts, and the same seed.
The three valid campaigns all used run seed `2969721820538843830`, route SHA-256
`01497c19609a91d0f75a2bbc9008b10974a22a91094d35c7bfbff42a49b3fd25`, and the
same coherent drift sample (delay 5.1445 s, speed 1.5717 m/s, bearing 340.9628°).
Each experiment record showed the requested speedup as applied through the
`sim_vehicle.py -S` startup option, and each landing-disable command was
acknowledged.

| Speedup | Campaign | Wall time | `GLOBAL_POSITION_INT` samples | Simulated timestamp span | Max route deviation | Endpoint distance | Outcome |
|---:|---|---:|---:|---:|---:|---:|---|
| 1× | `20261127T041940.584581Z` | 209.667 s | 827 | 206.5 s | 184.548 m | 183.816 m | Route-deviation failure; landed outside endpoint radius |
| 2× | `20261127T042331.479733Z` | 105.970 s | 827 | 208.5 s | 184.575 m | 183.819 m | Route-deviation failure; landed outside endpoint radius |
| 3× | `20261127T042533.908450Z` | 71.447 s | 827 | 210.5 s | 184.923 m | 184.122 m | Route-deviation failure; landed outside endpoint radius |

Relative to 1×, wall time fell by 49.5% at 2× and 65.9% at 3×. Each run
captured 22,958–22,960 telemetry messages and 827 `GLOBAL_POSITION_INT`
samples. Maximum route deviation differed by less than 0.4 m across conditions,
and endpoint distance differed by less than 0.31 m. These three runs showed the
same outcome and very similar observed paths while reducing wall time close to
the requested simulation multiplier.

This is an initial one-seed screening result, not a general equivalence claim.
The simulated timestamp spans vary by four seconds across conditions, and
wall-clock based observation limits remain a possible confound. The sandboxed
attempt `20261127T041901.130791Z` was excluded: System V shared-memory setup was
denied before SITL started, so it produced no telemetry and no speedup
acknowledgement.

On 2026-11-27, a separate 2× run with `--map --console` verified the startup
path used by interactive SITL runs. Campaign `20261127T044231.770465Z` reached
takeoff, completed the mission, and recorded `applied: true` with effective
speedup 2.0. It ended with the expected route-deviation failure outcome
(`landing_outside_endpoint_radius`), not a startup error. The earlier attempt
`20261127T044138.004558Z` was excluded because `-S` was initially passed as
`2.0`; `sim_vehicle.py` requires an integer argument. Configuration validation
now rejects fractional speedups and formats the startup option as an integer.

The two-iteration map/console campaign `20261127T044614.750514Z` exposed a
landing-detection edge case in its second run. ArduCopter reported `Disarming
motors` after the final LAND item, and `TERRAIN_REPORT.current_height` was
0.0 m, while `GLOBAL_POSITION_INT.relative_alt` remained 7.865 m because the
terrain was above the mission home altitude reference. The previous 1 m
home-relative-altitude check therefore waited for its 90 s landing timeout.
Landing detection now also accepts a recent terrain-clearance report at or
below 1 m together with a disarmed heartbeat after the final mission item.
This change is based on the recorded telemetry and still needs a repeat SITL
run to confirm the shorter completion time.
