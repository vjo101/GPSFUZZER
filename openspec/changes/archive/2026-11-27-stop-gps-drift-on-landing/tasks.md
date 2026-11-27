# Tasks

## 1. Detect the terminal LAND item

- [x] 1.1 Expose a one-shot landing-phase trigger when the final route item is active and its command is `NAV_LAND`; verify unit tests distinguish a terminal LAND item from other final commands and repeated progress messages do not retrigger it
- [x] 1.2 Add mission-monitor tests for terminal LAND activation, including mission progress reported through `MISSION_CURRENT` and `MISSION_ITEM_REACHED`; verify the existing outcome behavior remains unchanged before LAND activation

## 2. Disable and record GPS drift

- [x] 2.1 Update the runner to publish a fresh disabled hook command on the landing-phase trigger and latch the disabled state; verify runner tests show the command sequence advances once and no heartbeat republishes active drift
- [x] 2.2 Wait for and record the disabled-command acknowledgment, trigger time, sequence, and hook state; verify tests cover successful acknowledgment and missing/stale acknowledgment while telemetry collection continues and the run is marked incomplete
- [x] 2.3 Update `docs/GPSFUZZER_ARCHITECTURE.md` and `docs/SITL_VALIDATION.md` to describe the LAND activation trigger and separate GPS estimate from `SIMSTATE`; verify the docs match the recorded experiment fields and expected behavior
- [x] 2.4 Confirm armed-to-disarmed low-altitude touchdown regardless of endpoint radius and preserve endpoint-miss or route-deviation classification; verify focused outcome tests show off-endpoint touchdown ends observation immediately
- [x] 2.5 Update the architecture and SITL validation docs to describe the endpoint-independent disarm confirmation and prompt off-endpoint failure; verify documented outcomes match the implementation

## 3. Verify landing behavior end to end

- [x] 3.1 Run the relevant Python test suite and a mission SITL experiment with a terminal LAND item; verify drift stops after LAND activation, the hook acknowledges disable, outcome monitoring continues through landing, and `SIMSTATE` remains an unfrozen physical position stream
- [x] 3.2 Rerun the seeded terminal-LAND SITL mission after the fallback change; verify an off-endpoint disarm ends the run immediately with the expected failure classification and no landing-timeout wait
