# MLC handover notes

MLC is not bundled. Record the approved binary version and Host OS directory in
the local profile. Confirm a usable root shell, required privileges and the
`msr` module before testing.

The existing serial helper runs idle latency, latency matrix, bandwidth matrix,
peak injection bandwidth, loaded latency and c2c latency measurements. Results
are saved under a timestamped Host OS directory and the Windows log root.

The helper uses a runtime credential source only when login is required.
The local wrapper does not automatically transmit a local environment secret to
the remote Windows process. Never add a password to source or a tracked profile.

The helper still has platform-specific prompt assumptions and a COM3-named
interaction log. Review those assumptions on migration. Require the saved
per-test result exit markers and complete logs; command echo is not success.

Measured values from a different topology, BIOS, CPU stepping, DIMM population,
OS or tool version must be labeled with their applicability limits.
