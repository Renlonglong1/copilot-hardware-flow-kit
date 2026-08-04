---
name: codesign-coverage-investigation
description: "**WORKFLOW SKILL** — Guides the full coverage-investigation for a given coverage point by providing a structured todo list. Use when: the user asks why a coverage point is not hit, asks for help investigating a coverage point, or has no specific sub-question — e.g. 'why isn't this coverage point hit?', 'why is it not hit in regression?', 'help me investigate this coverage point'. This is the DEFAULT skill for any unhit coverage point investigation question."
---

# Goal
Guide the coverage-investigation for users who have a coverage point but no specific question. Infer which skills have already been run from the conversation context, then follow the todo list below.

# Input
- `type_name`, `group_name`, `item_name`, `bin_name`: Coverage point identifiers
- `cluster` / `dut` / `ip`: The hardware block under test — may be a cluster, DUT, or IP name *(ask the user if not explicitly provided)*
- `model_path`: Root directory of the codebase *(infer from the workspace if a model is open; if not provided and no model is in the workspace, this is a BLOCKING step — use `vscode_askQuestions` to request it from the user before proceeding)*

# Global Execution Rules

> These rules apply throughout this skill.

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.

2. **STOP when coverage point violates specification**: If Step 2 (`codesign-is-valid-coverage`) determines that the coverage point **violates the architecture specification documents**, **IMMEDIATELY STOP the investigation** and report findings. Do NOT proceed to Steps 3–6. When the specification explicitly states that the behavior being tested cannot occur or is architecturally invalid, further investigation is unnecessary. Present the Key Findings & Recommendations section immediately (see Quality Rules below) and include:
   - **Root Causes**: The specification violation as the primary root cause
   - **Detailed Explanation**: Exact specification references (document name, section, quoted text) that the coverage point violates, explaining precisely why the expected behavior is architecturally impossible
   - **Top Recommendation**: Exclude the coverage point
   - Skip the follow-up questions — the investigation is complete.

3. **Skip sub-skill Mandatory Context Gathering**: When invoking any sub-skill as part of this workflow (Steps 2–6), skip its "Mandatory Context Gathering" section entirely. The coverage point identifiers, cluster/dut/ip, and model path come from the original user request; the RTL scenario is available after Step 1 and satisfies all subsequent prerequisites. Proceed directly to each sub-skill's Method.


# Coverage Closure Todo List

Check the conversation context to determine which items are already done, then work through the remaining ones in order. Skip completed items; pick up from the first incomplete step.

- [ ] **Step 1 — `codesign-rtl-scenario-analysis-coverage`**: Trace RTL signals and build the cycle-level hardware scenario. This is always the first step — all other skills depend on its output.

- [ ] **Step 2 — `codesign-is-valid-coverage`**: Validate the coverage point against the architecture spec. **You must run `tool_search` for `codesign-ask-specs-and-wikis` to load the spec query tool, and then execute this skill. Do NOT substitute RTL or CTE code evidence for a spec document query.**

- [ ] **Step 3 — `codesign-constraint-scan-coverage`**: Scan all 7 constraint mechanisms.

- [ ] **Step 4 — `codesign-cte-analysis-coverage`**: Find ~3 runnable test templates, build the ASCII call tree, and map CTE variables to RTL signals.

- [ ] **Step 5 — `codesign-hsd-search-coverage`**: Search for open bugs blocking the coverage point. **Run `tool_search` for `codesign-ask-hsd-agent-mcp` to load the HSD query tool, then execute this skill.**

- [ ] **Step 6 — `codesign-stimuli-finding-coverage`**: Translate the test list (Step 4) and constraint context (Step 3) into concrete, executable knob configurations. Only start after Steps 3 and 4 are complete.

# Quality Rules
This skill is responsible for ensuring each step's output is clearly surfaced to the user. All concrete findings come from the sub-skills listed above. After the full investigation:

1. Present the key findings and recommendations in a prominent **"Key Findings & Recommendations"** section using the following format:
   - A `##` heading: `## Key Findings & Recommendations`
   - **Root Causes** (bold label): a numbered list of all identified root causes, one per line.
   - **Top Recommendation** (bold label): a single, concrete, actionable recommendation — the highest-impact next step the user should take.
   - **Additional Recommendations** (bold label, only if applicable): up to 2 additional recommended actions, as a short bulleted list.

   > This section must be visually distinct and appear before any follow-up questions. Do NOT produce a step-by-step summary table here.

2. Suggest 3 simple, concrete follow-up questions based on the findings. The **first follow-up question must always be**: *"Would you like a brief summary table of each investigation step and its key finding?"* The remaining 2 questions must only refer to things that can be looked up statically in the codebase — for example, showing where a constraint is defined, tracing an RTL signal, looking up a CTE variable, or checking a specific file or knob. Do not suggest questions about logs, simulation runs, or test results.