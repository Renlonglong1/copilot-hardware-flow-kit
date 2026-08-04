# Standard RAK Case Reference

Purpose: provide compact example patterns extracted from historical EGS, BHS, and OKS RAK cases.

This file is an examples-only reference. It is not the authoritative rule source for layout, APIs, BIOS knobs, CScripts calls, register paths, or generated-case format.

## 1. Reference Priority

When generating or reviewing a RAK case, use references in this order:

1. User request and source recipe.
2. `RAK_Instructions.md`.
3. `Standard_RAK_Case_Format.md`.
4. `RAK_API_Reference.md`.
5. `CScript_Functions_Reference.md`.
6. `BIOS_Knobs_Mapping.md`.
7. `EGS_BHS_OKS_Register_Path_Mapping.md`.
8. This file.

Rules:
- Use this file only to understand scenario flow and validation intent.
- Do not copy a full historical case from this file into a generated case.
- Do not let an example in this file override a whitelist or platform rule in another reference file.
- If an example is missing a required modern rule, add the rule from the authoritative reference.
- If an example has an unknown exact expected value, use a non-zero check instead of inventing a value.

## 2. Case Pattern Index

| Platform family | Scenario | Reusable intent |
|---|---|---|
| EGS | ADDDC memory CE | Enable ADDDC, inject repeated CE, verify retry log, sparing state, and ADDDC status. |
| EGS | PCIe eDPC CTO | Verify clean PCIe AER/DPC state, inject UCE, verify DPC trigger, resume, verify clear/recovery. |
| EGS | UPI CE / link retry | Inject UPI CRC, verify `bios_kti_err_st`, collect trace/dmesg/serial evidence. |
| BHS | ADDDC memory CE | Same ADDDC intent as EGS, but use BHS memory paths and `ei.mem.*` APIs. |
| BHS | PCIe eDPC CTO | Same AER/DPC intent as EGS, but derive `{io}` with `pxp_io_map` and use BHS PCIe paths. |
| BHS | UPI CE / link retry | Derive `{io}` with `upi_io_map`, verify `upi_regs.bios_kti_err_st`, collect logs. |
| BHS | S3M / IEH | Inject S3M unsupported request, verify SAT IEH/S3M registers, then resume and verify clear state. |
| OKS | Memory CSMI threshold | Verify RASIP CSMI threshold config, inject repeated CE, verify SMI count changes at threshold. |
| OKS | Memory CE cloaking | Enter SMM for MSR check, inject CE, verify no SMM error handler flow and unchanged SMI count. |
| OKS | PCIe CE/UCE | Use OKS PCIe path base, verify AER fields and RASIP/IOMCA evidence. |
| OKS | PCIe CE threshold | Inject CE repeatedly without clearing, verify `corerrcnt` reaches threshold and clears after handling. |
| OKS | Hardcoded address memory CE | Preserve hardcoded address, translate it, bind topology, inject to address, verify translated target. |

## 3. Standard Flow Pattern

Use this flow unless the source recipe explicitly requires a different order:

```python
if not RAK_CHECK_OS_READY():
    itp.resettarget()

RAK_WAIT_SYSTEM_STATUS(SYS_STATUS.OS.OS_READY, timeout=1000)

# Use these only when the case defines HW_INFO.
RAK_SHOW_HWCONFIG()
RAK_CHECK_HWCONFIG(HW_INFO)
RAK_UEFI_KNOBS(UEFI_BIOS_knobs)

RAK_DELAY(15)
RAK_WAIT_SYSTEM_STATUS(SYS_STATUS.OS.OS_READY, timeout=1000)
```

When the case verifies post-injection dmesg and needs a clean baseline, clear dmesg before injection:

```python
RAK_CMD_REMOTE("sudo dmesg -C")
```

For OKS / DMR-AP CScripts flows only, this call is mandatory. If the example changes BIOS knobs, it MUST be placed after the BIOS-knob flow and before the first OKS CScripts action:

```python
cscripts.services.activate_cli_logging(True)
```

Rules:
- For EGS examples, `itp.pulsepwrgood()` may appear in old cases; use the reset method required by the selected platform and recipe.
- For BHS examples, `itp.resettarget()` is the common historical reset pattern.
- For OKS CScripts examples, `cscripts.services.activate_cli_logging(True)` is mandatory. When the example changes BIOS knobs, it MUST be placed after the BIOS-knob flow and before the first OKS CScripts injection, register access, or CScripts-based verification; do not place it at the start of the script before BIOS-knob changes.
- Load `acpi_extlog` only when the case analyzes OS extended error logs.
- Keep every generated `RAK_ASSERT_CSR(...)` call on one physical line.

## 4. Memory Patterns

### 4.1 EGS ADDDC CE

Target extraction:

```python
inject_to_socket = int(hardware.dimm_1.socket)
inject_to_mc = int(hardware.dimm_1.mc)
inject_to_ch = int(hardware.dimm_1.channel)
inject_to_dimm = int(hardware.dimm_1.slot)
inject_to_channel = inject_to_mc * 2 + inject_to_ch
```

Injection pattern:

```python
halt()
ei.memDevs(dev0=1, dev0msk=0x3, dev1msk=0x0)
for threshold in range(0, max_threshold):
    halt()
    ei.injectMemError(socket=inject_to_socket, channel=inject_to_channel, sub_channel=0, dimm=inject_to_dimm, rank=0, sub_rank=0, bank_group=0, bank=0, errType='ce', showInjectors=False, showErrorRegs=False)
    go()
    RAK_DELAY(15)
```

Verification pattern:

```python
halt()
sv.socket{inject_to_socket}.uncore.memss.mc{inject_to_mc}.ch{inject_to_ch}.retry_rd_err_set2_log_address1.show()
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.memss.mc{inject_to_mc}.ch{inject_to_ch}.sparing_control.adddc_sparing, 0x1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.memss.mc{inject_to_mc}.ch{inject_to_ch}.sparing_control.region_size, 0x0)
ras.adddc_status_check(socket=inject_to_socket, mc=inject_to_mc, ch=inject_to_ch)
go()
```

### 4.2 BHS ADDDC CE

Target extraction:

```python
inject_to_socket = int(hardware.dimm_1.socket)
inject_to_mc = int(hardware.dimm_1.mc)
inject_to_ch = int(hardware.dimm_1.channel)
inject_to_dimm = int(hardware.dimm_1.slot)
```

Injection pattern:

```python
halt()
ei.utils.resetInjectorLockCheck()
ei.mem.memDevs(dev0=1, dev0msk=0x3, dev1msk=0x0)
for threshold in range(0, max_threshold):
    halt()
    ei.mem.injectMemError(socket=inject_to_socket, channel=inject_to_mc, sub_channel=0, dimm=inject_to_dimm, rank=0, sub_rank=0, bank_group=0, bank=0, errType='ce', ps_ch=0, verbose=True)
    go()
    RAK_DELAY(25)
```

Verification pattern:

```python
halt()
sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.retry_rd_err_log_address1[3].show()
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.sparing_control.adddc_sparing, 0x1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.sparing_control.region_size, 0x0)
ras.mem.adddc_status_check(socket=inject_to_socket, mc=inject_to_mc, ch=inject_to_ch)
go()
```

### 4.3 OKS Memory CSMI Threshold

Target and RASIP bank pattern:

```python
inject_to_socket = int(hardware.dimm_1.socket)
inject_to_imh = int(hardware.dimm_1.imh)
inject_to_mc = int(hardware.dimm_1.mc)
inject_to_subch = 0
inject_to_dimm = int(hardware.dimm_1.slot)
McBankNum = 13 + inject_to_mc
```

Threshold verification pattern:

```python
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem.reg_csmithres{McBankNum}.match_en, 0x1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem.reg_csmithres{McBankNum}.bios_ce_threshold, 0x3)
SmiCount0 = msr(0x34)
```

Repeated injection and counter pattern:

```python
ei.mem.inject_mem_error(socket=inject_to_socket, imh=inject_to_imh, mc=inject_to_mc, dimm=inject_to_dimm, rank=0, sub_rank=0, subch=0, bank_group=0, bank=0, error_type="ce")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.correrrcnt[0], 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.imc0_mc_status_shadow.cor_err_cnt, 1)
```

After the threshold is reached, resume the system, halt again, and verify `msr(0x34)` increments as the recipe expects.

### 4.4 OKS Hardcoded Address Memory CE

Preserve a source recipe's hardcoded system address. Translate it first and bind the translated topology before injection or assertion.

```python
halt()
SystemAddress = 0x100000FC0
translation_info = mc.add_tran({'core_addr': SystemAddress})
translation_info.raw_data.show()
inject_to_socket = translation_info.raw_data.socket
inject_to_imh = translation_info.raw_data.imh
inject_to_mc = translation_info.raw_data.mc
inject_to_subch = translation_info.raw_data.subch
inject_to_dimm = translation_info.raw_data.dimm
```

Inject to the hardcoded address and verify the translated target:

```python
ei.mem.inject_mem_error(SystemAddress, error_type='ce')
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.imc0_mc_status_shadow.uc, 0x0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.imc0_mc_status_shadow.mscod, 0x80)
sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.retry_rd_err_log[0].show()
sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.retry_rd_err_log_address1[0].show()
sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.retry_rd_err_log_address2[0].show()
```

## 5. PCIe / IIO Patterns

### 5.1 EGS PCIe eDPC CTO

Target extraction:

```python
inject_to_socket = int(hardware.pcie.socket)
inject_to_pxp = int(hardware.pcie.pxp)
inject_to_pcieg = int(hardware.pcie.pcieg)
inject_to_port = int(hardware.pcie.port)
```

Pre-injection baseline:

```python
halt()
pcie.topology()
pcie.port_map()
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.devsts, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.erruncsts, 0)
OrgLinkSpeed = int(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.linksts.cls)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.erruncmsk.ctem, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.erruncsev.ctes, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.dpcctl.dpcte, 2)
```

Injection and result checks:

```python
halt()
ei.resetInjectorLockCheck()
ei.injectPcieError(socket=inject_to_socket, port=f"pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}", errType='uce')
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.devsts.nfed, 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.erruncsts.cte, 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.dpcsts.dpcts, 1)
go()
RAK_DELAY(60)
halt()
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.erruncsts, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.dpcsts.dpcts, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.linksts.cls, OrgLinkSpeed)
```

### 5.2 BHS PCIe eDPC CTO

Use common AER/DPC register suffixes, but build paths with the BHS path base and `pxp_io_map`.

```python
inject_to_socket = int(hardware.pcie.socket)
inject_to_pxp = int(hardware.pcie.pxp)
inject_to_port = int(hardware.pcie.rp)
pxp_io_map = {'pxp0': 0, 'pxp1': 0, 'pxp2': 0, 'pxp3': 0, 'pxp4': 1, 'pxp5': 1}
pxp_io_number = pxp_io_map[f"pxp{inject_to_pxp}"]
```

```python
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.erruncmsk.ctem, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.erruncsev.ctes, 0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.dpcctl.dpcte, 2)
ei.utils.resetInjectorLockCheck()
ei.iio.injectPcieError(socket=inject_to_socket, port=f"pxp{inject_to_pxp}.rp{inject_to_port}", errType='uce')
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.devsts.nfed, 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.erruncsts.cte, 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.dpcsts.dpcts, 1)
```

### 5.3 OKS PCIe CE / UCE

Target extraction:

```python
inject_to_socket = int(hardware.pcie.socket)
inject_to_imh = int(hardware.pcie.imh)
inject_to_pxp = int(hardware.pcie.pxp)
inject_to_pcieg = int(hardware.pcie.pcieg)
inject_to_port = int(hardware.pcie.rp)
cxp = hardware.pcie.cxp
```

Correctable PCIe pattern:

```python
halt()
error.sys.clear_all_errors()
error.sys.check_rasip_errors()
error.iio.check_pcie_errors()
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem.reg_miscctrl0.iomca_en, 0x1)
ei.iio.inject_pcie_error(socket=inject_to_socket, port_id=f"imh{inject_to_imh}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}", error_type="ce")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.devsts.ced, 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.errcorsts.re, 1)
go()
RAK_DELAY(10)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.errcorsts.re, 0)
```

Uncorrectable nonfatal pattern:

```python
ei.iio.inject_pcie_error(socket=inject_to_socket, port_id=f"imh{inject_to_imh}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}", error_type="uce", severity="nonfatal")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.devsts.nfed, 1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.erruncsts.cte, 1)
```

PCIe correctable threshold pattern:

```python
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.corerrcnt, 0x0)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.corerrth, 0x3)
ei.iio.inject_pcie_error(socket=inject_to_socket, port_id=f"imh{inject_to_imh}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}", error_type="ce", clear_error=False)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.corerrcnt, 0x1)
```

## 6. UPI Patterns

### 6.1 EGS UPI CE

```python
inject_to_socket_1 = int(hardware.upi_1.socket)
inject_to_port_1 = int(hardware.upi_1.port)
inject_to_socket_2 = int(hardware.upi_2.socket)
inject_to_port_2 = int(hardware.upi_2.port)

halt()
upi.topology()
upi.printErrors()
ei.resetInjectorLockCheck()
ei.injectUpiError(socket=inject_to_socket_1, port=inject_to_port_1, num_crcs=1)
upi.printErrors()
RAK_ASSERT_CSR(sv.socket{inject_to_socket_1}.uncore.upi.upi{inject_to_port_1}.bios_kti_err_st, {"bit52-38": 1, "bit21-16": 0x30})
go()
RAK_DELAY()
RAK_ASSERT_CSR(sv.socket{inject_to_socket_1}.uncore.upi.upi{inject_to_port_1}.bios_kti_err_st, {"bit52-38": 0, "bit21-16": 0})
```

### 6.2 BHS UPI CE

```python
inject_to_socket_1 = int(hardware.upi_1.socket)
inject_to_port_1 = int(hardware.upi_1.port)
inject_to_socket_2 = int(hardware.upi_2.socket)
inject_to_port_2 = int(hardware.upi_2.port)
upi_io_map = {'upi0': 0, 'upi1': 0, 'upi2': 1, 'upi3': 1, 'upi4': 1, 'upi5': 1}
upi_io_map_1 = upi_io_map[f"upi{inject_to_port_1}"]

halt()
upi.topology()
upi.printErrors()
ei.utils.resetInjectorLockCheck()
ei.iio.injectUPIError(socket=inject_to_socket_1, port=inject_to_port_1, num_crcs=1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket_1}.io{upi_io_map_1}.uncore.upi.upi{inject_to_port_1}.upi_regs.bios_kti_err_st, {"bit52-38": 1, "bit21-16": 0x30})
go()
RAK_DELAY(60)
RAK_ASSERT_CSR(sv.socket{inject_to_socket_1}.io{upi_io_map_1}.uncore.upi.upi{inject_to_port_1}.upi_regs.bios_kti_err_st, {"bit52-38": 0, "bit21-16": 0})
```

Rules:
- Use both `hardware.upi_1` and `hardware.upi_2` for link endpoint context.
- Do not generate OKS UPI paths from current references.
- Some UPI status bits are cleared by BIOS/SMI after `go()`. Assert pre-clear state before `go()` and recovery state after resume.

## 7. SMM / MSR Patterns

For OKS MSR checks that fail in halted state, try platform-supported SMM access before removing or weakening the check.

```python
sys.state.enter_smm()
RAK_DELAY()
RAK_ASSERT_MSR(int(itp.threads[0].msr(0x4d7)), expected)
sys.state.exit_smm()
RAK_DELAY()
halt()
```

For OKS CE cloaking examples, the historical case used `msr(0x52)`. Prefer the access form required by the source recipe and `RAK_Instructions.md`.

```python
sys.state.enter_smm()
RAK_DELAY()
RAK_ASSERT_MSR(msr(0x52), {"bit0": 1})
sys.state.exit_smm()
RAK_DELAY()
halt()
```

## 8. Log Evidence Patterns

Use log checks only when the source recipe or user provides exact keywords.

Common historical examples:

```python
RAK_DMESG_ANALYSE("dmesg", "normal", "unsequential", "exist", "AER: device recovery successful", "DPC: unmasked uncorrectable error detected")
RAK_SERIAL_ANALYSE("normal", "unsequential", "exist", "[IEH] error found at IEH", "IEH CORRECT ERROR")
RAK_SERIAL_ANALYSE("normal", "sequential", "exist", "[Mca] Clear Status", "[Mca]ClearErrLogReg", "[Mca]Sending CMCI")
```

Rules:
- Do not invent dmesg, serial, local-file, or SSH-session keywords.
- Do not claim pass from log text only when the recipe also supports deterministic register or state checks.
- Clear dmesg only when the case needs a clean dmesg baseline.

## 9. Generation Pitfalls

- Do not include ICX in target-platform examples generated by this skill.
- Do not use `DFXEnable` for BHS; use `DfxEvMode` from `BIOS_Knobs_Mapping.md`.
- Do not use legacy platform-split unlock replacements such as `DFXEnable` or
    `DfxDisableBiosDone` for newly generated RAK RAS cases unless an explicit user/source
    reference requires them in addition to the baseline knobs.
- Do not omit the RAS baseline knobs: `RasLogLevel=0x3`, `DfxEvMode=0x1`,
    `DfxUnlockErrorInjEn=0x1`, and `DfxDisableCctBiosDone=0x1`.
- Do not mix EGS `sv.socket{}.uncore` paths with BHS `sv.socket{}.soc` or `sv.socket{}.io` paths.
- Do not mix EGS `ei.injectPcieError` / `ei.injectUpiError` with BHS `ei.iio.*` injectors.
- Do not generate runtime sPPR for SRF targets.
- Do not place transient post-injection register assertions after `go()` if BIOS/SMI is expected to clear the register.
- Do not omit `RAK_SHOW_HWCONFIG()` and `RAK_CHECK_HWCONFIG(HW_INFO)` before injection when the case uses `HW_INFO`.
- Do not omit the standalone `##HW-configuration:` header when using `RAK_CHECK_HWCONFIG(HW_INFO)`.
- Do not use BHS `pxp_io_map` or `upi_io_map` for OKS paths.
- Do not treat common PCIe AER/DPC register names as common full paths.

## 10. Quick Self-Review Checklist

Before using any pattern from this file, confirm:

- The selected platform family matches the API namespace and register path base.
- Required BIOS knobs come from `BIOS_Knobs_Mapping.md`.
- Required CScripts calls come from `CScript_Functions_Reference.md`.
- Register paths and fields come from `EGS_BHS_OKS_Register_Path_Mapping.md`.
- Hardware targets are derived from `hardware.*` or address translation.
- Hardcoded address recipes preserve the hardcoded address and bind translated topology before verification.
- `RAK_ASSERT_CSR(...)` calls are one physical line.
- Exact expected values are grounded; otherwise use a non-zero check.
- OKS CScripts flows MUST include `cscripts.services.activate_cli_logging(True)` after the BIOS-knob flow when BIOS knobs are changed, and before the first OKS CScripts injection, register access, or CScripts-based verification.