---
name: codesign-is-valid-coverage
description: "Validates whether a coverage point is architecturally correct and not outdated by querying specification documents and wikis. Returns VALID or INVALID with supporting spec excerpts."
---

# Goal
Return whether the coverage point is valid and meets the current architecture specification.

# Input
- `type_name`, `group_name`, `item_name`, `bin_name`: Coverage point identifiers
- `cluster` / `dut` / `ip`: The hardware block under test — may be a cluster, DUT, or IP name *(ask the user if not explicitly provided)*
- `model_path`: Root directory of the codebase *(infer from the workspace if a model is open; if not provided and no model is in the workspace, this is a BLOCKING step — use `vscode_askQuestions` to request it from the user before proceeding)*

# Mandatory Context Gathering

> **BLOCKING STEP — do NOT proceed to Method until the user has answered this question.**

**IF** `vscode_askQuestions` is available, YOU MUST call it with:
- **header**: `"RTL Scenario Context"`
- **question**: `"Translating the coverage point into spec-level language is easier with the RTL scenario. Choose an option, or describe the RTL scenario in the text box below."`
- **options**:
  - `"Run RTL scenario analysis first"` *(recommended)*
- `allowFreeformInput: true`

**ELSE** (`vscode_askQuestions` is unavailable or disabled): post the following inline in chat and **stop** — wait for the user's reply before continuing:
> Translating the coverage point into spec-level language is easier with the RTL scenario. How do you want to proceed?
> 1. Run RTL scenario analysis first *(recommended)*
> 2. Describe the hardware scenario yourself — reply with the feature/transaction being tested, what must happen, and any relevant signal conditions or timing constraints

Once the user has replied, follow the matching branch:
- **"Run RTL scenario analysis first"**: invoke the `codesign-rtl-scenario-analysis-coverage` skill, then proceed.
- **Freeform text / option 2**: use the user's description as the hardware scenario context and proceed.

# Method

> **Note**: Presence of the coverage group in CTE code or RTL signals in RTL files is NOT sufficient to conclude VALID. This skill requires evidence from architecture specification documents.

## 1. Get Valid Project IDs
Search for tools matching `codesign-get-spec-sources`, then call it to retrieve valid project IDs and their display names. This step is mandatory — you cannot proceed without it.

Identify the relevant project(s) from the coverage point context. Search the FULL returned list for the target project ID (case-insensitive match on `project_id` and `project_text`). NEVER conclude a project is absent without searching the entire list of valid projects.
Validate every candidate project ID against the returned list.
- If a specific project is identifiable and valid, use only that project.
- If no specific project can be determined, use all available project IDs.

## 2. Query the Spec
Incrementally call `codesign-ask-specs-and-wikis` with:
- `graph_id`: always `"spec_agent"`
- `thread_id`: a single UUID v4 generated once; reuse it across all calls in this session
- `input.query`: one focused architectural question per call — translate the RTL scenario into spec-level language (features, transactions, behaviors — NOT CTE variable names or RTL signal names)
- `input.sources`: validated project IDs from step 1

**One question per call**: never combine multiple questions. The tool uses semantic similarity — multi-question queries get averaged and produce less relevant results.

Make multiple calls with different focused questions until sufficient spec coverage is gathered.
Always prioritize project-specific sources over generic ones. Do not query generic architecture documents (e.g., System Design Manual, SDM) unless project-specific sources have been exhausted and you still lack sufficient coverage or direct matches to the coverage point's context.

# Global Execution Rules

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.

# Output
Return in-chat:
- **Spec References**: 2-4 directly relevant references (document, section, quoted excerpt)
- **Verdict**: VALID or INVALID — 1-2 sentence explanation. If INVALID, explain what part of the spec it does not meet.