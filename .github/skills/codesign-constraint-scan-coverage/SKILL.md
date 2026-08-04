---
name: codesign-constraint-scan-coverage
description: "Determines if a coverage point is blocked by scanning all 7 constraint mechanisms: (1) hard constraints fixing field values, (2) custom constraint macros, (3) config knobs gating features, (4) chicken bits / CB defeature registers, (5) preloads that fix register state, (6) force/override directives, (7) disabled or excluded flows. Delivers a CONSTRAINED / NOT CONSTRAINED verdict."
---

# Goal
Determine whether a coverage point is structurally reachable given the full CTE constraint environment. Deliver a `CONSTRAINED` / `NOT CONSTRAINED` verdict with concrete evidence.

# Input
- `type_name`, `group_name`, `item_name`, `bin_name`: Coverage point identifiers
- `cluster` / `dut` / `ip`: The hardware block under test — may be a cluster, DUT, or IP name *(ask the user if not explicitly provided)*
- `model_path`: Root directory of the codebase *(infer from the workspace if a model is open; if not provided and no model is in the workspace, this is a BLOCKING step — use `vscode_askQuestions` to request it from the user before proceeding)*


# Quality Rules
- **CONCRETE ONLY**: every `file:line` must be from code you have actually read
- State `NOT FOUND` if absent — never speculate

# Mandatory Context Gathering

> **BLOCKING STEP — do NOT proceed to Method until the user has answered this question.**

**IF** `vscode_askQuestions` is available, YOU MUST call it with:
- **header**: `"RTL Scenario Context"`
- **question**: `"RTL scenario analysis identifies which signals and fields to check for constraints. Choose an option, or type your own RTL scenario in the text box below."`
- **options**:
  - `"Run RTL scenario analysis first"`*(recommended)*
  - `"Go straight to constraint scan using just the coverage definition"` 
- `allowFreeformInput: true`

**ELSE** (`vscode_askQuestions` is unavailable or disabled): post the following inline in chat and **stop** — wait for the user's reply before continuing:
> RTL scenario analysis identifies which signals and fields to check for constraints. How do you want to proceed?
> 1. Run RTL scenario analysis first *(recommended)*
> 2. Go straight to constraint scan using just the coverage definition
> 3. Provide your own RTL context — reply with signal names, relevant modules, and required field values

Once the user has replied, follow the matching branch:
- **"Run RTL scenario analysis first"**: invoke the `codesign-rtl-scenario-analysis-coverage` skill, then proceed.
- **"Go straight to constraint scan"**: proceed with just the coverage definition.
- **Freeform text / option 3**: use the user's input as the RTL context and proceed.


# Search Efficiency Guidelines

When searching `<model_path>`, you MUST follow these patterns to minimize context consumption:

1. **List files first, read second**: ALWAYS start with `grep -rl '<pattern>' <path>` to identify matching files. Only then read content from top hits. NEVER use `grep -rn` across a directory — that dumps content for every match.

2. **Use bounded context reads**: Use `grep -n -B5 -A20 '<pattern>' <file>` for surrounding context. Never use `cat`, `head -N`, or `cat file | head -N` — these read from the top without knowing where the relevant content is. ALWAYS use `grep -n` to locate the relevant lines first, then `sed -n 'start,endp'` to read around them. For a newly discovered file where you don't yet know what pattern to grep for, use your coverage point terms and driver function names as the initial pattern — e.g., `grep -n -E 'term1|term2|term3' <file>` — never cat to read the whole file "to understand it".

3. **Combine related patterns**: Use `grep -E 'term1|term2|term3'` to search for multiple related symbols in a single pass rather than separate searches.

4. **Progressive narrowing** (3-step drill-down):
   - Step 1: `grep -rl` across a broad scope → file list
   - Step 2: `grep -n -B5 -A20` in the specific files → line numbers + context
   - Step 3: `sed -n 'start,endp' file` for a full function/block body (only when needed)

5. **Searching Across Multiple Scopes**: Use `grep -rl pattern dir1/ dir2/` over `find -o` pipelines when searching across two scopes.

# Method

## 1. Identify Coverage Fields
From the coverage definition, extract:
- The struct(s) the coverage point is defined on
- The fields in the cross-product and the specific bin values required

## 2. Systematic Constraint Scan
For each coverage field, check all 7 mechanisms. Document every finding with `file:line`. State `NOT FOUND` if absent.

**Enumeration rule**: Do NOT assume filenames. Enumerate relevant constraint files under `<model_path>` (`.e`, `.sv`, `.svh`, or equivalent for the project's methodology).

### Mechanism 1 — Hard Constraints
Explicit constraint statements that restrict a field to a fixed set of values and cannot be overridden at runtime.

**What to look for by methodology:**
- Specman: `keep` statements (without `soft`) in `.e` files
- UVM/SV: `constraint` blocks (without `soft`) in `.sv`/`.svh` class files
- Other: equivalent fixed-value randomization constraints in the project's language

**Note:** Always check both DUT/IP/cluster-specific and shared/common directories to ensure constraints defined in shared files are not missed.

### Mechanism 2 — Custom Constraint Macros
Project-defined macros that expand into constraint statements. Search for macro invocations near coverage-related structs; look up macro definitions to verify what constraints they emit.

### Mechanism 3 — iCon / Config Knobs
Runtime config knobs that gate feature enablement. Search `<model_path>` for knob definitions and their default/fixed values. Look for files matching `*.cfg`, `*.yaml`, `*.csv`, `*config*`, `*knob*`.

### Mechanism 4 — Chicken Bits
Single-bit defeature fields in register definition files.

**Where to search**: Search `<model_path>` for register definition files. The format depends on the project:
- OneSource XML: Look for `Struct_reg_*DEFEATURE*`, `*PWRDN_OVRD*`, `*TESTMODE*`, `*CFG*`. Check `<BitField>` entries for `CB_field="true"`, `rand_env="true|false"`, `ResetValue` (`0x1` = feature disabled by default).
- CREST/SAFD: Look for defeature or disable fields in register list XML/CSV files.
- Other: Search for register definitions containing "defeature", "chicken", "disable", "bypass".

1. Find register definition directories under `<model_path>`
2. Search for defeature-related register files: `*DEFEATURE*`, `*PWRDN_OVRD*`, `*DEALLOCMASK*`, `*TESTMODE*`, `*CFG*`
3. For each matching file, find bit fields related to the feature under test
4. Check if the field's reset value disables the feature by default

### Mechanism 5 — Preloads
Register/memory init running before the test body. Search `<model_path>` for preload/init files. Also look for register-init sequences in test setup files and test-bench init methods.

### Mechanism 6 — Overrides
Explicit force or override directives. Search for: `force_*`, `override`, `set_override`, `force` HDL statements, override tables in test config files.

### Mechanism 7 — Disabled / Excluded Flows
Flow-level disabling. Search for: `disable_flow`, `exclude_flow`, flow exclusion tables, `DISABLED`/`EXCLUDED` markers in CTE call-tree config or test-list files.

## 3. Verdict

| Verdict | Meaning |
|---------|---------|
| `NOT CONSTRAINED` | No blocking constraints found across all 7 mechanisms |
| `CONSTRAINED` | At least one mechanism makes the bin combination impossible or practically unreachable |

Include additional observations only if there is concrete evidence of a blocking reason outside the 7 mechanisms (cite file:line). Omit otherwise.

# Global Execution Rules

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.

# Output
Return in-chat:
- Per-mechanism findings 
- Verdict with summary table and 1-2 sentence conclusion
