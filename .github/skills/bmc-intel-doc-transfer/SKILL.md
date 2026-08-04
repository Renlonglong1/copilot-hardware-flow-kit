---
name: bmc-intel-doc-transfer
description: "Use when converting Intel PDF documents into searchable Markdown with outline.md and chapter-based chunks for BMC/PECI/TPMI debug consumption. Trigger phrases: BMC Intel PDF conversion, PDF to Markdown, searchable spec artifacts, outline.md, chapter chunks, convert_pdf_to_searchable_md.py."
argument-hint: "Provide a source PDF path or raw-PDF directory and the converted Markdown output path."
user-invocable: true
---

# BMC Intel Doc Transfer

## Purpose

Convert Intel PDF documents into searchable Markdown artifacts that are easier for GitHub Copilot to read, search, and cite during development and validation workflows.

The conversion flow is centered on the packaged script at `scripts/convert_pdf_to_searchable_md.py` beside this `SKILL.md`. When this skill is invoked from `plat-eng-ai-tools`, use the repository copy under `copilot/skills/bmc-intel-doc-transfer/scripts/convert_pdf_to_searchable_md.py`; when installed elsewhere, use the equivalent linked or copied skill path. Do not generate a replacement converter script, notebook, or ad hoc one-off implementation when this script already exists and is runnable. Only modify or replace the script if the user explicitly asks for that change or validation proves the existing script cannot satisfy the requested conversion.

It produces:

- `outline.md` extracted from PDF bookmarks or synthesized headings
- `chapters/` with chapter-based Markdown files
- `chunks/` with page-range Markdown chunks
- `README.md` index inside each generated output folder

## When to Use

- The user wants to ingest Intel PDF specifications into a Copilot-friendly text format.
- The task requires converting one PDF or a batch of PDFs into Markdown.
- The user wants output split into `chapters/` plus an `outline.md` file.
- The user needs searchable workspace artifacts before asking technical questions about a spec.
- The user can provide the source raw PDF path and the converted output path to use.

Do not use this skill when:

- The source document is already clean Markdown.
- The user only wants a summary and does not need reusable converted artifacts.

## Workflow

1. Confirm the exact input and output paths with the user.
	For batch conversion, require the user to provide the raw PDF directory path.
	For single-file conversion, require the user to provide the source PDF file path.
	In both modes, require the user to provide the output directory or output root path for converted Markdown artifacts.

2. Verify prerequisites.
	The conversion script requires `pdftohtml` to be available in `PATH`.

3. Choose conversion mode.
	Use batch mode when the user provides a raw PDF directory path and a target output root path.
	Use single-file mode when the user provides a specific PDF path and a target output directory path.

4. Run the converter.
	Main script: `scripts/convert_pdf_to_searchable_md.py`
	Before doing any implementation work, check whether this skill directory already contains this script and use it as the default execution path.
	Do not write a new conversion program just because the current workspace does not contain the script; the skill's own installed files are the source of truth.
	Do not assume default input or output paths when the user has not explicitly provided them.

5. Validate generated artifacts.
	Check that the output directory contains:
	`outline.md`, `chapters/`, `chunks/`, and output `README.md`.

6. Use the converted Markdown for follow-up tasks.
	Prefer `outline.md` to identify the right section first, then read the matching chapter file.

## Script Usage

Always execute the existing skill script first. Treat new converter generation as an exception, not the default path.

Single PDF:

```bash
python3 scripts/convert_pdf_to_searchable_md.py <input.pdf> <output_dir>
```

Batch mode:

```bash
python3 scripts/convert_pdf_to_searchable_md.py --raw-dir <raw_pdf_dir> --output-root <output_root>
```

Useful options:

- `--chunk-size <n>` to control page count per chunk
- `--first-page <n>` and `--last-page <n>` to limit the PDF page range
- `--title <text>` to override the document title in single-file mode
- `--raw-dir <dir>` to change the batch input directory
- `--output-root <dir>` to change the batch output base directory

## Required User Inputs

Before running the conversion, collect these paths from the user:

- Batch mode: `raw_PDFs` directory path and converted output root path
- Single-file mode: source PDF file path and converted output directory path

If the user does not provide both the source path and the destination path, ask for them before running the script.

## References

- `scripts/convert_pdf_to_searchable_md.py`: main conversion entrypoint
- `assets/`: source document area
- `references/`: supporting notes or extracted document references