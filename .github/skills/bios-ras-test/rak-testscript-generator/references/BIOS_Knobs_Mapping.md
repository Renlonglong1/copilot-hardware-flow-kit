# BIOS Knobs Mapping

Purpose: define platform-specific BIOS knob names, menu paths, setup types, and legal values for generated RAK RAS cases.

This file is a whitelist. Do not invent knob names, paths, values, setup types, or cross-platform replacements.

## 1. Use Rules

- Use the common RAS baseline table first, then use the selected platform family table for
	feature-specific knobs.
- Every generated RAK RAS case must include the RAS baseline knobs listed in section 2.
- Add feature-specific BIOS knobs only when the case behavior depends on them.
- In `UEFI_BIOS_knobs`, generate each knob as `KnobName=0xVALUE`.
- When a path is listed here, include the exact path as the knob line comment.
- Do not copy a knob from another platform because the name looks similar.
- Do not change legal values unless the user or source recipe explicitly provides a newer platform reference.

Setup type rules:
- `oneof`: use only one listed text/value pair.
- `numeric`: use only values inside the listed range.
- `checkbox`: `0x0` means unchecked or disabled; use `0x1` as the preferred enabled value unless the table says otherwise.

## 2. Common Base Knob Patterns

These RAS baseline knobs are mandatory for every generated RAK RAS case:

| Knob | Required value | Purpose |
|---|---|---|
| `RasLogLevel` | `0x3` | Enable MAX RAS logging. |
| `DfxEvMode` | `0x1` | Enable EV DFX features for RAS validation and error injection flows. |
| `DfxUnlockErrorInjEn` | `0x1` | Unlock error injection DFX support. |
| `DfxDisableCctBiosDone` | `0x1` | Disable BIOS_DONE programming for CCT/MSR_BIOS_DONE flows. |

Use these additional knobs only when the scenario needs the matching behavior.

| Scenario | Platform family | Required knobs |
|---|---|---|
| RAK RAS baseline | EGS/BHS/OKS | `RasLogLevel=0x3`, `DfxEvMode=0x1`, `DfxUnlockErrorInjEn=0x1`, `DfxDisableCctBiosDone=0x1` |
| EINJ support | EGS/BHS/OKS | `WheaErrorInjSupportEn=0x1` |
| PCIe EINJ support | EGS/BHS/OKS | `WheaErrorInjSupportEn=0x1`, `WheaPcieErrInjEn=0x1` |

Legacy note: older platform-specific CScripts rules used `DFXEnable` or `DfxDisableBiosDone`.
Do not use those legacy replacements for newly generated RAK RAS cases unless the user provides
a newer platform reference that explicitly requires them in addition to the RAS baseline knobs.

OKS injection unlock rule: `DfxUnlockErrorInjEn=0x1` is the required unlock mechanism for OKS
RAK RAS cases. Do not add an extra `ei.utils.reset_injector_lock_check()` call for OKS just to
unlock injection when this BIOS knob is present.

## 3. EGS BIOS Knobs

Target platforms: `SPR`, `EMR`.

| Knob | Path | setupType | Allowed values / range |
|---|---|---|---|
| ADDDCEn | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> ADDDC Sparing | oneof | Disable=0x0<br>Enable=0x1 |
| AttemptFastBoot | EDKII Menu -> Socket Configuration -> Memory Configuration -> Attempt Fast Boot | oneof | Disable=0x0<br>Enable=0x1 |
| AttemptFastBootCold | EDKII Menu -> Socket Configuration -> Memory Configuration -> Attempt Fast Cold Boot | oneof | Disable=0x0<br>Enable=0x1 |
| CloakingEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Memory Corrected Error -> System Cloaking | oneof | Disable=0x0<br>Enable=0x1 |
| CoreCrashLogDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> Core CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| CorrMemErrEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Memory Corrected Error | oneof | Disable=0x0<br>Enable=0x1 |
| CpuCrashLogFeature | Platform Configuration -> System Event Log -> Crash Log Enabling -> CPU CrashLog Feature | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| CpuCrashLogReArm | Platform Configuration -> System Event Log -> Crash Log Enabling -> CPU CrashLog ReArm | oneof | Disable=0x0<br>Enable=0x1 |
| DfxDisableBiosDone | EDKII Menu -> Socket Configuration -> IIO Configuration -> DFX Global Configuration -> Disable BIOS Done | checkbox | 0x0=Unchecked/Disable<br>non-zero=Checked/Enable<br>preferred enable value=0x1 |
| DfxPmicIsolation | EDKII Menu -> Socket Configuration -> Memory Configuration -> PMIC Failure Isolation | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| DFXEnable | EDKII Menu -> Socket Configuration -> IIO Configuration -> DFX Global Configuration -> EV DFX Features | oneof | Disable=0x0<br>Enable=0x1 |
| DirectoryModeEn | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> Directory Mode Enable | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| EdpcEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Reporting -> IIO eDPC Support<br>EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO eDPC Support | oneof | Disable=0x0<br>On Fatal Error=0x1<br>On Fatal and Non-Fatal Errors=0x2 |
| EdpcErrCorMsg | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO eDPC ERR_COR Message | oneof | Disable=0x0<br>Enable=0x1 |
| ElogIgnOptin | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> Ignore OS ELOG Opt-in | oneof | Disable=0x0<br>Enable=0x1 |
| EmcaCsmiEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA CMCI-SMI Morphing | oneof | Disable=0x0<br>EMCA gen 2 CSMI=0x2 |
| EmcaCsmiThreshold | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA CMCI-SMI Threshold | numeric | min=0x0<br>max=0x7FFF<br>step=0x1 |
| EmcaEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA Logging Support | oneof | Disable=0x0<br>Enable=0x1 |
| EmcaMsmiEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA MCA-SMI Enable | oneof | Disable=0x0<br>EMCA gen 2 - MSMI=0x2 |
| EnableGlobalIntegrity | EDKII Menu -> Socket Configuration -> Security Configuration -> Memory Integrity | oneof | Disable=0x0<br>Enable=0x1 |
| EnableMktme | EDKII Menu -> Socket Configuration -> Security Configuration -> Total Memory Encryption Multi-Tenant (TME-MT) | oneof | Disable=0x0<br>Enable=0x1 |
| EnableTme | EDKII Menu -> Socket Configuration -> Security Configuration -> Memory Encryption (TME) | oneof | Disable=0x0<br>Enable=0x1 |
| ErrorCheckScrub | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> DDR5 ECS | oneof | Disable=0x0<br>Enable=0x1<br>Enable ECS with Result Collection=0x2 |
| ForcePprOnAllDramUce | EDKII Menu -> Socket Configuration -> Memory Configuration -> Force PPR On All DRAM For UCE | oneof | Disabled=0x0<br>Enabled=0x1 |
| IerrResetEnabled | Platform Configuration -> System Event Log -> DWR Configuration -> IERR Global Reset | oneof | Disabled=0x0<br>Enabled=0x1 |
| IioErrorEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO/PCH Global Error Support | oneof | Disable=0x0<br>Enable=0x1 |
| IoMcaEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Reporting -> IIO MCA Support | oneof | Disable=0x0<br>Enable=0x1 |
| KtiFailoverEn | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> UPI Failover Support | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| KtiLinkL0pEn | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> Link L0p Enable | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| KtiLinkL1En | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> Link L1 Enable | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| LmceEn | Platform Configuration -> System Event Log -> EMCA Settings -> LMCE Support | oneof | Disable=0x0<br>Enable=0x1 |
| LockChipset | EDKII Menu -> Socket Configuration -> Processor Configuration -> Lock Chipset | oneof | Enable=0x1<br>Disable=0x0 |
| McaBankErrInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> MCA Bank Error Injection Support | oneof | Disable=0x0<br>Enable=0x1 |
| McerrTriggerDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> MCERR Trigger CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| MirrorMode | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Mirror Mode | oneof | Disable=0x0<br>Full Mirror Mode=0x1<br>Partial Mirror Mode=0x3 |
| OsNativeAerSupport | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> OS Native AER Support | oneof | Disable=0x0<br>Enable=0x1 |
| partialmirrorsad0 | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Mirror TAD0 | oneof | Enable=0x1<br>Disable=0x0 |
| PartialMirrorUefi | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> UEFI ARM Mirror | oneof | Disable=0x0<br>Enable=0x1 |
| PartialMirrorUefiPercent | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> ARM Mirror Percentage | numeric | min=0x0<br>max=0x1388<br>step=0x1 |
| PatrolScrub | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Patrol Scrub | oneof | Disable=0x0<br>Enable at End of POST=0x2 |
| PcieAerAdNfatErrEn | EDKII Menu -> Platform Configuration -> System Event Log -> PCIe Error Enabling -> PCIe AER Advisory Nonfatal Error | oneof | Disable=0x0<br>Enable=0x1 |
| PcieCorErrCntr | Platform Configuration -> System Event Log -> PCIe Error Enabling -> PCIe Corrected Error Threshold Counter | oneof | Disable=0x0<br>Enable=0x1 |
| PfdEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> PFD | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| PoisonEn | EDKII Menu -> Platform Configuration -> System Event Log -> System Memory Poison | oneof | Disable=0x0<br>Enable=0x1 |
| pprType | EDKII Menu -> Socket Configuration -> Memory Configuration -> DDR PPR Type | oneof | PPR Disabled=0x0<br>Hard PPR=0x2<br>Soft PPR=0x1 |
| ProcessorMsrLockControl | EDKII Menu -> Socket Configuration -> Processor Configuration -> MSR Lock Control | oneof | Disable=0x0<br>Enable=0x1 |
| promoteMrcWarnings | EDKII Menu -> Socket Configuration -> Memory Configuration -> MRC Promote Warnings | oneof | Disable=0x0<br>Enable=0x1 |
| promoteWarnings | EDKII Menu -> Socket Configuration -> Memory Configuration -> Promote Warnings | oneof | Disable=0x0<br>Enable=0x1 |
| RasLogLevel | EDKII Menu -> Platform Configuration -> System Event Log -> RAS Log Level | oneof | None=0x0<br>MIN (BASIC_FLOW)=0x1<br>MID (BASIC_FLOW, FUNC_FLOW)=0x2<br>MAX (BASIC_FLOW, FUNC_FLOW, REG)=0x3 |
| RtRowSparing | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Runtime PPR / Row Sparing | oneof | Disable=0x0<br>Enable=0x1 |
| SmbusErrorRecovery | EDKII Menu -> Socket Configuration -> Processor Configuration -> SMBus Error Recovery | oneof | Disable=0x0<br>Enable=0x1 |
| spareErrTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Correctable Error Threshold | numeric | min=0x0<br>max=0x7FFF<br>step=0x1 |
| SpareIntSelect | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Spare Interrupt | oneof | Disable=0x0<br>SMI=0x1<br>Error Pin=0x2<br>CMCI=0x4 |
| SparePerRowTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> SW Per Row Threshold | numeric | min=0x1<br>max=0x7FFF<br>step=0x1 |
| SparePerBankTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> SW Per Bank Threshold | numeric | min=0x1<br>max=0x7FFF<br>step=0x1 |
| SystemErrorEn | EDKII Menu -> Platform Configuration -> System Event Log -> System Errors | oneof | Disable=0x0<br>Enable=0x1<br>Auto=0x2 |
| TorCrashLogDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> TOR CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| TriggerSWErrThEn | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Trigger SW Error Threshold | oneof | Disable=0x0<br>Enable=0x1 |
| UncoreCrashLogDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> Uncore CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| ViralEn | EDKII Menu -> Platform Configuration -> System Event Log -> Viral Status | oneof | Disable=0x0<br>Enable=0x1 |
| WheaErrorInjSupportEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> WHEA Error Injection Support | oneof | Disable=0x0<br>Enable=0x1 |
| WheaPcieErrInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> WHEA PCIe Error Injection Support | oneof | Disable=0x0<br>Enable=0x1 |
| WheaSupportEn | EDKII Menu -> Platform Configuration -> System Event Log -> WHEA Settings -> WHEA Support | oneof | Disable=0x0<br>Enable=0x1 |

## 4. BHS BIOS Knobs

Target platforms: `GNR-AP`, `GNR-SP`, `SRF-AP`, `SRF-SP`, `CWF-AP`.

| Knob | Path | setupType | Allowed values / range |
|---|---|---|---|
| ADDDCEn | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> ADDDC Sparing | oneof | Disable=0x00<br>Enable=0x01 |
| AttemptFastBoot | EDKII Menu -> Socket Configuration -> Memory Configuration -> Attempt Fast Boot | oneof | Disable=0x00<br>Enable=0x01 |
| AttemptFastBootCold | EDKII Menu -> Socket Configuration -> Memory Configuration -> Attempt Fast Cold Boot | oneof | Disable=0x00<br>Enable=0x01 |
| CeCloakingEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Memory Corrected Error -> System Cloaking | oneof | Disable=0x00<br>Enable=0x01 |
| CoreCrashLogDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> Core CrashLog Disable | oneof | No=0x00<br>Yes=0x01 |
| CorrMemErrEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Memory Corrected Error | oneof | Disable=0x00<br>Enable=0x01 |
| CpuCrashLogFeature | Platform Configuration -> System Event Log -> Crash Log Enabling -> CPU CrashLog Feature | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| CpuCrashLogReArm | Platform Configuration -> System Event Log -> Crash Log Enabling -> CPU CrashLog ReArm | oneof | Disable=0x00<br>Enable=0x01 |
| DfxClearAllPPRData | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Clear All PPR Entries Data | oneof | Disable=0x00<br>Enable=0x01 |
| DfxDisableBiosDone | EDKII Menu -> Socket Configuration -> IIO Configuration -> DFX Global Configuration -> Disable BIOS Done | checkbox | 0x0=Unchecked/Disable<br>non-zero=Checked/Enable<br>preferred enable value=0x1 |
| DfxEvMode | EDKII Menu -> Socket Configuration -> IIO Configuration -> DFX Global Configuration -> EV DFX Features | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| DfxPmicIsolation | EDKII Menu -> Socket Configuration -> Memory Configuration -> PMIC Failure Isolation | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| DfxPoisonEn | EDKII Menu -> Platform Configuration -> System Event Log -> System Memory Poison | oneof | Disable=0x00<br>Enable=0x01 |
| DirectoryModeEn | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> Directory Mode Enable | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| EdpcEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Reporting -> IIO eDPC Support<br>EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO eDPC Support | oneof | Disable=0x00<br>On Fatal Error=0x01<br>On Fatal and Non-Fatal Errors=0x02 |
| EdpcErrCorMsg | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO eDPC ERR_COR Message | oneof | Disable=0x00<br>Enable=0x01 |
| ElogIgnOptin | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> Ignore OS ELOG Opt-in | oneof | Disable=0x00<br>Enable=0x01 |
| ElogMultiError | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> Multi Error Section Support | oneof | Disable=0x00<br>Enable=0x01 |
| EmcaCsmiEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA CMCI-SMI Morphing | oneof | Disable=0x00<br>EMCA gen 2 CSMI=0x02 |
| EmcaCsmiThreshold | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA CMCI-SMI Threshold | numeric | min=0x0<br>max=0x7FFF<br>step=0x1 |
| EmcaEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA Logging Support | oneof | Disable=0x00<br>Enable=0x01 |
| EmcaMsmiEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Setting -> EMCA MCA-SMI Enable | oneof | Disable=0x00<br>EMCA gen 2 - MSMI=0x02 |
| EnableGlobalIntegrity | EDKII Menu -> Socket Configuration -> Security Configuration -> Memory Integrity | oneof | Disable=0x00<br>Enable=0x01 |
| EnableMktme | EDKII Menu -> Socket Configuration -> Security Configuration -> Total Memory Encryption Multi-Tenant (TME-MT) | oneof | Disable=0x00<br>Enable=0x01 |
| EnableTme | EDKII Menu -> Socket Configuration -> Security Configuration -> Memory Encryption (TME) | oneof | Disable=0x00<br>Enable=0x01 |
| ErrorCheckScrub | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> DDR5 ECS | oneof | Disable=0x00<br>Enable=0x01<br>Enable ECS with Result Collection=0x02 |
| ForcePprOnAllDramUce | EDKII Menu -> Socket Configuration -> Memory Configuration -> Force PPR On All DRAM For UCE | oneof | Disable=0x00<br>Enable=0x01 |
| IerrResetEnabled | Platform Configuration -> System Event Log -> DWR Configuration -> IERR Global Reset | oneof | Disabled=0x00<br>Enabled=0x01 |
| IioErrorEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO/PCH Global Error Support | oneof | Disable=0x00<br>Enable=0x01 |
| IoMcaEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Reporting -> IIO MCA Support | oneof | Disable=0x00<br>Enable=0x01 |
| KtiFailoverEn | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> UPI Failover Support | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| KtiLinkL0pEn | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> Link L0p Enable | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| KtiLinkL1En | EDKII Menu -> Socket Configuration -> Uncore Configuration -> Uncore General Configuration -> Link L1 Enable | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| LmceEn | Platform Configuration -> System Event Log -> EMCA Settings -> LMCE Support | oneof | Disable=0x00<br>Enable=0x01 |
| LockChipset | EDKII Menu -> Socket Configuration -> Processor Configuration -> Lock Chipset | oneof | Enable=0x01<br>Disable=0x00 |
| McaBankErrInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> MCA Bank Error Injection Support | oneof | Disable=0x00<br>Enable=0x01 |
| McerrTriggerDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> MCERR Trigger CrashLog Disable | oneof | No=0x00<br>Yes=0x01 |
| MirrorMode | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Mirror Mode | oneof | Disable=0x00<br>Full Mirror Mode=0x01 |
| OobRasSupport | EDKII Menu -> Platform Configuration -> System Event Log -> OOB RAS Support | oneof | Disable=0x00<br>Enable=0x01 |
| OsNativeAerSupport | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> OS Native AER Support | oneof | Disable=0x00<br>Enable=0x01 |
| partialmirrorsad0 | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Mirror TAD0 | oneof | Enable=0x01<br>Disable=0x00 |
| PartialMirrorUefi | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> UEFI ARM Mirror | oneof | Disable=0x00<br>Enable=0x01 |
| PartialMirrorUefiPercent | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> ARM Mirror Percentage | numeric | min=0x0<br>max=0xFA0<br>step=0x1 |
| PatrolScrub | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Patrol Scrub | oneof | Disable=0x00<br>Enable at End of POST=0x02 |
| PcieAerAdNfatErrEn | EDKII Menu -> Platform Configuration -> System Event Log -> PCIe Error Enabling -> PCIe AER Advisory Nonfatal Error | oneof | Disable=0x00<br>Enable=0x01 |
| PcieCorErrCntr | Platform Configuration -> System Event Log -> PCIe Error Enabling -> PCIe Corrected Error Threshold Counter | oneof | Disable=0x00<br>Enable=0x01 |
| PcieErrInjActionTable | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> WHEA PCIe Error Injection Action Table | oneof | Disable=0x00<br>Enable=0x01 |
| PfdEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> PFD | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| pprType | EDKII Menu -> Socket Configuration -> Memory Configuration -> DDR PPR Type | oneof | PPR Disabled=0x00<br>Hard PPR=0x02<br>Soft PPR=0x01 |
| ProcessorMsrLockControl | EDKII Menu -> Socket Configuration -> Processor Configuration -> MSR Lock Control | oneof | Disable=0x00<br>Enable=0x01 |
| promoteMrcWarnings | EDKII Menu -> Socket Configuration -> Memory Configuration -> MRC Promote Warnings | oneof | Disable=0x00<br>Enable=0x01 |
| promoteWarnings | EDKII Menu -> Socket Configuration -> Memory Configuration -> Promote Warnings | oneof | Disable=0x00<br>Enable=0x01 |
| RasLogLevel | EDKII Menu -> Platform Configuration -> System Event Log -> RAS Log Level | oneof | None=0x00<br>MIN (BASIC_FLOW)=0x01<br>MID (BASIC_FLOW, FUNC_FLOW)=0x02<br>MAX (BASIC_FLOW, FUNC_FLOW, REG)=0x03 |
| RtRowSparing | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Runtime PPR / Row Sparing | oneof | Disable=0x00<br>Enable=0x01 |
| SmbusErrorRecovery | EDKII Menu -> Socket Configuration -> Processor Configuration -> SMBus Error Recovery | oneof | Disable=0x00<br>SMI=0x01<br>Error Pin=0x02 |
| spareErrTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Correctable Error Threshold | numeric | min=0x0<br>max=0x7FFF<br>step=0x1 |
| SpareIntSelect | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Spare Interrupt | oneof | Disable=0x00<br>SMI=0x01<br>Error Pin=0x02<br>CMCI=0x04 |
| SparePerRowTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> SW Per Row Threshold | numeric | min=0x1<br>max=0x7FFF<br>step=0x1 |
| SparePerBankTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> SW Per Bank Threshold | numeric | min=0x1<br>max=0x7FFF<br>step=0x1 |
| SystemErrorEn | EDKII Menu -> Platform Configuration -> System Event Log -> System Errors | oneof | Disable=0x00<br>Enable=0x01<br>Auto=0x02 |
| timeWindow | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Correctable Error Time Window | numeric | min=0x0<br>max=0x18<br>step=0x1 |
| TorCrashLogDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> TOR CrashLog Disable | oneof | No=0x00<br>Yes=0x01 |
| TriggerSWErrThEn | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Trigger SW Error Threshold | oneof | Disable=0x00<br>Enable=0x01 |
| UcnaCloakingEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Memory Corrected Error -> System Cloaking | oneof | Disable=0x00<br>Enable=0x01 |
| UncoreCrashLogDisable | Platform Configuration -> System Event Log -> Crash Log Enabling -> Uncore CrashLog Disable | oneof | No=0x00<br>Yes=0x01 |
| ViralEn | EDKII Menu -> Platform Configuration -> System Event Log -> Viral Status | oneof | Disable=0x00<br>Enable=0x01 |
| WheaErrorInjSupportEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> WHEA Error Injection Support | oneof | Disable=0x00<br>Enable=0x01 |
| WheaPcieErrInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> WHEA PCIe Error Injection Support | oneof | Disable=0x00<br>Enable=0x01 |
| WheaSupportEn | EDKII Menu -> Platform Configuration -> System Event Log -> WHEA Settings -> WHEA Support | oneof | Disable=0x00<br>Enable=0x01 |

## 5. OKS BIOS Knobs

Target platform: `DMR-AP`.

| Knob | Path | setupType | Allowed values / range |
|---|---|---|---|
| ADDDCEn | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> ADDDC Sparing | oneof | Disabled=0x0<br>Enabled=0x1 |
| DfxEnableCapInj | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory Dfx
Configuration -> CAP Error Injection Extra Cycle | oneof | Disable=0x0<br>Enable=0x1 |
| AttemptFastBoot | EDKII Menu -> Socket Configuration -> Memory Configuration -> Attempt Fast Boot | oneof | Disabled=0x0<br>Enabled=0x1 |
| AttemptFastBootCold | EDKII Menu -> Socket Configuration -> Memory Configuration -> Attempt Fast Cold Boot | oneof | Disabled=0x0<br>Enabled=0x1 |
| CeCloakingEn | EDKII Menu -> Platform Configuration -> System Event Log -> Corrected Error Cloaking | oneof | Disabled=0x0<br>Enabled=0x1 |
| CoreCrashLogDisable | EDKII Menu -> Platform Configuration -> System Event Log -> Crash Log Enabling -> Core CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| CorrMemErrEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Memory Corrected Error | oneof | Disabled=0x0<br>Enabled=0x1 |
| CpuCrashLogReArm | EDKII Menu -> Platform Configuration -> System Event Log -> Crash Log Enabling -> CPU Crashlog ReArm | oneof | Disabled=0x0<br>Enabled=0x1 |
| DfxEvMode | EDKII Menu -> IO Configuration -> DFX Global Configuration -> EV DFX Features | oneof | Disabled=0x0<br>Enabled=0x1<br>Auto=0x2 |
| DfxDisableCctBiosDone | EDKII Menu -> Security Dfx Configuration -> Disable BIOS_DONE programming | oneof | Disabled=0x0<br>Enabled=0x1<br>Auto=0x2 |
| DfxPmicIsolation | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory Dfx Configuration -> Pmic Failure Isolation | oneof | Disabled=0x0<br>Enabled=0x1<br>Auto=0x2 |
| DfxPoisonEn | EDKII Menu -> Platform Configuration -> System Event Log -> System Memory Poison | oneof | Disabled=0x0<br>Enabled=0x1 |
| DfxUnlockErrorInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> Unlock Error Injection DFX Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| EdpcEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO eDPC Support | oneof | Disabled=0x0<br>On Fatal Error=0x1<br>On Fatal and Non-Fatal Errors=0x2 |
| EdpcErrCorMsg | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO eDPC ERR_COR Message | oneof | Disabled=0x0<br>Enabled=0x1 |
| ElogIgnOptin | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> Ignore OS ELOG Opt-in | oneof | Disabled=0x0<br>Enabled=0x1 |
| ElogMultiError | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> Multi Error Section Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| EmcaCsmiEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> EMCA CMCI-SMI Morphing | oneof | Disabled=0x0<br>EMCA gen 2 CSMI=0x2 |
| EmcaCsmiThreshold | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> EMCA CMCI-SMI Threshold | numeric | min=0x0<br>max=0x7FFF<br>step=1 |
| EmcaEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> EMCA Error Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| EmcaMsmiEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> EMCA MCE-SMI Enable | oneof | Disabled=0x0<br>EMCA gen 2 - MSMI=0x2 |
| EnableTme | EDKII Menu -> Socket Configuration -> Security Configuration -> Memory Encryption (TME) | oneof | Disabled=0x0<br>Enabled=0x1 |
| ErrorCheckScrub | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> DDR5 ECS | oneof | Disabled=0x0<br>Enabled=0x1<br>Enable ECS with Result Collection=0x2 |
| ForcePprOnAllDramUce | EDKII Menu -> Socket Configuration -> Memory Configuration -> Force PPR On All Dram For UCE | oneof | Disabled=0x0<br>Enabled=0x1 |
| IioErrorEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO -> IBL Global Error Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| IoMcaEn | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> IIO MCA Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| LmceEn | EDKII Menu -> Platform Configuration -> System Event Log -> eMCA Settings -> LMCE Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| McaBankErrInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> Mca Bank Error Injection Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| McerrTriggerDisable | EDKII Menu -> Platform Configuration -> System Event Log -> Crash Log Enabling -> MCERR Trigger CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| MirrorMode | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Mirror Mode | oneof | Disabled=0x0<br>Full Mirror Mode=0x1 |
| OobRasSupport | EDKII Menu -> Platform Configuration -> System Event Log -> OOB RAS Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| OsNativeAerSupport | EDKII Menu -> Platform Configuration -> System Event Log -> IIO Error Enabling -> Os Native AER Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| partialmirrorsad0 | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Mirror TAD0 | oneof | Enabled=0x1<br>Disabled=0x0 |
| PartialMirrorUefi | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> UEFI ARM Mirror | oneof | Disabled=0x0<br>Enabled=0x1 |
| PartialMirrorUefiPercent | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> ARM Mirror percentage | numeric | min=0x0<br>max=0xFA0<br>step=1 |
| PatrolScrub | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Patrol Scrub | oneof | Disabled=0x0<br>Enable at End of POST=0x2 |
| PcieAerAdNfatErrEn | EDKII Menu -> Platform Configuration -> System Event Log -> PCIe Error Enabling -> PCIE AER Advisory Nonfatal Error | oneof | Disabled=0x0<br>Enabled=0x1 |
| PcieCorErrCntr | EDKII Menu -> Platform Configuration -> System Event Log -> PCIe Error Enabling -> PCIE Corrected Error Threshold Counter | oneof | Disabled=0x0<br>Enabled=0x1 |
| PfdEn | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Pfd | oneof | Disabled=0x0<br>Enabled=0x1<br>Auto=0x2 |
| pprType | EDKII Menu -> Socket Configuration -> Memory Configuration -> DDR PPR Type | oneof | PPR Disabled=0x0<br>Hard PPR=0x2<br>Soft PPR=0x1 |
| ProcessorMsrLockControl | EDKII Menu -> Socket Configuration -> Processor Configuration -> MSR Lock Control | oneof | Disabled=0x0<br>Enabled=0x1 |
| promoteMrcWarnings | EDKII Menu -> Socket Configuration -> Memory Configuration -> MRC Promote Warnings | oneof | Disabled=0x0<br>Enabled=0x1 |
| promoteWarnings | EDKII Menu -> Socket Configuration -> Memory Configuration -> Promote All Warnings | oneof | Disabled=0x0<br>Enabled=0x1 |
| RasLogLevel | EDKII Menu -> Platform Configuration -> System Event Log -> RAS Log Level | oneof | None=0x0<br>MIN (BASIC_FLOW)=0x1<br>MID (BASIC_FLOW, FUNC_FLOW)=0x2<br>MAX (BASIC_FLOW, FUNC_FLOW, REG)=0x3 |
| RtRowSparing | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Runtime PPR -> Row Sparing | oneof | Disabled=0x0<br>Enabled=0x1 |
| SmbusErrorRecovery | EDKII Menu -> Platform Configuration -> System Event Log -> Smbus Error Recovery | oneof | Disabled=0x0<br>SMI=0x1<br>Error Pin=0x2 |
| spareErrTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Correctable Error Threshold | numeric | min=0x0<br>max=0x7FFF<br>step=1 |
| SpareIntSelect | EDKII Menu -> Platform Configuration -> System Event Log -> Memory Error Enabling -> Spare Interrupt | oneof | Disabled=0x0<br>SMI=0x1<br>Error Pin=0x2<br>CMCI=0x4 |
| SparePerRowTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> SW Per Row Threshold | numeric | min=0x1<br>max=0x7FFF<br>step=1 |
| SparePerBankTh | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> SW Per Bank Threshold | numeric | min=0x1<br>max=0x7FFF<br>step=1 |
| SystemErrorEn | EDKII Menu -> Platform Configuration -> System Event Log -> System Errors | oneof | Disabled=0x0<br>Enabled=0x1<br>Auto=0x2 |
| TorCrashLogDisable | EDKII Menu -> Platform Configuration -> System Event Log -> Crash Log Enabling -> TOR CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| TriggerSWErrThEn | EDKII Menu -> Socket Configuration -> Memory Configuration -> Memory RAS Configuration -> Trigger SW Error Threshold | oneof | Disabled=0x0<br>Enabled=0x1 |
| UcnaCloakingEn | EDKII Menu -> Platform Configuration -> System Event Log -> UCNA Cloaking | oneof | Disabled=0x0<br>Enabled=0x1 |
| UncoreCrashLogDisable | EDKII Menu -> Platform Configuration -> System Event Log -> Crash Log Enabling -> Uncore CrashLog Disable | oneof | No=0x0<br>Yes=0x1 |
| ViralEn | EDKII Menu -> Platform Configuration -> System Event Log -> Viral Status | oneof | Disabled=0x0<br>Enabled=0x1 |
| WheaErrorInjSupportEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> WHEA Error Injection Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| WheaPcieErrInjEn | EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> Whea PCIE Error Injection Support | oneof | Disabled=0x0<br>Enabled=0x1 |
| WheaSupportEn | EDKII Menu -> Platform Configuration -> System Event Log -> Whea Settings -> WHEA Support | oneof | Disabled=0x0<br>Enabled=0x1 |

## 6. Generation Checklist

Before generating `UEFI_BIOS_knobs`, confirm:
- The target platform family is known.
- Every knob comes from the common baseline table, the selected platform table, or an explicit
	user/source override.
- Every value is legal for that knob setup type.
- Every RAK RAS case includes `RasLogLevel=0x3`, `DfxEvMode=0x1`,
  `DfxUnlockErrorInjEn=0x1`, and `DfxDisableCctBiosDone=0x1`.
- Do not fall back to legacy platform-split CScripts unlock knobs unless explicitly required by
  a newer user/source reference.
- EINJ knobs are included only for EINJ flows.
- Scenario knobs are included only when required by the recipe.
