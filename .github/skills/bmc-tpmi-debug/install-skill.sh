#!/usr/bin/env bash

set -euo pipefail

skill_name="bmc-tpmi-debug"
script_dir="$({ cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd; })"
source_dir="$script_dir"

force_install=0
global_install=0
workspace_path=""

usage() {
    cat <<'EOF'
Usage:
  ./install-skill.sh [--force] [--global]
  ./install-skill.sh [--force] <workspace-path>

Options:
  --force     Overwrite an existing installed skill
  --global    Install for the current user into ~/.copilot/skills/<name>
  -h, --help  Show this help text

Notes:
  - Without --global, pass a workspace path to install into:
      <workspace>/.github/skills/<name>
  - On Windows, run this script from Git Bash, MSYS2, Cygwin, or WSL.
EOF
}

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

resolve_home() {
    if [[ -n "${HOME:-}" ]]; then
        printf '%s\n' "$HOME"
        return 0
    fi

    if [[ -n "${USERPROFILE:-}" ]]; then
        printf '%s\n' "$USERPROFILE"
        return 0
    fi

    fail 'Unable to determine the current user home directory.'
}

is_windows_shell() {
    case "$(uname -s 2>/dev/null || printf 'unknown')" in
        MINGW*|MSYS*|CYGWIN*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

to_unix_path() {
    local input_path="$1"

    if is_windows_shell && command -v cygpath >/dev/null 2>&1; then
        cygpath -u "$input_path"
    else
        printf '%s\n' "$input_path"
    fi
}

normalize_path() {
    local input_path="$1"

    if is_windows_shell && command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$input_path"
    else
        printf '%s\n' "$input_path"
    fi
}

validate_source_tree() {
    local missing=0
    local required_paths=(
        "SKILL.md"
        "README.md"
        "references/instruction.md"
        "references/workflow.md"
        "references/reflection.md"
        "scripts/README.md"
    )

    local required_path
    for required_path in "${required_paths[@]}"; do
        if [[ ! -e "$source_dir/$required_path" ]]; then
            printf 'Missing required file: %s\n' "$required_path" >&2
            missing=1
        fi
    done

    if [[ "$missing" -ne 0 ]]; then
        fail 'Source skill tree is incomplete.'
    fi
}

copy_tree() {
    local destination="$1"

    mkdir -p "$destination"

    cp "$source_dir/SKILL.md" "$destination/SKILL.md"
    cp "$source_dir/README.md" "$destination/README.md"
    cp "$source_dir/install-skill.sh" "$destination/install-skill.sh"

    rm -rf "$destination/assets" "$destination/references" "$destination/scripts"
    mkdir -p "$destination/references" "$destination/scripts"

    cp -R "$source_dir/references/." "$destination/references/"
    cp -R "$source_dir/scripts/." "$destination/scripts/"

    chmod +x "$destination/install-skill.sh" || true
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            force_install=1
            shift
            ;;
        --global)
            global_install=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --*)
            fail "Unknown option: $1"
            ;;
        *)
            if [[ -n "$workspace_path" ]]; then
                fail 'Only one workspace path can be provided.'
            fi
            workspace_path="$1"
            shift
            ;;
    esac
done

if [[ "$global_install" -eq 1 && -n "$workspace_path" ]]; then
    fail 'Use either --global or a workspace path, not both.'
fi

if [[ "$global_install" -eq 0 && -z "$workspace_path" ]]; then
    fail 'A workspace path is required unless --global is used.'
fi

if [[ "$global_install" -eq 1 ]]; then
    target_dir="$(to_unix_path "$(resolve_home)")/.copilot/skills/$skill_name"
else
    workspace_path="$(to_unix_path "$workspace_path")"
    if [[ ! -d "$workspace_path" ]]; then
        fail "Workspace path does not exist: $(normalize_path "$workspace_path")"
    fi
    workspace_path="$(cd "$workspace_path" && pwd)"
    target_dir="$workspace_path/.github/skills/$skill_name"
fi

if [[ -e "$target_dir" ]]; then
    if [[ "$force_install" -ne 1 ]]; then
        fail "Target already exists: $(normalize_path "$target_dir"). Re-run with --force to overwrite."
    fi

    rm -rf "$target_dir"
fi

validate_source_tree
copy_tree "$target_dir"

printf 'Installed %s to %s\n' "$skill_name" "$(normalize_path "$target_dir")"