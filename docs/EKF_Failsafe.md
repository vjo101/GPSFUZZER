## How the EKF failsafe is triggered

ArduCopter checks EKF health at 10 Hz. It considers the checks failed when either the EKF variances are over threshold or it no longer has a usable position estimate. After 10 consecutive failed checks—about one second—it logs an EKF check error and triggers the EKF failsafe. Before that, it requests a yaw reset and then a lane switch as recovery attempts. See ekf_check.cpp.

The variance check uses filtered position and velocity variances. It trips when combinations of compass, velocity, and position variances exceed FS_EKF_THRESH; the default threshold is 0.8. If the failsafe fires while the vehicle is armed, the configured FS_EKF_ACTION determines the response. The default is Land. If disarmed, Copter records the failsafe state but takes no flight action. See ekf_check.cpp and config.h.

## What the current GPS injection can do

The SITL hook adds a steady, integrated horizontal drift to GPS position. In coherent mode, it also adds the same drift velocity to GPS velocity; in position-only mode, GPS velocity stays unchanged. It does not inject abrupt jumps or alter GPS fix and accuracy fields. See SIM_GPS.cpp.

It could trigger an EKF failsafe, but the current injection does not guarantee one. In coherent mode, matching position and velocity drift may look like a plausible trajectory and stay within innovation limits. Position-only mode creates a position/velocity mismatch, so it has a clearer path to elevated EKF innovations. But EKF3 applies innovation gates: it can reject inconsistent samples, reset its position or velocity state after timeouts, and clear the reported test ratios during recovery. See AP_NavEKF3_PosVelFusion.cpp.

The practical distinction is that a GPS attack can produce a wrong but internally plausible estimate without causing Copter’s EKF failsafe. To confirm a failsafe in a campaign, inspect the EKF Failsafe telemetry message and the DataFlash EKF innovation and variance logs; a mutated input alone is not evidence that the failsafe fired.
