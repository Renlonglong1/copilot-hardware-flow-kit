---
name: generic-technical-pptx
description: "Create source-grounded, editable PowerPoint presentations with substantial engineering depth. Use this skill whenever the user asks for a technical deck, architecture presentation, design review, feature deep dive, code walkthrough, validation or performance report, debugging/root-cause presentation, research talk, or a PPT/PPTX built from specifications, PDFs, source code, logs, test data, wikis, or existing slides. Prefer this skill over a generic presentation workflow when technical background, implementation details, measured results, citations, interfaces, trade-offs, or limitations matter. This skill owns research, evidence, narrative, and technical content; it delegates PowerPoint construction and visual QA to generic-manipulate-pptx."
compatibility: "Requires the generic-manipulate-pptx skill for creating, editing, rendering, and inspecting .pptx files. Optional authorized source tools may be used for internal specifications, wikis, repositories, and ticket systems."
---

# Technical PPTX

Create an editable PowerPoint deck that can withstand questions from an engineering
audience. Optimize first for technical correctness, traceability, and explanatory depth.
Visual polish supports those goals but does not replace them.

## Division of responsibility

This skill is the orchestration and technical-content layer.

- This skill owns source ingestion, evidence tracking, technical analysis, storyline,
  slide planning, citations, speaker notes, and factual QA.
- `generic-manipulate-pptx` owns PowerPoint file mechanics, template handling,
  PptxGenJS implementation, rendering, overflow checks, and visual QA.

At the start of any run that creates or edits a `.pptx`, invoke
`generic-manipulate-pptx` and follow its instructions for the production layer. Do not
copy or reimplement that skill's private implementation instructions.

Do not generate a Beamer or HTML intermediate unless the user explicitly requests one.
The primary deliverable is a native, editable `.pptx`.

## Operating principles

1. Build the deck from evidence, not plausible-sounding prose.
2. Preserve the technical chain from background through implementation and results.
3. Show concrete artifacts: architecture, interfaces, flows, code, logs, traces,
   register fields, tables, charts, screenshots, and measured data.
4. Separate facts, interpretations, assumptions, and recommendations.
5. Put details needed for live explanation in speaker notes or an appendix rather than
   deleting them solely to make slides sparse.
6. Prefer exact values with units and conditions over qualitative comparisons.
7. Keep all internal or confidential material within authorized tools and locations.
   Never send it to an external service.

## Credibility contract

Resolve every technical statement using this order:

1. Directly supported by a supplied or authorized source.
2. Derived from source evidence with the derivation shown.
3. Explicitly provided by the user.
4. Clearly labeled as an assumption, hypothesis, proposal, or missing-data placeholder.

Never fabricate:

- benchmark or validation results
- latency, bandwidth, throughput, power, capacity, or reliability values
- dates, versions, register definitions, protocol behavior, or interface contracts
- root causes, fixes, or implementation status
- citations or source names

If a value is unavailable but required for the story, write a visible placeholder such
as `TBD: measured p99 latency under configuration X` and list it in the delivery report.
Omit nonessential unsupported claims instead of padding the deck.

## Phase 1: Establish the presentation contract

Infer reasonable defaults and proceed automatically. Ask one focused question only when
the answer would materially change the deck.

Determine:

- audience and expected technical level
- presentation objective or decision required
- available speaking time and approximate slide count
- source scope and source authority
- required template, branding, aspect ratio, and output path
- whether speaker notes and a technical appendix are required

Default assumptions when unspecified:

- audience: engineers familiar with the domain but not this implementation
- format: 16:9 editable PowerPoint
- depth: engineering deep dive
- slide count: 12-18 core slides plus appendix
- notes: concise speaker notes for each substantive slide
- style: clean technical documentation with restrained decoration

## Phase 2: Build a source and artifact inventory

Read the relevant supplied materials before outlining the deck. Sources may include:

- specifications, design documents, PDFs, DOCX files, and requirement documents
- source trees, README files, APIs, schemas, configuration, and commit history
- internal wikis, tickets, issue reports, and validation plans
- logs, traces, crash dumps, screenshots, and failure signatures
- spreadsheets, CSV files, benchmark results, and test reports
- existing PPTX templates or prior presentations
- research papers, preprints, and figure sets

Create a working inventory with these fields:

| Field | Meaning |
|---|---|
| `artifact_id` | Stable identifier used during planning |
| `source` | File, URL, repository path, ticket, or document |
| `location` | Page, section, line range, sheet, test row, or symbol |
| `artifact_type` | Requirement, architecture, code, metric, log, figure, decision, etc. |
| `content` | Exact fact, value, excerpt, or summarized artifact |
| `units_conditions` | Units, workload, platform, version, configuration, and environment |
| `confidence` | Confirmed, derived, user-provided, assumed, or missing |
| `slide_candidate` | Likely role in the deck |

The inventory is the factual source of truth. When two sources conflict, surface the
conflict and prefer the source with higher authority or newer applicable revision.

## Phase 3: Choose the technical narrative

Select a structure that matches the engineering task rather than forcing every deck into
the same generic story.

### Architecture or design review

1. Objective and decision required
2. Background and current system
3. Requirements and constraints
4. Options considered
5. Proposed architecture
6. Component responsibilities
7. Interfaces and data/control flow
8. Key implementation details
9. Failure handling, security, and observability
10. Trade-offs and rejected alternatives
11. Validation evidence
12. Risks, open questions, and next steps

### Feature or implementation deep dive

1. Problem and user-visible behavior
2. Required technical background
3. End-to-end flow
4. Relevant subsystem architecture
5. Data structures, APIs, registers, or protocols
6. Important code paths and state transitions
7. Error handling and edge cases
8. Integration and compatibility
9. Validation method and results
10. Limitations and follow-up work

### Debugging or root-cause review

1. Failure summary and impact
2. Reproduction environment
3. Expected versus observed behavior
4. Failure signature and timeline
5. Call flow or subsystem path
6. Evidence collected
7. Hypotheses tested
8. Root cause with causal chain
9. Fix and why it addresses the cause
10. Regression coverage and residual risks

### Performance or validation report

1. Question being measured
2. Platform and configuration
3. Workload and methodology
4. Baseline and comparison points
5. Primary results with exact units
6. Distribution, variance, and confidence
7. Bottleneck analysis
8. Interpretation and causal explanation
9. Limitations of the test
10. Recommendation and next experiment

### Research or paper presentation

1. Motivation and technical gap
2. Necessary background and related approaches
3. Key insight or hypothesis
4. Method and system design
5. Experimental setup
6. Main results
7. Ablations or sensitivity analysis
8. Limitations and threats to validity
9. Conclusions and open questions

## Phase 4: Create the slide plan

Plan the whole deck before writing rendering code. For each slide, record:

```yaml
id: 6
title: "Posted writes bypass the completion path"
purpose: "Explain the protocol behavior required to understand the failure"
message: "The requester cannot use a completion timeout to detect this class of loss"
evidence:
  - artifact_id: SPEC-14
    use: "Definition of posted request behavior"
  - artifact_id: TRACE-03
    use: "Observed missing downstream write"
visual:
  type: "annotated sequence diagram"
  content: "Requester -> Root Port -> Endpoint with the missing transaction highlighted"
details:
  - "Ordering rule and relevant state"
  - "Detection mechanism that remains available"
speaker_notes:
  - "Explain why this differs from a non-posted request"
appendix_links:
  - "A4: Full trace"
```

Every core slide should have:

- one defensible primary message
- enough background to understand that message
- one or more linked source artifacts
- a visual form appropriate to the information
- speaker notes for details that should be spoken rather than displayed

Use assertion-style titles when evidence supports them. Use neutral titles when the slide
is purely explanatory and a claim would overstate the evidence.

## Technical content standards

### Background

Include the minimum background required to follow the later implementation details.
Do not assume that naming a component explains what it does. Define relevant terminology,
ownership boundaries, invariants, and protocol rules.

### Architecture and flows

- Show system context before detailed component diagrams.
- Label boundaries, ownership, direction, and interfaces.
- Distinguish control flow, data flow, and error flow when they differ.
- Use sequence diagrams for time-ordered interactions.
- Use state diagrams for lifecycle or protocol behavior.
- Keep diagram labels editable whenever practical.

### Code and interfaces

- Show only the code needed to explain the mechanism.
- Include file path, symbol, and relevant line range in the citation or notes.
- Highlight the active lines and explain caller/callee context.
- Preserve exact API names, field names, constants, and return behavior.
- Use pseudocode only when clearly labeled.

### Data and measurements

Always include:

- exact values and units
- platform, workload, configuration, software or firmware version
- sample count or run count when available
- baseline and comparison definition
- whether the value is average, median, percentile, min/max, or single observation

Charts must communicate actual values. Do not use decorative charts or unlabeled axes.
When comparing results, state the measured values rather than only saying one is better.

### Failures and root cause

Separate:

- symptom
- trigger
- propagation mechanism
- detection point
- root cause
- corrective action

A root-cause slide must show the causal chain and supporting evidence. Do not present an
untested hypothesis as a confirmed cause.

### Trade-offs and limitations

Include meaningful disadvantages, unsupported scenarios, performance costs, complexity,
compatibility constraints, security implications, and remaining unknowns. A credible
technical deck explains where the proposal or result does not apply.

## Density and readability

Do not apply a universal marketing rule such as "five words per bullet." Technical slides
may be information-dense when the information is structured and readable.

- Prefer diagrams, tables, annotated screenshots, and compact callouts over long prose.
- Split a slide when it contains multiple independent reasoning steps.
- Move raw traces, full tables, code listings, and register dumps to the appendix.
- Keep critical labels readable from presentation distance.
- Do not shrink text to preserve decoration.
- Use speaker notes to preserve explanation without overcrowding the slide.

Visual quality matters, but technical information hierarchy takes priority over novelty.

## Phase 5: Produce the PowerPoint

Use `generic-manipulate-pptx` for all `.pptx` operations.

1. Analyze an existing template when one is supplied.
2. Build native editable text, shapes, tables, charts, and diagrams where practical.
3. Use images for screenshots, plots that cannot be recreated faithfully, and complex
   source figures.
4. Add source footers or numbered references without crowding the body.
5. Add speaker notes containing explanation, transitions, assumptions, and source detail.
6. Add an appendix for evidence that supports questions but is too detailed for the main
   narrative.
7. Render and inspect the deck using the production skill's required QA workflow.

## Phase 6: Technical QA

Perform technical QA separately from visual QA.

### Evidence QA

- Every quantitative or externally verifiable claim has a source.
- Values, units, versions, names, and conditions match the source.
- Derived values can be recomputed from displayed or cited inputs.
- Assumptions and placeholders are visibly labeled.
- Conflicting evidence is not silently resolved.

### Narrative QA

- The audience receives enough background before the deep technical material.
- Architecture and flows are consistent across slides.
- The conclusion follows from the evidence shown.
- Trade-offs, limitations, and open questions are not hidden.
- Core slides do not contradict appendix evidence.

### PowerPoint QA

Follow `generic-manipulate-pptx` for text extraction, slide rendering, overlap detection,
overflow checks, contrast, alignment, and placeholder removal. Fix discovered problems
before delivery.

## Delivery

Deliver:

- the editable `.pptx`
- concise speaker notes inside the deck when requested or useful
- a source list or appendix with traceable references
- a short list of unresolved placeholders, assumptions, or evidence gaps

Do not claim the presentation is technically complete while unsupported values,
unreviewed contradictions, or unresolved rendering defects remain.
