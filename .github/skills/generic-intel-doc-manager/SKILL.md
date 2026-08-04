---
name: intel-doc-manager
description: "Use when downloading, updating, browsing, or validating Intel cdrdv2 / internal BIOS-related documents by Doc ID, platform, or curated common-document list. Trigger phrases: Intel doc download, update document folder, common documents, Doc ID lookup, BIOS documents, document manager, cdrdv2 download, re-login browser, list common documents."
argument-hint: "Provide document IDs, platform/category filters, output folder, local folder, or whether you want the GUI."
---

# Intel Doc Manager

This skill is the dedicated Intel document retrieval and folder-refresh workflow. It covers download/update operations, the curated common-document list, and the GUI/browser login flow. After documents are local, use the workflow guidance below for document search, register lookup, and report generation with the appropriate local search or document-generation tools.

## Tools

The `tools/` folder lives beside this `SKILL.md`, so all examples below use relative paths.

| Friendly name | Canonical file | Primary use |
|---|---|---|
| Intel Doc Manager CUI | `tools/intel_doc_manager_cui.py` | Automated document download, organized common-document browsing, and folder refresh |
| Intel Doc Manager GUI | `tools/intel_doc_manager_gui.pyw` | Interactive document download/update, organized common-document browsing, and credential refresh |

## When To Use This Skill

Use this skill when the user wants one or more of these actions as one document workflow:

- Download Intel documents by Doc ID.
- Download or update a curated common-document set by platform/category, with optional platform/category subfolder organization in both GUI and CUI.
- Refresh a local document folder and keep the latest version per Doc ID.
- Browse common documents by platform/category instead of copying IDs manually.
- Launch the GUI for manual selection, folder browsing, or credential refresh.

Use the dedicated `bios-firmware-decoder` skill for BIOS binary decode or patch workflows.

## Decision Rules

1. Search local files first when the user is asking a question about a document and has not explicitly asked to download or update.
2. If the needed document is not local, ask before downloading it, unless the user already authorized retrieval.
3. Prefer the CUI for repeatable automation and the GUI for manual browsing or browser re-login; both support organized common-document downloads.
4. For common documents, use the curated list and platform/category filters instead of hardcoding IDs in the answer.
5. Default to direct download without `relogin`.
6. If a download fails because authentication is stale or the browser session is invalid, ask the user whether to run `relogin` before retrying.
7. When a user asks for the latest local copy, use folder refresh; when they ask for a known Doc ID, use direct download.
8. If the user provides an explicit document ID, skip common-document lookup and call the CUI download path directly.
9. If the user provides only a document description or document name, first match it against `COMMON_DOCUMENTS` in `tools/intel_doc_manager_gui.pyw`, then download the matched document.

## Required Inputs

Collect only the missing inputs needed for the requested phase:

- `doc_ids`: explicit Intel Doc IDs to download or refresh.
- `platform`: common-document platform filter, such as OKS, BHS, EGS, Whitley, or Generic.
- `category`: optional common-document category filter.
- `output_dir`: destination directory for downloaded documents.
- `folder`: local folder to refresh.
- `interactive`: whether to launch the GUI.

## Workflow

### Automated Document Operations

Use the CUI for automation and repeatable updates:

```powershell
python tools\intel_doc_manager_cui.py --help
python tools\intel_doc_manager_cui.py list-common --platform OKS
python tools\intel_doc_manager_cui.py download-common --platform OKS --category Tools --out <output_dir>
python tools\intel_doc_manager_cui.py download-common --platform OKS --category Tools --out <output_dir> --organize
python tools\intel_doc_manager_cui.py download --doc-id <doc_id...> --out <output_dir>
python tools\intel_doc_manager_cui.py update-folder --folder <folder>
python tools\intel_doc_manager_cui.py relogin
```

Default behavior for download commands:

1. Run `download` or `download-common` without `--relogin` first.
2. If the download fails due to login or authentication, pause and ask the user whether to run `relogin`.
3. Only retry with `--relogin` after the user agrees.

Useful variants:

```powershell
python tools\intel_doc_manager_cui.py download --doc-id <doc_id> --out <output_dir> --force
python tools\intel_doc_manager_cui.py download --doc-id <doc_id> --out <output_dir> --relogin
python tools\intel_doc_manager_cui.py update-folder --folder <folder> --force
python tools\intel_doc_manager_cui.py update-folder --folder <folder> --doc-id <doc_id...>
```

### GUI Entry

```powershell
pythonw tools\intel_doc_manager_gui.pyw
```

### Common-Document Lookup

Use the common-document list when the user wants platform/category-based browsing:

```powershell
python tools\intel_doc_manager_cui.py list-common
python tools\intel_doc_manager_cui.py list-common --platform OKS --category Tools
python tools\intel_doc_manager_cui.py download-common --platform BHS --category RAS --out <output_dir>
python tools\intel_doc_manager_cui.py download-common --platform BHS --category RAS --out <output_dir> --organize
```

If the user asks for a document that is missing from the curated list, do not invent a Doc ID. Ask whether downloading the relevant document is allowed and then retrieve it.

## Document Search And Register Lookup

Use this workflow when the user asks to search document content, locate a register, explain a register field, or answer a spec question from downloaded documents:

1. Identify the most likely source documents first, such as EDS, BWG, IVG, RAS, debug handbook, or MoW.
2. Search local files first unless the user explicitly asked to download or update documents.
3. If the needed document is not local, ask the user for permission to download the relevant document before using the CUI. Explain that the download is needed to answer the register, spec, or document question.
4. If the document is local but may be stale, use the local copy by default and mention the staleness risk; ask before refreshing unless the user requested the latest content.
5. Search exact register names, aliases, field names, acronyms, table titles, and nearby section headers.
6. For register questions, capture register purpose, offset or address when present, field and bit definitions, access attributes, reset or default values, and platform applicability.
7. If multiple documents disagree, report the conflict and prefer the newest or most authoritative source by document type and revision.
8. Cite the source document path and page or section context in the final answer when available.

## Report Generation

Use this skill to turn downloaded Intel technical documents into a polished user-facing report when the user asks for a report, review, summary, or analysis deliverable.

Preferred output:

- PDF for most report and review requests.
- PPT when the user explicitly asks for slides or a deck.

Recommended report flow:

1. Extract the relevant pages or sections from the source document.
2. Summarize the requested changes, issues, or register details.
3. Build a polished PDF or PPT instead of stopping at Markdown unless the user explicitly asks for Markdown only.
4. Include tables, key findings, and a simple diagram when the flow is non-trivial.

If a user asks for a user-facing report, the final deliverable should be ready for review by a user, manager, or customer.

## User-Facing Report Requirements

When generating a report, include the following structure when it fits the request:

1. Cover page with title, source document, Doc ID, and week or revision.
2. Executive summary.
3. Update index table from the Contents page when available.
4. Issue update sections.
5. BKC or release update tables.
6. Tools or debug update table.
7. Action items.

For complex flows, include a diagram in the report. Good diagram candidates include:

- Seamless update or rollback sequences.
- BIOS or MCU update order.
- Error injection setup requirements.
- Root-cause chains from version mismatch to stale training data.

Use a simple flowchart if that is sufficient. Use the `generic-fireworks-tech-graph` skill for complex SVG or PNG diagrams, or render an inline SVG or HTML flowchart before PDF export.

Report generation options:

- PDF via HTML plus Playwright `page.pdf()`: good default because Playwright is already required by the CUI tool.
- PDF via `generic-minimax-pdf`: use when a highly polished design system is needed.
- PPT via `generic-manipulate-pptx`: use when the user explicitly requests slides or a deck.

For HTML plus Playwright PDF:

1. Create a styled `.html` report with tables and diagrams.
2. Use Playwright Chromium to export a PDF.
3. Verify the PDF with `pypdf.PdfReader` and report page count.

## Verification

Always verify after downloading or updating documents:

- Confirm the target files exist in the output directory or refreshed folder.
- Include the final output folder in the response.
- If the command downloaded multiple files, summarize any missing, failed, or current documents.
- If download/authentication fails, retry with `relogin` or launch the GUI and complete sign-in.
- For report generation, confirm the PDF or PPT exists and mention the validation performed, such as page count or successful export.

## Final Response Format

For completed operations, report:

- Requested document IDs or filters.
- Output folder or refreshed folder.
- Any missing, skipped, or failed documents.
- Verification summary, including whether the requested files were found or updated.
- For report or analysis requests, also include the report path, source document path, and a short summary of key findings.
