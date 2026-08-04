# CScripts Functions Reference

Purpose: define the platform-specific CScripts calls that may be used directly inside generated RAK Python cases when CScripts / ITP is enabled.

This file is a whitelist. Do not use a CScripts function, module path, parameter, return value, or platform spelling that is not listed here or explicitly supplied by the user.

## 1. Core Rules

### 1.1 Direct RAK Calls

Listed CScripts functions are callable directly in the `CscriptsCommand` body with normal Python syntax.

Example for a BHS memory flow after topology variables have been derived:

```python
halt()
ei.mem.injectMemError(socket=inject_to_socket, channel=inject_to_channel, dimm=inject_to_dimm, rank=0, errType=error_type)
go()
```

Do not wrap listed CScripts calls in shell commands, external CScripts sessions, remote interactive consoles, or SSH commands unless the user explicitly requests that execution model.

### 1.2 Platform Isolation

Use only the CScripts calls for the selected platform family.

| Platform family | `target_platform` values | Required naming style |
|---|---|---|
| EGS | `SPR`, `EMR` | Flat forms such as `ei.injectMemError(...)`, `ei.injectPcieError(...)`, `ras.adddc_status_check(...)`. |
| BHS | `GNR-AP`, `GNR-SP`, `SRF-AP`, `SRF-SP`, `CWF-AP` | Namespaced camelCase forms such as `ei.mem.*`, `ei.iio.*`, `ei.sys.*`, `ras.mem.*`, `ras.iio.*`, `ras.sys.*`. |
| OKS | `DMR-AP` | Namespaced snake_case forms such as `ei.mem.inject_mem_error(...)`, `ei.iio.inject_pcie_error(...)`, `error.sys.clear_all_errors(...)`. |

Do not copy a function from another platform family because the name looks similar.

### 1.3 Topology Parameters

For topology-based injection, fill topology parameters from `hardware.*` fields defined in `Standard_RAK_Case_Format.md`.

Rules:
- DIMM memory targets use `hardware.dimm_1` unless a reference explicitly supports another object.
- PCIe targets use `hardware.pcie`; PEI card targets use `hardware.pei_card`.
- UPI targets use both `hardware.upi_1` and `hardware.upi_2`.
- System-address memory targets translate the address first and bind translated topology variables before register verification.
- Treat values such as `socket=0`, `port="1a"`, `mc=0`, `channel=0`, `dimm=0`, or `imh=0` as IVG examples, not generated defaults.

Platform memory targeting reminders:
- EGS: derive `inject_to_socket`, `inject_to_mc`, `inject_to_ch`, and `inject_to_dimm`; compute `inject_to_channel = inject_to_mc * 2 + inject_to_ch` for injection.
- BHS: derive `inject_to_socket`, `inject_to_mc`, `inject_to_ch`, and `inject_to_dimm`; BHS `inject_to_ch` must be `0`; compute `inject_to_channel = inject_to_mc * 1 + inject_to_ch`.
- EGS and BHS RAK hardware configuration does not provide rank selection; use `rank=0` unless the source recipe explicitly supplies another rank.
- OKS: derive `inject_to_socket`, `inject_to_imh`, `inject_to_mc`, `inject_to_subch`, and `inject_to_dimm`.

### 1.3.1 Topology Variable Naming

Use topology variable names that are explicit and stable across generated cases.

Recommended topology-variable style:

| Logical field | Preferred variable name |
|---|---|
| socket | `inject_to_socket` |
| imh | `inject_to_imh` |
| mc | `inject_to_mc` |
| subchannel | `inject_to_subch` |
| channel | `inject_to_ch` |
| dimm/slot | `inject_to_dimm` |
| pcieg | `inject_to_pcieg` |
| pxp | `inject_to_pxp` |
| root port | `inject_to_port` |

Rules:
- Generate case commands with `inject_to_*` topology variables.
- Prefer node aliases for long register paths only at stable parent scopes: bind once to the channel, port, IP block, or register-block scope, then append concrete registers and fields when showing or asserting.
- Do not bind a `*_node` alias directly to a concrete leaf register. RAK path handling may not preserve equivalent behavior when a specific register object is replaced by an alias.

Node-alias pattern:

```python
mem_node = sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}
RAK_ASSERT_CSR(mem_node.mcdata.imc0_mc_status_shadow.uc, 0x0)
```

```python
port_node = sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}
RAK_ASSERT_CSR(port_node.rooterrsts.cer, 0x1)
```

Invalid leaf-register alias pattern:

```python
smisrclog_node = sv.socket{inject_to_socket}.imh{inject_to_imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem.reg_cr_smisrclog
smisrclog_node.show()
```

Valid parent-scope alias pattern:

```python
rasip_mem_handler_node = sv.socket{inject_to_socket}.imh{inject_to_imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem
rasip_mem_handler_node.reg_cr_smisrclog.show()
RAK_ASSERT_CSR(rasip_mem_handler_node.reg_cr_smisrclog.sidebandvalid, 0x1)
```

### 1.4 Halt and Resume

If a CScripts flow requires halted/probe state, call `halt()` before the CScripts function. Perform transient register reads and assertions before `go()` when BIOS, SMI, firmware, OS recovery, or device recovery may clear status.

### 1.5 Normalization

If an IVG spelling differs from the platform user guide, use the normalization notes in this file.

Rules:
- Correct obvious typos such as `toplogy` to `topology`.
- Preserve IVG-only aliases when reproducing that IVG flow exactly.
- Do not infer parameters from function names. Use only listed parameters or parameters explicitly supplied by the source recipe.

## 2. EGS CScripts Whitelist

EGS uses flat module functions. Do not convert EGS calls to BHS/OKS namespaced forms.

### 2.1 EGS Error Injection and Setup

| Function | Use | Parameters / notes |
|---|---|---|
| `ei.clearMemInjectors(...)` | Clear memory injector state. | `socket`, `hbm`, `mc`, `channel`. |
| `ei.find_2LM_alias_addr(...)` | Find 2LM alias address for memory targeting. | `sys_addr`. |
| `ei.injectCMDParity(...)` | Inject DDR command parity error. | `socket`, `mc` / `channel` / `sub_ch`, `numErrors`. |
| `ei.injectDmiError(...)` | Inject inbound DMI receiver error. | `errType` such as `ce`, `uce`, or `both`. |
| `ei.injectIIOtcparError(...)` | Inject IIO traffic-controller parity error. | `socket`, `iou`, `direction`, `errType`. |
| `ei.injectI3CControllerError(...)` | Inject I3C controller error. | `socket`, `lpss`, `errType`; IVG uses `errType=0x13`. |
| `ei.injectMemError(...)` | Main EGS memory CE/UCE/SDDC/ADDDC/mirror injection primitive. | Address-based or `socket`, absolute `channel`, `sub_channel`, `dimm`, `rank`, `sub_rank`, `bank_group`, `bank`, `errType`. |
| `ei.injectPcieError(...)` | Inject PCIe CE/UCE on root port. | `socket`, `port`, `errType`, optional `severity`. |
| `ei.injectUpiError(...)` | Inject UPI CRC/data-link error. | `socket`, `port`, `num_crcs`, `direction`, `laneNum`. |
| `ei.injectUpiLLError()` | Inject UPI link-layer error. | IVG no-arg form; call after injector lock reset when the recipe requires it. |
| `ei.injUpiDataLinkFailover(...)` | Exercise UPI data-link failover. | `socket`, `port`, `direction`, `dataLanes`. |
| `ei.memDevs(...)` | Configure DRAM device masks for memory injection. | `dev0`, `dev0msk`, `dev1`, `dev1msk`. |
| `ei.resetInjectionLockCheck()` | Reset injection lock check. | IVG-used spelling. |
| `ei.resetInjectorLockCheck(...)` | Reset injector lock check. | User-guide spelling; supports `lock790`. |

### 2.2 EGS Discovery, Decode, and Error Utilities

| Function | Use | Parameters / notes |
|---|---|---|
| `ei.sa2da_table(...)` | Translate system address range to DDR address information. | `start_addr`, `end_addr`, `step_size`. |
| `ei.show_ecc_mode(...)` | Print ECC mode per channel. | `socket`, `mc`, `ch`. |
| `ei.show_pxp_ieh_map()` | Show SPR IIO PXP/IEH/internal PCI bus map. | No arguments. |
| `error.check_ieh_errors(...)` | Check IEH machine-check errors. | `socket_id`, `ip_list`, `errors_only`. |
| `error.check_machine_check_errors(...)` | Check MCA machine-check state. | `socket_id`, `errors_only`. |
| `error.check_mem_errors(...)` | Check memory machine-check errors. | `socket_id`, `ip_list`. |
| `error.check_upi_errors(...)` | Check UPI machine-check errors. | `socket_id`, `ip_list`. |
| `error.clearAllErrors()` | Clear CPU/PCI/PCH error state. | No arguments. |
| `error.clearPciErrors(...)` | Clear PCI errors. | `bus`, `dev`, `fnc`. |
| `error.manualMcaDecode()` | Decode MCA status/address/misc interactively. | Interactive MCA inputs; avoid in fully automated cases unless the recipe requires manual flow. |
| `mc.addTran(address=None)` | Translate system address to DDR5/rank topology. | Address or interactive menu mode. |
| `mc.dimminfo(...)` | Print memory subsystem and DIMM/SPD information. | `socket`, `skipSPD`. |
| `mc.dimminfoNoSPD(...)` | Print memory subsystem without SPD checks. | `socket`. |
| `pci.config(...)` | Read/write PCI config space. | `bus`, `dev`, `fnc`, `offset`, `value`, `seg`. |
| `pci.decode(...)` | Decode PCI config/capability information. | `bus`, `dev`, `fnc`, `seg`. |
| `pci.dump(bus=None, dev=None, fnc=None, seg=0)` | Dump PCI configuration data. | May be scoped or interactive depending on recipe. |
| `pcie.port_map()` | Display PCIe port mapping. | No arguments. |
| `pcie.topology(...)` | Print PCIe topology. | `socket`. |
| `ras.adddc_status_check(...)` | Dump ADDDC status/control registers. | `socket`, `mc`, `ch`. |
| `ras.check_config_LeakyBucket(...)` | Check PCIe leaky bucket configuration. | `socket`, `port`. |
| `ras.retry_rd_log_decode(...)` | Decode retry read error logs. | `socket`, `mc`, `ch`, `subch`. |
| `ras.showBankSparing(...)` | Show bank sparing state. | `socket`, `hbm`, `mc`, `ch`, `pch`. |
| `upi.printErrors()` | Print UPI CE/UCE error state. | No arguments. |
| `upi.topology(...)` | Print UPI topology. | `socket`. |

### 2.3 EGS CXL Helpers

| Function | Use | Parameters / notes |
|---|---|---|
| `cxl.cxl_cmem_error_check(socket, port)` | Check or dump CXL cache/memory error information. | `socket`, `port`; IVG also shows no-arg current-context use. |
| `cxl.cxl_dp_rcrb_error_dump(socket=None, port=None)` | Dump downstream-port RCRB/AER error registers. | `socket`, `port`; IVG also shows current-context use. |
| `cxl.cxl_ieh_error_dump(socket=None, port=None)` | Dump CXL IEH error registers. | `socket`, `port`; IVG also shows no-arg use. |
| `cxl.cxl_iep_dvsec_show(socket, port)` | Dump CXL RCiEP DVSEC registers. | `socket`, `port`. |
| `cxl.get_cxl_rcrb_bar(socket, port)` | Return CXL RCRB BAR. | `socket`, port string such as `"pxp3.pcieg5.port0"`. |

### 2.4 EGS Normalization Notes

| IVG spelling or object | Use / resolution |
|---|---|
| `ei.resetInjectionLockCheck(...)` | Valid IVG-used spelling. Prefer `ei.resetInjectorLockCheck(...)` for user-guide spelling unless reproducing the IVG flow exactly. |
| `pcie.toplogy(...)` | Typo. Use `pcie.topology(...)`. |
| `ei.injectI3CControllerError(...)` | Valid EGS IVG-used function. Use only EGS table parameters. |
| `ei.injectUpiLLError(...)` | Valid EGS IVG-used function. Do not replace with `ei.injectUpiError(...)` unless the recipe says they are interchangeable. |
| `ras.showBankSparing(...)` | Valid EGS IVG-used function. |
| `cxl.cxl_dp_rcrb_error_dump(...)`, `cxl.cxl_ieh_error_dump(...)`, `cxl.cxl_iep_dvsec_show(...)`, `cxl.cxl_cmem_error_check(...)`, `cxl.get_cxl_rcrb_bar(...)` | Valid EGS IVG CXL helpers. Use CXL port context from topology or the recipe. |
| `upi.upi0...show()`, `upi.upi0...getspec()`, `upi.upis...show()` | Register/object access methods, not top-level functions. Use exact paths only when deterministic. |

## 3. BHS CScripts Whitelist

BHS uses namespaced camelCase modules. Do not convert BHS calls to EGS flat forms or OKS snake_case forms.

### 3.1 BHS IIO, CXL, and PCIe

| Function | Use | Parameters / notes |
|---|---|---|
| `cxl.addMap(...)` | Display CXL system address map. | No required args in IVG-style discovery flows. |
| `cxl.addTran(...)` | Return address mapping for CXL port/device context. | Use only when CXL address or port context is provided. |
| `cxl.capabilities(socket=None, port=None)` | Return/display CXL/PCIe capability objects. | `socket`, `port`; IVG typo `cxl.capabilties` normalizes here. |
| `cxl.cxl_cmem_err_check(socket, port)` | Dump CXL cache/memory errors. | `socket`, port string such as `"1a"`. |
| `cxl.cxl_device_command(...)` | Execute CXL device command sequence. | Use opcode/command fields from the recipe. |
| `cxl.cxl_ieh_error_dump(socket, port)` | Dump IEH local error registers for CXL path. | `socket`, port string such as `"1a"`. |
| `cxl.topology(socket=None)` | Display PCIe/CXL topology. | `socket` or no args. |
| `ei.iio.injectDSAError(socket, imh, dsa, err_type='correctable', bar=0)` | Inject DSA error. | Use DSA target from recipe/topology. |
| `ei.iio.injectPcieError(socket, port, errType=None, severity=None)` | Inject inbound PCIe error. | `socket`, port string, `errType`, optional `severity`. |
| `ei.iio.injectS3MError()` | Inject S3M/IIO error. | IVG no-arg form. |
| `ei.iio.injectUPIDataLinkFailover(socket=0, port=0, direction=0, data_lanes=0xF, port_reset=1)` | Exercise UPI data-link failover through IIO EI path. | Replace example socket/port with `hardware.upi_*` values. |
| `ei.iio.injectUPIError(socket=0, port=0, num_crcs=2, stop_inj=False, check_error=True)` | Inject UPI CRC/data-link error. | IVG may use `stop_inject` and `check_error`; use recipe spelling when supplied. |
| `ei.iio.injectURError(bus, dev, fnc, seg, mode='mem', access='read', severity='nonfatal')` | Inject unsupported-request error. | Use bus/dev/fnc/seg from recipe or discovery. |
| `ei.iio.showIehMapping()` | Display IEH mapping. | No arguments. |
| `ras.iio.check_config_leakybucket(...)` | Check PCIe leaky bucket configuration. | `socket`, `port`. |
| `pci.config(...)` | Read/write PCI config space. | `bus`, `dev`, `fnc`, `offset`, `value`, `seg`. |
| `pci.decode(...)` | Decode PCI capability/configuration. | `bus`, `dev`, `fnc`, `seg`. |
| `pcie.port_map()` | Display PCIe port number/name map. | No arguments. |
| `pcie.topology(socket=None)` | Print PCIe topology. | `socket` or no args. |

### 3.2 BHS Memory

| Function | Use | Parameters / notes |
|---|---|---|
| `ei.mem.clearMemInjectors(socket=0)` | Clear memory injector status. | `socket`; optional memory target fields when scoped. |
| `ei.mem.injectCMDParity(socket=0, mc=0, ch=0)` | Inject command parity error. | `socket`, `mc`, `channel`/`ch`, optional `hbm`, `sub_ch`, `numErrors`. |
| `ei.mem.injectCxlError(socket, port, error_type, Severity='nonfatal', Verbose=True)` | Inject CXL cache/memory error. | `socket`, port string, `error_type`, `Severity`, `Verbose`. |
| `ei.mem.injectMemError(addr=None, socket=None, channel=None, sub_channel=None, dimm=None, rank=None, sub_rank=None, bank_group=None, bank=None, errType='ce', immInject=True, immConsume=True, oneInjection=True, PatrolConsume=False, verbose=True, ps_ch=0)` | Inject memory error. | Address-based or socket/channel/dimm/rank targeting; `errType` `ce` or `uce`. |
| `ei.mem.injectPMICError(socket=0, mc=0, channel=0, slot=0, raw_value=0x82, verbose=True)` | Inject PMIC error. | `socket`, `mc`, `channel`, `slot`, `raw_value`, `verbose`. |
| `ei.mem.memDevs(dev0=None, dev0msk=None, dev1=None, dev1msk=None)` | Display/set memory device parameters. | Use masks from recipe; do not invent masks. |
| `ei.mem.showMemInjectors(socket=0)` | Show memory injector status. | `socket` or no args. |
| `ras.mem.adddc_status_check(...)` | Display ADDDC status/control registers. | `socket`, `mc`, `ch`. |
| `ras.mem.clearPMICErrorStatus(socket=None, mc=None, channel=None, slot=None)` | Clear PMIC error status. | `socket`, `mc`, `channel`, `slot`. |
| `ras.mem.PMICErrorStatus(socket=None, mc=None, channel=None, slot=None)` | Get PMIC error status. | `socket`, `mc`, `channel`, `slot`. |
| `ras.mem.memCorrEccCount(...)` | Display memory correctable ECC count. | `socket`, `mc`, `ch`. |
| `ras.mem.sa2da_table(start_addr, end_addr, step_size=1)` | Translate system address to DDR address. | `start_addr`, `end_addr`, `step_size`. |
| `ras.mem.show_ecc_mode(...)` | Print ECC mode table. | `socket`, `mc`, `ch`. |
| `ras.mem.show_ecc_modes(socket=None, mc=None, ch=None)` | IVG spelling variant for ECC mode display. | Prefer `show_ecc_mode(...)` unless preserving source flow. |
| `mc.addTran(address=None)` | System address translation. | Address or interactive mode. |
| `mc.dimminfoNoSPD(socket=None)` | Print memory subsystem information without SPD check. | `socket` or no args. |

### 3.3 BHS System Error and Error Utilities

| Function | Use | Parameters / notes |
|---|---|---|
| `ei.injectThreeStrike(socket=0, verbose=True)` | Inject three-strike error. | IVG also uses `ei.sys.injectThreeStrike(...)`. |
| `ei.sys.AMEI(verbose=True, validation=True)` | Inject MCA bank spoofing/error event through AMEI. | IVG also shows positional `ei.sys.AMEI(True, True)`. |
| `ei.sys.injectI3CError(socket=0, spdi3c=0, err_type=0x13)` | Inject I3C error. | IVG uses `0x13` for HALT error. |
| `ei.sys.injectIERR()` | Inject IERR. | No args in IVG example. |
| `ei.sys.injectMCERR(verbose=True)` | Inject MCERR. | IVG example uses no socket args. |
| `ei.sys.injectThreeStrike(socket=0, verbose=True)` | Inject three-strike error through system EI path. | `socket`, `verbose`. |
| `ei.utils.checkInjectorLockCheck()` | Check injector lock state. | IVG may shorten this to `ei.utils.checkInjectorLock`. |
| `ei.utils.enter_smm()` | Enter SMM entry-break/halt mode. | No arguments. |
| `ei.utils.exit_smm()` | Exit SMM entry-break/resume mode. | No arguments. |
| `ei.utils.resetInjectorLockCheck()` | Reset injector lock check / MSR lock behavior. | No args in IVG examples. |
| `error.check_ieh_errors(...)` | Check IEH MCA errors. | `socket_id`, `ip_list`. |
| `error.check_machine_check_errors(...)` | Check MCA state. | `socket_id`, `errors_only`. |
| `error.check_mem_errors(...)` | Check memory MCA errors. | `socket_id`, `ip_list`. |
| `error.clearAllErrors()` | Clear processor errors. | No arguments. |
| `error.crashdump_summary(...)` | Decode crashdump JSON summary. | `file`, `text_file`. |
| `error.manualMcaDecode()` | Decode MCA error values interactively. | Avoid in automated cases unless recipe requires manual flow. |
| `ras.sys.dump_EMCA2_logs(baseAddress=None)` | Print decoded eMCA2 eLOG table. | `baseAddress` only when recipe supplies one. |
| `ras.sys.viral_config_check(skip_ras_lvl_check=False)` | Display viral configuration. | Optional `skip_ras_lvl_check`. |
| `ras.sys.viral_error_check(skip_ras_lvl_check=False)` | Display viral error log. | Optional `skip_ras_lvl_check`. |
| `upi.printErrors()` | Print UPI error information. | No arguments. |

### 3.4 BHS Normalization Notes

| IVG spelling or object | Use / resolution |
|---|---|
| `cxl.capabilties(...)`, `cxl.toplogy(...)`, `pcie.toplogy(...)` | Typos. Use `cxl.capabilities(...)`, `cxl.topology(...)`, or `pcie.topology(...)`. |
| `ei.utils.clearMemInjectors` | Normalize to `ei.mem.clearMemInjectors(...)`. |
| `ei.utils.checkInjectorLock` | Normalize to `ei.utils.checkInjectorLockCheck()` unless reproducing exact source text. |
| `ei.mem.injectMemError(...)`, `ei.mem.injectPMICError(...)` | Valid BHS IVG-used functions. |
| `ei.iio.injectDSAError(...)`, `ei.iio.injectS3MError(...)`, `ei.iio.injectUPIDataLinkFailover(...)`, `ei.iio.injectUPIError(...)`, `ei.iio.injectURError(...)` | Valid BHS IVG-used functions. |
| `ei.sys.AMEI(...)`, `ei.sys.injectI3CError(...)`, `ei.sys.injectIERR(...)`, `ei.sys.injectMCERR(...)`, `ei.sys.injectThreeStrike(...)`, `ei.injectThreeStrike(...)` | Valid BHS IVG-used functions. |
| `ras.mem.show_ecc_modes(...)` | IVG spelling variant. Prefer `ras.mem.show_ecc_mode(...)` when the flow does not require preserving the variant. |
| `ras.corerrsts.show()`, `ras.errctl.show()`, `upi.upi*.upi_regs.*.show()`, `upi.upi*.upi_regs.*.getspec()`, `s3m.*.showfields()` | Register/object access methods, not top-level functions. Use only with exact BHS register paths and deterministic checks. |

## 4. OKS CScripts Whitelist

OKS / DMR-AP uses namespaced snake_case APIs. Do not convert OKS calls to EGS flat forms or BHS camelCase forms.

For OKS cases that use CScripts functions or CScripts-based verification, `RAK_Instructions.md` makes `cscripts.services.activate_cli_logging(True)` mandatory. If the case changes BIOS knobs with `RAK_UEFI_KNOBS(UEFI_BIOS_knobs)` or another supported BIOS-knob flow, this call MUST be placed after that BIOS-knob flow and before the first OKS CScripts injection, register access, or CScripts-based verification. Do not place it at the start of the script before BIOS-knob changes. If no BIOS-knob flow exists, place it before the first OKS CScripts action.

### 4.1 OKS IIO, PCIe, and CXL

| Function | Use | Parameters / notes |
|---|---|---|
| `cxl.add_map(verbose=False, get_rawdata=False, force_scan=False, add_cedt=False)` | Display CXL HDM/system address map. | Use options only when recipe requires them. |
| `cxl.add_tran(direction=None, address=None, socket=None, port_id=None, ...)` | Translate CXL address/map information. | Use only in explicit CXL address-based flows. |
| `cxl.capabilities(socket=None, port_id=None, force_scan=True)` | Return CXL/PCIe capability access object. | IVG typo `cxl.capabilties` normalizes here. |
| `cxl.cxl_cmem_error_check(socket=None, port_id=None, dp=True)` | Check CXL RAS capability CE/UCE registers. | IVG examples may show older positional forms. |
| `cxl.topology(socket=None, filterEn=None, vertical=None)` | Show PCIe/CXL devices and topology. | IVG typo `cxl.toplogy` normalizes here. |
| `ei.iio.inject_cxl_error(socket=None, port_id=None, error_type=None, severity=None, mem_address=None, consume_error=True)` | Inject CXL.io/CMEM error. | `port_id` may be short form such as `"3a"` or full topology form. |
| `ei.iio.inject_pcie_error(socket=None, port_id=None, error_type=None, severity=None)` | Inject inbound PCIe/CXL.io receiver error. | IVG old spelling `ei.iio.injectPcieError` normalizes here. |
| `ei.iio.show_rasip_mapping()` | Print I/O instance to RASIP mapping. | No arguments. |
| `error.iio.check_pcie_errors(pcie_port=None, errors_only=True)` | Check PCIe error registers. | IVG old flat form normalizes here. |
| `error.sys.check_rasip_errors(io_stack=None, errors_only=True)` | Check RASIP errors. | `io_stack` or no args. |
| `pcie.port_map()` | Show I/O configuration port mapping. | No arguments. |
| `pcie.topology(socket=None, vertical=True)` | Display CPU PCIe topology. | IVG typo `pcie.toplogy` normalizes here. |
| `pci.config(bus, dev, fnc, offset, value=None, seg=0)` | Read/write PCI config space. | `bus`, `dev`, `fnc`, `offset`, `value`, `seg`. |

### 4.2 OKS Memory

| Function | Use | Parameters / notes |
|---|---|---|
| `ei.mem.inject_mem_error(address=None, socket=None, imh=None, mc=None, subch=0, dimm=0, rank=0, sub_rank=0, bank=0, bank_group=None, row=None, column=0, pseudo_channel=0, error_type='ce')` | Inject ECC memory error by core address or DRAM location. | OKS topology is `socket -> imh -> mc -> subch -> dimm`. |
| `ei.mem.inject_mem_error_multi_addr(addr_list, error_type='ce', ...)` | Inject ECC memory error on multiple addresses. | Use only when scenario explicitly requires multi-address injection. |
| `error.mem.check_mem_errors(controller=None, errors_only=True)` | Check memory error registers. | IVG variant `error.mem.check_memory_errors` normalizes here. |
| `mc.add_map(map_type='all')` | Show system address map tables. | `map_type` values include `all`, `dimm_config`, `mmio`, `dram`, `cxl` when recipe requires them. |
| `mc.add_tran(address=None)` | Translate system address to DRAM address, or reverse-translate a DRAM tuple. | Prefer for OKS memory-address-based flows before register assertions; hardcoded core-address flows may use `mc.add_tran({'core_addr': SystemAddress})`. |
| `ras.mem.adddc_status_check(socket=None, imh=None, mc=None, subch=None)` | Display ADDDC control/status for selected memory slice. | Use OKS topology fields. |
| `ras.mem.show_ecc_mode(socket=None, imh=None, mc=None, subch=None)` | Print ECC mode table. | IVG also uses no-arg form. |

### 4.3 OKS System Error and Error Utilities

| Function | Use | Parameters / notes |
|---|---|---|
| `ei.sys.inject_dsa_error(socket, dsa, err_type='cor', bar=0, restore=False)` | Inject DSA accelerator UR/error. | Use DSA target from recipe/topology. |
| `ei.sys.inject_ierr(socket=0, die=0, method='three_strike')` | Inject IERR through OKS system-EI path. | IVG may use MC/subch-scoped forms and `method='ierr'`. |
| `ei.sys.inject_mcerr(socket=None, imh=None, mc=None)` | Inject MCERR. | IVG old spelling `ei.uncore.inject_mcerr` normalizes here. |
| `ei.utils.reset_injector_lock_check(lock790=True)` | Reset injector lock check state. | Do not use for OKS unlock when `DfxUnlockErrorInjEn=0x1` is present. If a recipe or user explicitly requires this call, write it as `ei.utils.reset_injector_lock_check(True)`; never emit the no-argument form. |
| `error.sys.check_machine_check_errors(socket=None, bank=None, errors_only=True, ...)` | Check MCA machine-check errors. | Pass only arguments needed by the scenario. |
| `error.sys.clear_all_errors()` | Clear memory, PCIe, RASIP, and PCI errors. | IVG old flat form normalizes here. |

### 4.4 OKS Release-Note / IVG Additions

These additions are confirmed by OKS IVG or user-guide notes, but signatures may require the full source reference. Do not invent parameters from names alone.

| Function | Use rule |
|---|---|
| `ei.iio.inject_s3m_error(...)` | Use only with recipe-provided parameters. |
| `ei.iio.inject_ur_error(...)` | Use only with recipe-provided parameters. |
| `ei.sys.inject_i3c_error(...)` | Use only with recipe-provided parameters. |
| `ei.sys.inject_three_strike(...)` | Use only with recipe-provided parameters. |
| `ei.mem.clear_mem_injectors(...)` | Use only with recipe-provided parameters. |
| `ei.mem.show_mem_injectors(...)` | Use only with recipe-provided parameters. |
| `ras.mem.device_sparing_harasser(...)` | Use only with recipe-provided parameters. |
| `ras.mem.is_ddr_addr_in_vls(...)` | Use only with recipe-provided parameters. |
| `ras.iio.trigger_sw_dpc(...)` | Use only with recipe-provided parameters. |
| `error.crashdump_summary(...)` | Use only with recipe-provided parameters. |

### 4.5 OKS Memory `error_type` Values

Use these values only when the selected OKS memory flow requires the matching behavior.

| Scenario | Accepted values |
|---|---|
| Consume correctable | `consume_correctable`, `ce`, `correctable` |
| Consume uncorrectable | `consume_uncorrectable`, `uc`, `uncorrectable` |
| Inject correctable only | `inject_correctable`, `inj_ce`, `inj_correctable` |
| Inject uncorrectable only | `inject_uncorrectable`, `inj_uc`, `inj_uncorrectable` |
| Arm correctable only | `arm_correctable`, `arm_ce`, `only_arm_ce` |
| Arm uncorrectable only | `arm_uncorrectable`, `arm_uc`, `only_arm_uc` |
| Patrol consume correctable | `consume_patrol_correctable`, `patrol_ce`, `patrol_correctable` |
| Patrol consume uncorrectable | `consume_patrol_uncorrectable`, `patrol_uc`, `patrol_uncorrectable` |
| Mirror consume correctable | `consume_mirror_correctable`, `mirror_ce`, `mirror_correctable` |
| Mirror consume uncorrectable | `consume_mirror_uncorrectable`, `mirror_uc`, `mirror_uncorrectable` |
| Mirror failover | `consume_mirror_failover`, `mirror_failover` |
| Continuous consume correctable | `consume_continuous_correctable`, `continuous_ce`, `cont_ce` |
| Continuous consume uncorrectable | `consume_continuous_uncorrectable`, `continuous_uc`, `cont_uc` |

### 4.6 OKS Normalization Notes

| Legacy spelling / source | Use / resolution |
|---|---|
| `ei.iio.injectPcieError(...)` | Old camelCase IVG spelling. Use `ei.iio.inject_pcie_error(...)`. |
| `ei.uncore.inject_mcerr(...)` | Old IVG spelling. Use `ei.sys.inject_mcerr(...)`. |
| `error.check_pcie_errors(...)` | Old flat IVG spelling. Use `error.iio.check_pcie_errors(...)`. |
| `error.check_rasip_errors(...)` | Old flat IVG spelling. Use `error.sys.check_rasip_errors(...)`. |
| `error.clear_all_errors(...)` | Old flat IVG spelling. Use `error.sys.clear_all_errors(...)`. |
| `error.mem.check_memory_errors(...)` | IVG spelling variant. Use `error.mem.check_mem_errors(...)`. |
| `cxl.cxl_cm_err_check(...)` | IVG spelling variant. Use `cxl.cxl_cmem_error_check(...)`. |
| `mc.addTran(...)` | Older camelCase spelling. Use `mc.add_tran(...)`. |
| `cxl.capabilties(...)`, `cxl.toplogy(...)`, `pcie.toplogy(...)` | Typos. Use `capabilities(...)` and `topology(...)`. |
| `ras.corerrsts.show()`, `ras.show()` | Register/object access methods, not top-level functions. Use only with exact OKS register paths and deterministic checks. |

## 5. Generation Checklist

Before generating CScripts calls from this file, confirm:
- CScripts / `ITP_enable=true` is declared when required.
- The selected platform family matches the function table.
- OKS CScripts cases include `cscripts.services.activate_cli_logging(True)` as required by `RAK_Instructions.md`.
- Topology arguments come from `hardware.*` or from translated hardcoded addresses.
- IVG example constants are not copied as generated defaults.
- Spelling variants and typos are normalized according to the platform notes.
- Interactive utilities are avoided in Automation-Level 3 cases unless the source recipe explicitly requires manual interaction.
- Assertions and register reads that may be cleared by recovery happen before `go()`.
- No function, parameter, return object, or expected side effect is inferred from a similar platform.
