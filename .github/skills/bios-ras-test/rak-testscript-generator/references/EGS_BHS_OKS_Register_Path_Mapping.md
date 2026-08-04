# EGS BHS OKS Register Path Mapping

Purpose: define platform-specific CScripts `sv.*` register path templates and discovery rules for generated RAK RAS cases.

This file is a whitelist. Do not invent register roots, register names, fields, array indices, expected values, or cross-platform path replacements.

## 1. Use Rules

- Use the path table for the selected platform family only.
- Build register paths from topology variables already derived from `hardware.*` or address translation.
- Do not copy a CSR path from another platform because the register or field name looks similar.
- Do not hardcode topology values when translated or user-selected topology variables are available.
- If a path segment is unknown, validate it with minimal-scope `showsearch()` or another explicit source before using it.
- If the exact expected value is unknown, check that the selected register or field is non-zero instead of inventing a value.
- Every generated `RAK_ASSERT_CSR(...)` call must be one physical line.

## 2. Placeholder Rules

| Placeholder | Meaning |
|---|---|
| `{socket}` | Socket index. |
| `{io}` | BHS IO die index. |
| `{imh}` | OKS IMH index. |
| `{pxp}` | PXP index. |
| `{pcieg}` | PCIEG index. |
| `{rp}` / `{port}` | Root-port or UPI port index, depending on path family. |
| `{cxp}` | OKS CXP port prefix from hardware topology. |
| `{mc}` | Memory controller index. |
| `{ch}` | EGS/BHS memory channel index. |
| `{subch}` | OKS memory subchannel index. |
| `{upi}` | UPI port index. |
| `[i]` | Array index that must come from a documented path or source recipe. |

Rules:
- Replace topology placeholders first.
- Treat `{io}`, `{cxp}`, `[i]`, and literal blocks such as `pi5` or `pi6` as evidence-bound; do not infer them from a similar path.
- Keep EGS/BHS/OKS memory topology isolated: EGS/BHS use `mc/ch`; OKS uses `imh/mc/subch`.

## 3. Platform Root Patterns

| Platform family | Common roots |
|---|---|
| EGS | `sv.socket{socket}.uncore.*`, `sv.sockets.uncore.*` |
| BHS | `sv.socket{socket}.io{io}.uncore.*`, `sv.socket{socket}.soc.memss.*`, `sv.sockets.ios.uncore.*` |
| OKS | `sv.socket{socket}.imh{imh}.memss.*`, `sv.socket{socket}.imh{imh}.pi6.*`, `sv.socket{socket}.imh{imh}.rasip.root_ras.*` |

## 4. PCIe and PEI Paths

PCIe targets use `hardware.pcie`. PEI card targets use `hardware.pei_card` and the same path rules as PCIe.

| Platform | Verification path base | Required topology fields |
|---|---|---|
| EGS | `sv.socket{socket}.uncore.pi5.pxp{pxp}.pcieg{pcieg}.port{port}.cfg` | `socket`, `pxp`, `pcieg`, `port` |
| BHS | `sv.socket{socket}.io{io}.uncore.pi5.pxp{pxp}.rp{rp}.cfg` | `socket`, `pxp`, `rp`; derive `{io}` from `pxp_io_map` |
| OKS | `sv.socket{socket}.imh{imh}.pi6.pcieg{pcieg}.pxp{pxp}.{cxp}port{port}` | `socket`, `imh`, `pxp`, `pcieg`, `rp`, `cxp` |

BHS PXP-to-IO map:

```python
pxp_io_map = {'pxp0': 0, 'pxp1': 0, 'pxp2': 0, 'pxp3': 0, 'pxp4': 1, 'pxp5': 1}
```

Common PCIe AER/DPC registers and fields:

These register and field names are common PCIe AER/DPC concepts. The platform-specific `sv.*` path base still comes from the platform table above.

| Register / field | Use |
|---|---|
| `devsts`, `devsts.ced`, `devsts.nfed` | Device status CE/NFE checks. |
| `errcorsts`, `errcorsts.re` | Correctable error status and receiver error. |
| `erruncsts`, `erruncsts.cte`, `erruncsts.uce` | Uncorrectable error status. |
| `erruncmsk.ctem`, `erruncmsk.ucem` | Uncorrectable error masks. |
| `erruncsev.ctes`, `erruncsev.uces` | Uncorrectable error severity. |
| `dpcctl.dpcte`, `dpcsts.dpcts` | DPC control/status. |
| `rooterrsts`, `linksts`, `linksts.cls`, `corerrcnt` | Root/link/counter status. |

Rules:
- BHS PEI uses the same `pxp_io_map` as BHS PCIe.
- Do not use the BHS `pxp_io_map` for OKS PCIe or OKS PEI paths.
- For OKS, append fields directly after the port scope, for example `.errcorsts.re`.
- Do not treat common register names as common full paths; only the suffix register/field names are common.

## 5. UPI Paths

UPI targets use both `hardware.upi_1` and `hardware.upi_2`.

| Platform | Verification path base | Required topology fields |
|---|---|---|
| EGS | `sv.socket{socket}.uncore.upi.upi{upi}` | `hardware.upi_*.socket`, `hardware.upi_*.port` |
| BHS | `sv.socket{socket}.io{io}.uncore.upi.upi{upi}.upi_regs` | `hardware.upi_*.socket`, `hardware.upi_*.port`; derive `{io}` from `upi_io_map` |
| OKS | Not defined in current references | Do not generate OKS UPI paths without future explicit OKS references. |

BHS UPI-to-IO map:

```python
upi_io_map = {'upi0': 0, 'upi1': 0, 'upi2': 1, 'upi3': 1, 'upi4': 1, 'upi5': 1}
```

Common UPI fields:

| Register / field | Use |
|---|---|
| `bios_kti_err_st`, `bios_kti_err_st.mscod_code` | BIOS UPI error status and MSCOD. |
| `bios_kti_err_misc` | UPI error misc information. |
| `ktireut_ph_css.s_clm` | Link state/control check. |
| `ktireut_ph_ctr1.c_failover_en` | Data-link failover enable check. |
| `ktireut_ph_rdc.rxdatalanedisable` | RX data-lane disable mask. |
| `ktireut_ph_tdc.txdatalanedisable` | TX data-lane disable mask. |
| `ktirxeinjctl0`, `kticrcerrcnt`, `ktils` | Injector, CRC counter, and link-state checks. |

## 6. Memory Paths

### 6.1 EGS Memory

| Scope | Path base |
|---|---|
| Main memory channel | `sv.socket{socket}.uncore.memss.mc{mc}.ch{ch}` |
| Mirror / MC bank | `sv.socket{socket}.uncore.memss.m2mem{mc}` |

Common fields:
- `retry_rd_err_set2_log_address1.failed_dev`
- `sparing_control.adddc_sparing`
- `sparing_control.region_size`
- `imc0_mc_status_shadow`
- `imc0_mc_status_shadow.cor_err_cnt`
- `imc0_mc_status_shadow.uc`
- `imc0_mc_misc_shadow`
- `correrrorstatus`
- `correrrorstatus.err_overflow_stat`
- `mci_misc_shadow.mirrorcorrerr`
- `mci_misc_shadow.mirrorfailover`

### 6.2 BHS Memory

| Scope | Path base |
|---|---|
| Main memory channel | `sv.socket{socket}.soc.memss.mc{mc}.ch{ch}.mcchan` |
| Mirror / MC bank | `sv.socket{socket}.soc.memss.b2cmi{mc}` |

Common fields:
- `retry_rd_err_log_address1[3].failed_dev`
- `sparing_control.adddc_sparing`
- `sparing_control.region_size`
- `imc0_mc_status_shadow`
- `imc0_mc_status_shadow.cor_err_cnt`
- `imc0_mc_status_shadow.uc`
- `imc0_mc_misc_shadow`
- `correrrorstatus`
- `mci_misc_shadow.mirrorcorrerr`
- `mci_misc_shadow.mirrorfailover`

### 6.3 OKS Memory

| Scope | Path base |
|---|---|
| Main memory data | `sv.socket{socket}.imh{imh}.memss.mc{mc}.subch{subch}.mcdata` |
| Main memory tracker | `sv.socket{socket}.imh{imh}.memss.mc{mc}.subch{subch}.mctrk` |

Common fields:
- `imc0_mc_status_shadow`
- `imc0_mc_status_shadow.uc`
- `imc0_mc_status_shadow.mscod`
- `imc0_mc_status_shadow.cor_err_cnt`
- `imc0_mc_misc_shadow`
- `imc0_mc_addr_shadow` under `mctrk`
- `correrrcnt`
- `correrrcnt[0]`
- `correrrthrshld`
- `retry_rd_err_log[0]`
- `retry_rd_err_log_address1[0]`
- `retry_rd_err_log_address2[0]`
- `retry_rd_err_log_address1[3].failed_dev`

## 7. OKS RASIP Paths

RASIP memory error-handler scope:

```text
sv.socket{socket}.imh{imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem
```

Common fields:
- `reg_miscctrl0.iomca_en`
- `reg_csmithres{McBankNum}.match_en`
- `reg_csmithres{McBankNum}.bios_ce_threshold`
- `reg_cr_smisrclog`
- `reg_remap_smi_status`
- `reg_gerrsrcid`

Rules:
- Use `McBankNum` only when the source recipe or translation flow defines it.
- Do not use RASIP paths for EGS or BHS.
- If creating a node alias for this scope, bind only to the memory error-handler parent block:
	`sv.socket{socket}.imh{imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem`.
- Do not alias a concrete RASIP leaf register such as `.reg_cr_smisrclog`, `.reg_remap_smi_status`, or `.reg_gerrsrcid` as `*_node`; keep the leaf register on the access line, for example `rasip_mem_handler_node.reg_cr_smisrclog.show()`.

## 8. IEH, Global Error, and Scratchpad Paths

### 8.1 EGS

| Scope | Path base or example |
|---|---|
| IEH global | `sv.socket{socket}.uncore.ieh_global` |
| IEH instance | `sv.socket{socket}.uncore.ieh{ieh}` |
| BIOS scratchpad | `sv.sockets.uncore.ubox.ncdecs.biosscratchpad6_cfg` |

### 8.2 BHS

| Scope | Path base or example |
|---|---|
| Global IEH | `sv.socket{socket}.io{io}.uncore.globalieh.iehregs` |
| SAT IEH | `sv.socket{socket}.io{io}.uncore.satieh.satiehs` |
| BIOS scratchpad | `sv.sockets.io0.uncore.ubox.ncdecs.biosscratchpad6_cfg` |
| Non-sticky BIOS scratchpad | `sv.sockets.io0.uncore.ubox.ncdecs.biosnonstickyscratchpad7_cfg` |

## 9. Minimal-Scope Discovery

Use the smallest known path prefix before `showsearch()`.

Preferred examples:

```python
sv.socket{socket}.uncore.memss.mc{mc}.ch{ch}.showsearch("adddc")
sv.socket{socket}.soc.memss.mc{mc}.ch{ch}.mcchan.showsearch("adddc")
sv.socket{socket}.imh{imh}.memss.mc{mc}.subch{subch}.showsearch("adddc_sparing")
```

Avoid broader searches when channel/subchannel scope is already known:

```python
sv.socket{socket}.uncore.memss.mc{mc}.showsearch("adddc")
sv.socket{socket}.soc.memss.mc{mc}.showsearch("adddc")
sv.socket{socket}.imh{imh}.memss.mc{mc}.showsearch("adddc_sparing")
```

## 10. Quick Path Templates

| Scenario | Template |
|---|---|
| EGS PCIe | `sv.socket{socket}.uncore.pi5.pxp{pxp}.pcieg{pcieg}.port{port}.cfg.{reg}` |
| BHS PCIe | `sv.socket{socket}.io{io}.uncore.pi5.pxp{pxp}.rp{rp}.cfg.{reg}` |
| OKS PCIe | `sv.socket{socket}.imh{imh}.pi6.pcieg{pcieg}.pxp{pxp}.{cxp}port{port}.{reg}` |
| EGS UPI | `sv.socket{socket}.uncore.upi.upi{upi}.{reg}` |
| BHS UPI | `sv.socket{socket}.io{io}.uncore.upi.upi{upi}.upi_regs.{reg}` |
| EGS memory | `sv.socket{socket}.uncore.memss.mc{mc}.ch{ch}.{reg}` |
| BHS memory | `sv.socket{socket}.soc.memss.mc{mc}.ch{ch}.mcchan.{reg}` |
| OKS memory | `sv.socket{socket}.imh{imh}.memss.mc{mc}.subch{subch}.mcdata.{reg}` |
| OKS RASIP | `sv.socket{socket}.imh{imh}.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_mem.{reg}` |

## 11. Generation Checklist

Before generating CSR paths, confirm:
- The selected platform family is known.
- Topology variables are derived from `hardware.*` or address translation.
- BHS PCIe paths derive `{io}` from `pxp_io_map`.
- BHS UPI paths derive `{io}` from `upi_io_map`.
- OKS UPI paths are not generated from current references.
- Array indices such as `[0]` or `[3]` come from this file or the source recipe.
- `RAK_ASSERT_CSR(...)` is written on one physical line.
- Expected values are exact when known; otherwise use a non-zero check rather than inventing a value.
