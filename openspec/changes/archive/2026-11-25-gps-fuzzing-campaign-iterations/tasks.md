# Tasks

## 1. Campaign orchestration and seed derivation

- [x] 1.1 Implement stable per-iteration seed derivation from campaign seed and iteration index; verify deterministic output and unique seeds across representative campaign sizes.
- [x] 1.2 Add sequential campaign orchestration that starts a fresh single-run SITL experiment for each requested iteration and continues after mission failure or incomplete outcomes; verify with mocked run results.
- [x] 1.3 Add `--iterations` CLI parsing with a backward-compatible default of 1 and reject non-positive or non-integer values before SITL launch; verify through CLI/configuration tests.

## 2. Campaign records and run artifacts

- [x] 2.1 Group run directories under a unique campaign directory and include campaign ID, campaign seed, iteration index, requested count, and per-run seed in each experiment record; verify the emitted JSON fields and paths.
- [x] 2.2 Write and incrementally update `campaign.json` with attempted count, each run path, status, termination reason, and effective attack; verify completed and interrupted campaign summaries.
- [x] 2.3 Ensure each iteration retains its own telemetry and SITL logs and that user interruption stops new iterations while preserving completed artifacts; verify using mocked interruption and cleanup tests.
- [x] 2.4 Stop and reap the full SITL process group after every result, including MAVProxy map/console children, before returning or starting the next iteration; verify normal, failure, incomplete, startup-error, and interruption cleanup paths leave no launched processes alive.

## 3. Documentation and end-to-end validation

- [x] 3.1 Document fixed-count campaign usage, seed reproducibility, campaign directory layout, and outcome continuation in the architecture and CLI documentation; verify the documented command and record schema match the implementation.
- [x] 3.2 Add an integration test that runs a multi-iteration campaign with a mocked SITL runner and checks distinct reproducible attacks, run isolation, and campaign summary references; verify it passes with the focused test suite.
- [x] 3.3 Run a short multi-iteration ArduCopter SITL campaign with map and console enabled and inspect per-run records, telemetry/log paths, sampled attack values, and the campaign summary; verify the requested number of attempts completed and no SITL/MAVProxy processes remain afterward.

## 4. Until-stopped campaign mode

- [x] 4.1 Add a mutually exclusive `--until-stopped` CLI option while preserving the default single iteration; verify the default, option conflict, and positive fixed-count parsing in CLI tests.
- [x] 4.2 Run until-stopped campaigns sequentially with per-iteration seed derivation and stop cleanly on Ctrl-C during or between experiments; verify no later run starts after interruption and active SITL cleanup completes.
- [x] 4.3 Record the campaign mode, null requested count, actual attempts, and interrupted status in campaign and experiment records; verify completed and interrupted summaries with a mocked campaign run.
- [x] 4.4 Document until-stopped usage, Ctrl-C behavior, and partial result layout; verify the documented command matches CLI help and the emitted summary fields.
