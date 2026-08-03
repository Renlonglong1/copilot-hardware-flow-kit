# BHS Platform Reference Knowledge

This is a portable, task-oriented index and distilled knowledge base for the reference PDFs in `learningfile\`. It complements, but never replaces, the source documents. The source PDFs are Intel Confidential; keep them local and do not distribute their contents outside authorized systems.

## Use Rules

- Read this index first to select the smallest relevant source document and section.
- Treat firmware, BIOS, BKC, and platform recommendations as version- and workload-specific. Do not apply a setting from a reference guide without confirming the target platform, BKC, workload, and release.
- These references inform investigation and planning only. They do not authorize SSH, flashing, power control, serial control, error injection, or MLC execution. Follow the task-specific skill and its safety contract before any hardware action.
- Preserve raw evidence before changing configuration or attempting reproduction.

## Source Catalog

| Topic | Source | Scope | Use it when |
| --- | --- | --- | --- |
| BHS RAS validation | `learningfile\742874_BHS_RAS_IVG_Rev_1_5.pdf` | RAS feature configuration, observability, and validation recipes | Diagnosing or planning PCIe, UPI, CPU, memory, CXL, MCA, AER, ELOG, or error-injection work |
| BHS hang/MCE triage | `learningfile\774112_BHS_System_Hang_MCE_Issue_Debug_Handbook_Rev1_0.pdf` | Classification and evidence-led debug of system hangs and MCEs | A BHS system hangs, reports IERR/MCERR, 3-strike/TOR timeout, shutdown state, or nested MCE |
| BHS performance and power | `learningfile\819861 Birch Stream Platform Performance and Power Optimization Rev. 1.8.pdf` | Workload-specific BIOS and platform performance/power tuning | Establishing a benchmark baseline or evaluating performance, latency, bandwidth, accelerator, or energy-efficiency configuration |
| Oak Stream weekly update | `learningfile\820238_OKS_MoW_WW28_2026.pdf` | Time-sensitive collateral, BKC, design, tool, and readiness updates | Confirming Oak Stream release/collateral status; not a BHS configuration authority |

## BHS RAS Validation Guide (742874, Rev. 1.5, August 2025)

### Scope and feature map

- The guide organizes RAS by IIO/PCIe, UPI, CPU/core, system, memory, CXL, cross-RAS, and RAS-offload flows.
- Runtime ownership matters: IIO, UPI, CPU/core, memory, and CXL features may depend on runtime UEFI firmware; system RAS additionally needs OS/software support.
- Important areas include PCIe/CXL.io corrected and uncorrectable flows, retraining/recovery, link CRC retry, eDPC, UPI retry, MCA recovery, viral/crash-dump behavior, SDDC/ADDDC, mirroring, patrol scrub, PPR, SMBus hang recovery, CXL event logging, and poison handling.

### Establish observability before diagnosis or validation

1. Record the exact BIOS/BKC, OS/kernel, topology, DIMM/CXL/PCIe population, and workload.
2. Preserve CrashDump/BMC dump and OS evidence before reset or configuration changes.
3. On Linux, capture MCA, AER, memory-failure, EDAC, and extended memory-log events. The guide's baseline FTrace events are `mce/mce_record`, `ras/aer_event`, and `ras/memory_failure_event`; `ras/mc_event` and `ras/extlog_mem_event` add EDAC and eLog visibility.
4. Use `dmesg` as a complementary record; its detail depends on kernel and configuration. For panic-prone tests, `ftrace_dump_on_oops` may preserve pre-panic trace data only if the event reaches FTrace first.
5. Keep the raw trace and log alongside the test result, error-injection details, and post-test state.

### Validation prerequisites and cautions

- The reference configuration enables EMCA/ELOG and WHEA logging, error reporting, and the required error-injection controls. BIOS paths vary by implementation; verify against the target firmware rather than copying paths blindly.
- The RAS recipes require CScripts access and particular debug-oriented BIOS settings. Such settings, including disabling locks or BIOS-done behavior, are test prerequisites and must not be assumed appropriate for normal operation.
- The guide notes that CET-IBT can make CScripts recipes fail silently while halted; its validation baseline uses `ibt=off`.
- EINJ, ras-tools, FTrace, CrashDump, BMC dump, CScripts, and iotools are distinct evidence/injection tools. Select the least invasive tool needed; do not inject errors merely to investigate a live failure.

### Fast routing

| Symptom or goal | Start with |
| --- | --- |
| PCIe/CXL link or AER issue | IIO RAS; retain AER FTrace and topology evidence |
| UPI link issue | UPI RAS; retain first-error and link evidence |
| Processor/MCA issue | CPU/system RAS plus hang/MCE handbook |
| DIMM/DDR/poison/scrub issue | Memory RAS; record physical address, node/channel/module mapping, and ELOG/EDAC evidence |
| CXL error or poison | CXL RAS; retain CXL event logs and topology |
| Planned error-injection validation | Standard configuration and the exact feature recipe |

## BHS System Hang and MCE Debug Handbook (774112, Rev. 1.0, June 2024)

### Core triage model

Classify before changing anything:

1. Determine whether IERR and/or MCERR occurred from preserved CrashDump, BMC dump, or CScripts/register evidence.
2. If MCERR exists, identify the first MCERR in the whole system and debug from that source.
3. If there is IERR without MCERR, first rule out a real PCU error, then validate whether it is 3-strike-only, then determine whether the processor entered shutdown state.
4. If neither IERR nor MCERR is present and cores can still execute, route as a soft/non-MCE hang. This may be software or a hardware condition logged outside MCA banks; involve the appropriate OS, BIOS, or software owner.

### Evidence that must be preserved

- First IERR, MCERR, and recoverable-MCA source IDs per socket.
- Die-level internal versus observed IERR/MCERR/RMCA status.
- First IERR/MCERR/RMCA TSC values to establish system-wide ordering.
- MCA bank contents, relevant address/status registers, CrashDump/BMC dump, BIOS/OS logs, topology, BKC, and precise reproduction conditions.

### Important classifications

- **3-strike-only:** one or more MLC MCA banks report a 3-strike timeout with no corresponding CHA TOR timeout in the same socket. Confirm that TOR timeout and its MCA-bank control are enabled, and check for a stuck TOR entry if needed. Heavy `WBINVD` or bus-lock use is a possible software clue. Early boot can lack TOR enablement, so interpret absence of TOR timeout in context.
- **Nested MCE:** resolve one failure at a time. Find and fix the first MCE, reproduce, then evaluate the next first MCE; do not treat later cascaded errors as the original cause.
- **Shutdown state:** if accompanied by MCERR, follow the first-MCERR path. Cases without MCERR need case-specific investigation.
- **Soft/non-MCE hang:** inspect non-MCA CSR/MSR and platform/OS evidence. The handbook notes examples involving external PCIe-switch configuration, UEFI compilation, power sequencing/CPLD, and OS patches.

### Debug discipline

- Do not select a root cause from the most visible error. Use first-error order and source-ID evidence.
- For multi-socket failures, establish the first reporting socket before following any bank-specific recipe.
- Reduce variables only after evidence capture. The handbook notes that disabling VIRAL mode and eMCA 2.0 can simplify a failure, but this is an experiment requiring documented before/after configuration.

## BHS Performance and Power Optimization Guide (819861, Rev. 1.8, February 2026)

### Practical model

- There is no universal "best performance" BIOS. The guide provides separate recommendations for compute, memory bandwidth, transactional, database, web/network, AI, storage/network I/O, and energy-efficiency workloads.
- Establish a reproducible baseline before tuning: BKC/BIOS, processor SKU, memory topology, accelerator and NIC/storage topology, OS/kernel, workload version and parameters, benchmark metric, power/thermal environment, and all non-default knobs.
- Change a small, attributable configuration set per experiment; compare both target performance and power/latency side effects.

### Tuning domains to consult in the source

| Workload concern | Relevant guide areas |
| --- | --- |
| Compute/throughput | HPL, SPEC CPU, SPEChpc, AVX2/AVX-512/AMX, turbo, uncore ratio |
| Memory bandwidth/latency | STREAM, memory configuration/page policy, snoop/directory/SNC/virtual NUMA, prefetching, latency-sensitive settings |
| Transactional/database | SPECjbb, HammerDB, MongoDB, SQL Server OLTP/OLAP, core/turbo/power policy |
| Networking/storage/I/O | NGINX, VPP, IIO inbound/P2P/outbound flows, DDIO, DSA/IAA/QAT/VMD/VROC |
| AI | AI headnode, MLPerf inference, AMX and accelerator tuning |
| Energy efficiency | Workload efficiency configurations, memory population, networking considerations, power-related BIOS knobs, HWP, Energy Performance Bias, C-states, uncore controls, and thermal/VR/PSU considerations |

### Guardrails

- Apply recommendations only from the matching workload section and its assumptions.
- Treat changes to prefetching, snoop/directory mode, SNC/virtual NUMA, turbo, Hyper-Threading, C-states, uncore control, Intel SST, DDIO, and accelerator settings as benchmark experiments, not generic fixes.
- Compare performance, tail latency, power, thermals, stability, and NUMA locality; a gain in one metric can regress another.

## Oak Stream MoW (820238, WW28 2026, July 2026)

### Scope boundary

This is an Oak Stream release bulletin spanning 2024-2026, not a BHS operational guide. It may be used to locate current collateral and readiness information, but BHS changes still require BHS-specific source validation.

### Current WW28'26 highlights

- Diamond Rapids and Palm Ridge BIOS Developer's Guide, document 839071 Rev. 1.0, is available; it adds Platform RAPL (PSYS), Intel Firmware Support Package, revised memory-content organization, reclaim-lost-memory material, TME-MK, vendor-authorized boot/debug, and mailbox/unified-IFWI topics.
- Oak Stream Platform System Boards Design Archive, document 821025 Rev. 1.03, adds front-panel schematic/layout/BOM content; other included boards are unchanged.
- The bulletin publishes collateral/tool availability forecasts and a WW28 BKC release notification. Obtain the exact release entry from the source before selecting a BKC.
- Oak Stream 16-channel socket supplier parts reached DG0.7 production-candidate status; this is the first recommended status for beginning-of-life customer validation. The associated thermal-mechanical specification update was targeted for the end of July 2026.

## Retrieval Prompts

Use a focused request such as:

```text
Read docs\bhs_platform_reference_knowledge.md and the exact source section needed.
Treat the recommendation as version-specific. First provide the evidence to collect
and the non-invasive triage plan; do not perform hardware actions unless the selected
task skill explicitly authorizes them.
```
