---
name: bmc-skill-migration
description: "Migrate or refresh a skill from openbmc-copilot-tooling into plat-eng-ai-tools. Use when porting a new OpenBMC skill, syncing an already migrated skill with upstream changes, reconciling naming/frontmatter/layout differences, deciding which bundled assets belong in the target repo, or updating the plat-eng-ai-tools skills index after a migration."
argument-hint: "source skill path or name, whether this is a first migration or an update, and optional target skill name"
user-invocable: true
---

# Skill Migration

Use this skill to move a skill from `openbmc-copilot-tooling/skills/<source-skill>/` into `plat-eng-ai-tools/copilot/skills/<target-skill>/` or to refresh an already migrated skill when the upstream source changes.

Treat the migration as an adaptation, not a blind copy.

## Goals

- Preserve the source skill's workflow and guardrails.
- Adapt the skill to `plat-eng-ai-tools` naming and discovery rules.
- Keep only the assets that are useful in the target repo.
- Support both first-time migration and later update/sync work.

## Required Inputs

- Source skill path or source skill name.
- Mode: `initial-migration` or `update-migrated-skill`.
- Optional target skill name when the target should not match the source name.
- Optional scope if the user only wants part of the migration, such as `SKILL.md` only or `scripts` only.

## First Checks

1. Read the source `SKILL.md` and the target repo naming rules before editing.
2. If this is an update, read the existing migrated target skill first and identify any PAE-specific changes that must be preserved.
3. Decide the target skill name before copying files.
4. Confirm whether the source skill depends on bundled scripts, references, assets, or install-time instruction files.

## Naming Rules

- Follow the target repo naming schema from `plat-eng-ai-tools/README.md`.
- Prefer concise kebab-case names in `{domain}-{function}` form.
- For OpenBMC operational skills, prefer the `bmc` domain.
- Use the source name only when it already matches the target repo conventions.

Examples:

- `bmc-mctp-info-dump`
- `bmc-redfish-update`
- `bmc-source-index`
- `bmc-oks-build`

## Migration Workflow

### 1. Classify the source skill

Determine whether the source skill is primarily:

- a workflow-only skill documented mostly in `SKILL.md`
- a script-backed skill with reusable helpers under `scripts/`
- a reference-heavy skill with bundled design or usage docs
- a bootstrap skill that also relies on `instructions/`

This classification decides which folders need to be copied and validated.

### 2. Compare source and target before editing

- For `initial-migration`, inspect the source directory and create the target directory layout intentionally.
- For `update-migrated-skill`, compare source and target contents first.
- Separate differences into three buckets:
  - upstream fixes or behavior changes that should be pulled in
  - target-only PAE adjustments that must stay
  - source packaging content that should remain source-only

Do not overwrite target-specific naming, examples, or integration notes without checking whether they were intentionally adapted for `plat-eng-ai-tools`.

### 3. Copy only the reusable parts

Usually copy these when present:

- `SKILL.md`
- `scripts/`
- `references/`
- `assets/` only when the skill actually uses them
- `instructions/` only when the workflow depends on an installed instruction file in the target repo

Usually do not copy these blindly:

- `CHANGELOG.md`
- source-repo rollout notes
- release-specific metadata
- deploy/install wrappers whose only purpose is publishing assets from `openbmc-copilot-tooling`

If a helper script exists only to deploy packaged files from the source repo into another repo, omit it unless the same deployment behavior is still required in `plat-eng-ai-tools`.

### 4. Rewrite the target `SKILL.md`

Adapt the content instead of dropping in the source file unchanged.

Always do the following:

- normalize the YAML frontmatter for the target repo
- keep the description trigger-focused and explicit
- rewrite any "packaged assets" language so it matches the target repo layout
- update relative links so they resolve inside the target skill directory
- remove source-repo release or rollout instructions that do not apply in the target repo
- preserve workflow-critical guardrails from the source skill

Important example:

- For `openbmc-source-index`, preserve the hard stop on missing `en_env.sh`. Do not weaken that requirement during migration or later updates.

### 5. Update discovery documentation

After creating or refreshing the target skill:

- update `plat-eng-ai-tools/copilot/skills/README.md`
- if the migration introduces a new domain example or naming pattern that the top-level repo README should advertise, update `plat-eng-ai-tools/README.md` too

## Update Workflow For An Already Migrated Skill

When the target skill already exists, use this order:

1. Read the source `SKILL.md` and target `SKILL.md`.
2. Compare source and target scripts or references only if those folders changed or are relevant to the user's request.
3. Pull in upstream fixes with the smallest possible edit.
4. Preserve target-only metadata, naming, and any PAE-specific wording that improves discovery in the target repo.
5. Re-run focused validation on the files that changed.
6. Refresh the skills summary entry if the skill purpose or trigger phrases changed.

Do not replace the entire migrated skill just because the source changed. Merge intentionally.

## Validation

Use the narrowest checks that match the touched files:

- shell scripts: `bash -n`
- Python scripts: `PYTHONDONTWRITEBYTECODE=1 python -m py_compile`
- markdown or frontmatter issues: workspace diagnostics or file-level error checks

If only documentation changed, validate links and metadata consistency, then update the skills summary.

## Completion Checks

The migration is complete only when all of the following are true:

- the target skill folder is self-contained and uses the target repo naming convention
- the target `SKILL.md` is adapted for `plat-eng-ai-tools`, not left as a source-repo bundle description
- any required `scripts/`, `references/`, `assets/`, or `instructions/` were copied intentionally
- source-only rollout or release files were not copied without a reason
- `plat-eng-ai-tools/copilot/skills/README.md` reflects the migrated skill
- focused validation passed for each touched executable file

## Output Expectations

When reporting migration work back to the user, include:

- the source skill path
- the target skill path
- whether the work was an initial migration or an update
- what was copied, rewritten, or intentionally omitted
- what validation ran and whether it passed

If anything was intentionally left different from upstream, explain why.