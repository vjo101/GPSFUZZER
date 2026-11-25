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

An earlier upload attempt returned `MAV_MISSION_NO_SPACE` because it raced
ArduCopter startup and checked mission capacity before the mission library
initialized. Waiting for EKF/GPS readiness and following the reference
takeoff-before-upload sequence resolved the issue. The mission SITL run above
validates upload, AUTO execution, takeoff-gated activation, delayed drift, and
log/provenance retention end to end.
