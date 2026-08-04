# OKS Build Troubleshooting

## 1. do_fetch fails due to git-lfs

Symptom:

- Fetcher says repository has LFS content and git-lfs is required.

Action:

- Ensure git-lfs is installed and in PATH.
- Retry the failed task and then full build.

## 2. setup-meta-internal.py fails with BUILDDIR not set

Symptom:

- RuntimeError about BUILDDIR not set.

Action:

- Run after:

  export TEMPLATECONF=openbmc-meta-intel/meta-oks/conf/templates/default
  source ./oe-init-build-env

## 3. local.conf sample version mismatch

Symptom:

- sanity.bbclass says local.conf generated from older/newer sample.

Action:

- Backup build/conf and regenerate by sourcing oe-init-build-env again with TEMPLATECONF set.

## 4. do_image_pfr fails with key/sign errors

Symptom:

- Failed to read eckey rk_pub.pem
- sign operation failed

Action:

1. Run key generation script:
   python3 openbmc-meta-intel/scripts/gen-bmc-sign-keys.py
2. Ensure AIM override is masked in build/conf/local.conf:
   BBMASK += "meta-internal/recipes-intel/external-signing-utility/external-signing-utility-native.bbappend"
3. Run cleansstate:
   bitbake -c cleansstate external-signing-utility-native obmc-intel-pfr-image-native intel-platforms
4. Retry targeted task:
   bitbake -f -c image_pfr intel-platforms
5. Retry full build:
   bitbake intel-platforms

## 5. Tag alignment issues

Symptom:

- openbmc-openbmc and openbmc-meta-intel not on same tag.

Action:

- Checkout both repos to the same tag and verify with git describe --tags --exact-match.
