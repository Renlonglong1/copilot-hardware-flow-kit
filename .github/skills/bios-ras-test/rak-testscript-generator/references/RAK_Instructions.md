# RAK Generation Instructions

Purpose: generate, convert, review, or refine RAK Python cases that are deterministic, platform-correct, directly executable, and aligned with the user's intent.

This document is the top-level rule source. Use the other reference files for details:
- `Standard_RAK_Case_Format.md`: ConfigInfo format, hardware variables, and platform topology rules.
- `RAK_API_Reference.md`: allowed RAK framework APIs.
- `CScript_Functions_Reference.md`: allowed platform-specific CScripts calls.
- `BIOS_Knobs_Mapping.md`: platform BIOS knob names, paths, and legal values.
- `EGS_BHS_OKS_Register_Path_Mapping.md`: CSR path templates and discovery rules.
- `Standard_RAK_Case_Reference.md`: example cases only. Examples do not override this file.

## 1. Supported Tasks

The assistant must support these modes:
- Generate one executable RAK Python case from a natural-language scenario.
- Convert one or more recipes, pseudo-code snippets, partial scripts, or non-compliant RAK cases into compliant RAK Python cases.
- Review an existing RAK case for structure, API correctness, platform correctness, verification quality, dependency declarations, and halt/go semantics.
- Refine a failing RAK case while preserving the original test intent.

For batch conversion, preserve input order and produce one self-contained RAK case per input recipe.

## 2. Output Rules

When the user asks for a generated or converted RAK case, output only executable Python code. Do not add explanation outside the script.

Generated scripts must:
- Use English only.
- Include the required ConfigInfo markers from `Standard_RAK_Case_Format.md`.
- Use only APIs documented in `RAK_API_Reference.md` and platform-valid CScripts calls documented in `CScript_Functions_Reference.md`.
- Avoid pseudo-code, invented APIs, invented parameters, invented runtime objects, invented return values, invented register paths, and invented platform behavior.
- Avoid URLs, document names, source document IDs, page numbers, section numbers, and phrases such as "according to the document".

## 3. Information Priority

Apply rules in this order when references conflict:
1. User's explicit request, within documented RAK and platform capability.
2. This file.
3. `Standard_RAK_Case_Format.md`.
4. `RAK_API_Reference.md` and `CScript_Functions_Reference.md`.
5. `BIOS_Knobs_Mapping.md` and `EGS_BHS_OKS_Register_Path_Mapping.md`.
6. `Standard_RAK_Case_Reference.md` examples.

Historical examples may contain old markers, old API spellings, source comments, or platform-specific shortcuts. Normalize them only when the authoritative references say to do so.

## 4. No-Guessing Policy

Do not guess missing APIs, parameters, register paths, log keywords, platform capability, BIOS knob paths, topology fields, or expected values.

If information required for an executable and intent-correct script is missing, ask up to three concise clarification questions before generating the script.

## 5. Default Choices

Use these defaults only when the user did not specify otherwise and the scenario is unambiguous:
- Execution mode: FFM.
- Injection method: CScripts-based injection.
- EINJ: use only when explicitly requested or when the recipe clearly requires EINJ.
- OS Native AER: set `OsNativeAerSupport=0x1` only when OS Native mode is requested.

## 6. Standard Generation Flow

Use this order unless the recipe requires a different sequence:
1. Identify platform family: EGS, BHS, or OKS.
2. Build the ConfigInfo block.
3. Declare required dependencies in ConfigInfo or HW-configuration notes.
4. Prepare the environment and wait for OS readiness.
5. Apply the RAS baseline BIOS knobs, plus any feature-specific knobs the test behavior depends on.
6. Extract hardware topology or translate the hardcoded address.
7. Clear only the logs or error state required by the test intent.
8. Run pre-injection checks.
9. Inject the error using the platform-correct API.
10. Verify immediate post-injection state before `go()` when registers may be cleared by BIOS, SMI, firmware, or recovery flows.
11. Resume with `go()` only when needed.
12. Verify recovery, logs, final system state, or final register state.

## 7. Environment and Dependencies

Do not assume SSH, IPMI, BMC, Serial, SOL, JTAG, ITP, or CScripts are enabled.

If the script uses CScripts-dependent APIs, declare CScripts / `ITP_enable=true` in ConfigInfo or HW-configuration notes. CScripts-dependent APIs include `RAK_WAIT_SYSTEM_STATUS`, `RAK_ASSERT_SYSTEM_STATUS`, `RAK_ASSERT_CSR`, `RAK_ASSERT_MSR`, `RAK_SHOW_HWCONFIG`, and `RAK_CHECK_HWCONFIG`.

Environment preparation rules:
- If OS is not ready, reset the target using the platform-supported reset method.
- Prefer `RAK_WAIT_SYSTEM_STATUS(SYS_STATUS.OS.OS_READY, timeout=...)` for OS readiness.
- For RAS sparing flows, wait at most 30s after a sparing feature is triggered; after reset/reboot, wait at most 1000s for OS_READY.
- Add stabilization delay before OS-level actions when needed.
- Clear dmesg, SEL, BMC, or other logs only when the test requires a clean baseline.
- For every generated RAK RAS case, include and apply the RAS baseline knobs with
    `RAK_UEFI_KNOBS(UEFI_BIOS_knobs)` unless the user specifies another supported method.
- After BIOS knob changes, wait for OS ready again and add a stabilization delay.

## 8. OKS DMR-AP CScripts Logging

For OKS / DMR-AP cases that use CScripts functions or CScripts-based verification, this call is mandatory:

```python
cscripts.services.activate_cli_logging(True)
```

Placement is a MUST rule:
- If the case changes BIOS knobs with `RAK_UEFI_KNOBS(UEFI_BIOS_knobs)` or any other supported BIOS-knob flow, `cscripts.services.activate_cli_logging(True)` MUST be placed after the BIOS-knob flow and before the first OKS CScripts injection, register access, or CScripts-based verification.
- Do not place it at the start of the script or before BIOS-knob changes when the case has a BIOS-knob flow.
- If the case has no BIOS-knob flow, place it at the first OKS CScripts-related executable point before any CScripts injection, register access, or CScripts-based verification.

This function only increases CScripts CLI logging detail for later CScripts calls. It does not configure BIOS knobs.

Do not add it for:
- EGS platforms.
- BHS platforms.
- Pure EINJ cases.
- OS-native cases that do not use CScripts.
- Cases with `ITP_enable = False`.

## 9. Platform Isolation

Keep platform families fully isolated.

EGS uses SPR/EMR target platforms, EGS CScripts forms, and EGS register paths.
BHS uses GNR-AP, GNR-SP, SRF-AP, SRF-SP, or CWF-AP target platforms, BHS CScripts forms, and BHS register paths.
OKS uses DMR-AP target platform, OKS CScripts forms, and OKS register paths.

Do not copy APIs, topology formulas, BIOS knob requirements, or CSR paths between platform families.

Important platform limits:
- Runtime sPPR is not supported on SRF platforms.
- OOB RAS is not supported on EGS.
- Every generated RAK RAS case uses the RAS baseline knobs: `RasLogLevel=0x3`,
  `DfxEvMode=0x1`, `DfxUnlockErrorInjEn=0x1`, and `DfxDisableCctBiosDone=0x1`.
  Do not replace them with legacy platform-split unlock knobs unless explicitly required by a
  newer user/source reference.
- For OKS cases, `DfxUnlockErrorInjEn=0x1` is sufficient for error-injection unlock. Do not add
    `ei.utils.reset_injector_lock_check()` for OKS unlock. If a recipe or user explicitly requires
    that function, call `ei.utils.reset_injector_lock_check(True)` and never use the no-argument form.

## 10. Hardware Targeting

For topology-based injection, use only the matching `hardware.*` namespace from `Standard_RAK_Case_Format.md`.

Rules:
- DIMM-based memory injection uses `hardware.dimm_1` unless the reference explicitly supports another DIMM object.
- PCIe injection uses `hardware.pcie`.
- PEI card injection uses `hardware.pei_card`.
- UPI injection uses both `hardware.upi_1` and `hardware.upi_2`.
- Do not mix DIMM-based injection and system-address-based injection in the same case unless the recipe explicitly requires both and defines how they relate.
- For memory injection, use absolute channel indexing for injection and relative MC/channel indexing for register verification, according to platform rules.

## 11. Hardcoded Address Injection

When memory-error injection uses a hardcoded system address, translate the address before injection or before verification and bind the translated topology to variables.

Required behavior:
- Use the platform-supported translation API, such as `mc.add_tran(...)` or `RAK_ADDTRAN_SPA_TO_RANK(...)` when documented for that platform flow.
- Bind translated socket, IMH if applicable, MC, channel/subchannel, and DIMM/slot values to variables.
- Use those variables for subsequent CSR/MSR assertions and register path construction.
- Preserve hardcoded-address injection when the recipe uses a hardcoded address, but do not hardcode post-injection register paths when translation results are available.

Derived target rule:
- Do not hardcode any value that can be derived from user-selected hardware topology or address translation.
- This applies to injection targets, CSR/MSR register paths, MCA bank indices, counter slices, retry-log indices, and OS log keywords such as dmesg `MCx`, `Bank x`, socket, channel, subchannel, DIMM, or address strings.
- If a recipe provides a fixed injection address, preserve that address, then translate it and derive all downstream checks from the translated topology whenever the platform exposes enough information.
- If a bank/register/log identifier must be computed from topology, compute it in named variables before the assertion or log check. Do not bake example values such as `MC3`, `Bank 22`, `4*19 + 4*3`, socket 0, channel 0, or DIMM 0 into generated checks unless the recipe explicitly states that fixed target and no dynamic source exists.
- If the mapping from translated topology to an MSR bank, register slice, or dmesg identifier is not documented, add a discovery step or ask for the missing mapping instead of guessing or hardcoding an observed value.

## 12. halt() / go() Semantics

If register inspection is required immediately after injection in non-OOB RAS mode, perform reads, prints, and assertions before `go()`.

Do not assume registers persist after `go()`. BIOS, SMI, firmware, OS recovery, or device recovery may clear or modify status registers.

In OOB RAS mode, do not rely on halt-preserved register state as the only verdict. Prefer the OOB, firmware, OS, or BMC evidence explicitly required by the recipe.

## 13. Verification Rules

Every generated case must include deterministic verification that matches the test intent.

At least one verification must be assertive, such as:
- `RAK_ASSERT(...)`
- `RAK_ASSERT_EQUAL(...)`
- `RAK_ASSERT_NOTEQUAL(...)`
- `RAK_ASSERT_CSR(...)`
- `RAK_ASSERT_MSR(...)`
- a log analysis API with explicitly grounded keywords
- a system status assertion

Use multi-layer verification when the recipe supports it, for example register plus serial or dmesg evidence.

Log analysis rule:
- Use `RAK_DMESG_ANALYSE`, `RAK_SERIAL_ANALYSE`, `RAK_SOL_ANALYSE`, `RAK_SEL_LOG_ANALYSE`, or `RAK_LOCAL_FILE_ANALYSE` only when the exact keywords are provided by the user, recipe, or reference case and directly determine pass/fail.
- Do not invent generic panic, Oops, AER, MCA, or WHEA keywords for completeness.
- When log keywords include topology-derived identifiers such as socket, MC, channel, MCA bank, device, port, or injected address, build those keyword strings from the bound topology/address variables instead of hardcoding example identifiers.

ftrace vs. dmesg mapping rule (IVG documents):
- IVG recipe documents sometimes place `extlog_mem_event` entries inside an ftrace section. In real systems, the `acpi_extlog` driver emits these messages to **dmesg**, not to ftrace.
- When converting an IVG recipe to a RAK case, treat the block from `extlog_mem_event` through the matching `kworker` line inside the IVG ftrace section as **dmesg content**. Extract the keywords from that block and use them in `RAK_DMESG_ANALYSE`.
- Ignore all other ftrace content outside that block (scheduler events, function traces, IRQ traces, etc.). Do not create `RAK_LOCAL_FILE_ANALYSE` or any ftrace-specific check for the non-extlog ftrace lines.
- `extlog_mem_event` is the **ftrace event name** — it does NOT appear in real dmesg output. Do not use it as a `RAK_DMESG_ANALYSE` keyword.
- Extract the dmesg keywords from the **body** of the extlog block (the content after the `extlog_mem_event:` label), such as `"corrected error"`, `"single-bit ECC"`, `"parity error"`, etc. Use only the keywords that actually appear in the IVG extlog body; do not add keywords not shown in the recipe.

Register value rule:
- If the recipe gives an exact expected value, assert that exact value.
- If the exact expected value is unknown and cannot be determined from references, assert that the register is non-zero using native RAK assertion APIs.
- Register paths, MSR offsets, bank indices, and field slices must be derived from bound topology variables when possible; exact expected values may be fixed, but the target being checked should not be fixed unless the recipe explicitly requires that target.
- After memory-error injection, DIMM-location fields such as DIMM, rank, bank, bank group, row, column, and device/failed_dev may legitimately encode as `0`. Do not assert these fields equal `0`, and do not assert them non-zero as a workaround. Show them for observation, or assert only separate validity/status bits such as `failed_dev_valid` when the recipe explicitly defines that bit. The injected address is different: a real injected address must not be `0`, so generated cases MUST assert address fields such as physical address or retry-log `sysaddress` are non-zero at minimum. When the injected or translated expected address is available, assert exact equality to that address.
- When shortening long `sv.*` register paths with a `*_node` alias, bind the alias only to a stable register block, IP block, channel, port, or other parent scope. Do not bind a `*_node` alias directly to a concrete leaf register such as `...reg_cr_smisrclog`, `...retry_rd_err_log[0]`, or `...imc0_mc_status_shadow`; append the leaf register and field at the point of `.show()` or `RAK_ASSERT_*` access.
- Do not replace native assertions with custom `if` statements.

Before adding any assertion or log check, verify that a failure would truly mean the test failed.

## 14. Assertion Formatting

Keep every `RAK_ASSERT_CSR(...)` call on one physical line. Do not split it with parentheses, backslashes, or string concatenation.

## 15. MSR Access Refinement

When refining a case that fails to read an MSR in halted state, first try the platform-supported SMM access flow if available.

For OKS / DMR-AP, the pattern is:

```python
sys.state.enter_smm()
RAK_DELAY()
RAK_ASSERT_MSR(int(itp.threads[0].msr(0x4d7)), expected)
sys.state.exit_smm()
RAK_DELAY()
halt()
```

Keep the original MSR access form when wrapping it. For example, preserve `itp.threads[0].msr(...)` instead of replacing it with bare `msr(...)`.

Only downgrade or remove the MSR check if direct halted access and platform-supported SMM access both fail.

## 16. Script Quality and Final Sanitation

Generated scripts must be valid Python for a properly provisioned RAK environment.

Use concise English comments for major setup, topology translation, injection, and verification blocks. When converting an IVG-style recipe, preserve the recipe flow with comments, but do not include source document names, document IDs, URLs, page numbers, section numbers, or AI reasoning.

Before final output, ensure:
- Only Python code remains.
- Required ConfigInfo markers are present.
- `##HW-configuration:` is present when `RAK_CHECK_HWCONFIG(HW_INFO)` is used.
- Platform APIs, knobs, topology rules, and register paths are not mixed.
- No unsupported APIs or guessed values remain.
