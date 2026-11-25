# Proposal

## Why

GPSFuzzer supports reproducible fixed-count campaigns, but users must choose the campaign length before starting. An opt-in until-stopped mode lets exploratory fuzzing continue through new GPS attacks until the user interrupts it, while preserving the results gathered so far.

## What Changes

- Add a fixed iteration count for a campaign, running each iteration as a separate SITL experiment.
- Add an opt-in mode that keeps starting new experiments until the user stops the campaign.
- Derive a distinct, reproducible per-run seed from the campaign seed so every iteration samples a new GPS drift attack.
- Keep each run's telemetry, logs, effective attack, and outcome in its own record, and associate the runs with their campaign and iteration.
- Continue the campaign after mission failures or incomplete outcomes; each attempted run counts toward the requested iteration count.
- Preserve campaign and per-run records when an until-stopped campaign is interrupted, including the number of attempts completed.
- Stop and reap all processes launched for each SITL experiment, including MAVProxy map and console processes, after its result is obtained and before the next iteration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gps-sitl-fuzzing`: add bounded campaign execution with per-iteration GPS attack sampling and run provenance.

## Impact

The CLI and Python orchestration in `gpsfuzzer/` will gain campaign iteration handling and explicit cleanup of each complete SITL process group. Existing per-run SITL lifecycle and result directories will be reused, with campaign metadata added to run records and a campaign-level summary. No new runtime dependency or ArduPilot change is expected.
