#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="bmc-intel-doc-transfer"
TARGET_ROOT="${HOME}/.copilot/skills"
TARGET_DIR="${TARGET_ROOT}/${SKILL_NAME}"
MODE="link"
FORCE_INSTALL=0

usage() {
  cat <<'EOF'
Usage: ./install-skill.sh [--copy] [--link] [--global] [--force] [--name <skill-name>] [--target-root <dir>]

Install this repository as a local GitHub Copilot skill.

Options:
  --copy                Copy files into the target skill directory.
  --link                Symlink the repository into the target skill directory. Default.
  --global              Install to ~/.copilot/skills for the current user.
  --force               Overwrite an existing installation if present.
  --name <skill-name>   Override the installed skill folder name.
  --target-root <dir>   Override the skill root directory. Default: ~/.copilot/skills
  -h, --help            Show this help message.
EOF
}

require_value() {
  local option="$1"
  local value="${2-}"
  if [[ -z "$value" ]]; then
    echo "Missing value for ${option}" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --copy)
      MODE="copy"
      shift
      ;;
    --link)
      MODE="link"
      shift
      ;;
    --global)
      TARGET_ROOT="${HOME}/.copilot/skills"
      shift
      ;;
    --force)
      FORCE_INSTALL=1
      shift
      ;;
    --name)
      require_value "$1" "${2-}"
      SKILL_NAME="$2"
      shift 2
      ;;
    --target-root)
      require_value "$1" "${2-}"
      TARGET_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

TARGET_DIR="${TARGET_ROOT}/${SKILL_NAME}"

require_file() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "Required path not found: $path" >&2
    exit 1
  fi
}

require_file "${SCRIPT_DIR}/SKILL.md"
require_file "${SCRIPT_DIR}/scripts"
require_file "${SCRIPT_DIR}/assets"
require_file "${SCRIPT_DIR}/references"

mkdir -p "$TARGET_ROOT"

if [[ -e "$TARGET_DIR" || -L "$TARGET_DIR" ]]; then
  if [[ "$FORCE_INSTALL" -ne 1 ]]; then
    cat <<EOF >&2
Target already exists: ${TARGET_DIR}
Re-run with --force to overwrite the existing installation.
EOF
    exit 1
  fi
  rm -rf "$TARGET_DIR"
fi

if [[ "$MODE" == "copy" ]]; then
  cp -a "$SCRIPT_DIR" "$TARGET_DIR"
else
  ln -s "$SCRIPT_DIR" "$TARGET_DIR"
fi

if [[ -f "${SCRIPT_DIR}/scripts/convert_pdf_to_searchable_md.py" ]]; then
  chmod +x "${SCRIPT_DIR}/scripts/convert_pdf_to_searchable_md.py"
fi

cat <<EOF
Installed skill: ${SKILL_NAME}
Mode: ${MODE}
Target: ${TARGET_DIR}
Force install: ${FORCE_INSTALL}

Next checks:
  1. Ensure pdftohtml is installed and available in PATH.
  2. Restart or reload Copilot Chat if the new skill does not appear immediately.
EOF