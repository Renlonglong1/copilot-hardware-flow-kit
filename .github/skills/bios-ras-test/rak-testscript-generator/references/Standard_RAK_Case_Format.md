# Standard RAK Case Format

Purpose: define the required RAK case structure, ConfigInfo fields, optional RAK-CONFIG block, and hardware variable rules used for deterministic RAS test generation.

This file defines format and topology rules. It does not define the full allowed API set. Use `RAK_API_Reference.md` and `CScript_Functions_Reference.md` for API validity.

## 1. Required Case Layout

A generated RAK case must use this order. Include the RAK-CONFIG block only when it is required.

```python
##############ConfigInfo##############
...
############End ConfigInfo###############

##############RAK-CONFIG##############
...
##############End-configure###########

##############CscriptsCommand##############
...
##############End CscriptsCommand##############
```

Rules:
- The ConfigInfo block is required.
- The RAK-CONFIG block is optional.
- The CscriptsCommand block is required for executable case steps.
- Use the markers exactly as shown when generating new cases.
- Do not copy older marker variants from historical examples.

## 2. ConfigInfo Block

The ConfigInfo block starts and ends with these exact markers:

```text
##############ConfigInfo##############
############End ConfigInfo###############
```

Each field uses `Key: Value` format. Empty values are allowed only when the field is optional.

### 2.1 Required and Common Fields

| Field | Required | Rule |
|---|---:|---|
| `Automation-Level` | Yes | Always use `Automation-Level: 3` for AI-generated RAS cases. |
| `repeat_time` | Yes | Use a small integer such as `1` unless the user requests stress or repeat testing. |
| `target_platform` | Yes for RAS/platform cases | Use comma-separated RAK target values. Leave empty only for genuinely common cases. |
| `##HW-configuration:` | Required when `RAK_CHECK_HWCONFIG(HW_INFO)` is used | Must appear as a standalone header line at the beginning of the HW configuration section. |
| `script_max_duration` | Optional | Omit unless a non-default timeout is required. RAK default is 60 minutes. |
| `CPU Configuration` | Required only when topology matters | Required for UPI and explicit socket-count cases. |
| `UEFI_BIOS_knobs` | Required for every RAK RAS case | Include the RAS baseline knobs plus feature-specific knobs required by the case. |

### 2.2 target_platform Values

| Platform family | target_platform values |
|---|---|
| EGS | `SPR`, `EMR` |
| BHS | `GNR-AP`, `GNR-SP`, `SRF-AP`, `SRF-SP`, `CWF-AP` |
| OKS | `DMR-AP` |

Limits:
- Runtime sPPR must not target SRF platforms.
- OOB RAS must not target EGS platforms.
- OKS UPI generation is not supported unless a future OKS reference explicitly defines the flow.

### 2.3 CPU Configuration

Rules:
- DMR-AP non-UPI cases have no mandatory CPU count requirement.
- DMR-AP UPI cases require CPU count `2` or `4`.
- Non-DMR UPI cases require CPU count `2`, `4`, or `8`.
- Do not add CPU count restrictions when the test intent does not require them.

### 2.4 UEFI_BIOS_knobs

Rules:
- Include the RAS baseline knobs in every generated RAK RAS case.
- Add feature-specific BIOS knobs only when the case behavior depends on them.
- Each knob line must use `KnobName=0xVALUE`.
- If a path is known in `BIOS_Knobs_Mapping.md`, include that exact path as the line comment.
- Do not invent knob names, knob paths, or values.
- Do not use legacy platform-split unlock replacements for newly generated RAK RAS cases unless
    an explicit user/source reference requires them in addition to the baseline knobs.

RAS baseline knobs for every generated RAK RAS case:

| Knob | Required value |
|---|---|
| `RasLogLevel` | `0x3` |
| `DfxEvMode` | `0x1` |
| `DfxUnlockErrorInjEn` | `0x1` |
| `DfxDisableCctBiosDone` | `0x1` |

EINJ base knobs:
- `WheaErrorInjSupportEn=0x1`
- `WheaPcieErrInjEn=0x1` when EINJ targets PCIe.

### 2.5 ConfigInfo Template

The template below is an OKS / DMR-AP RAK RAS example. For EGS, BHS, EINJ, or OS-native cases, keep the RAS baseline BIOS knob lines and add only scenario-required values from `BIOS_Knobs_Mapping.md`.

```python
##############ConfigInfo##############
Automation-Level: 3
repeat_time: 1
target_platform: DMR-AP
##HW-configuration:
# CScripts / ITP_enable=true required.
script_max_duration:
CPU Configuration:
UEFI_BIOS_knobs:
- RasLogLevel=0x3 # EDKII Menu -> Platform Configuration -> System Event Log -> RAS Log Level
- DfxEvMode=0x1 # EDKII Menu -> IO Configuration -> DFX Global Configuration -> EV DFX Features
- DfxUnlockErrorInjEn=0x1 # EDKII Menu -> Platform Configuration -> System Event Log -> Error Injection Settings -> Unlock Error Injection DFX Support
- DfxDisableCctBiosDone=0x1 # EDKII Menu -> Security Dfx Configuration -> Disable BIOS_DONE programming
############End ConfigInfo###############
```

Generation checklist:
- Use exact ConfigInfo markers.
- Use `Automation-Level: 3`.
- Set `target_platform` for all RAS/platform-specific cases.
- Include `##HW-configuration:` when `RAK_CHECK_HWCONFIG(HW_INFO)` is used.
- Omit optional fields when they do not apply.
- Include the RAS baseline knobs in every RAK RAS case.
- Add only scenario-required knobs beyond the RAS baseline.

## 3. Optional RAK-CONFIG Block

Use this block only when a case must override framework settings.

```python
##############RAK-CONFIG##############
ITP:ITP_enable = False
##############End-configure###########
```

Common settings:

| Setting | Use only when |
|---|---|
| `ITP:ITP_enable = False` | The case does not use CScripts or ITP-dependent RAK APIs. |
| `ITP:Platform = GNR` | A documented case requires a platform override. |
| `BMC:SOL_enable = False` | A documented case requires SOL collection disabled. |

Rules:
- Omit this block for default CScripts-enabled cases.
- When `ITP_enable = False`, do not use CScripts functions or ITP-dependent RAK APIs.
- Use only documented non-CScripts reset and verification APIs in `ITP_enable = False` cases.

## 4. Hardware Variable Rules

The `hardware.*` namespace is the source for user-selected topology in topology-based injection.

Rules:
- Use only the namespace assigned to the target type.
- Do not infer unsupported hardware objects.
- Keep EGS, BHS, and OKS topology rules fully isolated.
- Do not mix absolute and relative channel indexing.
- Do not mix DIMM-based memory injection and system-address-based memory injection unless the recipe explicitly requires both and defines their relationship.

### 4.1 Topology Variable Naming

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
- Prefer node aliases for long register paths: bind once, then assert via `*_node`.
- In the same validation step, call `*.show()` before `RAK_ASSERT_CSR(...)` for that register block so failure triage keeps a direct pre-assert snapshot.

Node-alias pattern:

```python
mem_node = sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}
RAK_ASSERT_CSR(mem_node.mcdata.imc0_mc_status_shadow.uc, 0x0)
```

```python
port_node = sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}
RAK_ASSERT_CSR(port_node.rooterrsts.cer, 0x1)
```

Target namespace map:

| Target type | Namespace |
|---|---|
| DIMM memory target | `hardware.dimm_1`; EGS may use `hardware.dimm_2` only when explicitly selected. |
| PCIe device target | `hardware.pcie` |
| PEI card target | `hardware.pei_card` |
| UPI link target | `hardware.upi_1` and `hardware.upi_2` |
| System-address memory target | No required `hardware.*`; derive topology from address translation. |

## 5. Memory Targeting

### 5.1 DIMM-Based Memory Targeting

Use `hardware.dimm_1` by default.

EGS supports `hardware.dimm_1` and `hardware.dimm_2`, but generated cases should select exactly one DIMM object. BHS and OKS generated cases must use `hardware.dimm_1` unless a future platform reference explicitly defines another supported object.

| Platform | Required fields | Injection channel rule | Verification path rule |
|---|---|---|---|
| EGS | `socket`, `mc`, `channel`, `slot` | `inject_to_channel = inject_to_mc * 2 + inject_to_ch` | Use relative `mc` and `channel`. |
| BHS | `socket`, `mc`, `channel`, `slot` | `inject_to_ch` must be `0`; `inject_to_channel = inject_to_mc * 1 + inject_to_ch` | Use relative `mc` and `channel`. |
| OKS | `socket`, `imh`, `mc`, `subchannel`, `slot` | Use `socket`, `imh`, `mc`, `subch`, and `dimm` directly. | Use `socket`, `imh`, `mc`, and `subch`. |

EGS example:

```python
inject_to_socket = int(hardware.dimm_1.socket)
inject_to_mc = int(hardware.dimm_1.mc)
inject_to_ch = int(hardware.dimm_1.channel)
inject_to_dimm = int(hardware.dimm_1.slot)
inject_to_channel = inject_to_mc * 2 + inject_to_ch
ei.injectMemError(socket=inject_to_socket, channel=inject_to_channel, sub_channel=0, dimm=inject_to_dimm, rank=0, sub_rank=0, bank_group=0, bank=0, errType="ce", showInjectors=False, showErrorRegs=False)
sv.socket{inject_to_socket}.uncore.memss.mc{inject_to_mc}.ch{inject_to_ch}.retry_rd_err_set2_log_address1.show()
```

BHS example:

```python
inject_to_socket = int(hardware.dimm_1.socket)
inject_to_mc = int(hardware.dimm_1.mc)
inject_to_ch = int(hardware.dimm_1.channel)
inject_to_dimm = int(hardware.dimm_1.slot)
inject_to_channel = inject_to_mc * 1 + inject_to_ch
ei.mem.injectMemError(socket=inject_to_socket, channel=inject_to_channel, sub_channel=0, dimm=inject_to_dimm, rank=0, sub_rank=0, bank_group=0, bank=0, errType="ce", ps_ch=0, verbose=True)
sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.retry_rd_err_log_address1[3].show()
```

OKS example:

```python
inject_to_socket = int(hardware.dimm_1.socket)
inject_to_imh = int(hardware.dimm_1.imh)
inject_to_mc = int(hardware.dimm_1.mc)
inject_to_subch = int(hardware.dimm_1.subchannel)
inject_to_dimm = int(hardware.dimm_1.slot)
ei.mem.inject_mem_error(socket=inject_to_socket, imh=inject_to_imh, mc=inject_to_mc, subch=inject_to_subch, dimm=inject_to_dimm, rank=0, sub_rank=0, bank_group=0, bank=0, error_type="ce")
sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.retry_rd_err_log_address1[3].show()
```

### 5.2 System-Address-Based Memory Targeting

When a memory injection uses a hardcoded system physical address, translate the address and bind topology variables before verification.

| Platform | Translation API | Required bound variables |
|---|---|---|
| EGS | `RAK_ADDTRAN_SPA_TO_RANK(SystemAddress)` | `inject_to_socket`, `inject_to_mc`, `inject_to_ch`, `inject_to_dimm` |
| BHS | `RAK_ADDTRAN_SPA_TO_RANK(SystemAddress)` | `inject_to_socket`, `inject_to_mc`, `inject_to_ch`, `inject_to_dimm` |
| OKS | `mc.add_tran({'core_addr': SystemAddress})` | `inject_to_socket`, `inject_to_imh`, `inject_to_mc`, `inject_to_subch`, `inject_to_dimm`, `inject_to_rank` |

Note: the `inject_to_*` entries above define required bound topology fields; generated scripts should keep these topology names and may add `*_node` aliases from Section 4.1 for long register paths.

OKS rank binding rule:
- For OKS / DMR-AP system-address translation, bind `inject_to_rank = int(translation_info.raw_data.phys_rank)` when the script uses per-rank counters, thresholds, sparing, PPR, ADDDC, or any rank-indexed CSR.

EGS/BHS location-index rule:
- Use only documented indices from the platform example.
- Do not infer additional `location[]` meanings.

EGS example:

```python
SystemAddress = 0x00018008a040
location, rank_address = RAK_ADDTRAN_SPA_TO_RANK(SystemAddress)
inject_to_socket = location[0]
inject_to_mc = location[1]
inject_to_ch = location[2]
inject_to_dimm = location[4]
ei.injectMemError(SystemAddress, errType="ce")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.memss.mc{inject_to_mc}.ch{inject_to_ch}.imc0_mc_status_shadow.cor_err_cnt, 1)
```

BHS example:

```python
SystemAddress = 0x00018008a040
location, rank_address = RAK_ADDTRAN_SPA_TO_RANK(SystemAddress)
inject_to_socket = location[0]
inject_to_mc = location[1]
inject_to_ch = location[2]
inject_to_dimm = location[4]
ei.mem.injectMemError(SystemAddress, errType="ce", verbose=True)
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.imc0_mc_status_shadow.cor_err_cnt, 1)
```

OKS example:

```python
SystemAddress = 0x100000FC0
translation_info = mc.add_tran({'core_addr': SystemAddress})
inject_to_socket = translation_info.raw_data.socket
inject_to_imh = translation_info.raw_data.imh
inject_to_mc = translation_info.raw_data.mc
inject_to_subch = translation_info.raw_data.subch
inject_to_dimm = translation_info.raw_data.dimm
inject_to_rank = int(translation_info.raw_data.phys_rank)
ei.mem.inject_mem_error(SystemAddress, error_type="ce")
sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.mcdata.retry_rd_err_log_address1[3].show()
```

## 6. PCIe and PEI Targeting

PCIe and PEI targets use similar topology fields. Use `hardware.pcie` for PCIe device targets and `hardware.pei_card` for PEI card targets.

### 6.1 PCIe Targeting

| Platform | Required fields | Port string | Verification path base |
|---|---|---|---|
| EGS | `socket`, `pxp`, `pcieg`, `port` | `f"pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}"` | `sv.socket{socket}.uncore.pi5.pxp{pxp}.pcieg{pcieg}.port{port}.cfg` |
| BHS | `socket`, `pxp`, `rp` | `f"pxp{inject_to_pxp}.rp{inject_to_port}"` | `sv.socket{socket}.io{io}.uncore.pi5.pxp{pxp}.rp{rp}.cfg` |
| OKS | `socket`, `imh`, `pxp`, `pcieg`, `rp`, `cxp` | `f"imh{inject_to_imh}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}"` | `sv.socket{socket}.imh{imh}.pi6.pcieg{pcieg}.pxp{pxp}.{cxp}port{port}` |

BHS PCIe requires this PXP-to-IO map for register paths:

```python
pxp_io_map = {'pxp0': 0, 'pxp1': 0, 'pxp2': 0, 'pxp3': 0, 'pxp4': 1, 'pxp5': 1}
```

EGS PCIe example:

```python
inject_to_socket = int(hardware.pcie.socket)
inject_to_pxp = int(hardware.pcie.pxp)
inject_to_pcieg = int(hardware.pcie.pcieg)
inject_to_port = int(hardware.pcie.port)
ei.injectPcieError(socket=inject_to_socket, port=f"pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}", errType="uce")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.uncore.pi5.pxp{inject_to_pxp}.pcieg{inject_to_pcieg}.port{inject_to_port}.cfg.erruncsts, 0)
```

BHS PCIe example:

```python
inject_to_socket = int(hardware.pcie.socket)
inject_to_pxp = int(hardware.pcie.pxp)
inject_to_port = int(hardware.pcie.rp)
pxp_io_map = {'pxp0': 0, 'pxp1': 0, 'pxp2': 0, 'pxp3': 0, 'pxp4': 1, 'pxp5': 1}
pxp_io_number = pxp_io_map[f"pxp{inject_to_pxp}"]
ei.iio.injectPcieError(socket=inject_to_socket, port=f"pxp{inject_to_pxp}.rp{inject_to_port}", errType="uce")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.io{pxp_io_number}.uncore.pi5.pxp{inject_to_pxp}.rp{inject_to_port}.cfg.errcorsts, 0)
```

OKS PCIe example:

```python
inject_to_socket = int(hardware.pcie.socket)
inject_to_imh = int(hardware.pcie.imh)
inject_to_pxp = int(hardware.pcie.pxp)
inject_to_pcieg = int(hardware.pcie.pcieg)
inject_to_port = int(hardware.pcie.rp)
cxp = hardware.pcie.cxp
ei.iio.inject_pcie_error(socket=inject_to_socket, port_id=f"imh{inject_to_imh}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}", error_type="ce")
RAK_ASSERT_CSR(sv.socket{inject_to_socket}.imh{inject_to_imh}.pi6.pcieg{inject_to_pcieg}.pxp{inject_to_pxp}.{cxp}port{inject_to_port}.errcorsts.re, 1)
```

### 6.2 PEI Card Targeting

Use the same field and path rules as PCIe, but read values from `hardware.pei_card`.

| Platform | Required PEI fields |
|---|---|
| EGS | `socket`, `pxp`, `pcieg`, `port` |
| BHS | `socket`, `pxp`, `rp` |
| OKS | `socket`, `imh`, `pxp`, `pcieg`, `rp`, `cxp` |

Rules:
- For BHS PEI, use the same `pxp_io_map` as BHS PCIe.
- Do not use the BHS `pxp_io_map` for OKS PEI register paths.
- Generate an injection call only when a documented PEI injection API exists for the selected platform and scenario.

## 7. UPI Targeting

UPI injection requires both endpoints of the inter-socket link.

### 7.1 EGS UPI

Required fields:
- `hardware.upi_1.socket`
- `hardware.upi_1.port`
- `hardware.upi_2.socket`
- `hardware.upi_2.port`

Example:

```python
inject_to_socket_1 = int(hardware.upi_1.socket)
inject_to_port_1 = int(hardware.upi_1.port)
inject_to_socket_2 = int(hardware.upi_2.socket)
inject_to_port_2 = int(hardware.upi_2.port)
ei.injectUpiError(socket=inject_to_socket_1, port=inject_to_port_1, num_crcs=1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket_1}.uncore.upi.upi{inject_to_port_1}.ktireut_ph_ctr1.c_failover_en, 1)
```

### 7.2 BHS UPI

Required fields:
- `hardware.upi_1.socket`
- `hardware.upi_1.port`
- `hardware.upi_2.socket`
- `hardware.upi_2.port`

BHS UPI requires this UPI-to-IO map for register paths:

```python
upi_io_map = {'upi0': 0, 'upi1': 0, 'upi2': 1, 'upi3': 1, 'upi4': 1, 'upi5': 1}
```

Example:

```python
inject_to_socket_1 = int(hardware.upi_1.socket)
inject_to_port_1 = int(hardware.upi_1.port)
inject_to_socket_2 = int(hardware.upi_2.socket)
inject_to_port_2 = int(hardware.upi_2.port)
upi_io_map = {'upi0': 0, 'upi1': 0, 'upi2': 1, 'upi3': 1, 'upi4': 1, 'upi5': 1}
upi_io_map_1 = upi_io_map[f"upi{inject_to_port_1}"]
ei.iio.injectUPIError(socket=inject_to_socket_1, port=inject_to_port_1, num_crcs=1)
RAK_ASSERT_CSR(sv.socket{inject_to_socket_1}.io{upi_io_map_1}.uncore.upi.upi{inject_to_port_1}.upi_regs.ktireut_ph_ctr1.c_failover_en, 1)
```

### 7.3 OKS UPI

Do not generate OKS UPI cases from this file. OKS UPI requires future explicit OKS references for topology, APIs, and verification paths.

## 8. CSR Assertion Formatting

Every `RAK_ASSERT_CSR(...)` call must be written on one physical line.

Compliant:

```python
sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.retry_rd_err_log_address1[3].show()
```

Non-compliant:

```python
RAK_ASSERT_CSR(
    sv.socket{inject_to_socket}.soc.memss.mc{inject_to_mc}.ch{inject_to_ch}.mcchan.sparing_control.adddc_sparing,
    0x1
)
```

## 9. Final Generation Checks

Before generating a case from this file, confirm:
- ConfigInfo markers are exact.
- `Automation-Level: 3` is present.
- `target_platform` matches the selected platform family.
- `##HW-configuration:` is present when `RAK_CHECK_HWCONFIG(HW_INFO)` is used.
- BIOS knobs include the RAS baseline and any scenario-required feature knobs.
- Legacy platform-split CScripts unlock knobs are not used unless explicitly required by a newer user/source reference.
- Hardware variables come from the correct `hardware.*` namespace.
- System-address injection performs address translation first.
- Memory injection uses absolute channel indexing where required.
- Register verification uses relative MC/channel indexing where required.
- Injection targets, register paths, MSR bank/offset calculations, retry-log slices, and dmesg/log keywords are derived from `hardware.*` or address-translation variables whenever possible.
- Example topology identifiers such as socket 0, MC3, Bank 22, channel 0, DIMM 0, or hardcoded MCA formulas are not copied into generated checks unless the recipe explicitly requires that fixed target and no dynamic source exists.
- `RAK_ASSERT_CSR(...)` calls are single-line.
