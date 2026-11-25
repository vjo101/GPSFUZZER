# ArduPilot SITL GPS Analysis

This analysis is based on the current `../ardupilot` checkout. At inspection
time, that checkout has no modified files; the GPSFuzzer hook described below
is proposed and has not yet been implemented.

## Measurement path

`libraries/SITL/SIM_GPS.h` defines `SITL::GPS_Data`, the common sample passed
to GPS simulator backends. It includes timestamp, latitude/longitude,
altitude, N/E/D velocity, fix/lock information, accuracy, and attitude fields.
`GPS::update()` in `libraries/SITL/SIM_GPS.cpp` first initializes SITL and the
selected backend, reads position and velocity from `_sitl->state`, and checks
the configured GPS update rate. On an update it creates `GPS_Data`, adds
configured GPS noise, velocity error, antenna position/velocity offsets, and
delay/interpolation effects. It then applies the configured position glitch
and velocity glitch, optionally simulates jamming, and finally calls
`backend->publish(&d)`.

The common sample path is a suitable integration point because all supported
SITL GPS backends receive the same generated `GPS_Data`. The GPS mutation hook
should be applied after native sample generation and existing simulator
effects, but before `backend->publish(&d)`, so backend-specific packet formats
serialize the same mutated measurement. It should use simulation time and
leave `d` unchanged when no valid active command is available.

## Existing `SIM_GPS1_GLTV` behavior

The GPS parameters in the `SIM_GPS` implementation expose a velocity glitch
(`vel_glitch`), corresponding to `SIM_GPS1_GLTV` for GPS instance 1. The code
integrates the configured N/E/D velocity offset over elapsed milliseconds into
`vel_glitch_pos_ofs`. It converts the accumulated north/east displacement to
latitude/longitude using Earth radius and a latitude-dependent cosine, applies
the resulting displacement to reported position, and adds the same configured
offset to `speedN`, `speedE`, and `speedD`. Setting the parameter to zero clears
the accumulated position offset. The `GPSGlitchVelocity` autotest in
`Tools/autotest/arducopter.py` explicitly checks that position moves with the
velocity offset.

This existing behavior provides a coherent-drift reference and test precedent.
It does not provide an experiment start delay or a position-only mode, and it
does not use the GPSFuzzer command/status interface. The new hook therefore
needs independent state and must not alter the existing parameter behavior.

## Proposed scope and modified files

The planned hook location is `libraries/SITL/SIM_GPS.cpp`, in `GPS::update()`
immediately before backend publication. That file can read a GPS-specific
shared-memory command, validate freshness and version, acknowledge its
sequence, integrate horizontal displacement in simulation time, and optionally
offset horizontal velocity. Keep the hook inactive when startup finds no
command, when the command is disabled, or when validation/freshness fails.

Actual ArduPilot modification: `libraries/SITL/SIM_GPS.cpp` only. The change
adds the packed command/status declarations and the inactive-by-default
primary GPS hook in that file. No other ArduPilot source files were modified.

## Verification basis

The source locations were checked in `SIM_GPS.h`, `SIM_GPS.cpp`, and the
`GPSGlitchVelocity` autotest in `Tools/autotest/arducopter.py`. The modified
ArduCopter SITL target builds successfully. An inactive-command baseline is
described below.

## GPSFuzzer baseline run

An ArduCopter SITL baseline was run with `sim_vehicle.py -v ArduCopter -f
quad --no-rebuild --no-mavproxy --udp --no-extra-ports -S 1`, an inactive
GPSFuzzer command, and a 20-second post-readiness capture. The run record is
under `results/20261125T002136.701841Z/experiment.json` (generated artifacts
are ignored by Git). The hook acknowledged the inactive command and the normal
shutdown disable command. Telemetry included 71 `GPS_RAW_INT` and 71 `SIMSTATE`
messages; for the 41 pairs with a valid fix and nonzero position, latitude and
longitude matched exactly. This verifies the inactive path against simulator
truth for this launch and configuration. SITL did not produce a DataFlash BIN
because the vehicle remained disarmed; MAVLink telemetry and the console log
were retained.
