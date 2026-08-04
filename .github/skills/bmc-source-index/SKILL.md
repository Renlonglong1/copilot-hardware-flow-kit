---
name: bmc-source-index
description: "Build, refresh, and use a read-only source-index of unpacked recipe sources in OpenBMC/OpenEmbedded workspaces. Use it before deeper recipe-source lookup when you need to browse recipe source trees quickly."
argument-hint: "en_env.sh path, optional build dir, optional recipe/module name"
user-invocable: true
---

# BMC Source Index

Use this skill when you need a stable, editor-friendly view of unpacked recipe source trees in an OpenBMC or OpenEmbedded workspace.

## Purpose

The `source-index/` tree is a generated, read-only browsing surface that symlinks each retained recipe to its resolved source directory.

Use it to:

- browse unpacked recipe sources without jumping through `tmp/work/...` manually
- search code across many retained recipes from one stable top-level directory
- check quickly whether a target recipe source is already unpacked before doing deeper recipe or layer analysis

Do not use it as a replacement for `devtool modify`, recipe patch workflow, or recipe-accurate IntelliSense setup.

## First Checks

1. Check whether the repo root provides `en_env.sh`.
2. If `en_env.sh` is missing, stop immediately, ask the user explicitly for the `en_env.sh` path or contents, and print the example from `references/en_env.sh.example` to the user.
3. Check whether the top-level `source-index/` already exists.
4. If the target source is already present under `source-index/recipes/`, use that first.
5. If the top-level `source-index/` is missing and `en_env.sh` is present, run the source-index generator directly once.
6. If `build/pn-buildlist` is missing, the generator may create it with `bitbake -g <image>`; pass `--image <target>` when the active image cannot be inferred from deploy artifacts.
7. If the target is still missing after one refresh, stop repeating the same process and switch to direct recipe metadata/source investigation instead.

## Environment Bootstrap Requirement

This skill depends on a workspace-specific `en_env.sh`.

Purpose of `en_env.sh`:

- set any required workspace variables such as `TEMPLATECONF`
- enter the OpenEmbedded build environment
- make `bitbake`, `bitbake-getvar`, and BitBake Python APIs resolve the active build configuration correctly

Ask for `en_env.sh` explicitly when it is not already available in the repository root.

Do not accept any non-`en_env.sh` bootstrap script for this workflow.

If `en_env.sh` is missing, stop immediately and print the example from `references/en_env.sh.example` to the user when asking for it.

Reference example: [references/en_env.sh.example](./references/en_env.sh.example)

## Recommended Workflow

1. Detect the repo root and look for `en_env.sh` there.
2. If `en_env.sh` is missing, stop immediately, ask the user explicitly for its path or contents, and print the example from `references/en_env.sh.example` to the user.
3. Check the top-level `source-index/` first.
4. If `source-index/recipes/<target>` is present, browse that path instead of rebuilding the index.
5. If the workspace does not already contain the source-index scripts, use the packaged deploy helper at [deploy-openbmc-source-index-assets.sh](./scripts/deploy-openbmc-source-index-assets.sh) with `--scripts-only`, but do not install the instruction file yet.
6. If the top-level `source-index/` is absent and `en_env.sh` is available, run `scripts/oe-build-source-index` directly once.
7. If the index exists but is stale or the target source is missing, generate or refresh it once.
8. After `source-index/` is created successfully, install the packaged instruction file into `.github/instructions/`.
9. Prefer a batched BitBake metadata path, such as a single Tinfoil session, over per-recipe subprocess lookups.
10. Keep the helper lookup path available as a fallback and as a standalone inspection tool.
11. Write a manifest and skipped report so the generated state is explainable.
12. If `pn-buildlist` is absent, allow the generator to run `bitbake -g <image>` only after `en_env.sh` is available and an image is either supplied with `--image` or inferred unambiguously from deploy artifacts.
13. If the desired source is still missing after one refresh, move to direct recipe lookup rather than looping on index regeneration.

## Packaged Assets

This skill ships reusable workspace assets under its own directory so it can bootstrap a new OpenBMC repo instead of only documenting the process.

- `scripts/oe-build-source-index`: reusable generator with batched Tinfoil metadata loading and helper fallback
- `scripts/oe-find-recipe-source-tree`: reusable standalone helper with optional `--env-script`
- `scripts/oe-remediate-missing-source`: optional remediation helper that unpacks manifest-selected `source-not-unpacked` recipes and skips `no-do-unpack` / `do-unpack-disabled`
- `scripts/deploy-openbmc-source-index-assets.sh`: installs the packaged scripts, the instruction file, or both into a target repo; use `--scripts-only` for bootstrap and `--instructions-only` after successful index creation
- `instructions/openbmc-source-index-usage.instructions.md`: instruction file to install into `.github/instructions/`
- `references/build-source-index-design.md`: packaged design reference

## Deployment In A New Repo

When this skill is used in an OpenBMC repo that does not already contain the source-index workflow:

1. Ask for `en_env.sh` if the repo does not already provide it.
2. If `en_env.sh` is missing, stop immediately and print the example from `references/en_env.sh.example` to the user.
3. Install only the packaged source-index scripts into the target repo.
4. If `en_env.sh` is present and the top-level `source-index/` is absent, run `scripts/oe-build-source-index` directly once.
5. Otherwise, generate or refresh `source-index/` once.
6. If sources are still marked `source-not-unpacked`, run `scripts/oe-remediate-missing-source` once as a follow-up.
7. After `source-index/` is created successfully, install `instructions/openbmc-source-index-usage.instructions.md` into `.github/instructions/`.
8. If the repo uses repo-specific Copilot instructions, add or update a source-index-first rule to reference the deployed instruction file.

Example script-only bootstrap command:

```bash
./copilot/skills/bmc-source-index/scripts/deploy-openbmc-source-index-assets.sh --repo /path/to/openbmc-repo --scripts-only
```

Example direct generation command after script bootstrap:

```bash
scripts/oe-build-source-index --env-script /path/to/en_env.sh --image <image-target>
```

The `--image` argument is only required when `build/pn-buildlist` is missing and the image target cannot be inferred from existing deploy artifacts.

Example remediation command after the first index pass:

```bash
scripts/oe-remediate-missing-source --env-script /path/to/en_env.sh
```

Example instruction-file install after successful generation:

```bash
./copilot/skills/bmc-source-index/scripts/deploy-openbmc-source-index-assets.sh --repo /path/to/openbmc-repo --instructions-only
```

## Expected Outputs

- `source-index/manifest.json`
- `source-index/recipes/`
- `source-index/skipped/reasons.txt`

## Design Reference

See [references/build-source-index-design.md](./references/build-source-index-design.md).

## Fallback Behavior

If a workspace does not already contain the source-index tooling:

- if `en_env.sh` is missing, stop immediately and print the example from `references/en_env.sh.example` to the user
- deploy the packaged source-index scripts with `./copilot/skills/bmc-source-index/scripts/deploy-openbmc-source-index-assets.sh --scripts-only`
- if `en_env.sh` is present and the top-level `source-index/` is absent, run `scripts/oe-build-source-index` directly once
- if sources are still marked `source-not-unpacked`, run `scripts/oe-remediate-missing-source` once as a follow-up
- if `build/pn-buildlist` is missing, pass `--image <target>` unless the active image can be inferred from deploy artifacts
- after `source-index/` is created successfully, deploy the packaged `.github/instructions/openbmc-source-index-usage.instructions.md` with `./copilot/skills/bmc-source-index/scripts/deploy-openbmc-source-index-assets.sh --instructions-only`
- keep the output read-only and generated under `source-index/`

## Anti-Loop Rule

If a target source is missing from `source-index/`:

- if `source-index/` does not exist and `en_env.sh` is present, run the generator directly once
- otherwise run the source-index generation workflow once
- do not keep repeating the same refresh in a loop
- after one refresh, switch to direct recipe metadata lookup, unpack/build guidance, or ask the user for the missing build/environment inputs