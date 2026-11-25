# IMUFuzzer Reference Analysis

This note traces the checked-out IMUFuzzer reference at `../imufuzzer` and its
bundled ArduPilot tree at `../imufuzzer/data/ardupilot`. It describes what is
present in those trees; it does not claim that the bridge is upstream
ArduPilot behavior.

## Python orchestration

`main_module.py` initializes the fuzzing path in `init_fuzzer()`: it disables
mutations through `cleanupFuzzer()`, initializes shared memory with
`shmInit()`, and then launches mission execution. `execute_fuzzer()` monitors
the mission and starts a sensor mutation when the vehicle reaches the selected
start waypoint. It also coordinates crash/failsafe checks, stops the process,
and later collects DataFlash and MAVLink logs. The larger program performs
mission and parameter exploration and computes IMU-oriented resiliency scores;
that scoring is not a GPS behavior requirement.

`src/sensorFuzzingEngine.py` dispatches by target sensor and strategy. Its
`shmInit()` creates/initializes the mutation interface. `startFuzzing()` picks
a strategy from a comma-separated list and calls the matching accelerometer,
gyroscope, or barometer mutator. `cleanupFuzzer()` sends the `none` behavior to
all three mutators.

`src/sensorMutator.py` declares `ctypes.Structure` records and attaches Python
System V shared memory using `sysv_ipc`. Its input keys are 33000 (accelerometer),
33100 (gyroscope), and 33200 (barometer); each segment is requested at 100
bytes. The records use native C `int`/`float` compatible fields (`type`,
`count`, sensor values, and parameters). Initialization writes zeroed records.
This is a native-layout convention, not a versioned or portable wire format.
Other mutator methods write strategy parameters to these records; the C++ side
uses `count > 0` as an active-command signal and decrements it for finite
operations.

## ArduPilot-side bridge in the reference tree

`SensorFuzzer_Bridge.h` declares the same input keys and 100-byte size, along
with separate output keys (33001, 33101, 33201) and logging keys. Its structs
mirror the Python native fields. In `SensorFuzzer_Bridge.cpp`, bridge methods
call `shmget(key, size, IPC_CREAT|0666)`, attach with `shmat`, access the
record, and detach with `shmdt`. The mutation methods inspect `count` and
`type`, alter the sample, and generally decrement `count` when consuming a
finite mutation. This interface has no explicit version, sequence
acknowledgment, freshness timestamp, or robust error status; failed attachment
prints an error and exits the process in the reference implementation.

`AP_InertialSensor_SITL.cpp` calls `AccelBridge::mutate()` after accumulating
and correcting accelerometer samples (under the fast-sampling condition), then
publishes the result through `send_sensor_value()`. It similarly mutates and
publishes gyroscope samples in `generate_gyro()`. The bridge header is included
by that file. The GPS adaptation should retain the narrow Python-to-SITL
control idea but use a GPS-specific, fixed-width, versioned command/status
contract with explicit acknowledgment and staleness handling.

## Reference-tree edits versus upstream

At inspection time, `git -C ../imufuzzer/data/ardupilot status` reports local
modifications to `libraries/AP_InertialSensor/AP_InertialSensor_SITL.cpp` and
`libraries/AP_InertialSensor/SensorFuzzer_Bridge.cpp`. The SITL diff adds the
IMUFuzzer hook comments around calls to the bridge; the bridge diff includes
local changes to generalized mutation code and log output paths. These are
reference-tree local edits and should not be attributed to upstream ArduPilot.
`SensorFuzzer_Bridge.h` is present in the reference tree and currently has no
worktree modification reported for that path. The precise source history is
the reference checkout's commit `073d2677b5`; this note does not treat its
bundled files as a clean upstream baseline.

The active `../ardupilot` checkout is a separate tree. At inspection time it
has no modified files. No ArduPilot files have yet been changed for GPSFuzzer.
