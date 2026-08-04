# Assets

Store source materials used by this skill.

Use this directory only for small sample inputs or skill-owned reference assets. For normal conversions, write generated searchable document artifacts to the user-provided output path instead of this skill directory.

Recommended layout:

- `Intel_doc/raw_PDF/`: source Intel PDF files for batch conversion
- `Intel_doc/*_searchable/`: generated refined Markdown output folders created by the conversion script
	- `chapters/`: chapter-oriented Markdown for reading
	- `chunks/`: page-range Markdown for broader search
	- `tables/`: one Markdown file per extracted table for focused table lookup

Typical workflow:

1. Put original PDF files under the user-provided raw PDF directory.
2. Run `scripts/convert_pdf_to_searchable_md.py` from this skill directory or an installed copy of this skill.
3. Keep generated refined output under the user-provided output root, usually as `*_searchable/` folders.
4. Review generated `outline.md`, `chapters/`, `chunks/`, `tables/`, and output `README.md` under each searchable folder.

Keep large binaries here instead of `references/`.