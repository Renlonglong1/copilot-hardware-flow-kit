#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SKILL_SOURCE="$SCRIPT_DIR/SKILL.md"
README_SOURCE="$SCRIPT_DIR/README.md"

scope=""
workspace_root="$SCRIPT_DIR"
force=0
docs_root=""
skill_name=""
skill_description=""

usage() {
  cat <<EOF
Usage:
  ./install-skill.sh --workspace [--workspace-root <path>] [--docs-root <path>] [--force]
  ./install-skill.sh --global [--docs-root <path>] [--force]

Options:
  --workspace              Install into <workspace>/.github/skills/<skill-name>
  --global                 Install into ~/.copilot/skills/<skill-name>
  --workspace-root <path>  Workspace root used with --workspace
  --docs-root <path>       External converted-doc root containing *_searchable/ directories
  --force                  Replace an existing target directory
  -h, --help               Show this message
EOF
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

strip_matching_quotes() {
  local value="$1"

  if [[ ${#value} -ge 2 ]]; then
    if [[ ${value:0:1} == '"' && ${value: -1} == '"' ]]; then
      value=${value:1:${#value}-2}
    elif [[ ${value:0:1} == "'" && ${value: -1} == "'" ]]; then
      value=${value:1:${#value}-2}
    fi
  fi

  printf '%s' "$value"
}

load_skill_metadata() {
  local line=""
  local line_number=0
  local in_frontmatter=0
  local found_closing_delimiter=0

  [[ -f "$SKILL_SOURCE" ]] || fail "skill source file not found: $SKILL_SOURCE"

  while IFS= read -r line || [[ -n "$line" ]]; do
    ((line_number += 1))

    if [[ $line_number -eq 1 ]]; then
      [[ "$line" == "---" ]] || fail "SKILL.md must start with YAML frontmatter delimited by ---"
      in_frontmatter=1
      continue
    fi

    if [[ $in_frontmatter -eq 1 && "$line" == "---" ]]; then
      found_closing_delimiter=1
      break
    fi

    if [[ $in_frontmatter -eq 1 && "$line" =~ ^name:[[:space:]]*(.+)$ ]]; then
      skill_name=$(trim_whitespace "${BASH_REMATCH[1]}")
      skill_name=$(strip_matching_quotes "$skill_name")
      continue
    fi

    if [[ $in_frontmatter -eq 1 && "$line" =~ ^description:[[:space:]]*(.+)$ ]]; then
      skill_description=$(trim_whitespace "${BASH_REMATCH[1]}")
      skill_description=$(strip_matching_quotes "$skill_description")
      continue
    fi
  done < "$SKILL_SOURCE"

  [[ $found_closing_delimiter -eq 1 ]] || fail "SKILL.md frontmatter is missing the closing --- delimiter"
  [[ -n "$skill_name" ]] || fail "SKILL.md frontmatter must define a non-empty name"
  [[ "$skill_name" =~ ^[a-z0-9-]{1,64}$ ]] || fail "skill name must match ^[a-z0-9-]{1,64}$"
  [[ -n "$skill_description" ]] || fail "SKILL.md frontmatter must define a non-empty description"
}

ensure_directory() {
  local path="$1"
  [[ -d "$path" ]] || fail "directory not found: $path"
}

resolve_directory() {
  local path="$1"

  ensure_directory "$path"
  (
    cd "$path"
    pwd
  )
}

copy_optional_file() {
  local source_path="$1"
  local destination_path="$2"

  if [[ -f "$source_path" ]]; then
    cp "$source_path" "$destination_path"
  fi
}

copy_optional_dir() {
  local source_dir="$1"
  local destination_dir="$2"

  if [[ -e "$source_dir" && ! -d "$source_dir" ]]; then
    fail "expected directory but found non-directory path: $source_dir"
  fi

  if [[ -d "$source_dir" ]]; then
    mkdir -p "$destination_dir"
    cp -R "$source_dir/." "$destination_dir/"
  fi
}

prune_generated_content() {
  local root_dir="$1"

  find "$root_dir" \
    \( -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' \) \) \
    -prune -exec rm -rf {} +

  find "$root_dir" \
    -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) \
    -delete
}

write_doc_source_file() {
  local destination_path="$1"

  mkdir -p "$(dirname "$destination_path")"

  if [[ -n "$docs_root" ]]; then
    cat > "$destination_path" <<EOF
# Document Source

This skill resolves converted PECI reference documents from a user-managed docs root instead of bundled \`./assets\` content.

Configured docs root:
- $docs_root

Expected layout:
- $docs_root/*_searchable/outline.md
- $docs_root/*_searchable/chapters/
- $docs_root/*_searchable/chunks/

Resolution rules:
- If the user invokes the skill as /bmc-peci-debug --docs-root <docs-root> -- <request>, treat <docs-root> as the docs-root override for the current conversation.
- Use the configured docs root above before asking the user for a path.
- If the user explicitly provides a different docs root at runtime, treat the user-supplied path as an override for that conversation.
- Keep using chapter files before chunk files unless the chapter files are too coarse.
EOF
    return
  fi

  cat > "$destination_path" <<'EOF'
# Document Source

This skill resolves converted PECI reference documents from a user-managed docs root instead of bundled `./assets` content.

Configured docs root:
- not configured

Expected layout:
- <docs-root>/*_searchable/outline.md
- <docs-root>/*_searchable/chapters/
- <docs-root>/*_searchable/chunks/

Resolution rules:
- If the user invokes the skill as /bmc-peci-debug --docs-root <docs-root> -- <request>, treat <docs-root> as the docs-root override for the current conversation.
- Ask the user for the converted-doc root path before consulting local converted documents.
- Accept either an absolute path or a workspace-relative path that contains `*_searchable/` directories.
- If the user later provides a different docs root, treat that user-supplied path as the active source for the current conversation.
- Keep using chapter files before chunk files unless the chapter files are too coarse.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      [[ -n "$scope" ]] && fail "choose only one of --workspace or --global"
      scope="workspace"
      shift
      ;;
    --global)
      [[ -n "$scope" ]] && fail "choose only one of --workspace or --global"
      scope="global"
      shift
      ;;
    --workspace-root)
      [[ $# -lt 2 ]] && fail "--workspace-root requires a value"
      workspace_root="$2"
      shift 2
      ;;
    --docs-root)
      [[ $# -lt 2 ]] && fail "--docs-root requires a value"
      docs_root="$2"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "$scope" ]] || fail "missing install scope: use --workspace or --global"
load_skill_metadata

if [[ -n "$docs_root" ]]; then
  docs_root=$(resolve_directory "$docs_root")
fi

if [[ "$scope" == "global" ]]; then
  target_root="$HOME/.copilot/skills"
else
  ensure_directory "$workspace_root"
  target_root="$workspace_root/.github/skills"
fi

target_dir="$target_root/$skill_name"

if [[ -e "$target_dir" ]]; then
  if [[ "$force" -ne 1 ]]; then
    fail "target already exists: $target_dir (use --force to replace it)"
  fi

  rm -rf "$target_dir"
fi

mkdir -p "$target_dir"
cp "$SKILL_SOURCE" "$target_dir/SKILL.md"
copy_optional_file "$README_SOURCE" "$target_dir/README.md"
copy_optional_dir "$SCRIPT_DIR/references" "$target_dir/references"
copy_optional_dir "$SCRIPT_DIR/scripts" "$target_dir/scripts"
write_doc_source_file "$target_dir/references/doc-source.md"
prune_generated_content "$target_dir"

printf 'Installed skill to %s\n' "$target_dir"
printf 'Skill name: %s\n' "$skill_name"
if [[ -n "$docs_root" ]]; then
  printf 'Docs root: %s\n' "$docs_root"
else
  printf 'Docs root: not configured (the skill will ask the user at runtime)\n'
fi
if [[ "$scope" == "global" ]]; then
  printf 'Scope: global (~/.copilot/skills)\n'
else
  printf 'Scope: workspace (.github/skills)\n'
fi