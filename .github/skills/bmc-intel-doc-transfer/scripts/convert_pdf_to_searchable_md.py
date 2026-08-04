#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_PDF_DIR = REPO_ROOT / "assets" / "Intel_doc" / "raw_PDF"
DEFAULT_OUTPUT_ROOT = DEFAULT_RAW_PDF_DIR.parent
HEADER_CUTOFF = 110
FOOTER_CUTOFF = 1080
WATERMARK_OPACITY_THRESHOLD = 0.2
ZERO_WIDTH_CHARS = "\u200b\ufeff"
WHITESPACE_RE = re.compile(r"\s+")
NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
PDF_COPY_SUFFIX_RE = re.compile(r"\s+\(\d+\)$")
LINE_NUMBER_RE = re.compile(r"\d{1,5}")
LINE_NUMBER_PREFIX_RE = re.compile(r"^(\d{1,5})\s+(.+)$")
TOC_LEADER_LINE_RE = re.compile(r"\.{10,}\s+\d+\s*$")
PAGE_HEADER_RE = re.compile(r"^## PDF Page \d+$")
REGISTER_SUMMARY_HEADER_RE = re.compile(r"^Type Size(?: Scope)? Offset Default$")
OFFSET_SIZE_REGISTER_HEADER_RE = re.compile(r"^Offset Size Register Name Default Value$")
DEVICE_LOCATION_HEADER_RE = re.compile(r"^Die IP Instance Bus Device Function Device ID$")
IP_INSTANCE_LOCATION_HEADER_RE = re.compile(r"^IP Instance Bus Device Function Device ID$")
FIXED_DIE_DEVICE_LOCATION_HEADER_RE = re.compile(
    r"^(?P<die>[A-Z][A-Z0-9_/-]*) IP Instance Bus Device Function Device ID$"
)
HEXISH_VALUE_RE = re.compile(r"^(?:[0-9A-Fa-f]+h|N/A)$")
TABLE_UNIT_LINE_RE = re.compile(r"^\([^)]+\)$")
TABLE_TITLE_RE = re.compile(r"^Table\s+(?P<number>[A-Za-z0-9_.-]+)\.\s+(?P<title>.+)$")
TABLE_PAGE_HINT_RE = re.compile(r"^<!-- table-pages: (?P<start>\d+)-(?P<end>\d+) -->$")
TABLE_50_TITLE = "Rd/WrEndPointConfig() MMIO Command Parameters"
TABLE_51_TITLE = "Extended Machine Check Banks"
TABLE_52_TITLE = "Error Bitmask for Merged MC Banks"
TABLE50_ROW_START_RE = re.compile(
    r"^(?P<endpoint>.+?)\s+(?P<segment>255|0)\s+(?P<bdf>.+?)\s+(?P<bar>\d+)\s+Use domain ID\s+(?P<domain>\d+)\s+for\s+(?P<details>.+)$"
)
TABLE51_ROW_START_RE = re.compile(
    r"^(?P<bank>\d+)\s+(?P<ip>\S+)\s+(?P<domain>\S+)\s+(?P<processor>[0-9-]+)\s+(?P<registers>MC.+)$"
)
TABLE52_ROW_RE = re.compile(
    r"^(?P<bank>\d+)\s+(?P<ip>\S+)\s+(?P<domain>\S+)\s+(?P<register>0x[0-9A-Fa-f]+)\s+(?P<count>\d+)$"
)
REGISTER_FIELD_HEADER_RE = re.compile(r"^(?P<bits>\d+(?::\d+)?)\s+(?P<default>[0-9A-Fa-f]+h)\s+(?P<field>.+)$")
REGISTER_FIELD_ACCESS_RE = re.compile(
    r"^(?P<access>[A-Z]{1,3}(?:/[A-Z]{1,3})*(?:,\s*OOB)?)(?:\s+\((?P<field_id>[^)]+)\):?)?(?:\s+(?P<desc>.*))?$"
)
REGISTER_FORMATTED_FIELD_RE = re.compile(r"^- `(?P<bits>[^`]+)` \| default `(?P<default>[^`]+)` \| (?P<tail>.+)$")
LOW_QUALITY_TITLE_RE = re.compile(
    r"^((mark|ole[ _-]?link)[ _-]?\d+|temp[ _-]?bookmark[ _-]?\d+)$",
    re.IGNORECASE,
)
SECTION_HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")
SECTION_NUMBER_PREFIX_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\s+\S")
ACRONYM_PREFIX_RE = re.compile(r"^(ACPI|ARP|BCD|BMC|CIM|DSP|EID|FIFO|GUID|I2C|IANA|IPMI|IPMB|ISO|MAC|MCTP|PCI|PHY|RFC|RMII|SMBus|UUID)(?=[A-Za-z0-9])")
GLUED_TOKENS = ("ISO/IEC", "MCTP", "PCIe", "SMBus")
TOC_HEADINGS = {"contents", "table of contents"}
MOJIBAKE_REPLACEMENTS = {
    "Ã¡": "á",
    "Ã©": "é",
    "Ã­": "í",
    "Ã³": "ó",
    "Ãº": "ú",
    "Ã±": "ñ",
    "Ã¼": "ü",
    "Ã¶": "ö",
    "Ã„": "Ä",
    "Ã–": "Ö",
    "Ãœ": "Ü",
    "ÃŸ": "ß",
    "â€™": "'",
    "â€œ": '"',
    "â€�": '"',
    "â€“": "-",
    "â€”": "-",
    "ï»¿": "",
}


@dataclass
class FontSpec:
    size: float
    color: str
    opacity: float


@dataclass
class TextFragment:
    top: float
    left: float
    width: float
    height: float
    text: str
    font: FontSpec
    bold: bool


@dataclass
class ChapterRecord:
    title: str
    page_start: int
    page_end: int
    blocks: list[str]


@dataclass
class TableRecord:
    number: str
    title: str
    page_start: int
    page_end: int
    lines: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a PDF into searchable Markdown chunks for Copilot skill consumption."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        help="Path to the source PDF. Omit to convert every PDF under --raw-dir.",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        help="Directory where Markdown chunks, outline, and indexes will be written in single-PDF mode",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=250,
        help="Number of PDF pages per Markdown chunk (default: 250)",
    )
    parser.add_argument("--first-page", type=int, default=1, help="First PDF page to convert")
    parser.add_argument("--last-page", type=int, default=None, help="Last PDF page to convert")
    parser.add_argument(
        "--title",
        default=None,
        help="Optional document title written into generated Markdown files in single-PDF mode",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_PDF_DIR,
        help="Directory scanned for PDFs in batch mode",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base directory used to infer <pdf_stem>_searchable output folders",
    )
    return parser.parse_args()


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Required tool not found in PATH: {name}")


def normalize_pdf_stem(pdf_path: Path) -> str:
    return PDF_COPY_SUFFIX_RE.sub("", pdf_path.stem).strip()


def default_output_dir_for_pdf(pdf_path: Path, output_root: Path) -> Path:
    return output_root / f"{normalize_pdf_stem(pdf_path)}_searchable"


def discover_pdfs(raw_dir: Path) -> list[Path]:
    return sorted(
        path for path in raw_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def replace_common_mojibake(text: str) -> str:
    for source, target in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(source, target)
    return text


def fix_glued_tokens(text: str) -> str:
    for token in GLUED_TOKENS:
        escaped_token = re.escape(token)
        text = re.sub(rf"(?<=[A-Za-z])({escaped_token})", r" \1", text)
        text = re.sub(rf"({escaped_token})(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"\bID(?=[a-z])", "ID ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=(?:describes|defines|provides|specifies|supports)\b)", " ", text)
    return text


def normalize_text(text: str) -> str:
    text = html.unescape(text)
    text = replace_common_mojibake(text)
    text = text.translate({ord(ch): None for ch in ZERO_WIDTH_CHARS})
    text = text.replace("\xa0", " ")
    text = text.replace("\u2014", "-")
    text = WHITESPACE_RE.sub(" ", text)
    text = fix_glued_tokens(text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def slugify(text: str) -> str:
    slug = normalize_text(text).lower()
    slug = slug.replace("®", "")
    slug = NON_SLUG_RE.sub("-", slug)
    slug = slug.strip("-")
    return slug or "section"


def normalize_outline_title(text: str) -> str:
    text = normalize_text(text.replace("_", " "))
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?=[a-z])", " ", text)
    text = ACRONYM_PREFIX_RE.sub(r"\1 ", text)
    text = normalize_text(text)
    if text.lower().startswith("term "):
        text = text[5:]
    return text or "Document"


def is_low_quality_outline_title(text: str) -> bool:
    return bool(LOW_QUALITY_TITLE_RE.fullmatch(normalize_outline_title(text)))


def should_skip_fragment(fragment: TextFragment, page_height: float) -> bool:
    text = fragment.text
    lower_text = text.lower()
    if not text:
        return True
    if fragment.font.opacity < WATERMARK_OPACITY_THRESHOLD:
        return True
    if fragment.left < 0 or fragment.top < 0:
        return True
    if fragment.top < HEADER_CUTOFF:
        return True
    if fragment.top > min(FOOTER_CUTOFF, page_height - 80):
        return True
    if "yang du" in lower_text or "yang1.du@intel.com" in lower_text or "12170321" in lower_text:
        return True
    if lower_text in {
        "intel confidential",
        "diamond rapids processor",
        "registers specification",
        "march 2026",
    }:
        return True
    if lower_text.startswith("doc. no.: 793272"):
        return True
    return False


def detect_line_number_fragments(fragments: list[TextFragment]) -> set[int]:
    candidates = [
        (index, fragment, int(fragment.text))
        for index, fragment in enumerate(fragments)
        if LINE_NUMBER_RE.fullmatch(fragment.text)
        and fragment.left <= 85
        and fragment.width <= 40
    ]

    if len(candidates) < 8:
        return set()

    values = [value for _, _, value in candidates]
    increasing_steps = sum(1 for prev, curr in zip(values, values[1:]) if curr == prev + 1)
    if increasing_steps < max(6, int((len(values) - 1) * 0.6)):
        return set()

    return {index for index, _, _ in candidates}


def detect_line_number_prefixes(line_texts: list[str]) -> set[int]:
    candidates: list[tuple[int, int]] = []
    for index, line_text in enumerate(line_texts):
        match = LINE_NUMBER_PREFIX_RE.match(line_text)
        if not match:
            continue
        line_number = int(match.group(1))
        if line_number < 100:
            continue
        candidates.append((index, line_number))

    if len(candidates) < 8:
        return set()

    values = [value for _, value in candidates]
    increasing_steps = sum(1 for prev, curr in zip(values, values[1:]) if curr == prev + 1)
    if increasing_steps < max(6, int((len(values) - 1) * 0.6)):
        return set()

    return {index for index, _ in candidates}


def group_fragments_into_lines(fragments: list[TextFragment]) -> list[list[TextFragment]]:
    if not fragments:
        return []

    sorted_fragments = sorted(fragments, key=lambda item: (round(item.top), item.left))
    lines: list[list[TextFragment]] = []
    current_line: list[TextFragment] = [sorted_fragments[0]]
    current_top = sorted_fragments[0].top

    for fragment in sorted_fragments[1:]:
        threshold = max(2.0, min(fragment.height, current_line[-1].height) * 0.45)
        if abs(fragment.top - current_top) <= threshold:
            current_line.append(fragment)
            current_top = min(current_top, fragment.top)
            continue

        lines.append(sorted(current_line, key=lambda item: item.left))
        current_line = [fragment]
        current_top = fragment.top

    lines.append(sorted(current_line, key=lambda item: item.left))
    return lines


def should_insert_space(previous_text: str, current_text: str, gap: float) -> bool:
    if gap <= 0:
        return False
    if current_text.startswith((".", ",", ";", ":", ")", "]", "}", "%")):
        return False
    if previous_text.endswith(("(", "[", "{", "/", "-")):
        return False
    if gap > 2:
        return True

    previous_char = previous_text[-1]
    current_char = current_text[0]
    if not (previous_char.isalnum() and current_char.isalnum()):
        return False

    return gap >= 0.35 and (len(previous_text) > 1 or len(current_text) > 1)


def join_line_text(fragments: list[TextFragment]) -> str:
    parts: list[str] = []
    previous_end: float | None = None
    previous_text: str | None = None

    for fragment in fragments:
        text = fragment.text
        if not text:
            continue
        if previous_end is None:
            parts.append(text)
        else:
            gap = fragment.left - previous_end
            if previous_text is not None and should_insert_space(previous_text, text, gap):
                parts.append(" ")
            parts.append(text)
        previous_end = fragment.left + fragment.width
        previous_text = text

    return normalize_text("".join(parts))


def is_table_of_contents_page(rendered_lines: list[str]) -> bool:
    normalized_lines = [re.sub(r"^#{3,4}\s+", "", line).strip() for line in rendered_lines if line.strip()]
    if not normalized_lines:
        return False

    leader_line_count = sum(1 for line in normalized_lines if TOC_LEADER_LINE_RE.search(line))
    if leader_line_count >= 5:
        return True

    heading_count = sum(1 for line in normalized_lines[:3] if line.lower() in TOC_HEADINGS)
    return bool(heading_count and leader_line_count >= 3)


def classify_line(line_text: str, fragments: list[TextFragment]) -> str:
    if not line_text:
        return ""

    max_size = max(fragment.font.size for fragment in fragments)
    has_colored_fragment = any(fragment.font.color.lower() != "#000000" for fragment in fragments)

    if line_text.startswith("•"):
        bullet_text = normalize_text(line_text[1:])
        return f"- {bullet_text}" if bullet_text else ""
    if max_size >= 20:
        return f"### {line_text}"
    if has_colored_fragment and max_size >= 14 and not line_text.endswith("."):
        return f"#### {line_text}"
    return line_text


def format_page(page_number: int, page_height: float, fragments: list[TextFragment]) -> str:
    line_number_indexes = detect_line_number_fragments(fragments)
    usable_fragments = [
        fragment
        for index, fragment in enumerate(fragments)
        if index not in line_number_indexes and not should_skip_fragment(fragment, page_height)
    ]
    lines = group_fragments_into_lines(usable_fragments)
    line_texts = [join_line_text(line_fragments) for line_fragments in lines]
    prefixed_line_indexes = detect_line_number_prefixes(line_texts)

    rendered_lines: list[str] = []
    for index, line_fragments in enumerate(lines):
        line_text = line_texts[index]
        if not line_text:
            continue
        if index in prefixed_line_indexes:
            match = LINE_NUMBER_PREFIX_RE.match(line_text)
            if match:
                line_text = normalize_text(match.group(2))
        if re.fullmatch(r"\d+", line_text):
            continue
        rendered = classify_line(line_text, line_fragments)
        if rendered:
            rendered_lines.append(rendered)

    if not rendered_lines:
        return ""
    if is_table_of_contents_page(rendered_lines):
        return ""

    page_header = [f"## PDF Page {page_number}", ""]
    return "\n".join(page_header + rendered_lines).strip() + "\n"


def is_page_header_line(line: str) -> bool:
    return bool(PAGE_HEADER_RE.fullmatch(line.strip()))


def parse_table_title_line(line: str) -> re.Match[str] | None:
    stripped = line.strip()
    stripped = re.sub(r"^#{1,6}\s+", "", stripped)
    return TABLE_TITLE_RE.fullmatch(stripped)


def is_table_title_line(line: str) -> bool:
    return parse_table_title_line(line) is not None


def is_register_block_boundary(line: str) -> bool:
    stripped = line.strip()
    if not stripped or is_page_header_line(stripped):
        return False
    if REGISTER_SUMMARY_HEADER_RE.fullmatch(stripped):
        return True
    if stripped in {"Register Level Access:", "Bit Default and Field Name (ID): Description"}:
        return True
    if stripped.startswith(("### ", "#### ", "Table ")):
        return True
    return bool(SECTION_HEADING_RE.match(stripped))


def normalize_access_token(text: str) -> str:
    return normalize_text(text.replace(",", ", "))


def join_split_hex_tokens(tokens: list[str]) -> list[str]:
    if len(tokens) >= 2 and re.fullmatch(r"[0-9A-Fa-f]+", tokens[-2]) and tokens[-1] == "h":
        return [*tokens[:-2], f"{tokens[-2]}h"]
    if len(tokens) >= 2 and re.fullmatch(r"[0-9A-Fa-f]+", tokens[-2]) and re.fullmatch(r"[0-9A-Fa-f]+h", tokens[-1]):
        return [*tokens[:-2], f"{tokens[-2]}{tokens[-1]}"]
    return tokens


def parse_register_summary(header_line: str, value_lines: list[str]) -> dict[str, str] | None:
    tokens = join_split_hex_tokens(" ".join(value_lines).split())
    if len(tokens) < 5 or tokens[2] != "bit":
        return None

    summary = {
        "Type": tokens[0],
        "Size": f"{tokens[1]} {tokens[2]}",
    }
    tail_tokens = tokens[3:]
    if "Scope" in header_line.split():
        if len(tail_tokens) < 3:
            return None
        summary["Scope"] = tail_tokens[0]
        tail_tokens = tail_tokens[1:]

    default_value = tail_tokens[-1]
    if not re.fullmatch(r"[0-9A-Fa-f]+h", default_value):
        return None

    offset_value = " ".join(tail_tokens[:-1])
    if not offset_value:
        return None

    summary["Offset"] = offset_value
    summary["Default"] = default_value
    return summary


def rewrite_register_summary_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    value_lines: list[str] = []
    index = start_index + 1
    while index < len(lines) and len(value_lines) < 2:
        stripped = lines[index].strip()
        if not stripped or is_register_block_boundary(stripped):
            break
        value_lines.append(stripped)
        if len(value_lines) == 1 and re.fullmatch(r"[0-9A-Fa-f]+h", stripped):
            break
        index += 1

    if value_lines:
        index = start_index + 1 + len(value_lines)

    summary = parse_register_summary(lines[start_index].strip(), value_lines)
    if summary is None:
        return lines[start_index:index], index

    rewritten = ["#### Register Summary"]
    for key in ("Type", "Size", "Scope", "Offset", "Default"):
        value = summary.get(key)
        if value:
            rewritten.append(f"- {key}: {value}")
    return rewritten, index


def rewrite_register_access_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    rewritten = ["#### Register Level Access"]
    index = start_index + 1

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if is_register_block_boundary(stripped):
            break
        if is_page_header_line(stripped):
            rewritten.extend(["", stripped, ""])
            index += 1
            continue
        if stripped == "Out Of Band (OOB) Access:":
            rewritten.append("##### Out Of Band (OOB) Access")
        else:
            rewritten.append(f"- {normalize_text(stripped)}")
        index += 1

    return rewritten, index


def format_register_field(field: dict[str, str | list[str] | None]) -> str:
    field_name = str(field["field"])
    field_id = field.get("field_id")
    if field_id:
        field_name = f"{field_name} ({field_id})"

    parts = [
        f"`{field['bits']}`",
        f"default `{field['default']}`",
        field_name,
    ]
    access = field.get("access")
    if access:
        parts.append(f"access `{access}`")
    description_parts = field.get("description") or []
    description = " ".join(str(part) for part in description_parts if part)
    if description:
        parts.append(description)
    return "- " + " | ".join(parts)


def parse_formatted_register_field(line: str) -> dict[str, str | list[str] | None] | None:
    match = REGISTER_FORMATTED_FIELD_RE.match(line.strip())
    if match is None:
        return None

    tail_parts = match.group("tail").split(" | ")
    if not tail_parts:
        return None

    field_name = tail_parts[0]
    field_id = None
    field_id_match = re.match(r"^(?P<field>.+?) \((?P<field_id>[^)]+)\)$", field_name)
    if field_id_match is not None:
        field_name = field_id_match.group("field")
        field_id = field_id_match.group("field_id")

    field: dict[str, str | list[str] | None] = {
        "bits": match.group("bits"),
        "default": match.group("default"),
        "field": field_name,
        "field_id": field_id,
        "access": None,
        "description": [],
    }

    for part in tail_parts[1:]:
        if part.startswith("access `") and part.endswith("`") and field["access"] is None:
            field["access"] = part[len("access `"):-1]
            continue
        if part:
            field["description"].append(part)

    return field


def stabilize_bit_field_sections(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    rewritten: list[str] = []
    index = 0
    in_bit_fields = False
    current_field: dict[str, str | list[str] | None] | None = None

    while index < len(lines):
        stripped = lines[index].strip()

        if not in_bit_fields:
            rewritten.append(lines[index])
            if stripped == "#### Bit Fields":
                in_bit_fields = True
            index += 1
            continue

        if is_register_block_boundary(stripped) and stripped != "#### Bit Fields":
            if current_field is not None:
                rewritten.append(format_register_field(current_field))
                current_field = None
            in_bit_fields = False
            continue

        if not stripped:
            index += 1
            continue

        if is_page_header_line(stripped):
            rewritten.extend(["", stripped, ""])
            index += 1
            continue

        if stripped == "#### Bit Fields":
            index += 1
            continue

        parsed_field = parse_formatted_register_field(stripped)
        if parsed_field is not None:
            if current_field is not None:
                rewritten.append(format_register_field(current_field))
            current_field = parsed_field
            index += 1
            continue

        field_match = REGISTER_FIELD_HEADER_RE.match(stripped)
        if field_match is not None:
            if current_field is not None:
                rewritten.append(format_register_field(current_field))
            current_field = {
                "bits": field_match.group("bits"),
                "default": field_match.group("default"),
                "field": normalize_text(field_match.group("field").rstrip(":")),
                "field_id": None,
                "access": None,
                "description": [],
            }
            index += 1
            continue

        access_match = REGISTER_FIELD_ACCESS_RE.match(stripped)
        if current_field is not None and access_match is not None:
            current_field["access"] = normalize_access_token(access_match.group("access"))
            field_id = access_match.group("field_id")
            if field_id:
                current_field["field_id"] = normalize_text(field_id)
            access_description = access_match.group("desc")
            if access_description:
                current_field["description"].append(normalize_text(access_description))
            index += 1
            continue

        if current_field is not None and stripped.lower() != "continued...":
            current_field["description"].append(normalize_text(stripped))
            index += 1
            continue

        rewritten.append(lines[index])
        index += 1

    if current_field is not None:
        rewritten.append(format_register_field(current_field))

    return "\n".join(rewritten).rstrip() + "\n"


def rewrite_bit_field_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    rewritten = ["#### Bit Fields"]
    index = start_index + 1
    current_field: dict[str, str | list[str] | None] | None = None

    if index < len(lines) and lines[index].strip() == "Range Access":
        index += 1

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if is_page_header_line(stripped):
            rewritten.extend(["", stripped, ""])
            index += 1
            if index < len(lines) and lines[index].strip() == "Bit Default and Field Name (ID): Description":
                index += 1
                if index < len(lines) and lines[index].strip() == "Range Access":
                    index += 1
            continue
        if stripped == "Bit Default and Field Name (ID): Description":
            if current_field is not None:
                rewritten.append(format_register_field(current_field))
                current_field = None
            index += 1
            if index < len(lines) and lines[index].strip() == "Range Access":
                index += 1
            continue
        if stripped == "Range Access":
            index += 1
            continue
        if is_register_block_boundary(stripped):
            break

        field_match = REGISTER_FIELD_HEADER_RE.match(stripped)
        if field_match:
            if current_field is not None:
                rewritten.append(format_register_field(current_field))
            current_field = {
                "bits": field_match.group("bits"),
                "default": field_match.group("default"),
                "field": normalize_text(field_match.group("field").rstrip(":")),
                "field_id": None,
                "access": None,
                "description": [],
            }
            index += 1
            continue

        if stripped.lower() == "continued...":
            index += 1
            continue

        if current_field is None:
            break

        access_match = REGISTER_FIELD_ACCESS_RE.match(stripped)
        if access_match:
            current_field["access"] = normalize_access_token(access_match.group("access"))
            field_id = access_match.group("field_id")
            if field_id:
                current_field["field_id"] = normalize_text(field_id)
            access_description = access_match.group("desc")
            if access_description:
                current_field["description"].append(normalize_text(access_description))
        else:
            current_field["description"].append(normalize_text(stripped))
        index += 1

    if current_field is not None:
        rewritten.append(format_register_field(current_field))

    return rewritten, index


def rewrite_register_structures(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    rewritten: list[str] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if REGISTER_SUMMARY_HEADER_RE.fullmatch(stripped):
            replacement, index = rewrite_register_summary_block(lines, index)
            rewritten.extend(replacement)
            continue
        if stripped == "Register Level Access:":
            replacement, index = rewrite_register_access_block(lines, index)
            rewritten.extend(replacement)
            continue
        if stripped == "Bit Default and Field Name (ID): Description":
            replacement, index = rewrite_bit_field_block(lines, index)
            rewritten.extend(replacement)
            continue
        rewritten.append(lines[index])
        index += 1

    rewritten_text = "\n".join(rewritten).rstrip() + "\n"
    rewritten_text = stabilize_bit_field_sections(rewritten_text)
    rewritten_text = rewrite_common_tables(rewritten_text)
    return rewrite_special_case_tables(rewritten_text)


def is_common_table_boundary(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith(("### ", "#### ", "##### ")):
        return True
    if is_table_title_line(stripped):
        return True
    return bool(SECTION_HEADING_RE.match(stripped))


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    rendered = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        rendered.append("| " + " | ".join(row) + " |")
    return rendered


def parse_offset_size_register_row(text: str) -> list[str] | None:
    tokens = text.split()
    if len(tokens) < 4 or not tokens[1].isdigit():
        return None

    offset = tokens[0]
    default = tokens[-1]
    if not offset.endswith("h") or not HEXISH_VALUE_RE.fullmatch(default):
        return None

    register_name = " ".join(tokens[2:-1])
    if not register_name:
        return None

    return [offset, tokens[1], register_name, default]


def parse_device_location_row(text: str) -> list[str] | None:
    tokens = text.split()
    if len(tokens) < 6:
        return None
    if not (tokens[-4].isdigit() and tokens[-3].isdigit() and tokens[-2].isdigit()):
        return None
    if not HEXISH_VALUE_RE.fullmatch(tokens[-1]):
        return None

    die = tokens[0]
    ip_instance = " ".join(tokens[1:-4])
    if not ip_instance:
        return None

    return [die, ip_instance, tokens[-4], tokens[-3], tokens[-2], tokens[-1]]


def parse_ip_instance_location_row(text: str) -> list[str] | None:
    tokens = text.split()
    if len(tokens) < 5:
        return None
    if not (tokens[-4].isdigit() and tokens[-3].isdigit() and tokens[-2].isdigit()):
        return None
    if not HEXISH_VALUE_RE.fullmatch(tokens[-1]):
        return None

    ip_instance = " ".join(tokens[:-4])
    if not ip_instance:
        return None

    return [ip_instance, tokens[-4], tokens[-3], tokens[-2], tokens[-1]]


def parse_type_size_offset_default_row(text: str, header_line: str) -> list[str] | None:
    tokens = join_split_hex_tokens(text.split())
    has_scope = "Scope" in header_line.split()
    minimum_tokens = 6 if has_scope else 5
    if len(tokens) < minimum_tokens or tokens[2] != "bit":
        return None

    row = [tokens[0], f"{tokens[1]} {tokens[2]}"]
    offset_start = 3
    if has_scope:
        row.append(tokens[3])
        offset_start = 4

    default = tokens[-1]
    if not HEXISH_VALUE_RE.fullmatch(default):
        return None

    offset = " ".join(tokens[offset_start:-1])
    if not offset:
        return None

    row.append(offset)
    row.append(default)
    return row


def collect_common_table_rows(
    lines: list[str],
    start_index: int,
    header_line: str,
    parser: callable,
) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    index = start_index

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            break
        if (
            is_page_header_line(stripped)
            or stripped.lower() == "continued..."
            or stripped == header_line
            or TABLE_UNIT_LINE_RE.fullmatch(stripped)
        ):
            index += 1
            continue
        if is_common_table_boundary(stripped):
            break

        candidate = normalize_text(stripped)
        candidate_end = index + 1
        parsed = parser(candidate)

        while parsed is None and candidate_end < len(lines):
            next_stripped = lines[candidate_end].strip()
            if (
                not next_stripped
                or is_page_header_line(next_stripped)
                or next_stripped.lower() == "continued..."
                or next_stripped == header_line
                or is_table_title_line(next_stripped)
                or is_common_table_boundary(next_stripped)
            ):
                break
            candidate = normalize_text(f"{candidate} {next_stripped}")
            candidate_end += 1
            parsed = parser(candidate)

        if parsed is None:
            break

        rows.append(parsed)
        index = candidate_end

    return rows, index


def collect_fixed_die_device_location_rows(
    lines: list[str],
    start_index: int,
    header_line: str,
    die_token: str,
) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    index = start_index
    normalized_die = normalize_text(die_token)

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            break
        if (
            is_page_header_line(stripped)
            or stripped.lower() == "continued..."
            or stripped == header_line
            or TABLE_UNIT_LINE_RE.fullmatch(stripped)
        ):
            index += 1
            continue
        if is_table_title_line(stripped) or is_common_table_boundary(stripped):
            break

        candidate = normalize_text(stripped)
        parsed = parse_ip_instance_location_row(candidate)
        if parsed is None:
            break

        next_index = index + 1
        if next_index < len(lines) and normalize_text(lines[next_index].strip()) == normalized_die:
            next_index += 1

        rows.append([normalized_die, *parsed])
        index = next_index

    return rows, index


def rewrite_common_tables(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    rewritten: list[str] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()

        if OFFSET_SIZE_REGISTER_HEADER_RE.fullmatch(stripped):
            rows, next_index = collect_common_table_rows(
                lines,
                index + 1,
                stripped,
                parse_offset_size_register_row,
            )
            if rows:
                rewritten.extend(
                    render_markdown_table(["Offset", "Size", "Register Name", "Default Value"], rows)
                )
                index = next_index
                continue

        if DEVICE_LOCATION_HEADER_RE.fullmatch(stripped):
            rows, next_index = collect_common_table_rows(
                lines,
                index + 1,
                stripped,
                parse_device_location_row,
            )
            if rows:
                rewritten.extend(
                    render_markdown_table(["Die", "IP Instance", "Bus", "Device", "Function", "Device ID"], rows)
                )
                index = next_index
                continue

        if IP_INSTANCE_LOCATION_HEADER_RE.fullmatch(stripped):
            rows, next_index = collect_common_table_rows(
                lines,
                index + 1,
                stripped,
                parse_ip_instance_location_row,
            )
            if rows:
                rewritten.extend(
                    render_markdown_table(["IP Instance", "Bus", "Device", "Function", "Device ID"], rows)
                )
                index = next_index
                continue

        fixed_die_match = FIXED_DIE_DEVICE_LOCATION_HEADER_RE.fullmatch(stripped)
        if fixed_die_match is not None:
            rows, next_index = collect_fixed_die_device_location_rows(
                lines,
                index + 1,
                stripped,
                fixed_die_match.group("die"),
            )
            if rows:
                rewritten.extend(
                    render_markdown_table(["Die", "IP Instance", "Bus", "Device", "Function", "Device ID"], rows)
                )
                index = next_index
                continue

        if REGISTER_SUMMARY_HEADER_RE.fullmatch(stripped):
            rows, next_index = collect_common_table_rows(
                lines,
                index + 1,
                stripped,
                lambda text: parse_type_size_offset_default_row(text, stripped),
            )
            if rows:
                headers = ["Type", "Size"]
                if "Scope" in stripped.split():
                    headers.append("Scope")
                headers.extend(["Offset", "Default"])
                rewritten.extend(render_markdown_table(headers, rows))
                index = next_index
                continue

        rewritten.append(lines[index])
        index += 1

    return "\n".join(rewritten).rstrip() + "\n"


def collect_titled_table_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    block = [lines[start_index]]
    index = start_index + 1

    while index < len(lines):
        stripped = lines[index].strip()
        if index > start_index + 1 and is_table_title_line(stripped):
            break
        if index > start_index + 1 and (stripped.startswith(("### ", "#### ", "##### ")) or SECTION_HEADING_RE.match(stripped)):
            break
        block.append(lines[index])
        index += 1

    return block, index


def normalize_table_block_lines(lines: list[str], header_prefixes: tuple[str, ...]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if is_page_header_line(stripped) or stripped.lower() == "continued...":
            continue
        if any(stripped.startswith(prefix) for prefix in header_prefixes):
            continue
        cleaned.append(normalize_text(stripped))
    return cleaned


def build_table_page_hint_line(block: list[str], hinted_page_start: int) -> str:
    pages = [hinted_page_start] if hinted_page_start > 0 else []
    for line in block[1:]:
        stripped = line.strip()
        if is_page_header_line(stripped):
            pages.append(int(stripped.rsplit(" ", 1)[-1]))

    if not pages:
        return ""

    return f"<!-- table-pages: {min(pages)}-{max(pages)} -->"


def rewrite_table_50_block(lines: list[str], start_index: int, hinted_page_start: int) -> tuple[list[str], int]:
    block, next_index = collect_titled_table_block(lines, start_index)
    body_lines = normalize_table_block_lines(
        block[1:],
        ("Endpoint Segment BDF", "Type"),
    )

    rows: list[list[str]] = []
    current_row: list[str] | None = None

    for line in body_lines:
        match = TABLE50_ROW_START_RE.match(line)
        if match is not None:
            if current_row is not None:
                rows.append(current_row)
            current_row = [
                match.group("endpoint"),
                match.group("segment"),
                match.group("bdf"),
                match.group("bar"),
                match.group("domain"),
                normalize_text(f"{match.group('details')}") ,
            ]
            continue

        if current_row is not None:
            current_row[-1] = normalize_text(f"{current_row[-1]} {line}")

    if current_row is not None:
        rows.append(current_row)

    if not rows:
        return block, next_index

    page_hint = build_table_page_hint_line(block, hinted_page_start)
    rewritten = [
        block[0],
        *( [page_hint] if page_hint else [] ),
        *render_markdown_table(
            ["Endpoint", "Segment", "BDF (See note 1)", "BAR ID", "Domain ID", "Address and Address Type / Notes"],
            rows,
        ),
    ]
    return rewritten, next_index


def merge_table_51_ip_suffix(ip_name: str, line: str) -> tuple[str, str]:
    match = re.match(r"^(?P<suffix>[A-Z]{1,3})\s+(?P<rest>CTL2.*)$", line)
    if match is None:
        return ip_name, line
    return normalize_text(f"{ip_name}{match.group('suffix')}").lstrip("-"), normalize_text(match.group("rest"))


def format_numbered_notes(note_lines: list[str]) -> list[str]:
    if not note_lines:
        return []

    notes: list[str] = []
    current_note: str | None = None
    for line in note_lines:
        match = re.match(r"^(?P<number>\d+)\.\s+(?P<text>.+)$", line)
        if match is not None:
            if current_note is not None:
                notes.append(current_note)
            current_note = f"{match.group('number')}. {match.group('text')}"
            continue
        if current_note is None:
            current_note = line
            continue
        current_note = normalize_text(f"{current_note} {line}")

    if current_note is not None:
        notes.append(current_note)

    return ["Notes:", *notes]


def rewrite_table_51_block(lines: list[str], start_index: int, hinted_page_start: int) -> tuple[list[str], int]:
    block, next_index = collect_titled_table_block(lines, start_index)
    body_lines = block[1:]

    rows: list[list[str]] = []
    current_row: list[str] | None = None
    note_lines: list[str] = []
    tail_lines: list[str] = []
    in_notes = False

    for raw_line in body_lines:
        stripped = raw_line.strip()
        if not stripped or is_page_header_line(stripped) or stripped.lower() == "continued...":
            if in_notes and is_page_header_line(stripped):
                in_notes = False
            continue

        line = normalize_text(stripped)
        if line in {"Bank Valid Processor", "Dom", "ain", "ber Number)"} or line.startswith("Num IP ID"):
            continue
        if line == "NOTES":
            if current_row is not None:
                rows.append(current_row)
                current_row = None
            in_notes = True
            continue

        if in_notes:
            if TABLE_TITLE_RE.fullmatch(line) is not None:
                break
            note_lines.append(line)
            continue

        match = TABLE51_ROW_START_RE.match(line)
        if match is not None:
            if current_row is not None:
                rows.append(current_row)
            current_row = [
                match.group("bank"),
                normalize_text(match.group("ip")).lstrip("-"),
                match.group("domain"),
                match.group("processor"),
                normalize_text(match.group("registers")),
            ]
            continue

        if current_row is not None:
            current_row[1], line = merge_table_51_ip_suffix(current_row[1], line)
            current_row[-1] = normalize_text(f"{current_row[-1]} {line}")
            continue

        tail_lines.append(line)

    if current_row is not None:
        rows.append(current_row)

    if not rows:
        return block, next_index

    page_hint = build_table_page_hint_line(block, hinted_page_start)
    rewritten = [
        block[0],
        *( [page_hint] if page_hint else [] ),
        *render_markdown_table(
            ["Bank", "IP", "Domain", "Valid Processor ID Range", "Extended MC Bank Registers"],
            rows,
        ),
    ]
    formatted_notes = format_numbered_notes(note_lines)
    if formatted_notes:
        rewritten.extend(["", *formatted_notes])
    if tail_lines:
        rewritten.extend(["", *tail_lines])
    return rewritten, next_index


def rewrite_table_52_block(lines: list[str], start_index: int, hinted_page_start: int) -> tuple[list[str], int]:
    block, next_index = collect_titled_table_block(lines, start_index)
    body_lines = normalize_table_block_lines(
        block[1:],
        ("Bank Number of Instances per", "IP Domain Error Bitmask Register", "Number Die"),
    )

    rows: list[list[str]] = []
    for line in body_lines:
        match = TABLE52_ROW_RE.match(line)
        if match is None:
            continue
        rows.append([
            match.group("bank"),
            match.group("ip"),
            match.group("domain"),
            match.group("register"),
            match.group("count"),
        ])

    if not rows:
        return block, next_index

    page_hint = build_table_page_hint_line(block, hinted_page_start)
    rewritten = [
        block[0],
        *( [page_hint] if page_hint else [] ),
        *render_markdown_table(
            ["Bank Number", "IP", "Domain Die", "Error Bitmask Register", "Instances per IP"],
            rows,
        ),
    ]
    return rewritten, next_index


def rewrite_special_case_tables(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    rewritten: list[str] = []
    index = 0
    last_seen_page = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if is_page_header_line(stripped):
            last_seen_page = int(stripped.rsplit(" ", 1)[-1])
        title_match = parse_table_title_line(stripped)
        if title_match is not None:
            title = normalize_text(title_match.group("title"))
            if title == TABLE_50_TITLE:
                replacement, index = rewrite_table_50_block(lines, index, last_seen_page)
                rewritten.extend(replacement)
                continue
            if title == TABLE_51_TITLE:
                replacement, index = rewrite_table_51_block(lines, index, last_seen_page)
                rewritten.extend(replacement)
                continue
            if title == TABLE_52_TITLE:
                replacement, index = rewrite_table_52_block(lines, index, last_seen_page)
                rewritten.extend(replacement)
                continue

        rewritten.append(lines[index])
        index += 1

    return "\n".join(rewritten).rstrip() + "\n"


def run_pdftohtml(pdf_path: Path, xml_path: Path, first_page: int, last_page: int | None) -> None:
    command = [
        "pdftohtml",
        "-xml",
        "-i",
        "-nodrm",
        "-q",
        "-f",
        str(first_page),
    ]
    if last_page is not None:
        command.extend(["-l", str(last_page)])
    command.extend([str(pdf_path), str(xml_path.with_suffix(""))])
    subprocess.run(command, check=True)


def write_chunk_file(
    output_path: Path,
    title: str,
    source_pdf: Path,
    page_start: int,
    page_end: int,
    page_blocks: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        f"# {title}",
        "",
        f"Source PDF: {source_pdf.name}",
        f"PDF pages: {page_start}-{page_end}",
        "",
    ]
    body_content = rewrite_register_structures("\n".join(page_blocks))
    content = "\n".join(header) + body_content.rstrip() + "\n"
    output_path.write_text(content, encoding="utf-8")


def clear_generated_output(output_dir: Path) -> None:
    for directory_name in ("chapters", "chunks", "tables"):
        directory_path = output_dir / directory_name
        if directory_path.exists():
            shutil.rmtree(directory_path)

    for filename in ("outline.md", "README.md"):
        file_path = output_dir / filename
        if file_path.exists():
            file_path.unlink()


def section_number_depth(title: str) -> int | None:
    match = SECTION_NUMBER_PREFIX_RE.match(normalize_outline_title(title))
    if not match:
        return None
    return match.group("number").count(".") + 1


def is_glossary_like_top_level_outline(top_level_items: list[tuple[int, str]]) -> bool:
    if len(top_level_items) < 20:
        return False

    page_counts: dict[int, int] = {}
    chapter_like_count = 0
    short_title_count = 0
    for page, text in top_level_items:
        page_counts[page] = page_counts.get(page, 0) + 1
        if section_number_depth(text) is not None:
            chapter_like_count += 1
        if len(normalize_outline_title(text).split()) <= 3:
            short_title_count += 1

    max_items_per_page = max(page_counts.values(), default=0)
    chapter_like_ratio = chapter_like_count / len(top_level_items)
    short_title_ratio = short_title_count / len(top_level_items)
    return max_items_per_page >= 3 and chapter_like_ratio < 0.25 and short_title_ratio > 0.6


def synthesize_outline_from_page_blocks(page_blocks: dict[int, str]) -> list[tuple[int, int, str]]:
    synthesized: list[tuple[int, int, str]] = []
    for page in sorted(page_blocks):
        heading = extract_first_heading([page_blocks[page]])
        if not heading:
            continue
        heading = normalize_outline_title(heading)
        depth = section_number_depth(heading)
        if depth is None or depth > 2:
            continue
        if synthesized and synthesized[-1][2] == heading:
            continue
        synthesized.append((0, page, heading))
    return synthesized


def select_effective_outline_items(
    outline_items: list[tuple[int, int, str]], page_blocks: dict[int, str]
) -> list[tuple[int, int, str]]:
    if not outline_items or not page_blocks:
        return outline_items

    content_pages = sorted(page_blocks)
    first_content_page = content_pages[0]
    last_content_page = content_pages[-1]
    top_level_items = [
        (page, text)
        for level, page, text in outline_items
        if level == 0 and first_content_page <= page <= last_content_page
    ]
    if not is_glossary_like_top_level_outline(top_level_items):
        return outline_items

    synthesized_items = synthesize_outline_from_page_blocks(page_blocks)
    return synthesized_items or outline_items


def write_outline(
    output_dir: Path,
    title: str,
    outline_items: list[tuple[int, int, str]],
    page_blocks: dict[int, str],
) -> None:
    outline_items = select_effective_outline_items(outline_items, page_blocks)
    outline_path = output_dir / "outline.md"
    lines = [f"# {title} Outline", ""]
    for level, page, text in outline_items:
        if is_low_quality_outline_title(text):
            continue
        indent = "  " * max(level, 0)
        lines.append(f"{indent}- PDF page {page}: {normalize_outline_title(text)}")
    lines.append("")
    outline_path.write_text("\n".join(lines), encoding="utf-8")


def build_chapter_records(
    outline_items: list[tuple[int, int, str]], page_blocks: dict[int, str]
) -> list[ChapterRecord]:
    if not page_blocks:
        return []

    outline_items = select_effective_outline_items(outline_items, page_blocks)

    content_pages = sorted(page_blocks)
    first_content_page = content_pages[0]
    last_content_page = content_pages[-1]
    top_level_items = [
        (page, text)
        for level, page, text in outline_items
        if level == 0 and first_content_page <= page <= last_content_page
    ]

    deduped_items: list[tuple[int, str]] = []
    seen_pages: set[int] = set()
    for page, text in top_level_items:
        if page in seen_pages:
            continue
        deduped_items.append((page, text))
        seen_pages.add(page)

    if not deduped_items:
        return [
            ChapterRecord(
                title="Document",
                page_start=first_content_page,
                page_end=last_content_page,
                blocks=[page_blocks[page] for page in content_pages],
            )
        ]

    chapter_records: list[ChapterRecord] = []
    first_outline_page = deduped_items[0][0]
    if first_content_page < first_outline_page:
        front_pages = [page for page in content_pages if page < first_outline_page]
        if front_pages:
            chapter_records.append(
                ChapterRecord(
                    title="Front Matter",
                    page_start=front_pages[0],
                    page_end=front_pages[-1],
                    blocks=[page_blocks[page] for page in front_pages],
                )
            )

    for index, (page_start, chapter_title) in enumerate(deduped_items):
        next_page_start = deduped_items[index + 1][0] if index + 1 < len(deduped_items) else last_content_page + 1
        chapter_pages = [page for page in content_pages if page_start <= page < next_page_start]
        if not chapter_pages:
            continue
        chapter_records.append(
            ChapterRecord(
                title=chapter_title,
                page_start=chapter_pages[0],
                page_end=chapter_pages[-1],
                blocks=[page_blocks[page] for page in chapter_pages],
            )
        )

    return chapter_records


def write_chapter_files(
    output_dir: Path,
    title: str,
    source_pdf: Path,
    chapter_records: list[ChapterRecord],
) -> list[tuple[str, str, int, int]]:
    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    written_records: list[tuple[str, str, int, int]] = []
    for index, chapter in enumerate(chapter_records, start=1):
        chapter_title = choose_chapter_title(chapter)
        filename = (
            f"chapter-{index:03d}-pages-{chapter.page_start:04d}-{chapter.page_end:04d}-"
            f"{slugify(chapter_title)}.md"
        )
        write_chunk_file(
            chapters_dir / filename,
            f"{title} - {chapter_title}",
            source_pdf,
            chapter.page_start,
            chapter.page_end,
            chapter.blocks,
        )
        written_records.append((filename, chapter_title, chapter.page_start, chapter.page_end))

    return written_records


def extract_first_heading(blocks: list[str]) -> str | None:
    for block in blocks:
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                return normalize_text(stripped[4:])
            if stripped.startswith("#### "):
                return normalize_text(stripped[5:])
            if SECTION_HEADING_RE.match(stripped):
                return normalize_text(stripped)
    return None


def choose_chapter_title(chapter: ChapterRecord) -> str:
    normalized_title = normalize_outline_title(chapter.title)
    if not is_low_quality_outline_title(chapter.title):
        return normalized_title

    fallback_title = extract_first_heading(chapter.blocks)
    return fallback_title or normalized_title


def infer_table_page_span(lines: list[str], hinted_page_start: int, default_page_end: int) -> tuple[int, int]:
    pages: list[int] = [hinted_page_start]
    for line in lines:
        stripped = line.strip()
        if is_page_header_line(stripped):
            pages.append(int(stripped.rsplit(" ", 1)[-1]))

    if not pages:
        return hinted_page_start, default_page_end

    return min(pages), max(pages)


def extract_tables_from_markdown(
    markdown_text: str,
    default_page_start: int,
    default_page_end: int,
) -> list[TableRecord]:
    lines = markdown_text.splitlines()
    tables: list[TableRecord] = []
    current_match: re.Match[str] | None = None
    current_lines: list[str] = []
    last_seen_page = default_page_start
    current_start_page = default_page_start

    def flush_current() -> None:
        nonlocal current_match, current_lines, current_start_page
        if current_match is None:
            return

        page_hint_match = next(
            (TABLE_PAGE_HINT_RE.fullmatch(line.strip()) for line in current_lines if TABLE_PAGE_HINT_RE.fullmatch(line.strip())),
            None,
        )
        if page_hint_match is not None:
            page_start = int(page_hint_match.group("start"))
            page_end = int(page_hint_match.group("end"))
        else:
            page_start, page_end = infer_table_page_span(current_lines, current_start_page, default_page_end)
        tables.append(
            TableRecord(
                number=current_match.group("number"),
                title=normalize_text(current_match.group("title")),
                page_start=page_start,
                page_end=page_end,
                lines=current_lines[:],
            )
        )
        current_match = None
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if is_page_header_line(stripped):
            last_seen_page = int(stripped.rsplit(" ", 1)[-1])
        table_match = parse_table_title_line(stripped)
        if table_match is not None:
            flush_current()
            current_match = table_match
            current_start_page = last_seen_page
            current_lines = [stripped]
            continue

        if current_match is None:
            continue

        if stripped.startswith(("# ", "### ", "#### ", "##### ")) or SECTION_HEADING_RE.match(stripped):
            flush_current()
            continue

        current_lines.append(line)

    flush_current()
    return tables


def format_table_file_stem(table_number: str) -> str:
    if table_number.isdigit():
        return f"table-{int(table_number):03d}"
    return f"table-{slugify(table_number)}"


def write_table_files(
    output_dir: Path,
    title: str,
    chapter_records: list[tuple[str, str, int, int]],
) -> list[tuple[str, str, str, int, int]]:
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    written_records: list[tuple[str, str, str, int, int]] = []
    table_index_rows: list[tuple[str, str, str, str, str, int, int]] = []
    used_filenames: set[str] = set()

    for chapter_filename, chapter_title, default_page_start, default_page_end in chapter_records:
        chapter_path = output_dir / "chapters" / chapter_filename
        markdown_text = chapter_path.read_text(encoding="utf-8")
        for table in extract_tables_from_markdown(markdown_text, default_page_start, default_page_end):
            base_name = (
                f"{format_table_file_stem(table.number)}-pages-"
                f"{table.page_start:04d}-{table.page_end:04d}-{slugify(table.title)}"
            )
            filename = f"{base_name}.md"
            suffix = 2
            while filename in used_filenames:
                filename = f"{base_name}-{suffix}.md"
                suffix += 1
            used_filenames.add(filename)

            body_lines = table.lines[1:] if table.lines and is_table_title_line(table.lines[0]) else table.lines
            body_lines = [line for line in body_lines if TABLE_PAGE_HINT_RE.fullmatch(line.strip()) is None]
            content_lines = [
                f"# Table {table.number}. {table.title}",
                "",
                f"Source chapter: chapters/{chapter_filename}",
                f"Chapter title: {chapter_title}",
                f"PDF pages: {table.page_start}-{table.page_end}",
                "",
            ]
            if body_lines:
                content_lines.extend(body_lines)
                content_lines.append("")

            (tables_dir / filename).write_text("\n".join(content_lines), encoding="utf-8")
            written_records.append(
                (filename, f"Table {table.number}. {table.title}", chapter_title, table.page_start, table.page_end)
            )
            table_index_rows.append(
                (
                    filename,
                    table.number,
                    table.title,
                    chapter_filename,
                    chapter_title,
                    table.page_start,
                    table.page_end,
                )
            )

    lines = [
        f"# {title} Tables",
        "",
        "This directory contains one Markdown file per extracted table for focused workspace search.",
        "Machine-readable indexes are also available as tables.jsonl and tables.csv.",
        "",
    ]
    for filename, table_title, chapter_title, page_start, page_end in written_records:
        lines.append(
            f"- {filename}: {table_title} ({chapter_title}; PDF pages {page_start}-{page_end})"
        )
    lines.append("")
    (tables_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    jsonl_path = tables_dir / "tables.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for filename, number, table_title, chapter_filename, chapter_title, page_start, page_end in table_index_rows:
            handle.write(
                json.dumps(
                    {
                        "filename": filename,
                        "table_number": number,
                        "table_title": table_title,
                        "chapter_file": chapter_filename,
                        "chapter_title": chapter_title,
                        "page_start": page_start,
                        "page_end": page_end,
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")

    csv_path = tables_dir / "tables.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "filename",
            "table_number",
            "table_title",
            "chapter_file",
            "chapter_title",
            "page_start",
            "page_end",
        ])
        writer.writerows(table_index_rows)

    return written_records


def write_index(
    output_dir: Path,
    title: str,
    source_pdf: Path,
    chunk_records: list[tuple[str, int, int]],
    chapter_records: list[tuple[str, str, int, int]],
    table_records: list[tuple[str, str, str, int, int]],
) -> None:
    index_path = output_dir / "README.md"
    lines = [
        f"# {title}",
        "",
        "This directory contains a Markdown conversion of the source PDF for easier skill reading and workspace search.",
        "",
        f"Source PDF: {source_pdf.name}",
        "Artifacts:",
        "- outline.md: PDF bookmark outline extracted from the document",
        "- chapters/: body text split into chapter-based Markdown files",
        "- chunks/: body text split into page-based Markdown chunks",
        "- tables/: one Markdown file per extracted table for focused search",
        "",
        "## Chapters",
        "",
    ]
    for filename, chapter_title, page_start, page_end in chapter_records:
        lines.append(f"- chapters/{filename}: {chapter_title} (PDF pages {page_start}-{page_end})")
    lines.extend([
        "",
        "## Chunks",
        "",
    ])
    for filename, page_start, page_end in chunk_records:
        lines.append(f"- chunks/{filename}: PDF pages {page_start}-{page_end}")
    lines.extend([
        "",
        "## Tables",
        "",
        f"- tables/README.md: {len(table_records)} extracted tables indexed for focused search",
        "- tables/tables.jsonl: machine-readable table metadata for search pipelines",
        "- tables/tables.csv: spreadsheet-friendly table metadata index",
    ])
    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")


def convert(pdf_path: Path, output_dir: Path, chunk_size: int, first_page: int, last_page: int | None, title: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_generated_output(output_dir)
    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pdf-searchable-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        xml_prefix = tmp_dir / "document"
        xml_path = xml_prefix.with_suffix(".xml")
        run_pdftohtml(pdf_path, xml_prefix, first_page, last_page)

        outline_items: list[tuple[int, int, str]] = []
        chunk_records: list[tuple[str, int, int]] = []
        page_blocks: dict[int, str] = {}
        current_chunk_blocks: list[str] = []
        current_chunk_start: int | None = None
        current_chunk_end: int | None = None
        chunk_counter = 0

        in_page = False
        outline_depth = -1
        page_height = 0.0
        current_page_number = 0
        font_specs: dict[str, FontSpec] = {}
        page_fragments: list[TextFragment] = []

        for event, elem in ET.iterparse(xml_path, events=("start", "end")):
            tag = elem.tag

            if event == "start":
                if tag == "page":
                    in_page = True
                    current_page_number = int(elem.attrib["number"])
                    page_height = float(elem.attrib.get("height", "0"))
                    font_specs = {}
                    page_fragments = []
                elif tag == "outline" and not in_page:
                    outline_depth += 1
                continue

            if in_page and tag == "fontspec":
                font_specs[elem.attrib["id"]] = FontSpec(
                    size=float(elem.attrib.get("size", "0")),
                    color=elem.attrib.get("color", "#000000"),
                    opacity=float(elem.attrib.get("opacity", "1")),
                )
            elif in_page and tag == "text":
                raw_text = "".join(elem.itertext())
                text = normalize_text(raw_text)
                font = font_specs.get(elem.attrib.get("font", ""), FontSpec(0.0, "#000000", 1.0))
                page_fragments.append(
                    TextFragment(
                        top=float(elem.attrib.get("top", "0")),
                        left=float(elem.attrib.get("left", "0")),
                        width=float(elem.attrib.get("width", "0")),
                        height=float(elem.attrib.get("height", "0")),
                        text=text,
                        font=font,
                        bold=any(child.tag == "b" for child in elem.iter()),
                    )
                )
            elif in_page and tag == "page":
                page_block = format_page(current_page_number, page_height, page_fragments)
                if page_block:
                    page_blocks[current_page_number] = page_block
                    if current_chunk_start is None:
                        current_chunk_start = current_page_number
                    if (
                        current_chunk_start is not None
                        and current_page_number - current_chunk_start >= chunk_size
                        and current_chunk_blocks
                    ):
                        chunk_counter += 1
                        filename = (
                            f"chunk-{chunk_counter:03d}-pages-"
                            f"{current_chunk_start:04d}-{current_chunk_end:04d}.md"
                        )
                        write_chunk_file(
                            chunks_dir / filename,
                            title,
                            pdf_path,
                            current_chunk_start,
                            current_chunk_end,
                            current_chunk_blocks,
                        )
                        chunk_records.append((filename, current_chunk_start, current_chunk_end))
                        current_chunk_blocks = []
                        current_chunk_start = current_page_number

                    current_chunk_blocks.append(page_block)
                    current_chunk_end = current_page_number

                in_page = False
                elem.clear()
            elif tag == "item" and not in_page:
                item_text = normalize_text("".join(elem.itertext()))
                page = int(elem.attrib.get("page", "0"))
                if item_text and page:
                    outline_items.append((max(outline_depth, 0), page, item_text))
                elem.clear()
            elif tag == "outline" and not in_page:
                outline_depth -= 1
                elem.clear()
            elif not in_page:
                elem.clear()

        if current_chunk_blocks and current_chunk_start is not None and current_chunk_end is not None:
            chunk_counter += 1
            filename = (
                f"chunk-{chunk_counter:03d}-pages-"
                f"{current_chunk_start:04d}-{current_chunk_end:04d}.md"
            )
            write_chunk_file(
                chunks_dir / filename,
                title,
                pdf_path,
                current_chunk_start,
                current_chunk_end,
                current_chunk_blocks,
            )
            chunk_records.append((filename, current_chunk_start, current_chunk_end))

    chapter_records = write_chapter_files(
        output_dir,
        title,
        pdf_path,
        build_chapter_records(outline_items, page_blocks),
    )
    table_records = write_table_files(output_dir, title, chapter_records)
    write_outline(output_dir, title, outline_items, page_blocks)
    write_index(output_dir, title, pdf_path, chunk_records, chapter_records, table_records)


def main() -> None:
    args = parse_args()
    ensure_tool("pdftohtml")

    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size must be greater than 0")
    if args.first_page <= 0:
        raise SystemExit("--first-page must be greater than 0")
    if args.last_page is not None and args.last_page < args.first_page:
        raise SystemExit("--last-page must be greater than or equal to --first-page")

    output_root = args.output_root.resolve()

    if args.pdf is None:
        if args.output_dir is not None:
            raise SystemExit("output_dir requires an explicit pdf path")
        if args.title is not None:
            raise SystemExit("--title can only be used with an explicit pdf path")

        raw_dir = args.raw_dir.resolve()
        if not raw_dir.exists():
            raise SystemExit(f"Raw PDF directory not found: {raw_dir}")

        pdf_paths = discover_pdfs(raw_dir)
        if not pdf_paths:
            raise SystemExit(f"No PDF files found in: {raw_dir}")

        for pdf_path in pdf_paths:
            title = normalize_pdf_stem(pdf_path).replace("_", " ")
            output_dir = default_output_dir_for_pdf(pdf_path, output_root)
            print(f"[convert] {pdf_path.name} -> {output_dir}")
            convert(pdf_path, output_dir, args.chunk_size, args.first_page, args.last_page, title)
        return

    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    output_dir = args.output_dir.resolve() if args.output_dir is not None else default_output_dir_for_pdf(pdf_path, output_root)
    title = args.title or normalize_pdf_stem(pdf_path).replace("_", " ")
    print(f"[convert] {pdf_path.name} -> {output_dir}")
    convert(pdf_path, output_dir, args.chunk_size, args.first_page, args.last_page, title)


if __name__ == "__main__":
    main()