# HSD Sample Workbook Mapping

## Source Workbook
- Reference workbook filename: `HSD_Sample.xlsx`
- Default: use `HSD_Sample.xlsx` under the skill root when the user does not provide a workbook.
- Override: if the user provides a workbook path, use that workbook instead.
- Workbook sheets: `Sheet1`
- Header row detected on row 1
- Source workbook headers are positioned in `B1:I1`; generated HSD workbooks use columns `A:J`, repurpose column `A` as `HSD ID Number`, insert `Domain` between `Issue title` and `Problem Description`, and place `Source Sighting` in column `J`

## Detected Columns
- `Issue title`
- `Domain`
- `Problem Description`
- `System Configuration & Reproduction Step`
- `Root Cause`
- `Affected Products`
- `Details`
- `Conclusion`
- `Source Sighting`

## Recommended Mapping To HSD Summary
- `Issue description` -> Prefer `Problem Description`
- `Domain` -> Classify by issue description keywords. Prefer canonical labels: `Runtime sPPR`, `legacy IIO stack`, `IOMU`, `TDX`, `DSA`, `MMIO`; use `Other` when unmatched
- `Failure signature` -> Prefer explicit failure wording from the HSD ticket. If the workbook has no direct field, use a short symptom summary from `Problem Description` or `Comments` and mark it as inferred if needed
- `Duplicated configuration` -> Map to `System Configuration & Reproduction Step`
- `Final solution` -> Prefer the explicit fix from the HSD ticket. If the workbook has no direct field, use confirmed fix, workaround, or closure details and place supporting notes in `Comments` when needed
- `Impacted platform` -> Map to `Affected Products`
- `Root cause` -> Map to `Root Cause`, combining confirmed root cause and confirmed fix/workaround as `Root cause: <root cause>; Fix: <fix>` when both are available
- `Details` -> Combine severity, owner, component, status, submitted date, and brief notes
- `Conclusion` -> Classify whether the change should be imported using the four fixed labels: `Cannot import`, `Natural import`, `Suggested import`, or `Need import`
- `Source Sighting` -> Record the concrete source sighting as `<tenant.subject> / <sighting id>`, for example `sighting_central.sighting / 15018902052`

## Output Guidance
- Prefer [invoke-hsd-analysis.ps1](../scripts/invoke-hsd-analysis.ps1) when both Markdown and Excel outputs are required from the same normalized HSD analysis data.
- Use `HSD_Sample.xlsx` by default when the user does not provide a workbook path.
- If the user provides a workbook path, use that workbook's terms and layout instead.
- If the default template is unavailable, generate the workbook with the built-in standard headers instead of failing.
- Create a new workbook for each output file. Do not append rows into the reference workbook itself.
- Copy only the header row text, header row style, and the columns used by the generated output unless the user explicitly asks to copy more of the original formatting.
- Save each generated workbook using the naming rule `HSD_<ticketid>_analysis_<date>.xlsx`, where `<date>` uses `YYYYMMDD`.
- By default, save generated workbooks into the skill's `generated` directory unless the caller overrides the output location.
- If the JSON payload is only a temporary intermediate, the generator can remove it after a successful export when called with `DeleteInputJson`.
- In generated workbooks, set `A1` to `HSD ID Number` and write the ticket ID in column `A` for each data row.
- Use columns `A:J`. Place `Domain` in column `C`, the combined root cause/fix summary in column `F` as `Root Cause`, owner and other ticket metadata in column `H` as `Details`, the import decision in column `I` as `Conclusion`, and the concrete `sighting_central.sighting` source in column `J` as `Source Sighting`.
- Prefer [generate-hsd-workbook.ps1](../scripts/generate-hsd-workbook.ps1) for workbook creation so naming, header layout, and column A behavior stay consistent.
- Use [hsd-analysis-input.example.json](../assets/hsd-analysis-input.example.json) as the unified example input when the one-click script is used to create both `.md` and `.xlsx` outputs.
- Prefer [cleanup-generated.ps1](../scripts/cleanup-generated.ps1) for post-generation cleanup. Its default mode removes `.json` payloads only; add `IncludeWorkbooks` to also remove generated `.xlsx` files and add `IncludeDocuments` to remove generated `.md` result documents.
- If a required HSD field has no matching workbook column, keep the HSD field name in the summary and note the mismatch.
- Do not invent values to fill empty workbook-style columns.
- Separate confirmed ticket facts from inferred wording.

## Workbook Usage Notes
- `Issue title` can hold a short issue name or a workbook-specific title format.
- `Problem Description` is the primary target for the issue narrative.
- `System Configuration & Reproduction Step` is the primary target for reproduction setup.
- `Affected Products` should be used for platform or product impact when the workbook keeps that field.
- `Details` can hold owner and other supporting ticket metadata.
- `Conclusion` should hold a concise import decision, not a long rationale dump.
- `Source Sighting` should hold the resolved source sighting tenant and ID, not the AR ID or writeup ID.

## Caveats
- The workbook does not provide a dedicated `Failure signature` column.
- The workbook does not provide a dedicated standalone `Final solution` column; include the fix/workaround in `Root Cause` together with the root cause.
- `Root Cause` may be empty in some workbooks, so HSD ticket content should remain the primary source for technical conclusions.
- Use these fixed `Conclusion` labels and criteria:
	- `Cannot import`: has negative customer impact and should also be removed when upgrading the codebase, for example a change that hurts performance.
	- `Natural import`: no patch is needed; import it naturally during codebase upgrade because it is neither urgent nor important.
	- `Suggested import`: important but not urgent; import it opportunistically together with other planned changes.
	- `Need import`: urgent and important; field issues, known vulnerabilities, or firmware logic defects require patch import or full upgrade.