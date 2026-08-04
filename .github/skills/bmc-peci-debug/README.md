# BMC PECI Debug Skill
Skill for debugging PECI issues by asking targeted questions, generating commands, and analyzing outputs.

## Overview

This skill is intended to help with PECI debug sessions. It can guide troubleshooting, help construct PECI commands, and analyze returned results against expectations.

The repository is organized around a lightweight skill entrypoint and referenced support material:

- `SKILL.md`: discovery metadata, use cases, and the high-level procedure that routes to the deeper references.
- `references/workflow.md`: the authoritative PECI workflow, decision points, and failed-command reflection guidance.
- `references/doc-source.md`: converted-doc source resolution rules and expected searchable-doc layout.

This repo copy does not depend on bundled `assets/`. Point it at an external converted-doc root that contains the generated `*_searchable/` directories.

## Configure the document source

Preferred flow: pass the external converted-doc root at runtime with `--docs-root`, or configure it in `references/doc-source.md` for a local install.

The skill also supports a runtime override on invocation:

```text
/bmc-peci-debug --docs-root /my/source/path -- <your PECI question>
```

In that form, the `--docs-root` argument selects the converted-doc source for the current conversation and the `--` separator marks where the actual PECI request begins.

Expected external layout:

- `<docs-root>/*_searchable/outline.md`
- `<docs-root>/*_searchable/chapters/`
- `<docs-root>/*_searchable/chunks/`

If no default docs root is configured at install time, the skill will ask the user for the path when it needs local converted documents.

## Converted document layout

Keep converted reference documents under your chosen external docs root. The docs root should contain sibling `*_searchable/` directories for each converted document set.

### Install to current workspace

```bash
./install-skill.sh --workspace --docs-root /path/to/Intel_doc
```

### Install to global Copilot skills

```bash
./install-skill.sh --global --docs-root /path/to/Intel_doc
```

### Optional flags

- `--workspace-root /path/to/workspace`
- `--docs-root /path/to/Intel_doc`
- `--force`
