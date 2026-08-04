---
name: codesign-valplanai
description: 'Interact with ValPlan validation plans (also called valplans, test plans, TPs, or VPs) via MCP tools — list plans, drill down, answer questions about features, TCDs, test scenarios, and test cases. Use when the user asks to show, list, explore, or browse their validation plans, test plans, or valplans.ALWAYS read this SKILL.md in full before calling any valplan MCP tool or formatting any valplan output — never improvise the layout.'
---

# ValPlan MCP Skill

## MCP Tools Reference

| Tool | Input | Returns |
|------|-------|---------|
| `codesign-valplanai-get-list` | auth_user (header) | List of plans: conversation_id, plan_name, project_name, update_time |
| `codesign-valplanai-get-overview` | conversation_id | Plan metadata + feature list (feature_title, status, sources) |
| `codesign-valplanai-get-feature` | conversation_id, feature_id | Feature detail + TCD list (content_title, content_description, content_sources) |
| `codesign-valplanai-get-tcd` | conversation_id, feature_id, content_id | TCD detail + test cases grouped by type |

## Common Display Rules

**Note:** Source objects contain `{doc_name, doc_url, doc_id}`. The `doc_id` is used internally for precise document queries but must never be shown to users — display `doc_name` only.

**Sources:** When a `feature_sources` field (features) or `content_sources` field (TCDs) is present, show doc names only (never show `doc_id` to the user). If a source is `{doc_name, doc_url, doc_id}`, show as clickable link: [doc_name](doc_url). If plain string, show as text. The `doc_id` field is used internally for precise document lookups with `codesign-ask-specs-and-wikis` but must not appear in user-facing output.

**`[NEW]` / `[MODIFIED]` prefixes** (appear on test case keys and attribute strings after enhance):
- On Windows and macOS: 🔄 for `[MODIFIED]`, 🆕 for `[NEW]`, no icon for unprefixed.
- On Linux: show `[MODIFIED]` / `[NEW]` as plain text labels, no icons.
- Strip the prefix tag from the display value in all cases.

**Fidelity:** Never fabricate content. Show data as-is from the plan, only stripping HTML tags. If a field is empty/missing → "(No description provided)". Don't rename statuses, don't add/remove table columns, don't move information between phases unless the user explicitly asks.

## Navigation Flow (phased — never skip levels)

**One phase per response. Never skip or combine phases. Wait for user confirmation before advancing.**

### Phase 1: List plans (`codesign-valplanai-get-list`)
- Show as table: plan_name, project_name, update_time. Do NOT show conversation_id or run_id.
- **Duplicate name disambiguation:** If two or more plans share the same `plan_name`, add a `#` index column to the table (1-based row number). When the user refers to a duplicated name, ask: "Did you mean plan #<N> or plan #<M>?" and wait for the user to confirm before proceeding. Never show `conversation_id`.
- **Empty list — hard stop:** If `codesign-valplanai-get-list` returns 0 items, respond: "You don't have any validation plans yet. Create one in the [ValPlan UI](https://valplan.co-design.intel.com) first, then come back and I can explore it with you." **Do NOT call any further tools. Do NOT ask for a conversation_id. Stop here.**
- Ask: "Would you like to explore one of these plans?"

### Phase 2: Plan overview (`codesign-valplanai-get-overview`)
- Show features as numbered table: # | feature_title | status  (value comes from the `feature_generation_status` field)
- Status icons (Windows and macOS): ✅ Generation completed · 📄 Your original plan · 🔄 Content enhancement in progress · ❌ Generation failed · ❌ Enhancement failed · ⏳ In progress · ⬜ Not generated
  - On Linux: omit icons, show status text only.
- Use the `drillable` field to determine drill-down eligibility: `drillable: true` → drillable, `drillable: false` → not drillable.
- If `note` field exists, show below table as footnote.
- **Only ask "Would you like to drill down into a feature?" if at least one feature has `drillable: true`.** If no features are drillable (e.g. the plan has no generated content), do NOT suggest drilling — instead state: "No features have been generated yet. Generate content in the ValPlan UI first, then come back to explore."

### Phase 3: Feature detail (`codesign-valplanai-get-feature`)
- **Pre-call gate:** if the selected feature has `drillable: false` (known from Phase 2), do NOT call `get-feature`. Immediately respond: "⬜ **[feature_title]** has not been generated yet — no content to show. Generate it in the ValPlan UI first, then come back to explore." and stop.
- Only call `codesign-valplanai-get-feature` for features with `drillable: true`.
- Show: **feature_title**, feature_description, feature_sources, note (as info banner if present).
- Ask: "Would you like to drill down to the TCDs?"

### Phase 4: TCD list (from Phase 3 response)
- Show TCDs as formatted text (NOT a table — descriptions are too long):
  **TCD 1: content_title** — content_description · **TCD 2: content_title** — content_description · etc.
- Show `content_sources` per TCD. Display numbering starts from 1. Use `content_id` (not index) when calling `codesign-valplanai-get-tcd`.
- Ask: "Would you like to see the test cases for a specific TCD?"

### Phase 5: TCD test cases (`codesign-valplanai-get-tcd`)
- Show `content_sources`. List all test case keys with `[NEW]`/`[MODIFIED]` icons.
- If TST/CHK/COV grouping (pre-si format), show grouped by type.

### Phase 6: TC detail (user selects a test case)
- Each TC is an array of attribute strings with optional `[NEW]`/`[MODIFIED]` prefixes.
- Show as table: Field | Content | Status icon. Strip prefix tags and HTML.

## Presentation Conformance Gate (mandatory before every response)

Before sending any user-facing response, validate that presentation matches the active phase exactly.

**Hard rule: if any check fails, regenerate the response and re-check before sending.**

Validation checklist:
1. Output shape matches phase requirements (table vs formatted text vs grouped list).
2. Required fields/columns are present and no extra fields/columns were added.
3. Forbidden fields are not shown to user (`conversation_id`, `run_id`, `feature_id`, `content_id`, `doc_id`).
4. Status labels are unchanged from tool output.
5. Source rendering follows rule: `{doc_name, doc_url, doc_id}` as clickable link using `doc_name` only (never show `doc_id`), plain strings as text.
6. Empty/missing fields are shown as "(No description provided)".
7. The phase-appropriate follow-up question appears only when allowed by that phase's conditions.

Phase assertions:
- Phase 1 must show only `plan_name`, `project_name`, `update_time` (plus `#` only for duplicate-name disambiguation).
- Phase 2 must show numbered feature table exactly: `# | feature_title | status` (column value from `feature_generation_status` field).
- Phase 3 must show feature details only (feature_title, feature_description, feature_sources, note if present), without TCD details.
- Phase 4 must show TCDs as formatted text (not a table) and include per-TCD `content_sources`.
- Phase 5 must show test-case keys and group by `TST/CHK/COV` when present.
- Phase 6 must show TC detail table exactly: `Field | Content | Status icon`.

## Answering User Questions (available at any phase)

**Hard rule — NEVER answer from general training knowledge when in valplan context.** This applies to ANY question about a concept, term, acronym, technology, signal, register, protocol, or behavior that appears anywhere in the active valplan session (feature titles, descriptions, TCD titles, TCD descriptions, source doc names, test case content, etc.). It does not matter whether the concept seems "general" or "industry-standard" — if it came up in the context of a valplan, it must be looked up, not answered from training.

**Answering from general knowledge without lookup is a production bug.** It risks fabricating or outdating internal architectural details and violates user trust.

Trigger: if the user asks "what is X?", "tell me more about X", "explain X", "more info on X", or any similar question — and X appeared anywhere in the current valplan session — the mandatory lookup flow below MUST execute before any response is given. No exceptions.

Mandatory lookup order:
1. **Search inside the valplan first** — check already-retrieved plan data (features, TCDs, TCs). Show relevant coverage with references.
2. **Search the valplan's own source docs** — the plan's features have `feature_sources` and TCDs have `content_sources` with specific `doc_id` values. Use `codesign-ask-specs-and-wikis` scoped to the plan's `project_name`, referencing the specific `doc_id` values from the plan's sources in your query (e.g., "Search in doc_id: <id>") so the search is focused on those exact documents. Display results using `doc_name` only — never expose `doc_id` to the user.
3. **If still not found, broaden the search** — search across all available project sources via `codesign-ask-specs-and-wikis` without restricting to the plan's source docs.
4. **Combine results** if the plan partially covers the topic — show plan coverage + spec/wiki for gaps.
5. **If CoDe tools return no result**, say explicitly: "I could not find this in your spec documents. I can offer a general explanation from training knowledge, but treat it as unverified — would you like me to proceed?" Only answer from general knowledge after explicit user consent.

**Self-check before every answer to a question:** Ask yourself — "Did this term/concept appear in the current valplan session?" If yes, have I completed steps 1–4 above? If not, do not send the response — execute the lookup first.

## Write Operations

The MCP tools are **read-only**. When the user asks to add/edit content, respond with a deep link:

`https://valplan.co-design.intel.com/valplan?conversation_id=<conversation_id>&run_id=<run_id>`

Show as clickable markdown link with plan name. Do NOT show raw IDs. Offer to export content in copy-paste format.

## Terminology

- "validation plans" / "test plans" / "valplans" / "TPs" / "valP" / "vplan" / "VPs" / "my plans" → use this skill
- "test cases" → TCs · "scenarios" → TCDs · "features" / "TPFs" → Features
- Users refer to plans by focus phrase — match from list

## conversation_id Integrity

**NEVER fabricate or guess a `conversation_id`.** Valid IDs are UUID v4 (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) and can only come from `codesign-valplanai-get-list` in the current session. If no UUID v4 ID was returned by get-list, there is nothing valid to pass — stop and follow the Phase 1 empty-list rule. If the user provides a non-UUID string, call get-list instead.

## Notes

- Always call `codesign-valplanai-get-list` first if no conversation_id is known
- Match by focus_phrase rather than asking the user to pick
- Use `feature_id` from overview, `content_id` from feature response
 