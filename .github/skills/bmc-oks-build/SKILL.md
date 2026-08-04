---
name: bmc-oks-build
description: 'Build OpenBMC OKS image by tag. Use when user asks to checkout openbmc-openbmc and openbmc-meta-intel to a specific oks tag and run bitbake intel-platforms, including PFR key generation, cleansstate recovery, and do_image_pfr failure handling.'
argument-hint: 'tag=<oks-tag>'
user-invocable: true
---

# BMC OKS Build

Use this skill when you need a repeatable, end-to-end OKS OpenBMC image build from a specific tag across both `openbmc-openbmc` and `openbmc-meta-intel`.

## When To Use

- User asks to build OKS platform image in OpenBMC.
- User provides an OKS tag, for example oks-2026.19.0.
- User wants repeatable end-to-end flow across different OpenBMC workspaces.

## Inputs

- tag: Required. Target tag for both repos, usually oks-*.

## Purpose

This workflow standardizes a local OKS image build and handles common failure points up front:

- synchronized tag checkout in both repositories
- deterministic environment setup
- required PFR key generation
- local build guard for non-AIM environments
- targeted recovery path for `do_image_pfr` and `git-lfs` fetch issues

## Procedure

1. Validate workspace and repos.
2. Checkout both repos to the same tag.
3. Run environment setup.
4. Generate PFR debug signing keys from project script.
5. Ensure build config avoids AIM-only override for external-signing-utility.
6. Run build.
7. If build fails on do_image_pfr or key format, run targeted recovery and rebuild.

## Step Details

1. Validate repo layout

- Ensure current working directory is inside openbmc-openbmc repo.
- Ensure openbmc-meta-intel exists under repo root.
- Ensure tag exists in both repos.

2. Checkout tag in both repos

- In repo root: git fetch --tags origin && git checkout -f tags/<tag>
- In repo root/openbmc-meta-intel: git fetch --tags origin && git checkout -f tags/<tag>
- Verify both are exactly on <tag> via git describe --tags --exact-match.

3. Setup meta-internal and build env
- export TEMPLATECONF=openbmc-meta-intel/meta-oks/conf/templates/default
- source ./oe-init-build-env
- After sourcing, the shell is typically in the build directory.
- From build/, run setup script from openbmc-meta-intel:
  python3 ../openbmc-meta-intel/scripts/setup-meta-internal.py
- If setup fails due to stale conf mismatch, regenerate build/conf from TEMPLATECONF and rerun setup.

4. Generate PFR keys (required for OKS image)

- From build/, run project script:
  python3 ../openbmc-meta-intel/scripts/gen-bmc-sign-keys.py
- This generates ../openbmc-meta-intel/scripts/keys/rk_prv.pem, rk_pub.pem, rk_cert.pem, csk_prv.pem, csk_pub.pem.

5. Apply build guard for offline/non-AIM env

- In build/conf/local.conf ensure this line exists:
  BBMASK += "meta-internal/recipes-intel/external-signing-utility/external-signing-utility-native.bbappend"
- Rationale: prevents forcing AIM service dependency during local build.

6. Build command
- bitbake intel-platforms

## Recovery Logic

If build fails with do_image_pfr, apply the following in order:

1. Re-run key generation script.
2. Run cleansstate on key/signing/image recipes:
- bitbake -c cleansstate external-signing-utility-native obmc-intel-pfr-image-native intel-platforms
3. Re-run targeted task:
- bitbake -f -c image_pfr intel-platforms
4. Re-run full build:
- bitbake intel-platforms

If build fails with git-lfs required during fetch:
1. Ensure git-lfs exists in PATH.
2. If system install is unavailable, install user-local git-lfs and export PATH accordingly.
3. Retry failed fetch task then full build.

## Command Template

Use this as a concise, copy-safe sequence after replacing `<tag>`:

```bash
# repo root: openbmc-openbmc
git fetch --tags origin
git checkout -f tags/<tag>

pushd openbmc-meta-intel
git fetch --tags origin
git checkout -f tags/<tag>
git describe --tags --exact-match
popd

git describe --tags --exact-match

export TEMPLATECONF=openbmc-meta-intel/meta-oks/conf/templates/default
source ./oe-init-build-env
python3 scripts/setup-meta-internal.py
python3 openbmc-meta-intel/scripts/gen-bmc-sign-keys.py

# Ensure local.conf contains the BBMASK guard before building
bitbake intel-platforms
```

## Guardrails

- Keep both repos on the same exact tag before entering build flow.
- Do not skip key generation for OKS images.
- Keep the `BBMASK` guard in local/offline environments to avoid AIM-only override path.
- If the same recovery loop repeats, stop and inspect key files and recipe logs before retrying.

## Suggested Execution Script

Use this script for consistent runs:

- [scripts/build_oks_by_tag.sh](./scripts/build_oks_by_tag.sh)

## Design Documentation

- [references/design.md](./references/design.md)

## Troubleshooting Reference

- [references/troubleshooting.md](./references/troubleshooting.md)