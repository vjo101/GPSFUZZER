# SITL Validation Results

Validation was performed with the ArduCopter SITL binary built from the
`../ardupilot` checkout. Waf was configured for `--board sitl` and
`./waf copter` completed successfully. Waf's `empy==3.3.4` and `pexpect` build
tools and GPSFuzzer's pinned `pymavlink` dependency were installed in the
GPSFuzzer `.venv`; no ArduPilot runtime or framework dependency was installed
into system/user Python.

The runs used `sim_vehicle.py -v ArduCopter -f quad --no-rebuild --no-mavproxy
--udp --no-extra-ports -S 1`, disabled GUI/MAVProxy, requested MAVLink data
streams at 4 Hz, and captured 20 seconds after hook readiness unless stated
otherwise. Raw `telemetry.jsonl`, console output, and `experiment.json` are
retained in the ignored `results/<run-id>/` directories.

| Run | Configuration and result |
| --- | --- |
| `20261125T003533.091288Z` | Baseline, mutation disabled. The hook acknowledged the disabled command and shutdown disable. There were 71 `GPS_RAW_INT` and 71 `SIMSTATE` messages; all 41 valid, nonzero GPS samples matched simulator latitude/longitude exactly. No DataFlash BIN was produced because the vehicle stayed disarmed. |
| `20261125T002407.131722Z` | Coherent mode, seed `20261124`: delay 7.119475 s, speed 1.512977 m/s, bearing 1.231780°. The last valid GPS position was 19.17 m north and 0.41 m east of simulator truth; `GPS_RAW_INT.vel` was 151 cm/s and course was 1.23°. |
| `20261125T002510.204229Z` | Position-only mode with the same seed and ranges. It sampled the same delay, speed, and bearing, and produced the same 19.17 m north / 0.41 m east position offset. Reported GPS velocity and course remained zero. |
| `20261125T002839.218083Z` | Position-only at 60° latitude, fixed 1 m/s eastward drift, zero delay, 12-second capture. The final east offset was 11.79 m, while reported GPS velocity and course stayed zero. |
| `20261125T003035.232392Z` | Position-only with a fixed 15-second delay, 1 m/s northward speed, 20-second capture. SITL acknowledged the command at simulation time zero. The first valid GPS samples began at 9.973 s and remained at native position through 14.573 s. At 19.973 s, the north offset was 4.79 m, consistent with roughly 4.8 seconds of drift after the delay. GPS velocity remained zero. |
| `20261125T003744.517794Z` | Communication-loss injection stopped command heartbeats five seconds after readiness. The two-second command TTL expired; SITL reported state 3 (`stale`) at simulation time 6.729 s. The runner returned `incomplete` with reason `hook_command_stale`, retained 489 telemetry messages and the console log, then acknowledged the shutdown disable command. |
| `20261125T021320.525941Z` | End-to-end delayed position-only mission run with `waypoints.txt`. Following IMUFuzzer ordering, the runner waited for `EKF3 IMU0 is using GPS`, took off in GUIDED, detected the 10 m climb, uploaded all five mission items, then entered AUTO. Takeoff was detected 9.476 s after the takeoff command; the active sequence was acknowledged at simulation time 53.389 s. The configured delay was 15 s. GPS_RAW_INT versus SIMSTATE median north offset was 0 m before takeoff and -0.03 m before the delay; it then rose to 3.26 m by simulation time 73.373 s. The completed record retained 7,641 telemetry messages and a DataFlash BIN. |

The non-mission drift runs acknowledged active command sequence 1 and normal
shutdown disable sequence 2. The mission run acknowledged active sequence 2
at takeoff and shutdown disable sequence 3. The seeded coherent and
position-only records include
the same effective sampled values and identical position progression, while
their velocity fields differ as specified. The two runs at approximately
35° and 60° latitude confirm the north/east conversion at representative
latitudes; the eastward 60° run showed the expected longitude scaling.

The experiment records include ArduPilot/GPSFuzzer commit IDs, dirty-worktree
flags and SHA-256 fingerprints, SITL command/settings, sampled values,
telemetry counts, hook status events, termination reasons, and log paths. Both
repositories were dirty for these runs because the implementation was still
uncommitted. The disarmed baseline had no DataFlash BIN; the mission run
retained a DataFlash BIN alongside telemetry and console output.

The focused Python suite also exercised seeded configuration, IPC layout and
cleanup, mission upload/start, baseline disable, both velocity modes, an
unavailable hook, and a stale hook status. The unavailable-hook case is
reported failed; the stale mid-run case is reported incomplete, with
`experiment.json` and telemetry paths retained.

## Mission outcome monitor validation

The mission outcome monitor records one of `success`, `failure`, or
`incomplete`, plus a reason. Success requires the final navigation item to
have been reached, `EXTENDED_SYS_STATE` to report landed, and the current
position to be within the endpoint radius. Failure reasons include
`crash_detected`, `ekf_failsafe`, `route_deviation`,
`landing_outside_endpoint_radius`, `landing_timeout`, and
`waypoint_progress_timeout`. SITL exit, experiment duration expiry, and runner
interruptions remain incomplete outcomes with their termination reason.

Each mission record stores the final waypoint sequence and coordinate, current
and last-progress sequences, final-item active/reached flags, landed and armed
state, latest vehicle position, endpoint distance, maximum route deviation,
landing-confirmation source, safety events, and the thresholds used. The
defaults are 15 metres for both route deviation and endpoint landing radius,
90 seconds without progress, and 1 metre relative altitude for the disarmed
heartbeat landing fallback. Tune these named defaults in
`gpsfuzzer/outcome.py` after comparing false positives and missed events
against representative missions; the applied values are copied into each
`experiment.json` record so runs remain interpretable.

When the terminal mission item is a LAND command, GPSFuzzer now sends an
explicit disabled GPS-hook command as soon as mission progress reports that
item active. The runner records its trigger time, command sequence, hook state,
acknowledgment time, and simulation timestamp under
`mission.landing_drift_disable`. It continues capturing telemetry and
evaluating the mission outcome through landing. If the disable is not
acknowledged, the run is marked incomplete and active drift is not sent again.
Disabling spoofing restores native GPS measurements; it does not freeze the
vehicle's physical `SIMSTATE` position, which continues to be recorded for
route and endpoint evaluation.

Focused tests cover success evidence, endpoint miss, both timeout paths,
deviation, crash/EKF reports and their precedence, absent mission telemetry,
mission duration expiry, and retained JSONL telemetry. A new baseline outcome
mission was run from the ArduPilot venv. SITL started and 4,371 telemetry
messages were captured, but the hook remained in `STATE_STARTING` with
acknowledged sequence 0, so the run ended as `hook_unavailable_or_not_ready`
before mission upload. The experiment record and telemetry are retained under
`/tmp/gpsfuzzer-outcome-results/20261125T045041.082959Z/`. The recorded SITL
command includes `--no-rebuild`; inspection showed the `arducopter` binary
predated the hook source. Rebuilding with `CCACHE_DIR=/tmp/ardupilot-ccache`
and `CCACHE_TEMPDIR=/tmp` succeeded and compiled `libraries/SITL/SIM_GPS.cpp`.

The rebuilt SITL accepted the short three-item test mission and retained
telemetry, MAVProxy console/tlog, and DataFlash logs. The first attempt reported
`route_deviation` at 18.30 metres when the vehicle was 0.34 metres from the
endpoint because `MISSION_CURRENT` regressed from sequence 2 to 1. The monitor
now ignores that stale backwards update. On the next run, ArduCopter reached
the endpoint and disarmed, but did not emit `MISSION_ITEM_REACHED` for its
terminal LAND item or any `EXTENDED_SYS_STATE`; the monitor therefore waited
90 seconds and reported `waypoint_progress_timeout`. The monitor now accepts a
disarmed heartbeat as landing evidence after observing the vehicle armed, when
the final item is active, relative altitude is at most 1 metre, and vehicle
position is available. Endpoint distance determines success or failure rather
than whether touchdown is recognized. It prefers `EXTENDED_SYS_STATE` when
available and records the fallback source. The follow-up run
`20261125T051500.327771Z` completed as `landed_at_final_waypoint`: all three
mission items uploaded, 8,933 telemetry messages retained, the final
coordinate was 0.33 metres away, relative altitude was 0.078 metres, and the
recorded landing source was `disarmed_low_altitude_near_final_waypoint`.
MAVProxy console/tlog and a DataFlash BIN were also retained. This confirms
the SITL success path. Controlled SITL failure-signal runs remain outstanding;
crash, EKF failsafe, deviation, timeout, and precedence classifications are
currently covered by focused unit tests.

The first coherent-drift run using the project `waypoints.txt` and seed
`20261124` stopped at sequence 2 with a reported 95.22 metre route deviation.
The vehicle was still at home (`-35.3632619, 149.1652372`) near 20 metres
altitude. Its active route leg incorrectly started at the WPL `NAV_TAKEOFF`
coordinate, about 90 metres from home, although ArduCopter had climbed in
place. Route construction now uses home as the origin for the first horizontal
leg after `NAV_TAKEOFF`; the prior result should not be treated as an actual
95 metre drift detection. Rerun the same config and mission to measure the
fuzzer's real drift progression with the corrected leg.

The subsequent coherent-drift run `20261125T052906.000619Z` reached the
terminal LAND item and ended with `route_deviation`; it retained 16,656
telemetry messages, console/tlog, and DataFlash. Its effective drift was
7.119 seconds delay, 1.513 m/s, bearing 1.232 degrees. The then-current
monitor used `GLOBAL_POSITION_INT` and saw 15.18 metres from the final
coordinate. Comparing the same final telemetry with `SIMSTATE` shows the
simulated vehicle was actually 138.58 metres from the endpoint; replaying its
positions against the corrected home-origin route crosses 15 metres of true
route deviation at sequence 2. This demonstrates why the outcome monitor must
prefer simulator truth over the GPS/EKF position being fuzzed. The monitor now
uses `SIMSTATE` for SITL route and endpoint checks while retaining
`GLOBAL_POSITION_INT` separately; rerun the drift experiment to verify this
source selection end to end. The follow-up run
`20261125T054056.783723Z` verified it: the seeded coherent drift ended as
`route_deviation` at mission sequence 2 after 79.853 seconds. Simulator truth
was 15.063 metres from the active leg while `GLOBAL_POSITION_INT` was only
0.596 metres from it, demonstrating that classification used the physical
SITL path rather than the mutated GPS/EKF estimate. The run retained 7,230
telemetry messages, MAVProxy console/tlog, and a DataFlash BIN. Together with
the successful endpoint-landing run above, the SITL success and route
deviation scenarios are validated. Crash and EKF-failsafe message
classification remains covered by unit tests; no separate SITL injection was
used for those signals.

The landing-phase disable was exercised in SITL campaign
`20261127T031858.168504Z` with static `waypoints.txt`. At terminal LAND
activation, command sequence 3 was acknowledged at simulation time 111.989 s.
The runner continued through touchdown and retained 21,909 telemetry
messages; after the acknowledgment, 360 `GPS_RAW_INT` and 360 `SIMSTATE`
samples were captured. Matching GPS and simulator coordinates by nearest host
timestamp gave a mean offset of 0.011 metres and a maximum of 0.400 metres,
consistent with the hook returning native GPS measurements after disable.
ArduCopter disarmed at 0.003 metres relative altitude, but 84.17 metres from
the mission endpoint, so this run correctly ended as a route-deviation failure
with `landing_timeout` as the observation termination reason. The record is
under `/tmp/gpsfuzzer-stop-landing-validation-escalated/20261127T031858.168504Z/`.

An earlier upload attempt returned `MAV_MISSION_NO_SPACE` because it raced
ArduCopter startup and checked mission capacity before the mission library
initialized. Waiting for EKF/GPS readiness and following the reference
takeoff-before-upload sequence resolved the issue. The mission SITL run above
validates upload, AUTO execution, takeoff-gated activation, delayed drift, and
log/provenance retention end to end.

After broadening disarmed low-altitude landing confirmation to work regardless
of endpoint distance, the same generated route was rerun as campaign
`20261127T034117.818777Z`. Command sequence 3 disabled drift at terminal LAND
activation and was acknowledged at simulation time 175.189 s. The vehicle
disarmed at 0.017 metres relative altitude, 183.80 metres from the endpoint.
GPSFuzzer ended immediately with `landing_outside_endpoint_radius` as the
termination reason while retaining `route_deviation` as the failure
classification. The run took 209.678 seconds versus 266.374 seconds for the
prior run of the same seeded route, eliminating the 90-second landing-timeout
wait; 22,957 telemetry messages were retained. Its record is under
`/tmp/gpsfuzzer-endpoint-independent-landing-validation/20261127T034117.818777Z/`.
