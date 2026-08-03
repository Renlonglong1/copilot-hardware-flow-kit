# Intel MLC Common Command Manual

This document summarizes common Intel Memory Latency Checker (Intel MLC) commands based on Intel MLC documentation and the current Host OS environment.

## Current Environment

Validated Host OS path:

```bash
/root/mlc_v3.11b/mlc
```

Detected version:

```text
Intel(R) Memory Latency Checker - v3.11b
```

Intel official page referenced by the user is Intel MLC v3.12. The current server has v3.11b installed, so command behavior should be mostly compatible, but v3.12-specific fixes/features may not be present.

## Linux Runtime Requirements

Intel MLC on Linux usually requires:

```bash
root privileges
msr kernel module loaded, usually: modprobe msr
```

Recommended precheck:

```bash
cd /root/mlc_v3.11b
whoami
modprobe msr || true
./mlc --help
```

If MSR/prefetcher control is unavailable, use `-e` or `-r` depending on the test:

```bash
./mlc -e
./mlc --idle_latency -e
./mlc --latency_matrix -e
```

## Common Commands

### 1. Default full test

```bash
cd /root/mlc_v3.11b
./mlc
```

Purpose:

- Automatically detects topology.
- Measures idle latency matrix.
- Measures peak bandwidth with multiple read/write ratios.
- Measures bandwidth matrix.
- Measures loaded latency.

Use this as the quick overall baseline.

### 2. Latency matrix

```bash
cd /root/mlc_v3.11b
./mlc --latency_matrix
```

Purpose:

- Prints local and cross-socket memory latency matrix.
- Useful for checking NUMA locality and cross-socket latency.

Expected output shape:

```text
Numa node
        0       1
0       xx.x    yy.y
1       yy.y    xx.x
```

### 3. Bandwidth matrix

```bash
cd /root/mlc_v3.11b
./mlc --bandwidth_matrix
```

Purpose:

- Prints local and cross-socket memory bandwidth matrix.
- Useful for NUMA bandwidth characterization.

### 4. Idle latency

```bash
cd /root/mlc_v3.11b
./mlc --idle_latency
```

Purpose:

- Measures idle memory latency of the platform.
- Useful as a low-load latency baseline.

### 5. Loaded latency

```bash
cd /root/mlc_v3.11b
./mlc --loaded_latency
```

Purpose:

- Measures latency while memory bandwidth load is injected.
- Useful for observing how latency changes under different bandwidth levels.

### 6. Peak injection bandwidth

```bash
cd /root/mlc_v3.11b
./mlc --peak_injection_bandwidth
```

Purpose:

- Measures peak memory bandwidth under different read/write ratios.
- Useful for maximum local memory bandwidth baseline.

### 7. Cache-to-cache latency

```bash
cd /root/mlc_v3.11b
./mlc --c2c_latency
```

Purpose:

- Measures cache-to-cache transfer latency.
- Useful for core-to-core/cache coherence latency checks.

### 8. Memory bandwidth scan

```bash
cd /root/mlc_v3.11b
./mlc --memory_bandwidth_scan
```

Purpose:

- Scans memory bandwidth across address ranges.
- Can take longer on large-memory systems.
- Use when detailed per-address-range bandwidth data is needed.

## Useful Options

### Do not modify hardware prefetcher state

```bash
./mlc --latency_matrix -e
```

Use this if MLC cannot access MSRs or if you want to avoid changing prefetcher settings.

### Random access latency mode

```bash
./mlc --idle_latency -r
```

Useful when prefetcher control is unavailable.

### Bind latency thread to a core

```bash
./mlc --idle_latency -c0
```

### Measure latency from a specific core to a specific NUMA node

```bash
./mlc --idle_latency -c0 -j0
./mlc --idle_latency -c16 -j1
```

### Set buffer size

```bash
./mlc --idle_latency -b4g
```

The existing server script uses this style:

```bash
./mlc --idle_latency -c$core -j$node -x0 -b4g
```

## Recommended Baseline Test Order

For this server, a practical baseline sequence is:

```bash
cd /root/mlc_v3.11b
modprobe msr || true
./mlc --idle_latency
./mlc --latency_matrix
./mlc --bandwidth_matrix
./mlc --peak_injection_bandwidth
./mlc --loaded_latency
./mlc --c2c_latency
```

Run `--memory_bandwidth_scan` separately because it can take longer on a 512 GB system.

## Log Naming Convention

Recommended result directory:

```bash
/root/mlc_v3.11b/results_YYYYMMDD_HHMMSS
```

Recommended log names:

```text
00_env.log
01_idle_latency.log
02_latency_matrix.log
03_bandwidth_matrix.log
04_peak_injection_bandwidth.log
05_loaded_latency.log
06_c2c_latency.log
07_memory_bandwidth_scan.log
summary.log
```

## Serial Automation Rules

The validated path runs MLC through COM3 after the boot flow reaches the Host OS login prompt.

Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -RunMlc
```

Important automation rules:

1. Wait for the real root shell prompt, not for a marker string that might appear in command echo.
2. Save each MLC command to a separate host log under `/root/mlc_v3.11b/copilot_mlc_results_YYYYMMDD_HHMMSS`.
3. Retrieve those host result files through COM3 into the Windows run directory as `host_mlc_results.log`; retain both this capture and the raw COM3 interaction log.
4. Verify success by reading saved log files and checking `EXIT:0` for `01_idle_latency.log` through `06_c2c_latency.log`. Use `grep --color=never` or strip ANSI control sequences before parsing its output.
5. If a serial command appears to finish instantly, inspect `COM3_mlc_interaction.log`; it may be a false completion caused by echoed command text.

Validated current result directories:

```text
/root/mlc_v3.11b/copilot_mlc_results_20260623_094808
/root/mlc_v3.11b/copilot_mlc_results_20260623_094928
```
