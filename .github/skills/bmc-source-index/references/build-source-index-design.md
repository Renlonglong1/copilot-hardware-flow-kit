# OpenBMC Source Index Design Reference

## 1. Purpose

This document describes a reusable design for generating a filtered, read-only `source-index/` tree in an OpenBMC or OpenEmbedded workspace.

The goal is to make source browsing easier without pretending that every active BitBake recipe produces a useful source tree.

The index is intended for reading, search, and navigation. It is not a replacement for recipe editing workflows such as `devtool modify`, and it is not a replacement for recipe-accurate IntelliSense setup such as `devtool ide-sdk`.

## 2. Problem Statement

In a typical OpenBMC build tree, the active recipe set can be derived from `build/pn-buildlist`, but the corresponding unpacked sources are scattered across many `build/tmp/work/...` directories.

That causes two recurring problems:

- code exploration is slower because related projects are spread across unrelated work directories
- editor indexing is less useful when there is no stable, curated top-level directory containing the meaningful source trees

At the same time, a naive aggregation of every active recipe is noisy and misleading because many active entries are build helpers, native tools, packagegroups, or image-like recipes rather than code a user wants to inspect directly.

## 3. Goals

- Generate a stable browsing surface at `source-index/`
- Generate `build/pn-buildlist` with `bitbake -g <image>` when the active recipe set is missing and the image target is known
- Refresh the generated index on every run so it tracks the current build state
- Include only recipes that are likely to have useful source trees
- Resolve source directories from BitBake metadata instead of guessing `tmp/work` paths
- Preserve one directory per recipe using symlinks rather than copies
- Emit a manifest that explains what was linked, what was skipped, and why
- Avoid running build or unpack tasks by default
- Keep the workflow portable across OpenBMC repositories with different environment bootstrap scripts

## 4. Non-Goals

- Replacing `devtool modify` for source changes
- Replacing `devtool ide-sdk` for recipe-accurate IntelliSense
- Forcing unpack or build tasks during the default run
- Guessing a repository-specific image target when neither `--image` nor deploy artifacts identify it
- Creating a single unified compile database across all recipes
- Flattening all recipe files into one merged directory

## 5. Key Design Decision

The source index should complement `devtool ide-sdk`, not compete with it.

- `devtool ide-sdk` remains the right tool when the user wants build-system-aware IntelliSense for a specific recipe
- `source-index/` is a read-oriented browsing aid for exploring many recipes quickly

This distinction matters because symlinks improve navigation and search, but they do not supply compile flags, generated headers, or recipe-specific sysroot semantics.

## 6. Environment Requirement

The workflow requires a workspace-local `en_env.sh` or an equivalent environment bootstrap script.

That bootstrap is responsible for making the active OpenEmbedded build configuration available by doing things such as:

- setting required environment variables such as `TEMPLATECONF` when applicable
- entering the OpenEmbedded build environment
- making `bitbake`, `bitbake-getvar`, and BitBake Python APIs resolve against the intended build tree

If a repository does not provide `en_env.sh` in a standard location, the workflow should accept an explicit path to an equivalent bootstrap script.

The current implementation also uses repo-root auto-detection when `--repo-root` is not passed. The implemented precedence is:

- nearest ancestor containing `en_env.sh`
- nearest ancestor containing `build/pn-buildlist`
- nearest ancestor containing both `poky/` and `scripts/lib/scriptpath.py`
- fallback nearest ancestor containing `oe-init-build-env` or `scripts/lib/scriptpath.py`

That ordering is intentional. It prevents nested `poky/` trees from being chosen as the repo root in OpenBMC workspaces that vendor OpenEmbedded under `poky/` while also keeping top-level copies of the source-index scripts.

## 7. Existing Helper Pattern

A reusable source-index workflow benefits from a standalone helper like `scripts/oe-find-recipe-source-tree`.

That helper should:

- source `en_env.sh` or an equivalent environment bootstrap script
- resolve `FILE`, `WORKDIR`, `S`, `SRC_URI`, and `SRCREV`
- prefer `bitbake-getvar` when available and fall back to `bitbake -e`
- emit either human-readable details or machine-readable JSON
- report whether the resolved source tree exists

The helper is useful both as:

- a fallback metadata backend for the index generator
- a standalone inspection tool for one recipe

The shipped helper currently supports these modes:

- `--details`
- `--json`
- `--workdir`
- `--env-script PATH`

The implemented CLI rules are:

- `--details` and `--json` are mutually exclusive
- `--json` and `--workdir` are mutually exclusive
- if `--env-script` is omitted and the detected repo root contains `en_env.sh`, the helper uses that automatically
- if no usable bootstrap script can be found, the helper exits with a clear error instead of guessing

## 8. Why The Design Changed

An earlier helper-first design resolved metadata recipe-by-recipe through repeated subprocess calls. That design was easy to reason about, but it scaled poorly in larger OpenBMC workspaces.

The preferred design changed to use a single in-process Tinfoil session as the default metadata path because it:

- amortizes BitBake parse and connection costs across all retained recipes
- keeps metadata resolution inside one Python process
- preserves the same generated output format for users

The helper should remain available as a fallback path rather than being removed.

## 9. Recommended Tool Shape

### 9.1 Scripts

The reusable workflow should normally be implemented with two scripts:

- `scripts/oe-build-source-index`
- `scripts/oe-find-recipe-source-tree`

An optional deploy helper can install those scripts and the related instruction file into a target repo when the repo does not already contain the workflow.

The current deploy helper can install these assets together or in staged mode:

- `scripts/oe-build-source-index`
- `scripts/oe-find-recipe-source-tree`
- `.github/instructions/openbmc-source-index-usage.instructions.md`

It also supports these implemented behaviors:

- `--scripts-only` to install only `scripts/oe-build-source-index` and `scripts/oe-find-recipe-source-tree`
- `--instructions-only` to install only `.github/instructions/openbmc-source-index-usage.instructions.md`
- `--with-doc` to copy the packaged design reference into `docs/`
- `--force` to overwrite differing existing files
- fail-fast behavior when a target file already exists and differs but `--force` was not requested

### 9.2 Recommended Language

Python is the better default language for `oe-build-source-index` because:

- manifest generation is simpler and less fragile
- symlink creation and atomic directory replacement are easier to implement correctly
- filtering and path classification logic are clearer than in shell
- the generator can use BitBake's Python APIs directly while keeping the helper as a subprocess fallback

### 9.3 Minimal CLI Contract

The generator should support a CLI shaped roughly like this:

```text
scripts/oe-build-source-index \
	--build-dir build \
	--output source-index
```

Useful optional flags include:

- `--repo-root`
- `--helper-script`
- `--env-script`
- `--image IMAGE`
- `--no-generate-pn-buildlist`
- `--manifest-name manifest.json`
- `--include-native`
- `--include-packagegroups`
- `--max-recipes N`
- `--metadata-backend auto|tinfoil|helper`
- `--verbose`

Default behavior should be:

- rebuild the generated output on every run
- stage results in a temporary sibling directory
- atomically replace the previous index
- in `auto` mode, try one Tinfoil session first and fall back to the helper backend if that fails
- pass `--env-script` only to the helper backend
- if `pn-buildlist` is missing, create it with `bitbake -g <image>` after sourcing `en_env.sh` or `--env-script`
- infer `<image>` only when deploy artifacts identify exactly one image target; otherwise require `--image`
- refuse to use the build directory itself as the output directory
- require the output parent directory to exist before generation starts

Deferred options for later iterations might include:

- `--unpack-missing`
- `--include-regex`
- `--exclude-regex`
- `--format jsonl`

## 10. Output Layout

The generated tree should be explicit and unsurprising.

```text
source-index/
	manifest.json
	recipes/
		bash -> ../../build/tmp/work/.../bash/5.2.37/bash-5.2.37
		bmcweb -> ../../build/tmp/work/.../bmcweb/1.0+git/git
	skipped/
		reasons.txt
```

Notes:

- `recipes/` contains one symlink per included recipe
- no file contents are copied
- `skipped/reasons.txt` is optional but useful for quick inspection without opening JSON
- `manifest.json` is the source of truth
- the whole tree is treated as generated state and may be fully replaced on the next run

## 11. Filtering Rules

Filtering should happen before metadata resolution where possible.

### 11.1 Default Name-Based Skip Rules

Skip recipes whose names match patterns like:

- `*-native`
- `nativesdk-*`
- `*-cross`
- `*-crosssdk*`
- `*-cross-canadian*`
- `packagegroup-*`
- image-like entries such as names that start with `image`, end with `-image`, or contain `-image-`

Repositories may add repo-specific image names to that default filter set.

### 11.2 Metadata-Based Skip Rules

After resolving metadata, skip entries when:

- the recipe does not expose a usable `do_unpack` task
- `S` is empty
- the resolved `S` path does not exist on disk
- the resolved path exists but is clearly not a meaningful source tree

The last rule should be conservative. A practical default is:

- accept the entry if `S` exists and is a directory
- do not overfit the filter logic to repo-specific expectations too early

For `do_unpack` capability, the current implementation distinguishes between:

- `no-do-unpack` when `do_unpack` is not present in the recipe task list
- `do-unpack-disabled` when `do_unpack` exists but is marked `noexec`

These entries remain in the manifest as `status: "missing-source"` with a more specific `skip_reason` so downstream remediation can avoid retrying them.

### 11.3 Special Cases

- If `S` resolves into `build/workspace/`, include the entry and mark the source origin as `workspace`
- If `S` resolves under `build/tmp/work/`, mark the source origin as `tmp-work`
- If `S` resolves outside those areas, include it and mark the source origin as `external`
- If multiple recipes resolve to the same `S`, keep separate manifest entries and generate unique link names only when required

## 12. Manifest Schema

The manifest should be machine-readable and sufficient for later tooling.

### 12.1 Top-Level Structure

```json
{
	"schema_version": 1,
	"generated_at": "2026-04-10T00:00:00Z",
	"repo_root": "/path/to/openbmc-repo",
	"build_dir": "/path/to/openbmc-repo/build",
	"output_dir": "/path/to/openbmc-repo/source-index",
	"pn_buildlist": "/path/to/openbmc-repo/build/pn-buildlist",
	"pn_buildlist_generated": false,
	"pn_buildlist_image": null,
	"refresh_mode": "full-regeneration",
	"metadata_backend": "tinfoil",
	"helper_script": "/path/to/openbmc-repo/scripts/oe-find-recipe-source-tree",
	"env_script": "/path/to/openbmc-repo/en_env.sh",
	"summary": {
		"total_candidates": 0,
		"filtered_before_resolution": 0,
		"resolved": 0,
		"linked": 0,
		"skipped_missing": 0,
		"skipped_other": 0
	},
	"entries": []
}
```

The manifest should include at least:

- `schema_version`
- `generated_at`
- `repo_root`
- `build_dir`
- `output_dir`
- `pn_buildlist`
- `pn_buildlist_generated`
- `pn_buildlist_image`
- `refresh_mode`
- `metadata_backend`
- `helper_script`
- `env_script`
- `summary`
- `entries`

In the current implementation, `helper_script` is always recorded in the manifest and `env_script` is recorded as either an absolute path or `null`.

### 12.2 Entry Structure

```json
{
	"recipe": "bmcweb",
	"status": "linked",
	"skip_reason": null,
	"link_name": "bmcweb",
	"link_path": "/path/to/openbmc-repo/source-index/recipes/bmcweb"
}
```