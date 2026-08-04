# OKS OpenBMC Build Skill Design

## 1. Purpose

This document explains the design of the `bmc-oks-build` skill so maintainers and users can understand:

- Why each step exists
- How recovery is handled
- Which assumptions are intentionally scoped to OKS only
- How to extend the flow safely

## 2. Scope

In scope:

- Build Intel OKS image for OpenBMC using `bitbake intel-platforms`
- Dual-repo tag alignment (`openbmc-openbmc` and `openbmc-meta-intel`)
- Environment setup and key generation required by current OKS flow
- Deterministic failure recovery for known blockers

Out of scope:

- Non-OKS platforms (DNL, GLR, etc.)
- Production key provisioning policy
- CI orchestration and pipeline integration

## 3. Inputs and Outputs

Inputs:

- `tag`: target release tag (for example `oks-2026.19.0`)

Not an input anymore:

- `repo` is intentionally removed. The skill auto-discovers the current repo root via git and runs in the active `openbmc-openbmc` workspace.

Primary output:

- Successful completion of `bitbake intel-platforms`

Secondary outputs:

- Diagnostic path for failed tasks
- Reusable troubleshooting actions

## 4. Workflow Architecture

The workflow is stateful and recovery-driven.

Stages:

1. Source alignment
2. Environment setup
3. PFR key material preparation
4. Build execution
5. Failure detection and targeted recovery
6. Rebuild and final verification

Design principle:

- Prefer narrow remediation over full clean rebuild.

## 5. Rationale By Stage

### 5.1 Source alignment by tag

Both repos are explicitly checked out to the same tag to avoid mixed metadata/runtime combinations.

### 5.2 Setup

`TEMPLATECONF` + `oe-init-build-env` creates consistent build config.
`setup-meta-internal.py` handles expected internal layer integration for this environment.

### 5.3 PFR key generation

The skill always uses project-local generation (`openbmc-meta-intel/scripts/gen-bmc-sign-keys.py`) to avoid dependence on host-global key material.

### 5.4 BBMASK guard

`meta-internal` can override `external-signing-utility` with AIM-dependent behavior.
For local/offline reproducibility, the override is masked:

- `BBMASK += "meta-internal/recipes-intel/external-signing-utility/external-signing-utility-native.bbappend"`

### 5.5 Recovery-first build strategy

Known failure classes are addressed by targeted actions:

- `git-lfs` fetch failures
- `do_image_pfr` key/sign failures
- stale sstate reuse of wrong key artifacts

## 6. Recovery Matrix

### Case A: Fetch failure requiring git-lfs

Symptoms:

- fetcher indicates LFS object dependency

Actions:

1. Ensure `git-lfs` is available in `PATH`
2. Retry failed fetch/recipe
3. Resume full build

### Case B: `do_image_pfr` failure with key parsing/signing

Symptoms:

- `Failed to read eckey rk_pub.pem`
- `sign operation failed`

Actions:

1. Regenerate keys via `gen-bmc-sign-keys.py`
2. Run cleansstate:
   - `external-signing-utility-native`
   - `obmc-intel-pfr-image-native`
   - `intel-platforms`
3. Force rerun `image_pfr`:
   - `bitbake -f -c image_pfr intel-platforms`
4. Run full build again

Why cleansstate:

- Prevent stale sysroot/sstate from reusing old key artifacts.

## 7. Reusability Strategy

The skill is designed to be reused across OpenBMC workspaces because it:

- Accepts tag as parameter and auto-discovers current repo root via git
- Uses repository-local scripts and configuration
- Avoids hard-coding one workspace layout beyond required dual-repo structure

## 8. Safety and Change Guidelines

When updating this skill:

- Keep recovery steps idempotent
- Avoid deleting global caches unless unavoidable
- Keep BBMASK decision explicit and documented
- Prefer adding new failure cases to troubleshooting docs before widening default behavior

## 9. Known Constraints

- Assumes workspace includes `openbmc-openbmc/openbmc-meta-intel`
- Assumes invocation happens from within an `openbmc-openbmc` git working tree
- Assumes tag exists in both repos
- Assumes user environment can run bitbake and required tooling

## 10. Suggested Future Extensions

- Add optional `machine` parameter when OKS variants diverge
- Add non-interactive log summarizer for failed tasks
- Add optional artifact collection report after success
