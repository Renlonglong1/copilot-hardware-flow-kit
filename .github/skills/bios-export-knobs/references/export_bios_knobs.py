#!/usr/bin/env python3
"""Export BIOS setup knobs from HFR/VFR into JSON and XLSX."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

PLATFORM_ROOTS = {
    "EGS": Path(r"D:/Code/Gen2"),
    "BHS": Path(r"D:/Code/ServerGen3"),
    "OKS": Path(r"D:/Code/dmr_bios"),
}

HEADERS = [
    "knob name",
    "knob variable",
    "description",
    "knob options",
    "default value",
    "menu path",
    "hfr file location",
    "dependency",
]

QUESTION_TYPES = ("oneof", "checkbox", "numeric", "orderedlist", "string", "date", "time")

EXCLUDED_PLATFORM_DIRS_BY_PLATFORM = {
    "OKS": {
        "FishhawkFallsRpPkg",
        "LoganvilleRpPkg",
        "GnrwsRpPkg",
        "KaseyvilleRpPkg",
        "DunlowPlatSamplePkg",
        "NovaLakePlatSamplePkg",
        "Features",
        "NovaLakeRestrictedPkg",
        "SummitvilleRpPkg",
    },
}

EXCLUDED_PLATFORM_DIRS_GLOBAL = {
    "FishhawkFallsRpPkg",
    "LoganvilleRpPkg",
    "GnrwsRpPkg",
    "KaseyvilleRpPkg",
    "DunlowPlatSamplePkg",
    "NovaLakePlatSamplePkg",
    "Features",
    "NovaLakeRestrictedPkg",
    "SummitvilleRpPkg",
}

QUESTION_START_RE = re.compile(r"^\s*(oneof|checkbox|numeric|orderedlist|string|date|time)\b", re.IGNORECASE)
VARID_RE = re.compile(r"varid\s*=\s*([^,;\n]+)", re.IGNORECASE)
TOKEN_RE = re.compile(r"STRING_TOKEN\(([^)]+)\)", re.IGNORECASE)
HELP_RE = re.compile(r"\bhelp\s*=\s*STRING_TOKEN\(([^)]+)\)", re.IGNORECASE)
PROMPT_RE = re.compile(r"\bprompt\s*=\s*STRING_TOKEN\(([^)]+)\)", re.IGNORECASE)
OPTION_RE = re.compile(
    r"option\s+text\s*=\s*STRING_TOKEN\(([^)]+)\)\s*,\s*value\s*=\s*([^,;\n]+)(?:\s*,\s*flags\s*=\s*([^;\n]+))?",
    re.IGNORECASE,
)
NUMERIC_MIN_RE = re.compile(r"\bminimum\s*=\s*([^,;\n]+)", re.IGNORECASE)
NUMERIC_MAX_RE = re.compile(r"\bmaximum\s*=\s*([^,;\n]+)", re.IGNORECASE)
NUMERIC_STEP_RE = re.compile(r"\bstep\s*=\s*([^,;\n]+)", re.IGNORECASE)
INLINE_DEFAULT_RE = re.compile(r"\bdefault\s*=\s*([^,;\n]+)", re.IGNORECASE)
DEFINE_RE = re.compile(r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*$")
FORM_START_RE = re.compile(r"^\s*form\b", re.IGNORECASE)
FORM_TITLE_RE = re.compile(r"\btitle\s*=\s*STRING_TOKEN\(([^)]+)\)", re.IGNORECASE)
FORM_END_RE = re.compile(r"^\s*endform\s*;?\s*$", re.IGNORECASE)
COND_START_RE = re.compile(r"^\s*(suppressif|grayoutif|disableif|inconsistentif|nosubmitif)\b(.*)", re.IGNORECASE)
COND_END_RE = re.compile(r"^\s*endif\s*;?\s*$", re.IGNORECASE)
DEFAULT_LINE_RE = re.compile(r"^\s*([^|\s]+)\s*\|\s*([^|\n]+)")
FIELD_COMMENT_RE = re.compile(r"^\s*(?:UINT\d+|INT\d+|BOOLEAN|CHAR\d+|UINTN|INTN)\s+([A-Za-z_][A-Za-z0-9_]*)\s*;\s*//\s*(.+)$")
COMMENT_NUM_RE = re.compile(r"(0x[0-9A-Fa-f]+|\d+)")


@dataclass
class OptionItem:
    text: str
    value: str
    is_default: bool


@dataclass
class KnobRow:
    knob_name: str
    knob_variable: str
    description: str
    knob_options: str
    default_value: str
    menu_path: str
    hfr_file_location: str
    dependency: str
    sort_file: str
    sort_line: int

    def as_dict(self) -> dict[str, str]:
        return {
            "knob name": self.knob_name,
            "knob variable": self.knob_variable,
            "description": self.description,
            "knob options": self.knob_options,
            "default value": self.default_value,
            "menu path": self.menu_path,
            "hfr file location": self.hfr_file_location,
            "dependency": self.dependency,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export BIOS knob options to Excel")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORM_ROOTS.keys()))
    parser.add_argument("--bios-path", default=None, help="BIOS source path; defaults to current directory")
    parser.add_argument("--output", required=True, help="Output .xlsx path")
    parser.add_argument("--json-output", default=None, help="Optional JSON output path")
    return parser.parse_args()


def normalize_path(path_text: str | None, cwd: Path) -> Path:
    if not path_text:
        return cwd
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()


def is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def split_comment(line: str) -> tuple[str, str]:
    if "//" not in line:
        return line.rstrip(), ""
    code, comment = line.split("//", 1)
    return code.rstrip(), comment.strip()


def load_uni_tokens(root: Path) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for uni in root.rglob("*.uni"):
        try:
            content = uni.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in content:
            m = re.search(r"#string\s+([A-Za-z0-9_]+)\b.*?\"(.*)\"", line)
            if not m:
                continue
            token = m.group(1).strip()
            text = m.group(2).replace('\\"', '"').strip()
            if token and text and token not in tokens:
                tokens[token] = text
    return tokens


def load_macros(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    defaults: dict[str, str] = {}
    all_macros: dict[str, str] = {}
    patterns = ("*.h", "*.inc", "*.dsc", "*.txt")
    for pattern in patterns:
        for path in root.rglob(pattern):
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line in lines:
                code, _ = split_comment(line)
                m = DEFINE_RE.match(code)
                if not m:
                    continue
                key = m.group(1).strip()
                value = m.group(2).strip()
                all_macros[key] = value
                if not key.endswith("_DEFAULT"):
                    continue
                defaults[key] = value
    return defaults, all_macros


def load_struct_defaults(root: Path) -> dict[str, str]:
    """Load defaults from generated/source setup default files by field name."""
    struct_defaults: dict[str, str] = {}
    patterns = (
        "*SetupDefault*.dsc*",
        "*PreBuildSetupPcdDefaults*.inc",
    )
    for pattern in patterns:
        for path in root.rglob(pattern):
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line in lines:
                code, _ = split_comment(line)
                m = DEFAULT_LINE_RE.match(code)
                if not m:
                    continue
                lhs = m.group(1).strip()
                rhs = m.group(2).strip()
                if "." not in lhs:
                    continue
                field = normalize_field_name(lhs.split(".")[-1]).lower()
                if field and field not in struct_defaults:
                    struct_defaults[field] = rhs
    return struct_defaults


def load_comment_defaults(root: Path) -> dict[str, str]:
    """Load defaults from struct field comments that annotate '(default)'."""
    comment_defaults: dict[str, str] = {}
    for path in root.rglob("*.h"):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            m = FIELD_COMMENT_RE.match(line)
            if not m:
                continue
            field = normalize_field_name(m.group(1)).lower()
            comment = m.group(2).strip()
            default_value = extract_default_from_comment(comment)
            if not default_value:
                continue
            if field not in comment_defaults:
                comment_defaults[field] = default_value
    return comment_defaults


def extract_default_from_comment(comment: str) -> str:
    """Extract numeric default from comments like '...; 2 - AUTO (default)'"""
    segments = re.split(r"[;]", comment)
    for seg in segments:
        if "default" not in seg.lower():
            continue
        nums = COMMENT_NUM_RE.findall(seg)
        if nums:
            return nums[-1]

    # Fallback: if only one numeric token exists and comment says default, use it.
    if "default" in comment.lower():
        nums = COMMENT_NUM_RE.findall(comment)
        if len(nums) == 1:
            return nums[0]

    return ""


def token_text(token: str, tokens: dict[str, str]) -> str:
    return tokens.get(token.strip(), token.strip())


def resolve_symbol(symbol: str, macros: dict[str, str], depth: int = 0) -> str:
    if depth > 8:
        return symbol
    value = macros.get(symbol)
    if value is None:
        return symbol
    value = value.strip().split()[0]
    if value == symbol:
        return symbol
    if value in macros:
        return resolve_symbol(value, macros, depth + 1)
    return value


def format_hex_if_int(text: str, macros: dict[str, str]) -> str:
    raw = text.strip()
    if re.fullmatch(r"0x[0-9A-Fa-f]+", raw):
        return f"0x{int(raw, 16):x}"
    if re.fullmatch(r"\d+", raw):
        return f"0x{int(raw):x}"
    if raw in macros:
        resolved = resolve_symbol(raw, macros)
        if re.fullmatch(r"0x[0-9A-Fa-f]+", resolved):
            return f"0x{int(resolved, 16):x}"
        if re.fullmatch(r"\d+", resolved):
            return f"0x{int(resolved):x}"
    return raw


def camel_to_upper_snake(name: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", spaced)
    return spaced.upper()


def normalize_field_name(name: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", name).strip()


def short_var(varid: str) -> str:
    cleaned = varid.strip()
    parts = [normalize_field_name(p) for p in cleaned.split(".") if p.strip()]
    if not parts:
        return cleaned

    tail = parts[-1].strip()
    # Template-driven structures often end with generic names (Value/Access).
    if tail.lower() in {"value", "access", "enable", "disable"} and len(parts) > 1:
        return parts[-2].strip()
    return tail


def extract_varid_expression(block_text: str) -> str:
    """Extract varid expression while tolerating commas inside macro calls."""
    m = re.search(r"\bvarid\s*=", block_text, re.IGNORECASE)
    if not m:
        return ""

    i = m.end()
    expr_chars: list[str] = []
    depth = 0
    while i < len(block_text):
        ch = block_text[i]
        if ch == "(":
            depth += 1
            expr_chars.append(ch)
        elif ch == ")":
            if depth > 0:
                depth -= 1
            expr_chars.append(ch)
        elif ch == "," and depth == 0:
            break
        elif ch == "\n" and depth == 0:
            break
        elif ch == ";" and depth == 0:
            break
        else:
            expr_chars.append(ch)
        i += 1

    return "".join(expr_chars).strip()


def template_var_candidates(var_text: str) -> list[str]:
    """Return possible field-name candidates from template-style var text."""
    candidates: list[str] = []
    text = var_text.strip()
    if not text:
        return candidates

    # CONCATENATE2(Foo, BAR) -> Foo
    m = re.match(r"CONCATENATE\d+\(([^,\)]+)", text, re.IGNORECASE)
    if m:
        base = normalize_field_name(m.group(1).strip())
        if base:
            candidates.append(base)

    # Cpu ## SKT ## ... ## KtiLinkSpeed -> KtiLinkSpeed
    if "##" in text:
        tokens = [normalize_field_name(t.strip()) for t in text.split("##") if t.strip()]
        if tokens:
            candidates.append(tokens[-1])

    # Last dotted token as an additional fallback.
    parts = [normalize_field_name(p) for p in text.split(".") if p.strip()]
    if parts:
        candidates.append(parts[-1])

    # De-dup, preserve order.
    out: list[str] = []
    for c in candidates:
        if c and c not in out:
            out.append(c)
    return out


def lookup_struct_default(candidates: list[str], struct_defaults: dict[str, str]) -> str:
    """Find default by exact/prefix match from candidate field names."""
    if not candidates:
        return ""
    keys = list(struct_defaults.keys())
    for c in candidates:
        ck = c.lower()
        if ck in struct_defaults:
            return struct_defaults[ck]

        # Prefix match for indexed variants: SataPortController -> SataPortController0
        prefix_hits = [k for k in keys if k.startswith(ck)]
        if prefix_hits:
            # Deterministic selection; usually all controller variants share same default.
            pick = sorted(prefix_hits)[0]
            return struct_defaults[pick]
    return ""


def extract_condition_text(code_line: str) -> str:
    m = COND_START_RE.match(code_line)
    if not m:
        return ""
    keyword = m.group(1).lower()
    rest = m.group(2).strip()
    if rest.endswith(";"):
        rest = rest[:-1].rstrip()
    if rest.startswith("ideq") or rest.startswith("id"):
        return f"{rest} ({keyword})"
    return f"{rest} ({keyword})" if rest else keyword


def parse_option_items(block_lines: list[str], tokens: dict[str, str]) -> list[OptionItem]:
    result: list[OptionItem] = []
    for line in block_lines:
        m = OPTION_RE.search(line)
        if not m:
            continue
        text_token = m.group(1).strip()
        value = m.group(2).strip()
        flags = (m.group(3) or "").upper()
        text = token_text(text_token, tokens)
        is_default = "DEFAULT" in flags
        result.append(OptionItem(text=text, value=value, is_default=is_default))
    return result


def resolve_default(
    var_name: str,
    varid_full: str,
    options: list[OptionItem],
    defaults: dict[str, str],
    struct_defaults: dict[str, str],
    comment_defaults: dict[str, str],
    macros: dict[str, str],
    prompt_token: str,
    block_lines: list[str],
) -> str:
    inline_default = ""
    for line in block_lines:
        m = INLINE_DEFAULT_RE.search(line)
        if m:
            inline_default = m.group(1).strip()
            break

    if inline_default:
        resolved_inline = resolve_symbol(inline_default, macros)
        return format_hex_if_int(resolved_inline, macros)

    for opt in options:
        if opt.is_default:
            return format_hex_if_int(opt.value, macros)

    candidates: list[str] = []
    if var_name:
        candidates.append(f"{camel_to_upper_snake(var_name)}_DEFAULT")
        candidates.append(f"{var_name.upper()}_DEFAULT")
    if prompt_token:
        token_norm = prompt_token
        if token_norm.startswith("STR_"):
            token_norm = token_norm[4:]
        candidates.append(f"{token_norm.upper()}_DEFAULT")

    for key in candidates:
        if key not in defaults:
            continue
        raw_default = defaults[key].strip()
        for opt in options:
            if opt.value.strip() == raw_default:
                return format_hex_if_int(opt.value, macros)
        # Handle macro indirection: e.g. PAGE_POLICY_DEFAULT OPEN_PAGE_ADAPTIVE
        if raw_default in defaults:
            indirect = defaults[raw_default].strip()
            for opt in options:
                if opt.value.strip() == indirect or opt.value.strip() == raw_default:
                    return format_hex_if_int(opt.value, macros)
            return format_hex_if_int(indirect, macros)
        resolved = resolve_symbol(raw_default, macros)
        for opt in options:
            if opt.value.strip() == resolved or resolve_symbol(opt.value.strip(), macros) == resolved:
                return format_hex_if_int(opt.value, macros)
        for opt in options:
            if opt.value.strip().upper() == raw_default.upper():
                return format_hex_if_int(opt.value, macros)
        return format_hex_if_int(raw_default, macros)

    if var_name:
        field_key = normalize_field_name(var_name).lower()
        if field_key in struct_defaults:
            return format_hex_if_int(struct_defaults[field_key], macros)

    if varid_full:
        tail = normalize_field_name(varid_full.split(".")[-1]).lower()
        if tail in struct_defaults:
            return format_hex_if_int(struct_defaults[tail], macros)
        if tail in comment_defaults:
            return format_hex_if_int(comment_defaults[tail], macros)

    if var_name:
        vk = normalize_field_name(var_name).lower()
        if vk in comment_defaults:
            return format_hex_if_int(comment_defaults[vk], macros)

    # Template-driven var names: CONCATENATE*/## placeholders.
    templ = lookup_struct_default(template_var_candidates(var_name), struct_defaults)
    if templ:
        return format_hex_if_int(templ, macros)
    templ2 = lookup_struct_default(template_var_candidates(varid_full), struct_defaults)
    if templ2:
        return format_hex_if_int(templ2, macros)

    return "Unresolved"


def option_text(question_type: str, options: list[OptionItem], block_lines: list[str], macros: dict[str, str]) -> str:
    qtype = question_type.lower()
    if qtype in ("oneof", "checkbox"):
        formatted = [f"{opt.text}({format_hex_if_int(opt.value, macros)})" for opt in options]
        return ", ".join(formatted) if formatted else "N/A"

    if qtype == "numeric":
        min_v = ""
        max_v = ""
        step_v = ""
        for line in block_lines:
            if not min_v:
                m = NUMERIC_MIN_RE.search(line)
                if m:
                    min_v = m.group(1).strip()
            if not max_v:
                m = NUMERIC_MAX_RE.search(line)
                if m:
                    max_v = m.group(1).strip()
            if not step_v:
                m = NUMERIC_STEP_RE.search(line)
                if m:
                    step_v = m.group(1).strip()
        chunks = []
        if min_v:
            chunks.append(f"min={min_v}")
        if max_v:
            chunks.append(f"max={max_v}")
        if step_v:
            chunks.append(f"step={step_v}")
        return " | ".join(chunks) if chunks else "numeric"

    return qtype


def collect_source_files(root: Path, platform: str) -> list[Path]:
    excluded_dirs = set(EXCLUDED_PLATFORM_DIRS_GLOBAL)
    excluded_dirs.update(EXCLUDED_PLATFORM_DIRS_BY_PLATFORM.get(platform, set()))
    files = [*root.rglob("*.hfr"), *root.rglob("*.vfr")]
    files = [f for f in files if f.is_file()]
    files = [
        f
        for f in files
        if not any(part in excluded_dirs for part in f.parts)
    ]
    files.sort()
    return files


def parse_knobs(
    root: Path,
    display_root: Path,
    source_files: Iterable[Path],
    tokens: dict[str, str],
    defaults: dict[str, str],
    struct_defaults: dict[str, str],
    comment_defaults: dict[str, str],
    macros: dict[str, str],
) -> list[KnobRow]:
    rows: list[KnobRow] = []

    for src in source_files:
        try:
            lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue

        cond_stack: list[str] = []
        form_title_stack: list[str] = []
        form_pending = False
        i = 0
        while i < len(lines):
            line = lines[i]
            code, _ = split_comment(line)
            stripped = code.strip()

            cond_start = COND_START_RE.match(stripped)
            if cond_start:
                cond_text = extract_condition_text(stripped)
                cond_stack.append(cond_text or cond_start.group(1).lower())
                i += 1
                continue
            if COND_END_RE.match(stripped):
                if cond_stack:
                    cond_stack.pop()
                i += 1
                continue

            if FORM_START_RE.match(stripped):
                form_pending = True
            form_match = FORM_TITLE_RE.search(stripped)
            if form_pending and form_match:
                form_token = form_match.group(1).strip()
                form_title_stack.append(token_text(form_token, tokens))
                form_pending = False
                i += 1
                continue
            if FORM_END_RE.match(stripped):
                if form_title_stack:
                    form_title_stack.pop()
                form_pending = False
                i += 1
                continue

            qstart = QUESTION_START_RE.match(stripped)
            if not qstart:
                i += 1
                continue

            question_type = qstart.group(1).lower()
            start_line = i + 1
            end_keyword = f"end{question_type}"
            block_lines = [line]
            j = i + 1
            while j < len(lines):
                block_lines.append(lines[j])
                if re.search(rf"\b{end_keyword}\b", lines[j], re.IGNORECASE):
                    break
                j += 1
            i = j + 1

            block_text = "\n".join(block_lines)

            varid_full = extract_varid_expression(block_text)
            if not varid_full:
                varid_m = VARID_RE.search(block_text)
                varid_full = varid_m.group(1).strip() if varid_m else ""
            var_short = short_var(varid_full) if varid_full else "N/A"

            prompt_m = PROMPT_RE.search(block_text)
            help_m = HELP_RE.search(block_text)
            prompt_token = prompt_m.group(1).strip() if prompt_m else ""
            help_token = help_m.group(1).strip() if help_m else ""
            knob_name = token_text(prompt_token, tokens) if prompt_token else var_short
            description = token_text(help_token, tokens) if help_token else knob_name

            options = parse_option_items(block_lines, tokens)
            options_text = option_text(question_type, options, block_lines, macros)
            default_value = resolve_default(
                var_short if var_short != "N/A" else "",
                varid_full,
                options,
                defaults,
                struct_defaults,
                comment_defaults,
                macros,
                prompt_token,
                block_lines,
            )

            try:
                rel = src.relative_to(display_root).as_posix()
            except ValueError:
                rel = src.relative_to(root).as_posix()
            location = f"{rel}:{start_line}"

            form_title = form_title_stack[-1] if form_title_stack else src.parent.name
            if "SocketSetup" in src.as_posix():
                menu_path = f"EDKII Menu\\Socket Configuration\\{form_title}\\{knob_name}"
            else:
                menu_path = f"EDKII Menu\\{form_title}\\{knob_name}"

            dependency = concise_dependency(cond_stack)

            rows.append(
                KnobRow(
                    knob_name=knob_name,
                    knob_variable=var_short,
                    description=description,
                    knob_options=options_text,
                    default_value=default_value,
                    menu_path=menu_path,
                    hfr_file_location=location,
                    dependency=dependency,
                    sort_file=rel,
                    sort_line=start_line,
                )
            )

    rows.sort(key=lambda r: (str(Path(r.sort_file).parent), r.sort_file, r.sort_line, r.knob_variable))
    return rows


def concise_dependency(cond_stack: list[str]) -> str:
    """Return concise visibility constraints from current condition stack."""
    for cond in reversed(cond_stack):
        text = re.sub(r"\s+", " ", cond).strip()
        text = text.replace("\\", "")
        text = text.rstrip(";").strip()
        if not text or text.startswith("if "):
            continue

        m = re.match(r"(.+)\s+\((suppressif|grayoutif|disableif|inconsistentif|nosubmitif)\)$", text, re.IGNORECASE)
        if m:
            expr = m.group(1).strip()
            cond_type = m.group(2).lower()
            return f"{cond_type}: {expr}"
        return text

    return ""


def is_fake_knob(row: KnobRow) -> bool:
    """Best-effort filter for non-setup or placeholder entries."""
    var_name = (row.knob_variable or "").strip()
    knob_name = (row.knob_name or "").strip()
    description = (row.description or "").strip()

    # Rows without a real varid are usually transient UI fields rather than setup knobs.
    if not var_name or var_name.upper() == "N/A":
        return True

    # Unresolved string tokens indicate placeholder entries, not user-facing setup knobs.
    if re.fullmatch(r"STR_[A-Z0-9_]+", knob_name) and description == knob_name:
        return True

    return False


def is_always_hidden_knob(row: KnobRow) -> bool:
    """Filter rows that are definitely hidden/disabled by unconditional guards."""
    dep = (row.dependency or "").strip()
    if not dep:
        return False

    # Keep this strict to avoid deleting conditionally-visible knobs.
    m = re.match(r"^(suppressif|grayoutif|disableif)\s*:\s*(.+)$", dep, re.IGNORECASE)
    if not m:
        return False

    expr = m.group(2).strip().rstrip(";")
    expr_upper = expr.upper()
    always_true_tokens = {
        "TRUE",
        "(TRUE)",
        "1",
        "0X1",
        "EFI_TRUE",
        "TRUE==TRUE",
        "1==1",
        "EFI_TRUE==EFI_TRUE",
    }
    expr_norm = re.sub(r"\s+", "", expr_upper)
    return expr_norm in always_true_tokens


def column_name(index: int) -> str:
    name = ""
    value = index
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xml_cell(cell_ref: str, value: str, style: int | None = None) -> str:
    style_attr = f' s="{style}"' if style is not None else ""
    return (
        f'<c r="{cell_ref}" t="inlineStr"{style_attr}>'
        f"<is><t>{escape(value)}</t></is>"
        f"</c>"
    )


def build_sheet_xml(rows: list[dict[str, str]]) -> str:
    full_rows = [dict(zip(HEADERS, HEADERS))]
    full_rows.extend(rows)

    widths = []
    for h in HEADERS:
        max_len = max([len(h), *[len(r.get(h, "")) for r in rows]]) if rows else len(h)
        widths.append(min(max(max_len + 2, 12), 100))

    cols_xml = []
    for idx, width in enumerate(widths, start=1):
        cols_xml.append(f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>')

    row_xml = []
    for r_idx, row in enumerate(full_rows, start=1):
        cells = []
        for c_idx, header in enumerate(HEADERS, start=1):
            ref = f"{column_name(c_idx)}{r_idx}"
            style = 1 if r_idx == 1 else None
            cells.append(xml_cell(ref, row.get(header, ""), style))
        row_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    last_cell = f"{column_name(len(HEADERS))}{len(full_rows)}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<dimension ref=\"A1:{last_cell}\"/>"
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{''.join(cols_xml)}</cols>"
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        f'<autoFilter ref="A1:{last_cell}"/>'
        '</worksheet>'
    )


def build_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="2">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '</fills>'
        '<borders count="1">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def write_xlsx(rows: list[dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_xml = build_sheet_xml(rows)
    styles_xml = build_styles_xml()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>',
        )
        workbook.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>',
        )
        workbook.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>BIOS Knob Export</dc:title>'
            '<dc:creator>bios-platform-knob-export</dc:creator>'
            '</cp:coreProperties>',
        )
        workbook.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>bios-platform-knob-export</Application>'
            '</Properties>',
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Knobs" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        )
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        workbook.writestr("xl/styles.xml", styles_xml)


def main() -> int:
    args = parse_args()

    cwd = Path.cwd().resolve()
    platform_root = PLATFORM_ROOTS[args.platform]
    intel_root = (platform_root / "Intel").resolve()
    if not intel_root.exists() or not intel_root.is_dir():
        print(f"Intel scope root not found: {intel_root}", file=sys.stderr)
        return 2

    if args.bios_path is None:
        search_root = intel_root
        print(f"[Info] BIOS path not specified, using Intel scope: {search_root}")
    else:
        search_root = normalize_path(args.bios_path, cwd)

    if not search_root.exists() or not search_root.is_dir():
        print(f"Invalid BIOS path: {search_root}", file=sys.stderr)
        return 2

    if not is_subpath(search_root, intel_root):
        print(
            f"Invalid BIOS path: {search_root}. Path must be under Intel scope: {intel_root}.",
            file=sys.stderr,
        )
        return 2

    out_xlsx = normalize_path(args.output, cwd)
    out_json = normalize_path(args.json_output, cwd) if args.json_output else out_xlsx.with_suffix(".json")

    source_files = collect_source_files(search_root, args.platform)
    if not source_files:
        print(f"No HFR/VFR files found under: {search_root}", file=sys.stderr)
        return 3

    tokens = load_uni_tokens(search_root)
    macro_root = intel_root
    defaults, macros = load_macros(macro_root)
    struct_defaults = load_struct_defaults(macro_root)
    comment_defaults = load_comment_defaults(macro_root)
    rows = parse_knobs(
        search_root,
        platform_root,
        source_files,
        tokens,
        defaults,
        struct_defaults,
        comment_defaults,
        macros,
    )

    no_fake_rows = [row for row in rows if not is_fake_knob(row)]
    removed_fake = len(rows) - len(no_fake_rows)

    filtered_rows = [row for row in no_fake_rows if not is_always_hidden_knob(row)]
    removed_always_hidden = len(no_fake_rows) - len(filtered_rows)

    dict_rows = [row.as_dict() for row in filtered_rows]
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"headers": HEADERS, "rows": dict_rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    write_xlsx(dict_rows, out_xlsx)

    unresolved = sum(1 for r in filtered_rows if r.default_value == "Unresolved")
    print(f"Platform: {args.platform}")
    print(f"Search root: {search_root}")
    print(f"Rows: {len(filtered_rows)}")
    print(f"Filtered fake rows: {removed_fake}")
    print(f"Filtered always-hidden rows: {removed_always_hidden}")
    print(f"Unresolved default: {unresolved}")
    print(f"JSON: {out_json}")
    print(f"XLSX: {out_xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
