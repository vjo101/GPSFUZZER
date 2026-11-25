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

All drift runs acknowledged active command sequence 1 and normal shutdown
disable sequence 2. The seeded coherent and position-only records include
the same effective sampled values and identical position progression, while
their velocity fields differ as specified. The two runs at approximately
35° and 60° latitude confirm the north/east conversion at representative
latitudes; the eastward 60° run showed the expected longitude scaling.

The experiment records include ArduPilot/GPSFuzzer commit IDs, dirty-worktree
flags and SHA-256 fingerprints, SITL command/settings, sampled values,
telemetry counts, hook status events, termination reasons, and log paths. Both
repositories were dirty for these runs because the implementation was still
uncommitted. DataFlash BIN logs were unavailable in these disarmed runs; the
runner retained the available telemetry and console logs instead.

The focused Python suite also exercised seeded configuration, IPC layout and
cleanup, mission upload/start, baseline disable, both velocity modes, an
unavailable hook, and a stale hook status. The unavailable-hook case is
reported failed; the stale mid-run case is reported incomplete, with
`experiment.json` and telemetry paths retained.

An optional mission-upload smoke run with `waypoints.txt`
(`20261125T004515.551942Z`) accepted mission clear, then returned
`MAV_MISSION_NO_SPACE` for the five-item upload before requesting any items.
The runner recorded the failure and retained the experiment metadata and
telemetry. Baseline and drift behavior above was validated without arming or
mission upload, so mission execution is not claimed as end-to-end validated.
The rejection originates in ArduPilot's mission-capacity check in
`MissionItemProtocol::handle_mission_count`; the runtime capacity value still
needs investigation.
