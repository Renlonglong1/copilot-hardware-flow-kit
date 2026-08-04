---
name: codesign-hsd-search-coverage
description: "Searches for bugs and HSD tickets that block a given coverage point from being hit. Only applicable when investigating why a coverage point is not covered — never for standalone bug/ticket lookups. Requires a specific coverage point as input. For tasks unrelated to coverage points, use the `codesign-ask-hsd-agent-mcp` tool directly and DO NOT read this skill."
---

# Goal
Determine if any open HSD bug prevents the coverage point from being hit — either by breaking the RTL scenario or by preventing the CTE from observing it. A CTE bug that stops the test environment from recognizing the coverage event is equally blocking. Provide historical context from closed or prior-stepping bugs.

**Precision is paramount.** Never mark a ticket as BLOCKING unless confidence is extremely high. When in doubt, do not include it.

# Quality Rules
- **BLOCKING only when certain**: all verification questions must be confirmed. When in doubt, SKIP.
- **Concrete evidence only**: every claim must reference an actual ticket description, not assumptions from the title alone.

# Input
- Coverage point identifiers and cluster/project/stepping
- RTL causal chain (from RTL analysis or user-provided scenario)

# Mandatory Context Gathering

> **BLOCKING STEP — do NOT proceed to Method until the user has answered this question.**

**IF** `vscode_askQuestions` is available, YOU MUST call it with:
- **header**: `"RTL Causal Chain Context"`
- **question**: `"HSD searches are structured around the RTL scenario's causal step chain. Choose an option, or type your own causal steps in the text box below (e.g. 'Step 1 — ROB: SMC response valid must be asserted')."`
- **options**:
  - `"Run RTL scenario analysis first to derive the causal chain"` *(recommended)*
  - `"Proceed with just the coverage definition (faster, less precise)"`
  - `"I will provide my own RTL scenario / causal steps"`
- `allowFreeformInput: true`

**ELSE** post inline and **stop**:
> HSD searches need the RTL causal step chain. How do you want to proceed?
> 1. Run RTL scenario analysis first *(recommended)*
> 2. Proceed with just the coverage definition *(faster, less precise — queries will be broader and may miss blocking tickets)*
> 3. Provide your own causal steps (reply with module/component + what must happen per step)
>
> Or type any other option below.

**Branches:**
- **"Run RTL scenario analysis first to derive the causal chain"**: invoke `codesign-rtl-scenario-analysis-coverage`, then proceed.
- **"Proceed with just the coverage definition (faster, less precise)"**: skip causal chain; derive queries from coverage point name and identifiers only.
- **"I will provide my own RTL scenario / causal steps"** or any other **freeform input**: use the user's causal steps as context and proceed.

# Understanding the HSD Tool

The `codesign-ask-hsd-agent-mcp` tool works in two stages:
1. **SQL filtering**: A backend LLM reads the agent's entire input and generates an SQL query to filter tickets by structured fields (cluster/dut/ip, project, stepping, component, status, etc.).
2. **Semantic ranking**: The filtered tickets are ranked by embedding similarity between the agent's input and ticket text.

**Query construction — DO:**
- Put filterable information (cluster/dut/ip name, project, stepping, component path, status constraints) in `invocation_purpose` — this drives the SQL filter.
- Use bug-report language in `query`: micro-architecture terms, behavioral descriptions, failure modes.
- **Derive query terms from the coverage point name itself.** The coverage point name directly reflects how engineers name features and bugs. Use the coverage point's vocabulary as a primary source for query phrasing.
- **Frame each query as a simple negation of the causal step's expected outcome.** Before adding mechanism details, write the query as "X does not happen" or "X not working" where X is the step's outcome in plain feature language. For example, for a step where MOClearEligible must be set, query "MOClear eligibility not set for MRN nuke loads" rather than jumping to specific gating mechanisms or signal names.
- Lead with the behavioral description in `query`; place cluster/dut/ip and component names at the end as context, not as primary search terms. Component names dominate embedding similarity and crowd out the behavioral signal.
- **Keep queries at the right abstraction level.** Start broad — describe the feature-level failure, not the signal-level mechanism. Only narrow a query after seeing too many results (>50). Engineers file bugs using feature names, not signal names. A broad query that finds the right ticket is better than a precise query that misses it.
- **Include performance bugs.** Bugs that disable or break a feature path are filed as performance regressions when the path is an optimization. These are equally blocking for coverage.
- **Differentiate queries**: Each query must focus on the behavioral aspect **unique** to that causal step. Do not repeat the same broad terms across every query — only include terms specific to the step being searched. If two queries would share >50% of their words, they are too similar and should be merged or rewritten to diverge.

  Broad feature terms appear in every relevant ticket. Repeating them across queries produces nearly identical embedding vectors and retrieves the same result set each time. Move shared feature terms to `invocation_purpose` (for SQL filtering) and make the `query` field contain only the **distinguishing** behavioral aspect of that step — the specific failure mode, the specific sub-feature, or the specific condition that differs from other steps.

**Query construction — DO NOT:**
- Include workflow metadata ("I am investigating step 3", "This is my second query for...") — it pollutes both the SQL generation and the embedding.
- Include raw RTL signal names unless the signal is well-known enough to appear in a bug report. Signal-level names are almost never in ticket titles and dilute the embedding.
- Include pipeline stage names in queries — these are RTL implementation details that rarely appear in bug titles.
- Over-specify queries with multiple mechanism details when a simple feature-level description suffices.
- Repeat broad component or feature terms in every query. These belong in `invocation_purpose` for SQL filtering. The `query` field should vary meaningfully between calls.

**Important tool input fields:**
- `query` — semantic query to retrieve tickets based on (drives embedding similarity)
- `invocation_purpose` — fuller context including all filterable fields. Use **broad component paths** (e.g., "component MEU/MOB") — never narrow to specific RTL submodules because bugs are filed against the parent component, not the submodule. Narrowing the component in `invocation_purpose` can cause the SQL filter to miss tickets or bias the semantic ranking toward the wrong subcomponent.
- `input_tenants_subjects` — Pass using dot notation (e.g., `tenant.bug` or `tenant.bugeco`). You MUST pass only `.bug` or `.bugeco` as the tenant subject, not any other subject.
   ! IMPORTANT: If you don't know the tenant - YOU MUST send a request to the tool for the available tenants.
  * `subject` - You MUST search ONLY for `bugeco` or `bug`.
- `relevant_ticket_ids` — IDs of already-found relevant tickets (for dedup/context)
- `conversation_id` — consistent UUID for the session (tracking only)

# Method

## 1. Parse the Causal Chain
From the RTL analysis or user-provided scenario, extract the ordered causal chain (Step 1 → Step N). Extract coverage point metadata: cluster/dut/ip name, project, stepping. For each step: note the module/component and behavioral description. Create a todo item for each step.

## 2. Construct and Execute Queries

**Merge causal steps** that share the same RTL module/component and behavioral domain into a single query.

Work through todos one at a time. For each query:

**Primary query** (current project/stepping):
- `query`: Lead with the behavioral description in bug-report language. Place cluster/dut/ip and component names at the end for context. No signal names, no agent metadata.

**Re-query on high ticket count**: If a query returns more than 50 tickets, the results are too broad. Narrow the query by adding more specific behavioral terms from the causal step and re-activate the tool.

**Secondary query** (prior steppings):
- Same structure but omit current project/stepping. Use broader scope to find bugs deferred from a past stepping that may now be due.

**Mandatory CTE injection query**: After completing all RTL-step queries, always issue one additional query targeting the verification / CTE and test run layer. 

Mark the todo step complete before moving to the next.

## 3. Classify Tickets

For every ticket returned in Step 2, determine whether it blocks the coverage point. Apply the verification checklist below to each one. Only tickets that pass all questions are included in the report.

### Verification Checklist

For each candidate ticket, answer all questions in your reasoning **before** assigning a category. If any answer is "no" or uncertain → SKIP.

**Q1 — Direction of impact**: Does this bug *prevent* the causal step from succeeding **or** prevent the CTE from observing the coverage event, or does it cause an opposite/tangential effect?
- A bug that produces *extra* or *spurious* values (e.g., false-positive triggers, wrong values in the enabling direction) is the opposite of blocking → SKIP.
- "Wrong value" does not imply blocking — check *which direction* is wrong.
- A CTE bug that prevents the test environment from injecting the stimulus needed to trigger the scenario, or from monitoring/recognizing the coverage event when the RTL hits it, counts as blocking.

**Q2 — Path completeness**: Does this bug block *all* paths to the coverage event, or only one narrow sub-scenario?
- Coverage requires only ONE working path through each causal step. If other sub-paths still produce the needed condition → SKIP.
- Ask: "Can a test hit this coverage point without ever exercising the broken path?" If yes → SKIP.
- CTE stimulus injection is not "one narrow sub-path" — it is the primary mechanism by which tests reach coverage points. If a CTE bug prevents injecting the stimulus needed to trigger the RTL scenario, treat the CTE injection path as blocking.

**Q3 — Causal specificity**: Is the broken mechanism on the *actual gating condition* for the coverage event (RTL or CTE), or on a tangential mechanism that shares vocabulary but doesn't gate it?
- A bug on a transient/cycle-level conflict condition (e.g., stop signals, arbitration priority) is not the same as a bug on a persistent eligibility condition.
- A bug from a different product/stepping is not PREVIOUSLY BLOCKING unless the same RTL exists in the current product and the bug was explicitly deferred/pushed.

**Q4 — Investigate before SKIP** *(conditional — apply only when Q1, Q2, or Q3 is uncertain, NOT clearly "no")*: When a ticket is in the **same hardware block/stepping** and meets **any** of the following conditions, you MUST re-query before skipping:
- The ticket is **open**.
- The ticket is **recently closed (within 60 days)**

AND its title shares vocabulary with the coverage point name or causal chain.

**Procedure:**
1. Re-query the HSD tool with the specific ticket ID in `relevant_ticket_ids` to retrieve its description.
2. Re-evaluate Q1–Q3 using the full description.
3. Only then assign BLOCKING, PREVIOUSLY BLOCKING, or SKIP.

This applies when the title is ambiguous about *where* in the causal chain the bug acts — terms that could refer to either the gating mechanism or a downstream consumer. The full description typically clarifies the mechanism.


### Categories

| Category | Criteria |
|---|---|
| **BLOCKING** | Open bug + all verification questions confirm direct impact. A prior-stepping bug counts as BLOCKING only if unresolved and deferred to the current stepping. |
| **PREVIOUSLY BLOCKING** | Closed bug that passes all verification questions and was closed in the past 60 days (relative to today). Historical context only. |
| **SKIP (default)** | Fails any verification question, insufficient confidence, or is a relevant but closed bug closed more than 60 days ago (relative to today). Exclude from report entirely. |

# Global Execution Rules

1. **Root-cause highlight**: If a root cause is identified at any point during investigation, surface it inline using this exact format before continuing:
   > ## Potential root cause
   > [one-sentence summary]
   
   Then continue the investigation without pausing. There may be multiple root causes — collect all of them.

# Output
Return in-chat:
- **Summary**: Yes / No / Possibly verdict — are there open bugs blocking this? (2 sentences)
- **Blocking Tickets**: ID, title, status, date opened (YYYY-MM-DD), project/stepping, causal step, affected condition, blocking rationale. "None found with sufficient confidence." if empty.
- **Previously Blocking**: ID, title, status, date opened (YYYY-MM-DD), project/stepping, causal step, one-line description. "None found." if empty.
- **Search Log**: number of tickets searched, 2-3 sentences on what was searched
