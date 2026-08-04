#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skill_script="${script_dir}/mctp_info_dump.py"

python_bin="${PYTHON_BIN:-python}"
dest_eid="${MCTP_DEST_EID:-8}"
interface="${MCTP_INTERFACE:-i3c}"
source_eid="${MCTP_SOURCE_EID:-0}"
message_type="${MCTP_MESSAGE_TYPE:-0x81}"
ssh_args=()

if [[ -n "${MCTP_SSH_HOST:-}" ]]; then
    ssh_args+=(-H "${MCTP_SSH_HOST}")
fi

if [[ -n "${MCTP_SSH_USER:-}" ]]; then
    ssh_args+=(-u "${MCTP_SSH_USER}")
fi

if [[ -n "${MCTP_SSH_PASSWORD:-}" ]]; then
    ssh_args+=(-p "${MCTP_SSH_PASSWORD}")
fi

exec "${python_bin}" "${skill_script}" \
    "${ssh_args[@]}" \
    -d "${dest_eid}" \
    -i "${interface}" \
    -s "${source_eid}" \
    -m "${message_type}" \
    "$@"