# GPSFuzzer - Agent Instructions

## 1. Project Overview

GPSFuzzer is an independent GPS fuzzing framework for ArduPilot.

The project is inspired by the existing IMUFuzzer implementation,
which uses Python scripts to generate fuzzing inputs and
C++ modifications to inject sensor abnormalities into ArduPilot.

Our objective is to adapt this general architecture to GPS.

The framework will investigate how GPS abnormalities affect
ArduPilot's navigation, estimation, and flight control systems.

The project is currently intended for research and experimentation
using ArduPilot Software In The Loop (SITL).

## 2. Related Repositories

The parent workspace contains three repositories:

### ../IMUFuzzer/

Original IMU fuzzing implementation.

Purpose:
- Reference implementation.
- Understand the existing fuzzing architecture.
- Understand Python-to-C++ communication.
- Understand SITL integration.
- Reference existing fuzzing methodologies.

This repository is READ-ONLY.

### ../ardupilot/

Our fork of the official ArduPilot repository.

Purpose:
- Contains the flight controller source code.
- May contain C++ modifications for GPS fuzzing.
- Used to build and execute ArduPilot SITL.

Modifications to this repository must be documented.

### GPSFuzzer/

This repository.

Purpose:
- Implement GPS fuzzing functionality.
- Generate and mutate GPS inputs.
- Coordinate fuzzing experiments.
- Communicate with ArduPilot.
- Monitor and evaluate experiment results.

All new framework code belongs here.

The current code (gpsSpoofingProto.py, sendyWayPoints.py, textMavConnection.py) are just toy examples and can be deleted if needed

## 3. Primary Development Goals

The project should eventually support:

1. GPS input generation.
2. GPS input mutation.
3. GPS fuzzing orchestration.
4. Communication with ArduPilot.
5. SITL integration.
6. Experiment monitoring.
7. Flight behavior analysis.
8. Reproducible experiments.
9. Automated test execution.

Do not assume all functionality must be implemented immediately.

Develop incrementally.

## 4. Architecture Principles

The framework should maintain a separation of responsibilities.

### Python Components

Python should primarily handle:

- Fuzzing orchestration.
- Input generation.
- Input mutation.
- Experiment configuration.
- Communication with ArduPilot.
- Experiment monitoring.
- Log collection.
- Result analysis.

### C++ Components

C++ modifications should primarily handle:

- GPS input interception or injection.
- GPS measurement modification.
- Integration with relevant ArduPilot interfaces.
- Any instrumentation required for fuzzing.

The exact division of responsibilities should be determined
through investigation of IMUFuzzer and ArduPilot.

Do not introduce unnecessary complexity.

## 5. Development Guidelines

### Python

- Use clear, modular code.
- Separate input generation from experiment orchestration.
- Avoid large monolithic scripts.
- Use type hints where practical.
- Handle communication failures gracefully.
- Make experiments reproducible.
- Keep configuration separate from implementation.

### C++

- Follow existing ArduPilot coding conventions.
- Minimize modifications to existing ArduPilot functionality.
- Document modifications to upstream source files.
- Avoid unnecessary dependencies.
- Ensure instrumentation can be enabled and disabled cleanly.

### Testing

- Write tests for new Python functionality.
- Test input generation independently.
- Test communication mechanisms independently.
- Verify expected behavior in SITL.
- Include regression tests for previously discovered issues.

## 6. Reference Implementation Requirements

Before implementing functionality that may already exist
in IMUFuzzer:

1. Search the IMUFuzzer repository.
2. Identify the relevant source files.
3. Understand the implementation.
4. Determine whether the approach applies to GPS.
5. Document similarities and differences.

Do not blindly copy code.

IMU and GPS measurements have different structures,
semantics, update rates, and processing pipelines.

GPS-specific functionality must account for these differences.

Document important findings in:

docs/IMUFUZZER_ANALYSIS.md

## 7. ArduPilot Integration

Before implementing GPS injection:

Investigate the relevant ArduPilot source code.

Areas of particular interest include:

- libraries/AP_GPS/
- libraries/AP_NavEKF/
- libraries/AP_AHRS/
- ArduCopter/
- SITL-related sensor simulation.

Determine:

1. Where GPS measurements enter ArduPilot.
2. How GPS measurements are processed.
3. Which interfaces support GPS injection.
4. Where instrumentation should be implemented.
5. Whether existing SITL functionality can be leveraged.
6. What modifications are necessary.

Document findings in:

docs/ARDUPILOT_GPS_ANALYSIS.md

Do not assume that modifying the GPS backend is necessarily
the best injection point.

Investigate existing interfaces first.

## 8. Documentation

Maintain the following documentation:

docs/
    IMUFUZZER_ANALYSIS.md
    ARDUPILOT_GPS_ANALYSIS.md
    GPSFUZZER_ARCHITECTURE.md

Additional documentation may be added as the project develops.

Document significant:
- Architectural decisions.
- Implementation choices.
- ArduPilot modifications.
- Testing procedures.
- Experimental findings.

## 9. Experiment Reproducibility

Experiments should be reproducible whenever possible.

Record:

- Random seed.
- Fuzzing configuration.
- ArduPilot commit hash.
- GPSFuzzer commit hash.
- SITL configuration.
- Experiment duration.
- Relevant telemetry and logs.

Separate experiment configuration from experiment results.

## 10. AI Agent Workflow

When assigned a task:

1. Read this AGENTS.md.
2. Review relevant project documentation.
3. Inspect existing implementations.
4. Identify the appropriate repository to modify.
5. Explain the proposed implementation.
6. Make focused changes.
7. Run relevant tests.
8. Summarize changes and test results.

For significant features, propose the architecture before
implementing it.

Do not rewrite working components without a clear reason.

Do not introduce dependencies without explaining their purpose.

## 11. Git Guidelines

- Work only in the GPSFuzzer repository unless ArduPilot
  modifications are explicitly necessary.
- Never modify IMUFuzzer.
- Keep commits focused.
- Use descriptive commit messages.
- Do not commit generated binaries or temporary experiment files.
- Do not commit or push without explicit user authorization.

## 12. Current Project Status

The project is currently in the research and architecture phase.

Initial priorities:

1. Analyze IMUFuzzer.
2. Understand its Python-to-C++ communication.
3. Investigate ArduPilot GPS architecture.
4. Identify potential GPS injection points.
5. Design the GPSFuzzer architecture.
6. Implement an initial working prototype.

Do not assume functionality has already been implemented
unless it exists in the repository.
