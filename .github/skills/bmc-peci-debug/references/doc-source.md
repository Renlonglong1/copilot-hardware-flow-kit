# Document Source

This skill resolves converted PECI reference documents from a user-managed docs root instead of bundled `./assets` content.

Configured docs root:
- not configured

Expected layout:
- <docs-root>/*_searchable/outline.md
- <docs-root>/*_searchable/chapters/
- <docs-root>/*_searchable/chunks/

Resolution rules:
- If the user invokes the skill as `/bmc-peci-debug --docs-root <docs-root> -- <request>`, treat `<docs-root>` as the docs-root override for the current conversation.
- Ask the user for the converted-doc root path before consulting local converted documents when no configured docs root is present.
- Accept either an absolute path or a workspace-relative path that contains `*_searchable/` directories.
- If the user later provides a different docs root, treat that user-supplied path as the active source for the current conversation.
- Keep using chapter files before chunk files unless the chapter files are too coarse.