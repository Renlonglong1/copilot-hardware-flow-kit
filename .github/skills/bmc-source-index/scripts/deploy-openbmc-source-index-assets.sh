#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
    deploy-openbmc-source-index-assets.sh [--repo PATH] [--force] [--with-doc] [--scripts-only | --instructions-only]

Options:
    --repo PATH           Target OpenBMC repository root. Defaults to the current working directory.
    --force               Overwrite existing files instead of failing.
    --with-doc            Also copy the packaged design document into docs/.
    --scripts-only        Install only the source-index scripts for the initial bootstrap step.
    --instructions-only   Install only the instruction file for the post-generation step.
    -h, --help            Show this help text.
EOF
}

skill_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target_repo="$PWD"
force=0
with_doc=0
scripts_only=0
instructions_only=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            if [[ $# -lt 2 ]]; then
                echo "error: --repo requires a path" >&2
                usage >&2
                exit 1
            fi
            target_repo="$2"
            shift 2
            ;;
        --force)
            force=1
            shift
            ;;
        --with-doc)
            with_doc=1
            shift
            ;;
        --scripts-only)
            scripts_only=1
            shift
            ;;
        --instructions-only)
            instructions_only=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

target_repo="$(realpath "$target_repo")"

if [[ ! -d "$target_repo" ]]; then
    echo "error: target repo does not exist: $target_repo" >&2
    exit 1
fi

if [[ "$scripts_only" -eq 1 && "$instructions_only" -eq 1 ]]; then
    echo "error: --scripts-only and --instructions-only cannot be used together" >&2
    usage >&2
    exit 1
fi

copy_asset() {
    local source_path="$1"
    local target_path="$2"
    local executable="$3"

    mkdir -p "$(dirname -- "$target_path")"

    if [[ -e "$target_path" && "$force" -ne 1 ]]; then
        if cmp -s "$source_path" "$target_path"; then
            printf 'unchanged %s\n' "$target_path"
            return
        fi
        echo "error: target already exists and differs: $target_path" >&2
        echo "hint: rerun with --force to overwrite skill-managed assets" >&2
        exit 1
    fi

    cp "$source_path" "$target_path"
    if [[ "$executable" == "yes" ]]; then
        chmod 755 "$target_path"
    fi
    printf 'installed %s\n' "$target_path"
}

if [[ "$instructions_only" -ne 1 ]]; then
    copy_asset "$skill_dir/scripts/oe-build-source-index" "$target_repo/scripts/oe-build-source-index" yes
    copy_asset "$skill_dir/scripts/oe-find-recipe-source-tree" "$target_repo/scripts/oe-find-recipe-source-tree" yes
    copy_asset "$skill_dir/scripts/oe-remediate-missing-source" "$target_repo/scripts/oe-remediate-missing-source" yes
fi

if [[ "$scripts_only" -ne 1 ]]; then
    copy_asset "$skill_dir/instructions/openbmc-source-index-usage.instructions.md" "$target_repo/.github/instructions/openbmc-source-index-usage.instructions.md" no
fi

if [[ "$with_doc" -eq 1 ]]; then
    copy_asset "$skill_dir/references/build-source-index-design.md" "$target_repo/docs/openbmc-source-index-design.md" no
fi

cat <<EOF
Deployed OpenBMC source-index skill assets into $target_repo

Next steps:
EOF

if [[ "$scripts_only" -eq 1 ]]; then
    cat <<EOF
1. Ensure the repo has en_env.sh or be ready to pass --env-script to scripts/oe-build-source-index and scripts/oe-find-recipe-source-tree.
2. Run scripts/oe-build-source-index --build-dir <build-dir> once to create source-index/. If pn-buildlist is missing and the image cannot be inferred, add --image <image-target>.
3. If needed, run scripts/oe-remediate-missing-source after the first index pass to unpack manifest-selected source-not-unpacked recipes.
4. After source-index/ is created successfully, run this deploy helper again with --instructions-only.
EOF
elif [[ "$instructions_only" -eq 1 ]]; then
    cat <<EOF
1. If the repo has custom Copilot instructions, add a source-index-first rule that references .github/instructions/openbmc-source-index-usage.instructions.md.
2. Use the instruction file only after source-index/ has been created successfully.
EOF
else
    cat <<EOF
1. Ensure the repo has en_env.sh or be ready to pass --env-script to scripts/oe-build-source-index and scripts/oe-find-recipe-source-tree.
2. If you want the staged bootstrap described by the skill, rerun this helper with --scripts-only first and --instructions-only after source-index/ is created successfully.
3. If the repo has custom Copilot instructions, add a source-index-first rule that references .github/instructions/openbmc-source-index-usage.instructions.md.
4. Run scripts/oe-build-source-index --build-dir <build-dir> once to create source-index/. If pn-buildlist is missing and the image cannot be inferred, add --image <image-target>.
5. If needed, run scripts/oe-remediate-missing-source after the first index pass to unpack manifest-selected source-not-unpacked recipes.
EOF
fi