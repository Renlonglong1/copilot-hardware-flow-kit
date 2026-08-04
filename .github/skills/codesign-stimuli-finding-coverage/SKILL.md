---
name: codesign-stimuli-finding-coverage
description: "Translates CTE call-tree and constraint analysis into concrete, executable regression test + knob configurations that increase the probability of hitting a coverage point."
---

# Goal
Produce concrete, executable knob configurations paired with existing tests to increase the probability of hitting the coverage point.

# Quality Rules
- **CONCRETE ONLY**: never invent knobs, tests, or parameters. Every `file:line` must be verified.
- **No new tests**: use only tests already identified in the conversation.
- **Verified executable format**: confirm knob value format from actual test configs — mapping files may show `ON`/`OFF` where command line requires `TRUE`/`FALSE`.
- **Meaningfully different recommendations**: each recommendation must reflect the unique behavioral focus of its test.

# Input
- `type_name`, `group_name`, `item_name`, `bin_name`: Coverage point identifiers
- `cluster` / `dut` / `ip`: The hardware block under test — may be a cluster, DUT, or IP name *(ask the user if not explicitly provided)*
- `model_path`: Root directory of the codebase *(infer from the workspace if a model is open; if not provided and no model is in the workspace, this is a BLOCKING step — use `vscode_askQuestions` to request it from the user before proceeding)*

# Mandatory Context Gathering

> **BLOCKING STEP — do NOT proceed to Method until the user has answered this question.**

**IF** `vscode_askQuestions` is available, YOU MUST call it with:
- **header**: `"Stimuli Context"`
- **question**: `"Stimuli finding needs a test list and constraint context. Choose an option, or type your own test list and/or constraint context in the text box below."`
- **options**:
  - `"Run CTE analysis + constraint scan first (provides test list and constraint context)"` *(recommended)*
  - `"Run CTE analysis only (provides test list, skip constraint check)"`
- `allowFreeformInput: true`

**ELSE** (`vscode_askQuestions` is unavailable or disabled): post the following inline in chat and **stop** — wait for the user's reply before continuing:
> Stimuli finding needs a test list and constraint context. How do you want to proceed?
> 1. Run CTE analysis + constraint scan first *(recommended)*
> 2. Run CTE analysis only (skip constraint check)
> 3. Provide your own context — reply with test file paths and any known constraint context (constrained fields, chicken bits, etc.)

Once the user has replied, follow the matching branch:
- **"Run CTE analysis + constraint scan first"**: run `codesign-cte-analysis-coverage` then `codesign-constraint-scan-coverage`, then proceed. If constraints show `CONSTRAINED` with no fixable knobs, report this and stop.
- **"Run CTE analysis only"**: run `codesign-cte-analysis-coverage`, then proceed without constraint context.
- **Freeform text / option 3**: use the user's input as the test list and/or constraint context and proceed.

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

Process each test from the conversation one at a time, sequentially.

### Step 1 — Characterize the Test
Identify the test's unique behavioral focus and how it relates to the coverage scenario. This drives test-specific knob selection.

### Step 2 — Layer 1 Knob Discovery (Coverage Infrastructure)
Search `<model_path>` for knobs that directly control the feature being covered, its drivers, or its monitors. Look for config files.

### Step 3 — Layer 2 Knob Discovery (Behavioral Amplification)
Based on the test's unique focus, grep config files under `<model_path>` for keywords from the test characterization. Do not stop at Layer 1 — always attempt Layer 2.

**Knob name mapping**: The verification environment may use an abstracted knob name that maps to a different runtime-configurable name. Search for mapping files (`.yaml`, `.cfg`, `.csv`) to find the executable knob name. Common patterns:
- Specman/e: `CFG[module].knob_name` → uppercase `MODULE_KNOB_NAME` in mapping files
- UVM: `uvm_config_db` settings, `cfg` class fields, CSV/YAML config files

### Step 4 — Select Knob Values
- Commit to **one exact value** per knob — no ranges, no alternatives.
- Verify executable format: grep actual test config files under `<model_path>` to confirm the value format used at runtime.
- Justify each value: how it biases stimulus generation toward the coverage scenario.

### Step 5 — Validate Constraints
For every recommended knob:
1. Search `<model_path>` for files constraining this knob. Follow file inheritance/import chains to find all constraints.
2. **Hard constraints** (cannot be overridden at runtime — e.g., Specman `keep` without `soft`, SV `constraint` without `soft`) — match the constrained value or remove the knob.
3. **Range constraints** (knob restricted to a range or set) — recommended value must satisfy them.
4. **Conditional/implication constraints** — trace all conditional logic with chosen values; validate dependent knobs together.

### Step 6 — Write Recommendation
Write the completed recommendation block for this test in-chat. Each recommendation must be independently executable.

# Global Execution Rules

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.

# Output
Return in-chat, one block per test:
- Test path (repository-relative)
- Configuration knobs table: name, type, location (file:line), default value, recommended value, justification
- Why this test + knob combination targets the coverage scenario
- How each knob biases execution toward the required conditions