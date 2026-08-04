---
name: sysdbg-symmarize-hsd-issue
description: 'Analyze Intel HSD issues and summarize issue description, failure signature, duplicated configuration, final solution, impacted platform, and an import recommendation conclusion. Use when the user asks to analyze an HSD ticket, summarize an issue, extract root cause and resolution, find Parent ID, map errata_central.ar tickets back to sighting_central.sighting source sightings, or produce a structured ticket digest. Example usage: "Analyze HSD 13013995575 and output the result." After the Excel file is generated, the user can request cleanup with "Clean up HSD 13013995575 information." Handles tenant.subject validation and resource-scope blockers before summarizing.'
argument-hint: 'HSD ticket number and any known tenant.subject'
user-invocable: true
---

# HSD Issue Analysis

Reference template: [HSD Sample Workbook Mapping](./references/Excel-reference.md)
One-click artifact generator: [invoke-hsd-analysis.ps1](./scripts/invoke-hsd-analysis.ps1)
Workbook generator: [generate-hsd-workbook.ps1](./scripts/generate-hsd-workbook.ps1)
Cleanup utility: [cleanup-generated.ps1](./scripts/cleanup-generated.ps1)
Example input: [hsd-workbook-input.example.json](./assets/hsd-workbook-input.example.json)
Unified analysis input example: [hsd-analysis-input.example.json](./assets/hsd-analysis-input.example.json)

## When to Use
- Analyze a specific HSD ticket and extract a concise technical summary.
- Summarize issue description, failure signature, duplicated configuration (meaning reproduction configuration), final solution, impacted platform, and a `Conclusion` import decision.
- Resolve `errata_central.ar` records to their source `sighting_central.sighting` tenant record through the verified Parent ID / From ID chain.
- Handle cases where HSD access is blocked by missing or incorrect tenant.subject scope.
- Produce a structured digest for firmware, BIOS, or platform issue review.
- Use the skill's MCP-driven HSD lookup to retrieve ticket content, then use the one-click script as the single local step that emits the final `.md` and `.xlsx` artifacts.

## Inputs
- HSD ticket ID.
- Optional tenant.subject if the user already knows it.
- Optional context such as platform, component, or suspected owner.
- Optional parent/source sighting context if the user already has a Parent ID or source sighting ID.
- Optional reference workbook path. If the user does not provide one, the workbook generator first tries `HSD_Sample.xlsx` under the skill root as the default template. If that file is not accessible, the generator still produces the workbook with the built-in standard header layout.

## Procedure
1. Identify the target HSD ticket ID from the user request.
2. Check whether the user already provided a tenant.subject.
3. If tenant.subject is missing, query HSD with the ticket ID first.
4. If the HSD tool returns a ticket-tenant and an allowed tenant.subject list, first normalize both sides into the same canonical tenant.subject form before checking membership.
5. For canonical comparison, treat `tenant.subject`, `tenant__subject`, and case-only differences as equivalent representations of the same tenant.subject.
6. If the normalized ticket-tenant matches any normalized allowed tenant.subject value, use that exact allowed tenant.subject value directly and re-run HSD automatically without asking the user.
7. Only when the normalized ticket-tenant is not represented in the current allowed tenant.subject list, or the tool output is ambiguous and cannot be resolved safely after normalization, present the exact allowed tenant.subject values to the user as an interactive selection list (no free-form input).
8. Use the user's selected tenant.subject value exactly as chosen and re-run the HSD query automatically.
9. If the tool reports the ticket belongs to a different tenant.subject outside the current resource scope, stop and tell the user exactly which tenant.subject must be added to the workspace resources.
10. Default execution mode is fully automatic end-to-end. Do not interrupt with progress prompts unless an error, blocker, or required user decision occurs.
11. Once the ticket content is available, extract the following fields from the ticket body and metadata:
   - Issue description
   - Failure signature
   - Duplicated configuration (reproduction configuration)
   - Final solution
   - Impacted platform
   - Conclusion
12. If the ticket tenant.subject is `errata_central.ar`, resolve the source sighting before artifact generation:
   - Read the AR header field `Parent ID`.
   - Open the Parent ID record. The expected parent tenant.subject is usually `errata_central.writeup`.
   - Read the parent writeup header field `From ID`.
   - Open the From ID record and confirm it is `sighting_central.sighting`.
   - Record `ParentId`, `SourceSightingId`, `SourceSightingTenantSubject`, and `SourceSightingUrl` in the unified analysis JSON.
   - If any hop is inaccessible or missing, state the missing hop explicitly instead of guessing.
13. Normalize the extracted HSD content into the unified analysis JSON shape shown in [hsd-analysis-input.example.json](./assets/hsd-analysis-input.example.json).
14. Use [invoke-hsd-analysis.ps1](./scripts/invoke-hsd-analysis.ps1) as the single artifact-generation step to create both the final Markdown document and the Excel workbook.
15. If the user supplies a reference workbook, pass it through to the one-click script so the workbook generator can mirror that workbook.
16. If the user does not supply a reference workbook and asks for Excel output, the workbook generator first tries `HSD_Sample.xlsx` under the skill root as the format reference.
17. When generating Excel output, create a new workbook every time. Do not append data into the original reference workbook.
18. Preserve only the reference workbook's header definitions and header style unless the user explicitly asks for more formatting to be copied.
19. Name generated Excel files using the fixed pattern `HSD_<ticketid>_analysis_<date>.xlsx`, where `<date>` must use `YYYYMMDD` format.
20. In generated Excel files, use columns `A:J` only.
21. Insert a `Domain` column between `Issue title` and `Problem Description` (between columns `B` and `C`) and classify from issue description text with canonical values such as `Runtime sPPR`, `legacy IIO stack`, `IOMU`, `TDX`, `DSA`, and `MMIO`; use `Other` when no match is found.
22. Set column `A` to `HSD ID Number`.
23. Use column `F` as `Root Cause` and populate it with a combined root cause/fix summary in the format `Root cause: <root cause>; Fix: <fix>`.
24. Use column `H` as `Details` and combine severity, owner, component, status, submitted date, and brief notes there.
25. Use column `I` as `Conclusion` for the import decision.
26. Use column `J` as `Source Sighting`, with values formatted as `<tenant.subject> / <sighting id>` such as `sighting_central.sighting / 15018902052`.
26. If the selected reference workbook is not accessible, say so and continue with the standard output structure unless the user provides a readable path.
27. The built-in standard output structure uses these headers in `A1:J1`: `HSD ID Number`, `Issue title`, `Domain`, `Problem Description`, `System Configuration & Reproduction Step`, `Root Cause`, `Affected Products`, `Details`, `Conclusion`, and `Source Sighting`.
28. If no `OutputDirectory` override is provided to the artifact generator, outputs are saved to the skill's `generated` directory.
29. When the unified analysis JSON is only a temporary intermediate file, the one-click script may be run with `DeleteInputJson` so the source JSON is removed after a successful Markdown and workbook save.
30. Use [cleanup-generated.ps1](./scripts/cleanup-generated.ps1) to clean the `generated` directory safely. By default it removes intermediate `.json` payloads only. It removes `.xlsx` files only when `IncludeWorkbooks` is specified, and removes Markdown result documents only when `IncludeDocuments` is specified.
31. If any field is missing from the ticket, state that it is not explicitly available instead of guessing.
32. Determine `Conclusion` using only these fixed classifications:
   - `Cannot import`: the change has negative customer impact and should also be removed when upgrading the codebase.
   - `Natural import`: no patch import is needed; bring it in naturally during codebase upgrade because it is not urgent and not important.
   - `Suggested import`: the change is important but not urgent; import it opportunistically with other planned changes.
   - `Need import`: the change is urgent and important because known field vulnerabilities or firmware logic defects require patch import or full upgrade.
32. Summarize the ticket in a compact technical format.
33. When the user asks for a result document, continue the flow after tenant.subject resolution without waiting for another confirmation: create the analysis summary, generate the workbook or document artifact, and report the saved path.

## Decision Points
- If the ticket is inaccessible because of tenant.subject scope, do not invent or infer the tenant.subject.
- If a ticket-tenant is provided by the HSD tool, normalize it first and compare it against normalized allowed tenant.subject values before deciding whether user interaction is needed.
- Treat `tenant.subject` and `tenant__subject` as equivalent when checking whether the ticket-tenant is already allowed.
- If the normalized ticket-tenant matches exactly one allowed tenant.subject entry, auto-select that allowed entry and continue without user interaction.
- If multiple tenant.subject values are plausible and cannot be disambiguated safely, ask the user to select one from the exact allowed list returned by the HSD tool.
- When tenant.subject is missing and auto-resolution is not possible after canonical normalization, prefer an interactive chooser with fixed options over a plain text question so the user can continue the workflow in one step.
- Keep execution non-interactive by default; only prompt the user when an explicit selection is required or when an error/blocker occurs.
- If the ticket content is partial, separate confirmed facts from inferred conclusions.
- If the ticket lacks a direct final fix statement, summarize the closest confirmed disposition such as workaround, owner action, or closure rationale.
- Treat duplicated configuration as the reproduction setup needed to reproduce the issue, not as duplicate-ticket linkage, unless the ticket explicitly says otherwise.
- For `errata_central.ar`, treat `Parent ID` as the writeup parent hop, not as the final source sighting. Follow the parent writeup's `From ID` to identify the concrete `sighting_central.sighting` record.
- Only populate `Source Sighting` after confirming the final record's tenant.subject is `sighting_central.sighting`; otherwise report the observed tenant.subject and the unresolved hop in notes.
- Derive `Conclusion` from customer impact, urgency, and importance, and output exactly one of `Cannot import`, `Natural import`, `Suggested import`, or `Need import`.
- Use `Cannot import` when the change would negatively affect customer scenarios and should be removed again during later codebase upgrades.
- Use `Natural import` when the change is neither urgent nor important and should arrive only through normal codebase upgrade, not a patch.
- Use `Suggested import` when the change is important but not urgent and can be carried with other planned code changes.
- Use `Need import` when the change is both urgent and important because a known field vulnerability or firmware logic defect needs patch import or full upgrade.
- If the user provides a reference workbook, prefer its terminology for the final headings.
- If the user does not provide a reference workbook, the workbook generator first tries `HSD_Sample.xlsx` under the skill root as the format baseline.
- Prefer [invoke-hsd-analysis.ps1](./scripts/invoke-hsd-analysis.ps1) as the only artifact-generation entrypoint after HSD content has been normalized into the unified analysis JSON shape.
- If generating an Excel file, do not reuse the reference workbook as the output file. Start from a new workbook and copy only the header row style and column layout needed for compatibility.
- If generating an Excel file, use the filename pattern `HSD_<ticketid>_analysis_<date>.xlsx` consistently, with the date encoded as `YYYYMMDD`.
- If generating an Excel file, populate column `A` with the HSD ID Number, place owner and related ticket metadata in column `G` as `Details`, place the import decision in column `H` as `Conclusion`, and place the resolved `sighting_central.sighting` source in column `I` as `Source Sighting`.
- If the default or user-supplied template is unavailable, continue with the built-in standard header layout instead of failing workbook generation.
- Treat generated `.json` payload files as cleanup-safe intermediates after a successful workbook export unless the user explicitly wants to keep them.
- Treat generated `.xlsx` files as user-facing outputs; only clean them up when the user explicitly asks or when a cleanup command includes workbook removal.
- Treat generated `.md` result documents as user-facing outputs; only clean them up when the user explicitly asks or when a cleanup command includes document removal.

## Output Format
Use this structure:

```markdown
## Ticket Summary
- Ticket ID: <ID>
- Tenant Subject: <tenant.subject>
- Parent ID: <parent writeup ID or omit if not applicable>
- Source Sighting: <sighting_central.sighting / ID or omit if not applicable>

## Analysis
- Issue description: <summary or "Not explicitly stated">
- Failure signature: <summary or "Not explicitly stated">
- Duplicated configuration: <reproduction setup summary or "Not explicitly stated">
- Final solution: <summary or "Not explicitly stated">
- Impacted platform: <summary or "Not explicitly stated">
- Conclusion: <Cannot import | Natural import | Suggested import | Need import | "Not explicitly classified">

## Notes
- Access blockers, ambiguity, or missing information.
```

## Quality Checks
- Confirm the ticket ID matches the user request.
- Confirm the tenant.subject used is explicitly provided by the user or by HSD tool feedback.
- Confirm that ticket-tenant versus allowed-list matching was performed on normalized canonical tenant.subject values, not on raw string equality alone.
- Confirm that when ticket-tenant exists in the allowed list after normalization, it was auto-resolved and executed without prompting the user.
- Confirm that user selection was requested only when auto-resolution was not possible after normalization (ticket-tenant not in allowed list or ambiguous tool output).
- For `errata_central.ar`, confirm the Parent ID was read from the AR header, the parent writeup was opened, and the parent writeup's From ID was opened to confirm the final `sighting_central.sighting` source.
- Do not guess missing fields.
- Separate access failure from content analysis.
- If a reference workbook is requested, confirm whether it was actually readable before claiming workbook-aligned output.
- If the reference workbook was not readable, confirm that the output used the built-in standard header layout instead of copied template styling.
- If generating a workbook, confirm it is a newly created file and that the reference workbook was used only for header style and column mapping.
- If generating a workbook, confirm the saved filename matches `HSD_<ticketid>_analysis_<date>.xlsx` with `YYYYMMDD` date formatting.
- If generating a workbook, confirm column `A` contains the correct HSD ID Number.
- If generating a workbook, confirm the output uses columns `A:J`, that column `C` is `Domain` (classified from issue description), column `F` is `Root Cause` containing the combined root cause/fix summary, column `H` is `Details`, column `I` is `Conclusion`, and column `J` is `Source Sighting`.
- If generating both Markdown and Excel outputs, confirm that both files were produced from the same ticket ID and date stamp.
- If cleanup is performed, confirm whether only `.json` intermediates were removed or whether `.xlsx` workbooks and `.md` documents were also explicitly included.
- Keep the final summary brief and technically precise.

## Example Prompts
- Analyze HSD <ticket-id> and summarize issue description, failure signature, duplicated configuration, final solution, and impacted platform.
- Analyze HSD 13013995575 and output the result.
- Summarize HSD <ticket-id> with root cause and final fix.
- Check why this HSD ticket cannot be queried and tell me which tenant.subject I need.
- Analyze HSD <ticket-id>, let me choose tenant.subject if needed, and continue to generate the final result document.
- Analyze HSD <ticket-id> and use the one-click artifact script to emit both the final `.md` and `.xlsx` outputs.
- For HSD <ticket-id> in errata_central.ar, find the Parent ID and map it back to the source sighting_central.sighting.
- Clean up HSD 13013995575 information.

## Interactive Tenant Flow
- If the initial HSD lookup returns both ticket-tenant and an allowed tenant.subject list, first normalize both sides and then auto-check membership.
- If the normalized ticket-tenant maps to one allowed tenant.subject entry, continue automatically with that exact allowed value and do not prompt the user.
- If the normalized ticket-tenant is not represented in the allowed list, or there is no safe automatic resolution after normalization, show allowed values as fixed options in an interactive picker.
- After the user picks one option, continue the remaining workflow automatically: re-run the HSD query, build the summary, and generate the requested result document if the user asked for one.
- Do not stop after tenant.subject selection unless the HSD tool reports a resource-scope blocker that cannot be resolved from the allowed list.
- Outside required tenant selection and error handling, do not emit intermediate prompts; finish the full workflow and return final outputs.

## Reference Use
- Use `HSD_Sample.xlsx` under the skill root as the first reference workbook source for Excel output.
- If the user provides a workbook path, use that workbook instead.
- Follow the field mapping and output conventions in [HSD Sample Workbook Mapping](./references/Excel-reference.md) unless the user provides a different workbook to mirror.
- For Excel output, create a new workbook and keep only the selected reference workbook's header style and the columns used by the generated output.
- If the reference workbook cannot be opened, continue by generating a new workbook with the built-in headers `HSD ID Number`, `Issue title`, `Domain`, `Problem Description`, `System Configuration & Reproduction Step`, `Root Cause`, `Affected Products`, `Details`, `Conclusion`, and `Source Sighting`.
- Save the generated workbook as `HSD_<ticketid>_analysis_<date>.xlsx`, using `YYYYMMDD` for the date.
- Put `HSD ID Number` in column `A`, the classified `Domain` in column `C`, the combined root cause/fix summary in column `F` as `Root Cause`, `Details` in column `H`, `Conclusion` in column `I`, and `Source Sighting` in column `J`.
- Use [invoke-hsd-analysis.ps1](./scripts/invoke-hsd-analysis.ps1) with a JSON payload shaped like [hsd-analysis-input.example.json](./assets/hsd-analysis-input.example.json) to generate both the Markdown result document and the Excel workbook in one step. Override `TemplatePath` when the user provides a different reference workbook, override `OutputDirectory` when outputs should be saved outside the skill's `generated` directory, and use `DeleteInputJson` when the unified analysis JSON is only a temporary intermediate.
- Use [generate-hsd-workbook.ps1](./scripts/generate-hsd-workbook.ps1) directly only when workbook-only generation is needed.
- Use [cleanup-generated.ps1](./scripts/cleanup-generated.ps1) to remove stale files from the skill's `generated` directory. The default mode removes `.json` payloads only. Add `IncludeWorkbooks` to also remove generated `.xlsx` files, add `IncludeDocuments` to also remove generated `.md` result documents, and use `OlderThanDays` to limit cleanup to older artifacts.