---
name: codesign-rtl-scenario-analysis-coverage
description: "Traces RTL signals for a coverage point and constructs the cycle-level hardware scenario needed to hit it. Extracts signal names from the verification environment's signal access layer, traces wires/regs/ports through the RTL hierarchy (3-5 levels), builds dependency chains, and produces a cycle-by-cycle scenario."
---

# Goal
Identify the RTL scenario required to hit the coverage point and return it in-chat.

# Input
- `type_name`, `group_name`, `item_name`, `bin_name`: Coverage point identifiers
- `cluster` / `dut` / `ip`: The hardware block under test — may be a cluster, DUT, or IP name *(ask the user if not explicitly provided)*
- `model_path`: Root directory of the codebase *(infer from the workspace if a model is open; if not provided and no model is in the workspace, this is a BLOCKING step — use `vscode_askQuestions` to request it from the user before proceeding)*

# Quality Rules
- **ONLY ACTUAL RTL SIGNALS** — wire/reg names from RTL files only, never CTE variable names
- **NO SPECULATION**: every `file:line` must be from code you have actually read
- State `NOT FOUND` or `NOT ACCESSIBLE` with search evidence if a signal cannot be located
- Always complete RTL tracing even if the bin appears unreachable

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

## 1. Extract RTL Signal Names from CTE Driver
Before searching RTL, extract actual signal names from CTE driver code.

**How to extract signal names (depends on methodology):**
- Specman/e: Look for `SIG[module].signal_name[x][y]` patterns in CTE driver/monitor files → RTL signal: `signal_name`, module: `module`
- UVM/SV: Look for `vif.signal` access, hierarchical paths in `bind`-ed modules, or `interface` definitions
- Other: Search coverage/driver files for RTL signal name references (often dot-separated hierarchical paths)

Build a search list of RTL signal names + module context.

Also check for signal interface/mapping files under `<model_path>` — not always present.

## 2. Iterative RTL Search
Loop between levels as needed.

**Level 1 — Find RTL Signals**: Search RTL files under `<model_path>` for each signal name from Step 1. Try variations if exact match fails (remove suffixes, partial matches). If not found → Level 2.

**Level 2 — Refine Signal Names**: Re-examine CTE driver/monitor files for missed signal-access patterns, extract more signal names, loop back to Level 1.

**Level 3 — Trace Signal Sources**: For each found signal, find assignments and driver logic. If port → trace through module hierarchy (parent instantiation → port mapping). Follow 3-5 levels.

**Level 4 — Build Dependencies**: Trace upstream signals, build chain: `signal_A ← signal_B ← signal_C`.

**Level 5 — Construct Scenario**: Cycle-by-cycle signal flow with timing constraints, state transitions, temporal event sequence with file:line refs.

Always complete RTL tracing even if the bin appears unreachable.

## 3. Handle Not-Found Signals
Check package/parameter files under `<model_path>` for the keyword.

Distinguish:
- **NOT ACCESSIBLE**: Signal referenced in CTE but not in RTL → likely encrypted/auto-generated
- **NOT FOUND**: No evidence in CTE or RTL → pure verification-computed variable

# Global Execution Rules

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.
   
# Output
Return in-chat:
- **Coverage Point**: type/group/item/bin, cluster/dut/ip, module, definition file:line, one-sentence description
- **RTL Scenario**: numbered flow — trigger, key RTL signals (name + file:line), timing constraints, outcome. Describe the scenario regardless of reachability.
