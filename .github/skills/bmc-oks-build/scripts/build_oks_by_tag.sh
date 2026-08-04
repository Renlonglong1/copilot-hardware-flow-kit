#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <oks-tag>"
  exit 2
fi

TAG="$1"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
META_INTEL_DIR="$REPO_ROOT/openbmc-meta-intel"

if [[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT/.git" ]]; then
  echo "ERROR: run this script inside an openbmc-openbmc git workspace"
  exit 2
fi

if [[ ! -d "$META_INTEL_DIR/.git" ]]; then
  echo "ERROR: missing repo $META_INTEL_DIR"
  exit 2
fi

echo "[1/8] Checkout tag in openbmc-openbmc"
cd "$REPO_ROOT"
git fetch --tags origin
git checkout -f "tags/$TAG"


echo "[2/8] Checkout tag in openbmc-meta-intel"
cd "$META_INTEL_DIR"
git fetch --tags origin
git checkout -f "tags/$TAG"


echo "[3/8] Verify both repos on exact tag"
cd "$REPO_ROOT"
git describe --tags --exact-match >/dev/null
cd "$META_INTEL_DIR"
git describe --tags --exact-match >/dev/null


echo "[4/8] Generate PFR keys from project script"
cd "$REPO_ROOT"
python3 openbmc-meta-intel/scripts/gen-bmc-sign-keys.py


echo "[5/8] Prepare build env"
export TEMPLATECONF="openbmc-meta-intel/meta-oks/conf/templates/default"
# shellcheck disable=SC1091
source "$REPO_ROOT/oe-init-build-env" > /dev/null


echo "[6/8] Run setup-meta-internal"
cd "$META_INTEL_DIR"
python3 scripts/setup-meta-internal.py || true


echo "[7/8] Ensure BBMASK for AIM-only override"
cd "$REPO_ROOT"
if ! grep -q "external-signing-utility-native.bbappend" build/conf/local.conf; then
  echo 'BBMASK += "meta-internal/recipes-intel/external-signing-utility/external-signing-utility-native.bbappend"' >> build/conf/local.conf
fi


echo "[8/8] Build with recovery"
# shellcheck disable=SC1091
source "$REPO_ROOT/oe-init-build-env" > /dev/null
if ! bitbake intel-platforms; then
  echo "Initial build failed, applying PFR recovery flow"
  python3 "$REPO_ROOT/openbmc-meta-intel/scripts/gen-bmc-sign-keys.py"
  bitbake -c cleansstate external-signing-utility-native obmc-intel-pfr-image-native intel-platforms
  bitbake -f -c image_pfr intel-platforms
  bitbake intel-platforms
fi

echo "Build completed successfully for tag: $TAG"