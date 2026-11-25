# Design

## Context

See proposal.md for the motivation and specs/gps-sitl-fuzzing/spec.md for the behavior contract. `ExperimentRunner.run()` currently owns one SITL lifecycle, samples drift using `ExperimentConfig.seed`, and writes a unique run directory with `experiment.json`, telemetry, and SITL logs. `sample_drift()` creates a new `random.Random(seed)` for each call, so the same seed repeats the same attack. IMUFuzzer's `multi_parameter.py` runs a loop that starts a fresh drone for each mission, records the outcome, mutates parameters, and disables fuzzing before the next run.

## Goals / Non-Goals

**Goals:**

- Add a campaign layer that runs either a fixed number or an unbounded sequence of independent GPSFuzzer experiments.
- Reuse the existing single-run lifecycle, outcome classification, and per-run artifacts.
- Make attack sampling different across iterations and repeatable from the campaign seed.
- Preserve records for all attempted runs and provide a campaign-level index of their outcomes.

**Non-Goals:**

- Feedback-guided mutation based on prior mission outcomes or resiliency scores.
- Mutating mission files or generating different routes.
- Running multiple SITL instances concurrently or resuming an interrupted campaign.

## Decisions

### Add a campaign orchestrator around the single-run runner

Keep `ExperimentRunner.run()` as the owner of one SITL lifecycle. Add a campaign orchestration layer that invokes it sequentially with a fresh run configuration and a per-run seed. Each iteration starts a new SITL process and gets the existing run-level telemetry and log collection. The CLI exposes mutually exclusive `--iterations N` and `--until-stopped` options. The fixed-count mode defaults to one iteration to preserve existing invocation behavior; until-stopped mode continues until Ctrl-C.

This follows IMUFuzzer's sequential fresh-drone loop while preserving GPSFuzzer's more structured per-run runner. Keeping the loop outside `run()` avoids mixing campaign control with MAVLink and SITL lifecycle logic.

### Derive each run seed deterministically from the campaign seed and index

Use a stable derivation based on the campaign seed and zero-based iteration index, rather than reusing the campaign seed for each call. Derive seeds as iterations begin instead of precomputing the full list, so until-stopped campaigns do not need a known endpoint. Track used seeds for collision detection. Store the campaign seed, iteration index, and derived per-run seed. Pass only the per-run seed to the existing drift sampler, which continues to record effective delay, speed, bearing, and mode.

This ensures identical campaign inputs reproduce the same attack sequence while each iteration explores a new sample. A campaign-local random generator could also generate seeds, but index-based derivation makes any individual iteration reproducible without replaying earlier loop state.

### Group campaign and run artifacts under a campaign identifier

Create a unique campaign directory under the configured results directory. Store `campaign.json` there and place each existing per-run directory under its `runs/` child. Add campaign ID, mode, iteration number, requested count (null in until-stopped mode), campaign seed, and per-run seed to each `experiment.json`. Update the campaign summary after each attempt with the run path, status, termination reason, and effective attack so partial results remain useful if an until-stopped campaign is interrupted. Record `requested_iterations: null` for until-stopped mode and retain the actual completed attempt count.

The existing per-run telemetry and SITL logs remain authoritative evidence; the campaign summary is an index, not a replacement for them. A timestamp-based campaign ID avoids collisions between invocations using the same seed.

### Continue after mission outcomes; stop cleanly on user interruption

Mission success, failure, and incomplete outcomes are results, not campaign control signals. Record the result and start the next requested iteration. On a user interrupt, stop launching iterations, allow the active runner's cleanup path to stop SITL and disable/detach the hook, and retain a partial campaign summary with requested and completed counts.

This matches the fuzzer goal of collecting multiple outcomes and avoids silently treating a crash or failsafe as a reason to abandon the remaining inputs. Infrastructure exceptions that prevent a run from producing a normal `RunResult` should be recorded as a failed attempt; whether the campaign can continue depends on whether shared SITL and IPC cleanup completed, and should be handled explicitly by the orchestrator.

For `--until-stopped`, treat Ctrl-C during an experiment as an incomplete run result after the runner has cleaned up SITL, then persist that result and mark the campaign interrupted without starting another iteration. Ctrl-C between runs similarly finalizes the summary with the attempts already recorded. This makes the summary's actual attempt count authoritative for unbounded campaigns.

### Stop and reap the full SITL process group before returning

Launch each experiment's SITL process in an isolated process group so the runner owns the full process tree it starts, including MAVProxy when map or console UI options are enabled. On every termination path, first publish the GPS hook disable command when communication is available, then send graceful termination to the process group, wait for it to exit, and force-kill the group if the grace period expires. Reap the SITL process and only then detach/remove shared memory, close run artifacts, and return the result to the campaign orchestrator.

Apply the same cleanup path after normal duration completion, mission success/failure/incomplete outcomes, startup errors, and user interruption. This prevents an old SITL or GUI process from surviving into the next iteration and interfering with its ports, telemetry, or map/console windows. Record cleanup errors in the experiment result and do not start another iteration while processes from the prior run may still be alive.

## Risks / Trade-offs

- [Repeated SITL startup adds runtime to campaigns] → Run sequentially and keep each lifecycle isolated so one experiment cannot leak hook state into the next.
- [A seed derivation could accidentally repeat a seed] → Use a stable cryptographic derivation from campaign seed and iteration index and record the result; validate that generated seeds are unique within the requested campaign.
- [A process or host failure can interrupt a campaign] → Persist the campaign summary after every attempt and retain each completed run directory; automatic resume is out of scope.
- [A child process may ignore graceful termination] → Escalate to process-group kill after a bounded wait, reap the SITL leader, and record cleanup failures.
- [An until-stopped campaign can accumulate unbounded logs and summary entries] → Make the mode opt-in, persist the summary incrementally, and report the number of attempts completed when the user stops it.
- [Changing result directory nesting may affect scripts that expect runs directly under `results/`] → Document the campaign directory layout and keep single-iteration invocations on the same campaign path model for consistency.

## Migration Plan

No data migration is required. Existing invocations default to one iteration and continue to produce the same run-level record contents, with campaign metadata added. Update the documented CLI examples and result layout when implementing.
