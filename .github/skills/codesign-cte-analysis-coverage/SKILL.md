---
name: codesign-cte-analysis-coverage
description: "Finds runnable stimuli-based test templates that can hit a coverage point, builds an ASCII call tree from tests through drivers and monitors to the coverage point, maps CTE variables to RTL signal names, and assigns reachability verdicts per test."
---

# Goal
Answer: What tests can hit this coverage point, how do I configure them, and why do they work?

# Input
- `type_name`, `group_name`, `item_name`, `bin_name`: Coverage point identifiers
- `cluster` / `dut` / `ip`: The hardware block under test — may be a cluster, DUT, or IP name *(ask the user if not explicitly provided)*
- `model_path`: Root directory of the codebase *(infer from the workspace if a model is open; if not provided and no model is in the workspace, this is a BLOCKING step — use `vscode_askQuestions` to request it from the user before proceeding)*

# Quality Rules
- **CONCRETE, NOT SPECULATIVE**: every `file:line` must be from code you have actually read
- **NOT formal/FPV tests**: only stimuli-based test templates that generate actual hardware stimulus
- **QUANTITY over single directed tests**: find ~3 tests that stress the area from different angles
- State `NOT FOUND` with search evidence if something cannot be located

# Mandatory Context Gathering

> **BLOCKING STEP — do NOT proceed to Method until the user has answered this question.**

**IF** `vscode_askQuestions` is available, YOU MUST call it with:
- **header**: `"RTL Scenario Context"`
- **question**: `"RTL scenario analysis provides signal names and cycle-level context for more precise analysis. Choose an option, or type your own RTL scenario in the text box below."`
- **options**:
  - `"Run RTL scenario analysis first"` *(recommended)*
  - `"Proceed with just the coverage definition (faster, less precise)"`
- `allowFreeformInput: true`

**ELSE** (`vscode_askQuestions` is unavailable or disabled): post the following inline in chat and **stop** — wait for the user's reply before continuing:
> RTL scenario analysis provides signal names and cycle-level context for more precise test matching. How do you want to proceed?
> 1. Run RTL scenario analysis first (recommended)
> 2. Proceed with just the coverage definition (faster, less precise)
> 3. Provide your own RTL scenario — reply with a description of the key signals, conditions, and cycle-level sequence

Once the user has replied, follow the matching branch:
- **"Run RTL scenario analysis first"**: invoke the `codesign-rtl-scenario-analysis-coverage` skill, then proceed to Method using the returned scenario.
- **"Proceed with just the coverage definition"**: proceed to Method using only the coverage definition.
- **Freeform text / option 3**: use the user's description as the RTL scenario context and proceed to Method.

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

## 1. Find Tests — Use All Search Strategies
Target: ~3 stimuli-based test templates exercising different angles of the coverage scenario.

1. Extract keywords from the RTL scenario (or coverage definition).
2. From the scenario, identify related components. Search test files that interact with these components.
3. Expand to tests stressing the general functional area (memory subsystem, cache coherency, pipeline).
4. If few tests found, look for config files with relevant knobs or driver files referencing test invocations.

## 2. Build Call Tree
Create an ASCII flow diagram showing ALL test paths to the coverage point:
- Multiple test templates = multiple starting points
- Show convergence where tests share common infrastructure
- Each node includes [file:line]
- Annotate paths with key constraints/signals
- Include both test configuration and driver/monitor connections for completeness
- Use standardized notation (e.g., arrows, brackets, indentation) for easier interpretation
- End at the coverage collection node

## 3. Verify Reachability
For each test template:
1. Check if it can meet ALL conditions from the coverage definition
2. Assign: 🟢 GREEN (high probability) | 🟠 ORANGE (low probability) | 🔴 RED (doesn't meet conditions)
3. Justify the verdict

## 4. Validate
Can someone run a test tomorrow using this output? Verify: actual file path exists, constraints are documented, connection from test to RTL scenario is explained. If any answer is no — keep searching.

# Global Execution Rules

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.

# Output
Return in-chat:
- Coverage point definition (file:line, snippet, description)
- ASCII call tree
- Per test: name, file:line, reachability verdict, why it hits the scenario
- CTE-to-RTL signal mapping table
