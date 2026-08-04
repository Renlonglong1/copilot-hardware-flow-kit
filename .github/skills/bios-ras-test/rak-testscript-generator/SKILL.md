---
name: rak-testscript-generator
description: 'Generate, transform, derive, or review RAK (RAS Automation Kit) Python test scripts for Intel platform RAS validation. Use whenever the user asks to write a RAK test case, convert a recipe/pseudo-code/partial script into a runnable RAK script, review or fix a RAK script for compliance, derive or port a RAK case from a previous-generation platform to the next-generation platform, or describes an Intel RAS test scenario involving memory errors, PCIe errors, UPI errors, CScripts injection, EINJ, BIOS knobs, ADDDC, sparing, eDPC, PPR, patrol scrub, IVG-based case generation, or any server RAS feature. Trigger even for "write a RAK case for X", "convert this recipe", "generate from IVG", "check my RAK script", "derive OKS from BHS", "port this case to next gen", "cross-generation derivation", or any Intel server RAS test automation request. When the user provides IVG material, Cscripts User Guide material, mentions OKS/BHS/EGS, or asks for a case derived from validation guides, use this skill. If the user asks for a test script without naming the target platform family, this skill must first ask which platform family they want: OKS, BHS, or EGS.'
argument-hint: 'Describe the RAS test scenario, paste a recipe to convert, paste a script to review, or provide an existing platform case to derive the next-gen version'
---

# RAK Test Script Generator

You generate, transform, and review RAK (RAS Automation Kit) Python test scripts for Intel
server platform RAS validation. Every output must be a single, deterministic, platform-correct,
directly executable RAK Python script — or a compliance review with concrete fixes.

## First: Load Your References

Before producing any script output, read the following files. They are the ground truth for
this skill; nothing outside them may be invented.

| File | When to read |
|------|-------------|
| [RAK_Instructions.md](./RAK_Instructions.md) | Always — core generation rules, hard output rules, verification requirements |
| [RAK_API_Reference.md](./RAK_API_Reference.md) | Always — authoritative API list; you may ONLY use APIs defined here |
| [Standard_RAK_Case_Format.md](./Standard_RAK_Case_Format.md) | Always — ConfigInfo block format, field rules, and **platform-specific hardware variable mappings** (topology hierarchy, channel formulas, injection examples, register path patterns per platform) |
| [CScript_Functions_Reference.md](./CScript_Functions_Reference.md) | Always — **authoritative per-platform CScripts function list**; you MUST use ONLY the functions listed under the target platform section (EGS / BHS / OKS). Never carry function names, namespaces, or parameter forms from another platform. |
| [EGS_BHS_OKS_Register_Path_Mapping.md](./EGS_BHS_OKS_Register_Path_Mapping.md) | Always — **cross-platform register path mappings**; essential for Mode E derivation to translate register assertions from source platform to target platform. Maps equivalent registers and bit fields across EGS, BHS, and OKS. |
| [BIOS_Knobs_Mapping.md](./BIOS_Knobs_Mapping.md) | When the scenario requires BIOS knobs — exact knob names and menu paths |
| [Standard_RAK_Case_Reference.md](./Standard_RAK_Case_Reference.md) | When you need a worked example or are unsure about a pattern |
| User-provided IVG excerpts / PDFs / notes | When the request is based on IVG — extract scenario intent, topology, sequencing, and required verification targets |
| User-provided Cscripts User Guide excerpts / PDFs | When the request uses CScripts injection or derives steps from IVG — confirm the concrete command names, arguments, register objects, and expected preconditions |

Read all five "Always" files before generating or reviewing any script.

When IVG and Cscripts User Guide are both present, treat them as complementary sources:
- IVG defines the validation intent, expected flow, and pass/fail targets
- Cscripts User Guide defines the allowed command forms and object usage for the implementation

Do not lift commands blindly from IVG prose. Resolve every concrete CScripts action against the Cscripts User Guide and every RAK helper/API against `RAK_API_Reference.md`.

---

## Determine the Mode

There are five modes. Identify which applies:

**A — Generate from description**: User provides a natural-language scenario. Produce one
executable script implementing it.

**B — Transform from recipe**: User provides a recipe, pseudo-code, partial script, or
non-compliant RAK case. Transform it into one compliant, executable script that preserves
the original intent while enforcing all hard rules.

**C — Generate from IVG**: User provides an IVG excerpt, PDF, extracted steps, or validation
expectations. Convert the validation intent into one compliant, executable script. Use IVG to
decide what must happen; use the Cscripts User Guide and `RAK_API_Reference.md` to decide how
to express each operation concretely.

**D — Review**: User provides an existing RAK script and wants compliance feedback. Identify
every violation with its exact location, explain why it violates the rules, and provide a
concrete compliant fix.

**E — Cross-Generation Derivation**: User provides (or points to) an existing RAK case from a
previous-generation platform and wants to derive the equivalent case for a next-generation
platform. Translate the case intent, sequence, topology, BIOS knobs, injection model, and
verification to the target platform. See the dedicated
[Cross-Generation Derivation](#cross-generation-derivation) section below for full rules.

For batch input (multiple recipes), produce one self-contained script per recipe in the same
order as input.

---

## Before Writing: Clarify if Needed

Apply the "No Guessing" rule strictly. If any of the following is missing AND is required to
produce a correct script, ask — do not guess:

1. **Platform family selection gate** — if the user did not explicitly identify the target
  platform family, you MUST ask first whether they want `OKS`, `BHS`, or `EGS` before writing
  any script. Do not infer the family from the error type alone.
2. **Target platform** — once the family is known, confirm the exact Intel platform(s)?
  (SPR/EMR/GNR-AP/GNR-SP/SRF-AP/SRF-SP/CWF-AP/DMR-AP). This matters because injection APIs,
  register paths, and platform constraints differ completely across platforms. Never reuse
  injection commands from one platform for another.
3. **Error type and injection method** — what error? CScripts injection (default) or EINJ
   (only if explicitly requested)?
4. **Verification intent** — what specifically should be verified? Register values? OS logs?
   Provide keywords only if the recipe/user explicitly states them — never invent log keywords.
5. **Hardware topology** — DIMM / PCIe / UPI target if relevant (usually satisfied by
   `hardware.*` namespace).

Ask at most 3 concise questions. Do NOT produce a script until required information is answered.

Platform family mapping for questioning and decision-making:
- `OKS` -> `DMR-AP`
- `BHS` -> `GNR-AP`, `GNR-SP`, `SRF-AP`, `SRF-SP`, `CWF-AP`
- `EGS` -> `SPR`, `EMR`

If the user names an exact platform such as `DMR-AP` or `SPR`, you do not need to ask the family
again because the family is already implied. If the user says only a generic request such as
"generate an SDDC testscript" or "write a memory CE case", stop and ask for the family first.

Use the defaults from `RAK_Instructions.md` section 4 when information is optional and
unambiguous (e.g., FFM mode by default, CScripts injection by default).

If the user asks for generation from IVG and no Cscripts User Guide content is attached or
available, still proceed only when the needed command forms are already covered by the skill's
built-in references. If the IVG requires a platform-specific CScripts sequence that is not
grounded by the available references, ask for the relevant guide excerpt instead of inventing it.

---

## IVG-Driven Generation Workflow

Use this workflow whenever the input contains IVG content or the user says the case should be
generated from IVG.

### 1. Extract the validation contract from IVG
- Identify platform, feature, error type, scope, and required topology
- Separate mandatory steps from explanatory background text
- Capture only explicit verification targets, register names, and expected outcomes
- If IVG gives examples or alternatives, choose the path that matches the user's platform and stated intent; do not merge variants

### 2. Resolve implementation details from command references
- For each IVG step that implies a CScripts action, verify the exact command, object path, and arguments against the Cscripts User Guide
- For each RAK helper or assertion, verify it exists in `RAK_API_Reference.md`
- If IVG names a register/log concept but not the exact command syntax, use the Cscripts User Guide to derive the concrete command form
- If the Cscripts User Guide and IVG appear inconsistent, prefer the source that is more concrete for the specific point, then call out the ambiguity instead of guessing

### 3. Translate into RAK structure
- Keep the IVG's test intent and ordering, but express it in standard RAK sections
- Convert prose requirements into deterministic assertions wherever possible
- Keep only the knobs and setup steps the flow actually depends on
- Preserve recipe readability by adding concise English comments for major IVG steps,
  especially where prose steps are translated into RAK helpers, CScripts calls, topology
  binding, register assertions, or log checks. Comments should explain the step intent
  without naming IVG files, revision numbers, page numbers, or section references.

### 4. Sanitize output
- Do not mention IVG filenames, revision numbers, or section references in the final script
- Do not paste Cscripts guide prose into comments
- Output only the executable script, with no document traceability text

---

## Script Generation Checklist

Work through these in order. Each is non-negotiable.

### 1. ConfigInfo Block
- Open with `##############ConfigInfo##############`, close with `############End ConfigInfo###############`
- `Automation-Level: 3` always for AI-generated cases
- `target_platform`: set for all RAS and platform-specific cases; leave empty only for
  genuinely common cases. **Never include SRF platforms for runtime sPPR flows.**
- `UEFI_BIOS_knobs`: include the RAS baseline knobs for every generated RAK RAS case, then
  add only feature-specific knobs the test actually depends on. For every knob, use exact name
  and value from `BIOS_Knobs_Mapping.md` and include the full `# EDKII Menu ->...` comment from
  that file. Never invent knob names or menu paths.
  - Every generated RAK RAS case must include the RAS baseline knobs:
    `RasLogLevel=0x3`, `DfxEvMode=0x1`, `DfxUnlockErrorInjEn=0x1`,
    `DfxDisableCctBiosDone=0x1`.
  - Do not use legacy platform-split CScripts unlock rules such as `DFXEnable` or
    `DfxDisableBiosDone` for newly generated RAK RAS cases unless the user explicitly provides
    a platform reference that requires them in addition to the baseline knobs.
  - EINJ injection always requires: `WheaErrorInjSupportEn=0x1`; add `WheaPcieErrInjEn=0x1`
    if targeting PCIe; add `PcieErrInjActionTable=0x1` for eDPC/PCIe EINJ tests
  - OOB RAS (RasOffload) requires: `OobRasSupport=0x1`; not supported on EGS platforms
- Mark `ITP_enable=true` as a dependency comment if the script uses any CScripts-dependent API
  (RAK_WAIT_SYSTEM_STATUS, RAK_ASSERT_SYSTEM_STATUS, RAK_ASSERT_CSR, RAK_ASSERT_MSR,
  RAK_SHOW_HWCONFIG, RAK_CHECK_HWCONFIG)

### 2. Environment Preparation
```python
if not RAK_CHECK_OS_READY():
    itp.resettarget()
RAK_WAIT_SYSTEM_STATUS(SYS_STATUS.OS.OS_READY, timeout=1000)
```
- Use `AC_CYCLE()` instead of `itp.resettarget()` when the test does NOT require an active
  ITP/CScripts connection (i.e., pure EINJ-based tests where `ITP:ITP_enable = False`
  is set in the RAK-CONFIG block).
- Clear logs only when the test intent requires a clean baseline (e.g., `RAK_CMD_REMOTE("sudo dmesg -C")`)
- For OOB RAS (RasOffload) cases, also clear BMC RAS manager logs:
  `RAK_CMD_BMC("journalctl -u com.intel.RAS -b --no-pager")` then
  `RAK_CMD_BMC("rm -rf /run/log/journal/*")`
- Always call `RAK_SHOW_HWCONFIG()` and `RAK_CHECK_HWCONFIG(HW_INFO)` before any injection
- Load `modprobe acpi_extlog` on remote OS after BIOS knobs are applied, for any test
  that depends on extended error log decoding in dmesg
- Apply BIOS knobs with `RAK_UEFI_KNOBS(UEFI_BIOS_knobs)` when the ConfigInfo block has knobs;
  follow with `RAK_DELAY(15)` and re-wait for `OS_READY`

### 3. Injection
- Use the `hardware.*` namespace for topology. The exact variable names and hierarchy **differ
  by platform** — always read `Standard_RAK_Case_Format.md` section 5 for the target platform:
  - EGS: `socket / mc / channel / slot`; absolute channel = `mc * 2 + ch`
  - BHS: `socket / mc / channel / slot`; absolute channel = `mc * 1 + ch`; `ch` must be 0
  - OKS: `socket / imh / mc / subchannel / slot`; **no absolute channel calculation**
- Select injection commands strictly from `CScript_Functions_Reference.md` under the target
  platform section. The function namespace, naming convention, and parameter names differ
  completely across platforms:
  - EGS: flat calls e.g. `ei.injectMemError(..., errType='ce')`
  - BHS: camelCase namespaced e.g. `ei.mem.injectMemError(..., errType='ce')`
  - OKS: snake_case namespaced e.g. `ei.mem.inject_mem_error(..., error_type='ce')`
- Register paths are platform-specific. Read `Standard_RAK_Case_Format.md` section 5 for
  the exact path pattern of the target platform before writing any `RAK_ASSERT_CSR()` call.
- Perform `halt()` before CScripts injection; do register reads/prints/assertions BEFORE
  `go()` in non-OOB mode; in OOB mode prefer firmware/OS logs over register state after halt

### 3a. Register Path Discovery Workflow (Mandatory)
- If the exact register path is uncertain, do NOT guess. Discover it with CScripts search first,
  then write assertions only from discovered paths.
- Always start from the smallest scope that is already known from topology extraction.
  Do not start from a broader parent path if a narrower child scope is already confirmed.
- Prefer `showsearch()` first because it returns both matched paths and current values, which is
  better for deciding deterministic assertions.
- Search escalation order (required):
  1. Fast scoped search without `"f"`
  2. If no result or ambiguous result, run deep search with `"f"`
- Preferred examples:
  - Scoped search: `sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.showsearch("adddc_sparing")`
  - Deep search fallback: `sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.subch{inject_to_subch}.search("adddc_sparing","f")`
- Explicit anti-pattern (do not do this when `subch` is known):
  - `sv.socket{inject_to_socket}.imh{inject_to_imh}.memss.mc{inject_to_mc}.showsearch("adddc_sparing")`
- `search()` and `showsearch()` have equivalent matching behavior. Use `showsearch()` by default;
  keep `search()` mainly for deep fallback or when value printout is unnecessary.
- If local references still do not resolve the path, you may run remote CScripts commands to
  discover it and use only returned evidence-backed paths in the generated script.

### 4. Verification
Every script must include at least one deterministic verification mechanism:
- `RAK_ASSERT_CSR(...)` or `RAK_ASSERT_MSR(...)` for register-level checks
- `RAK_ASSERT_SYSTEM_STATUS(...)` for system state checks
- Log analysis APIs only when **all three** conditions hold:
  1. The recipe/spec explicitly names the keywords
  2. The check directly determines PASS/FAIL
  3. The keywords are not inferred or guessed

At least one verification must be assertive (assert/exact match), not just informational prints.

### 5. Output Purity (Final Sanitization)
Before outputting, scan the script and remove:
- Any URLs (SharePoint, OneDrive, web links)
- Any document/spec/IVG names, page numbers, section numbers
- Any phrases like "according to the IVG", "as per spec section..."
- Any AI reasoning or explanation outside of code comments
- Any non-English text

The output must be **only** the Python script — nothing before or after the code block.

---

## Formatting Conventions

- `RAK_ASSERT_CSR(...)` must always be a single physical line — no line breaks inside the call
- Use `print("### Step N — [description] ###")` section markers for readability
- Use `f-strings` or `.format()` for dynamic register path construction with topology variables
- Inject `hardware.*` topology values into `int()` before arithmetic use

---

## Review Mode

When reviewing a script (Mode D), structure your output as:

1. **Summary** — one sentence verdict
2. **Violations** — numbered list, each with:
   - Location (line or section)
   - Rule violated (reference the rule name/section from `RAK_Instructions.md`)
   - Proposed fix (concrete, compliant replacement code)
3. **Corrected Script** — the full fixed script (optional but strongly preferred)

---

## Cross-Generation Derivation

This section defines Mode E — deriving a next-generation platform RAK case from an existing
previous-generation case. All other generation rules (ConfigInfo, Environment Prep, Injection,
Verification, Output Purity) still apply to the derived output.

### When to Use Mode E

- The user provides (or points to) an existing RAK case for a source platform and asks to
  derive the equivalent case for a target platform.
- Typical triggers: "derive OKS from BHS", "port this EGS case to OKS", "create next-gen version of this case".

### Required Grounding

Before writing a derived case, read the same reference files required for all modes (see
"First: Load Your References"), plus:
- The source-platform case provided by the user
- Any target-platform IVG extracts or User Guide excerpts available in the workspace

### Core Derivation Rules

1. **Preserve intent** — Keep the source case's validation intent, sequence, and pass/fail
   contract unless the target platform requires a structurally different implementation.
2. **Translate everything** — APIs, topology naming, BIOS knobs, register paths, helper usage,
   and injection commands must all be translated to the target platform family.
3. **Never carry over blindly** — Do not copy source-platform register paths, dump helpers,
   log strings, or expected bit fields into the target case without evidence.
4. **No invention** — Do not invent target-platform post-injection register checks, expected
   bit fields, log keywords, or pass strings.
5. **Evidence-gated additions** — A new register check or log keyword may be added only when:
   - It is grounded by target-platform references already in the workspace, OR
   - It is explicitly requested by the user, OR
   - It is observed from remote execution result logs (only when remote iteration is active)
6. **Unknown register path handling** — When a needed register path is not explicitly available in
  references, resolve it via the [Register Path Discovery Workflow](#3a-register-path-discovery-workflow)
  (showsearch/search, with deep `"f"` fallback) before adding `RAK_ASSERT_CSR(...)`.

### Default Derivation Strategy

1. Identify the nearest source case with matching feature intent.
2. Produce a target-platform first draft that is runnable and platform-correct.
3. Keep the first draft conservative: omit checks whose target-platform form is unknown rather
   than guessing.
4. Output the derived case. If the user has not requested remote iteration, stop here.
5. If remote iteration is requested, follow the
   [Remote Iteration Policy](#remote-iteration-policy) below.

### Quality Bar (Mode E)

- Prefer deterministic register assertions when they can be grounded.
- Prefer concrete target-platform dump commands over generic prints when documented or observed.
- Add log analysis only when observed key strings are relevant to pass/fail and stable.
- Remove checks that do not clearly belong to the target platform.
- A first-pass derived case may be incomplete, but it must not pretend to know unverified
  validation details.

### Communication Requirements (Mode E)

- Tell the user when you are in derivation mode.
- If remote iteration is active, tell the user which attempt number is being used.
- Tell the user when the default attempt budget has been reached.
- Ask for confirmation before exceeding the default 3-attempt budget (unless overridden).

---

## Remote Iteration Policy

This policy applies to **all generation modes** (A, B, C, E) — any newly generated or
materially modified script may be iteratively refined through remote execution feedback.

Remote iteration and remote verification are both **opt-in only**:

- Do NOT automatically invoke Phase 2 (remote deploy & run) after generating a case.
- Phase 2 is activated only when the user explicitly requests it — for example:
  "run it remotely", "帮我远程验证", "remote验证一下", "deploy and run".
- Remote **iteration** (run → analyze → refine → re-run) is activated only when the user
  explicitly asks for iterative refinement — for example: "use remote logs to optimize",
  "iterate with remote execution", "run it remotely and refine", "帮我远程验证并优化",
  "迭代优化".
- For cross-platform derivation, one complete iteration means: remote run completed, logs analyzed, and case refined from those results.
- If the user only asks to generate a case (without mentioning remote execution or iteration),
  output the script and stop.

### Iteration Budget

- **Default budget**: maximum 3 remote iteration attempts per case.
- **One attempt** = one deploy-and-run cycle of a materially updated case.
- **Stop early** if the case already runs correctly and validation coverage is sufficient.
- If the user specifies a different maximum, follow their instruction.
- If the user explicitly allows unlimited attempts, follow that instruction.
- After the default 3 attempts are exhausted and the case still has issues, stop and ask
  whether to continue.

### Per-Attempt Workflow

1. Update only the minimum set of case changes justified by current evidence.
2. Send the case to the remote machine (Phase 2) and execute it.
3. Inspect the returned logs to determine:
   - Whether the injection path actually executed
   - Which registers captured the event
   - Which dump commands expose useful validation state
   - Which log files and key strings are stable enough for automation
   - Which checks are wrong or insufficient
4. Apply only evidence-backed improvements.
5. Re-run only if another attempt is justified and within budget.

### Communication Requirements (Remote Iteration)

- Tell the user when remote iteration is active.
- Tell the user which attempt number is being used.
- Tell the user when the default attempt budget has been reached.
- Ask for confirmation before exceeding the default 3-attempt budget (unless overridden).

### Scope Boundary

- Remote iteration is for improving generated or derived RAK cases with real execution evidence.
- It does not authorize uncontrolled trial-and-error, unlimited silent reruns, or invented
  validation conditions.
- When no remote machine is available, produce the best static case possible from local
  references and stop at that point.

---

## Platform Isolation Reminder

Platforms (EGS / BHS / OKS) are fully isolated:
- EGS: SPR, EMR
- BHS: GNR-AP, GNR-SP, SRF-AP, SRF-SP, CWF-AP
- OKS: DMR-AP

Never carry register paths, injection commands, or topology formulas from one platform family
to another, even when error types appear similar. When in doubt about a platform-specific API,
ask rather than invent.
