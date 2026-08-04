#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  redfish-bmc-update.sh --bmc <hostname-or-ip> [--image <path>] [--user <name>] [--password <pass>]

Defaults:
  --user debuguser
  --password 0penBmc1
  --image <repo>/build/tmp/deploy/images/intel-ast2600/image-update

Environment overrides:
  BMCIP      Target BMC hostname or IP
  BMC_IMAGE  Image path
  BMC_USER   Username
  BMC_PASS   Password
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if command -v git >/dev/null 2>&1; then
    repo_root="$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null || true)"
fi
repo_root="${repo_root:-$(cd -- "${script_dir}/../../.." && pwd)}"
default_image="${repo_root}/build/tmp/deploy/images/intel-ast2600/image-update"

bmc_host="${BMCIP:-}"
image_path="${BMC_IMAGE:-}"
bmc_user="${BMC_USER:-debuguser}"
bmc_pass="${BMC_PASS:-0penBmc1}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bmc)
            bmc_host="$2"
            shift 2
            ;;
        --image)
            image_path="$2"
            shift 2
            ;;
        --user)
            bmc_user="$2"
            shift 2
            ;;
        --password)
            bmc_pass="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$bmc_host" ]]; then
    echo "error: missing required --bmc value" >&2
    usage >&2
    exit 1
fi

if [[ -z "$image_path" ]]; then
    if [[ -e "$default_image" ]]; then
        image_path="$default_image"
    else
        echo "error: missing --image and default image path was not found: $default_image" >&2
        exit 1
    fi
fi

if [[ ! -r "$image_path" ]]; then
    echo "error: image path is not readable: $image_path" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "error: curl is required but was not found in PATH" >&2
    exit 1
fi

echo "BMC target : $bmc_host"
echo "Image path : $image_path"
echo "Username   : $bmc_user"
echo "Starting Redfish update upload..."

curl --noproxy "$bmc_host" -k --fail-with-body -X POST \
    -u "$bmc_user:$bmc_pass" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@$image_path" \
    "https://$bmc_host/redfish/v1/UpdateService/update"

echo
echo "Redfish update request completed."