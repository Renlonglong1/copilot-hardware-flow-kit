# Personal Preferences and Troubleshooting Lessons

Use this document to retain reusable working preferences and validated troubleshooting lessons. Add only information that is actionable and safe to store; never record passwords, tokens, cookies, private keys, or other credentials.

## Reporting Preferences

- Deliver two complementary outputs for hardware reproduction work:
  - Email body: a detailed, staff-facing working conclusion focused on test results, key evidence, investigation findings, unresolved risks, and next validation direction.
  - Markdown report: the complete execution record, including reasoning, machine/BKC matching, environment comparison, operations, commands, artifact paths, measured results, and limitations.
- When lab and customer environments differ, run feasible issue-relevant tests on a compatible platform. Report the local measurement and material differences; do not claim a quantitative match to the customer without matching evidence.
- **Context**: automatic IPS Query reference selection. **Preference or lesson**: assess every successfully fetched IPS independently in AI batches, then render only the AI-ranked Top N cards. `int_sighting_url` and `close_reason=internal_*` are strong internal-evidence weights, not hard admission gates; rank primarily from concrete symptom/trigger/impact and reusable diagnosis, root cause, fix, workaround, reproduction, or debug content. Do not merge Query records or infer a common root cause. **Scope**: verified workflow rule.
- **Context**: automatic IPS Query reference selection. **Preference or lesson**: the full-automation form must offer **仅生成共性报告**. When selected, perform exactly one read-only Query pass to produce the Top IPS reference report, including linked `int_sighting_url` context; do not process Open IPS, invoke Debug, acquire hardware resources, poll, or send notifications. **Scope**: verified workflow rule.

## Validation Preferences

- For MLC, retain complete host-side result logs, not only serial interaction or command completion markers.
- Treat saved result-file `EXIT:0` evidence as the completion criterion; do not rely on echoed serial markers alone.

## How to Maintain This File

For each new lesson, record:

1. **Context**: platform, workflow, or problem type.
2. **Preference or lesson**: the reusable action or decision rule.
3. **Evidence**: report path, log path, or validation date when available.
4. **Scope**: whether it is a personal preference, a verified rule, or an unverified hypothesis.

Keep platform-specific operational details in their existing reference documents and add a short link here only when the lesson is broadly reusable.
