#!/usr/bin/env python
"""Portable local UI for IPS/HSD -> Copilot CLI workflows.

The app intentionally uses only the Python standard library so the hardware flow kit
can be copied to another Windows PC without installing web UI dependencies.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import date, datetime
import html
import json
import math
import os
import pathlib
import queue
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse, urlsplit


KIT_ROOT = pathlib.Path(__file__).resolve().parents[1]

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
AUTO_REPORTS_DIR = KIT_ROOT / "out" / "auto_reports"
MANUAL_REPORTS_DIR = KIT_ROOT / "out" / "manual_reports"
COMMON_ISSUE_DEFAULTS = {
    "maxDateRangeDays": 90,
    "defaultResultLimit": 50,
    "maxResultLimit": 200,
    "requestTimeoutSeconds": 120,
    "autoQueryArticleFetchMaxCount": 100,
    "autoQueryArticleFetchConcurrency": 6,
    "autoQueryArticleFetchTimeoutSeconds": 45,
    "autoQuerySightingFetchMaxCount": 100,
    "aiEnrichmentEnabled": True,
    "aiTimeoutSeconds": 120,
    "referenceAiBatchSize": 5,
    "referenceTopCount": 20,
    "eqlFields": {
        "id": "id",
        "title": "title",
        "description": "description",
        "platform": "family",
        "customer": "server_platf_ae.bug.ext_account_name",
        "component": "component",
        "submittedDate": "submitted_date",
        "sighting": "server_platf_ae.bug.int_sighting_url",
        "closeReason": "bug.closed_reason",
    },
    "platformAliases": {
        "BHS": ["Birch Stream Platform"],
        "OKS": ["Oak Stream DMR Platforms"],
        "EGS": ["Eagle Stream Platforms"],
    },
    "customerAliases": {
        "maginfra": ["Maginfra Co., Ltd."],
        "h3c": ["New H3C Information Technologies Co., Ltd"],
    },
    "reportDirectory": "out\\common_issue_reports",
}
ACTIVE_TASK_STATUSES = ("queued", "running", "waiting_resource", "cancelling")
TERMINAL_TASK_STATUSES = ("completed", "failed", "cancelled", "interrupted")


class DuplicateQueryTaskError(ValueError):
    def __init__(self, task: dict[str, Any]) -> None:
        self.task = task
        super().__init__(f"Query {task['query_id']} is already active")


def merge_config(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    template_path = KIT_ROOT / "config" / "ips-copilot-ui.template.json"
    if path.resolve() != template_path.resolve() and template_path.exists():
        with template_path.open("r", encoding="utf-8-sig") as f:
            cfg = merge_config(json.load(f), cfg)
    cfg["_config_path"] = str(path)
    return cfg


def load_machine_options(cfg: dict[str, Any]) -> list[dict[str, str]]:
    matching_cfg = cfg.get("machineMatching", {})
    inventory_path = pathlib.Path(
        matching_cfg.get("inventoryPath", "config/lab-machine-inventory.json")
    )
    if not inventory_path.is_absolute():
        inventory_path = KIT_ROOT / inventory_path
    with inventory_path.open("r", encoding="utf-8-sig") as f:
        inventory = json.load(f)

    options: list[dict[str, str]] = []
    for machine in inventory.get("machines", []):
        machine_id = safe_text(machine.get("id"))
        family = safe_text(machine.get("platformFamily"))
        user = safe_text(machine.get("ssh", {}).get("user"))
        host = safe_text(machine.get("ssh", {}).get("host"))
        if not all((machine_id, family, user, host)):
            raise ValueError(f"Invalid machine inventory entry: {machine!r}")
        options.append(
            {
                "value": f"{user}@{host}",
                "label": f"{machine_id} ({family}) - {user}@{host}",
            }
        )
    if not options:
        raise ValueError(f"No machines found in inventory: {inventory_path}")
    return options


def deep_set(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    node = cfg
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def require_numeric_id(value: str, field_name: str) -> str:
    if not value.isdigit():
        raise ValueError(f"{field_name} must contain digits only")
    return value


def auto_query_dir(query_id: str) -> pathlib.Path:
    return AUTO_REPORTS_DIR / f"query_{require_numeric_id(query_id, 'query_id')}"


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def safe_report_path(path_text: str) -> str:
    path = pathlib.Path(path_text)
    if path.is_absolute():
        raise ValueError("report_path must be relative to the kit root")
    resolved = (KIT_ROOT / path).resolve()
    out_root = (KIT_ROOT / "out").resolve()
    if resolved != out_root and out_root not in resolved.parents:
        raise ValueError("report_path must be under out")
    return str(resolved.relative_to(KIT_ROOT))


class CommonIssueFilters:
    """Validated, normalized read-only common-issue query inputs."""

    def __init__(self, platform: str, customer: str, submitted_start_date: str, submitted_end_date: str, component: str, keywords: str, result_limit: int) -> None:
        self.platform = platform
        self.customer = customer
        self.submitted_start_date = submitted_start_date
        self.submitted_end_date = submitted_end_date
        self.component = component
        self.keywords = keywords
        self.result_limit = result_limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform, "customer": self.customer,
            "submitted_start_date": self.submitted_start_date, "submitted_end_date": self.submitted_end_date,
            "component": self.component, "keywords": self.keywords, "result_limit": self.result_limit,
        }


class SightingLink:
    def __init__(self, url: str, title: str, reference: str, verified: bool, source_field: str) -> None:
        self.url, self.title, self.reference = url, title, reference
        self.verified, self.source_field = verified, source_field


class NormalizedCommonIssue:
    def __init__(self, **values: Any) -> None:
        self.values = values

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)


class CommonIssueGroup:
    def __init__(self, heading: str, common_problem_explanation: str, evidence_tier: str, grouping_key: str, records: list[dict[str, Any]]) -> None:
        self.heading, self.evidence_tier = heading, evidence_tier
        self.common_problem_explanation = common_problem_explanation
        self.grouping_key, self.records = grouping_key, records

    def to_dict(self) -> dict[str, Any]:
        return {
            "heading": self.heading, "evidence_tier": self.evidence_tier,
            "common_problem_explanation": self.common_problem_explanation,
            "grouping_key": self.grouping_key, "records": self.records,
        }


def common_issue_config(cfg: dict[str, Any]) -> dict[str, Any]:
    configured = cfg.get("commonIssueAnalysis", {})
    values = merge_config(COMMON_ISSUE_DEFAULTS, configured if isinstance(configured, dict) else {})
    try:
        values["maxDateRangeDays"] = max(1, int(values["maxDateRangeDays"]))
        values["defaultResultLimit"] = max(1, int(values["defaultResultLimit"]))
        values["maxResultLimit"] = max(values["defaultResultLimit"], int(values["maxResultLimit"]))
        values["requestTimeoutSeconds"] = max(1, int(values["requestTimeoutSeconds"]))
        values["aiTimeoutSeconds"] = max(1, int(values["aiTimeoutSeconds"]))
        values["referenceAiBatchSize"] = min(25, max(1, int(values["referenceAiBatchSize"])))
        values["referenceTopCount"] = min(50, max(1, int(values["referenceTopCount"])))
        values["autoQueryArticleFetchMaxCount"] = min(1000, max(1, int(values["autoQueryArticleFetchMaxCount"])))
        values["autoQueryArticleFetchConcurrency"] = min(32, max(1, int(values["autoQueryArticleFetchConcurrency"])))
        values["autoQueryArticleFetchTimeoutSeconds"] = min(300, max(1, int(values["autoQueryArticleFetchTimeoutSeconds"])))
        values["autoQuerySightingFetchMaxCount"] = min(1000, max(1, int(values["autoQuerySightingFetchMaxCount"])))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid commonIssueAnalysis configuration: {exc}") from exc
    if not isinstance(values["aiEnrichmentEnabled"], bool):
        raise ValueError("commonIssueAnalysis.aiEnrichmentEnabled must be a boolean")
    report_directory = pathlib.Path(safe_text(values["reportDirectory"]) or COMMON_ISSUE_DEFAULTS["reportDirectory"])
    if report_directory.is_absolute():
        resolved = report_directory.resolve()
    else:
        resolved = (KIT_ROOT / report_directory).resolve()
    out_root = (KIT_ROOT / "out").resolve()
    if resolved != out_root and out_root not in resolved.parents:
        raise ValueError("commonIssueAnalysis.reportDirectory must be under out")
    values["reportDirectory"] = str(resolved)
    return values


def common_issue_eql_fields(settings: dict[str, Any]) -> dict[str, str]:
    configured = settings.get("eqlFields", {})
    configured = configured if isinstance(configured, dict) else {}
    defaults = COMMON_ISSUE_DEFAULTS["eqlFields"]
    fields: dict[str, str] = {}
    for logical_name, default in defaults.items():
        field_name = safe_text(configured.get(logical_name, default))
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", field_name):
            raise ValueError(f"Invalid commonIssueAnalysis.eqlFields.{logical_name}")
        fields[logical_name] = field_name
    return fields


def _common_filter_text(value: Any, field_name: str) -> str:
    text = " ".join(safe_text(value).split())
    if len(text) > 160:
        raise ValueError(f"{field_name} is too long")
    if text and not re.fullmatch(r"[\w\u4e00-\u9fff .,:，；;/+&()#-]+", text):
        raise ValueError(f"{field_name} contains unsupported characters")
    return text


def validate_common_issue_filters(payload: dict[str, Any], cfg: dict[str, Any]) -> CommonIssueFilters:
    settings = common_issue_config(cfg)
    platform = _common_filter_text(payload.get("platform"), "platform")
    customer = _common_filter_text(payload.get("customer"), "customer")
    component = _common_filter_text(payload.get("component"), "component")
    keywords = _common_filter_text(payload.get("keywords"), "keywords")
    if not any((platform, customer, component, keywords)):
        raise ValueError("At least one of platform, customer, component, or keywords is required")
    start_text = safe_text(payload.get("submitted_start_date"))
    end_text = safe_text(payload.get("submitted_end_date"))
    try:
        start_date = date.fromisoformat(start_text)
        end_date = date.fromisoformat(end_text)
    except ValueError as exc:
        raise ValueError("submitted_start_date and submitted_end_date must use ISO YYYY-MM-DD") from exc
    if start_date.isoformat() != start_text or end_date.isoformat() != end_text:
        raise ValueError("submitted_start_date and submitted_end_date must use ISO YYYY-MM-DD")
    if start_date > end_date:
        raise ValueError("submitted_start_date must not be after submitted_end_date")
    if (end_date - start_date).days > settings["maxDateRangeDays"]:
        raise ValueError(f"Date range must not exceed {settings['maxDateRangeDays']} days")
    raw_limit = payload.get("result_limit", "")
    if raw_limit in ("", None):
        result_limit = settings["defaultResultLimit"]
    else:
        try:
            result_limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("result_limit must be an integer") from exc
    if not 1 <= result_limit <= settings["maxResultLimit"]:
        raise ValueError(f"result_limit must be between 1 and {settings['maxResultLimit']}")
    return CommonIssueFilters(platform, customer, start_text, end_text, component, keywords, result_limit)


def _candidate_value(row: dict[str, Any], candidates: tuple[str, ...]) -> tuple[str, str]:
    sources = [row]
    for name in ("fields", "attributes", "data"):
        nested = row.get(name)
        if isinstance(nested, dict):
            sources.append(nested)
    for candidate in candidates:
        parts = candidate.split(".")
        for source in sources:
            matching_key = next((key for key in source if key.lower() == candidate.lower()), None)
            if matching_key is not None:
                direct_value = source[matching_key]
                if isinstance(direct_value, (str, int, float)):
                    value = safe_text(direct_value)
                    if value:
                        return value, candidate
            current: Any = source
            for part in parts:
                if not isinstance(current, dict):
                    break
                matching_key = next((key for key in current if key.lower() == part.lower()), None)
                if matching_key is None:
                    break
                current = current[matching_key]
            else:
                if isinstance(current, (str, int, float)):
                    value = safe_text(current)
                    if value:
                        return value, candidate
    return "", ""


def derive_hsd_url(ips_id: str) -> str:
    return f"https://hsdes.intel.com/appstore/article_legacy/#/{ips_id}" if ips_id.isdigit() else ""


def _valid_sighting_url(value: str) -> str:
    parsed = urlsplit(value)
    return value if parsed.scheme in ("http", "https") and bool(parsed.netloc) else ""


def _normalize_sighting(row: dict[str, Any]) -> SightingLink:
    candidates = (
        "int_sighting_url", "int_sighting.id", "int_sighting.url",
        "server_platf_ae.bug.int_sighting_url",
        "in_sighting", "in_sighting_id", "in_sighting.id", "in_sighting.url",
        "tenant.in_sighting", "tenant.in_sighting_id", "tenant.in_sighting.id", "tenant.in_sighting.url",
        "sighting_id", "sighting.id", "sighting.url", "source_relationship", "source_relationship_id",
        "source_relationship.id", "source_relationship.url", "related_sighting", "related_sighting_id",
        "related_sighting.id", "related_sighting.url",
    )
    value, source_field = _candidate_value(row, candidates)
    title, _ = _candidate_value(row, (
        "in_sighting_title", "in_sighting.title", "tenant.in_sighting_title", "tenant.in_sighting.title",
        "sighting_title", "sighting.title", "source_relationship_title", "source_relationship.title",
        "related_sighting_title", "related_sighting.title",
    ))
    if not value:
        return SightingLink("", title, "", False, "")
    url = _valid_sighting_url(value)
    if not url:
        # HSD returns some int_sighting_url values as HTML/XML anchor markup.
        # Extract the actual target before validating it as a URL.
        match = re.search(r"https?://[^\s\"'<>()]+", html.unescape(value), flags=re.IGNORECASE)
        url = _valid_sighting_url(match.group(0)) if match else ""
    reference = ""
    if value.isdigit():
        reference = value
        url = derive_hsd_url(value)
    elif url:
        # HSD may expose the same sighting through URLs that differ only by
        # host case, trailing slash, fragment, or navigation query parameters.
        # Prefer its numeric article ID; otherwise retain a canonical URL key.
        numeric_ids = re.findall(r"(?<!\d)(\d{6,})(?!\d)", unquote(url))
        parsed = urlsplit(url)
        reference = numeric_ids[-1] if numeric_ids else (
            f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}".casefold()
        )
    else:
        return SightingLink("", title, "", False, source_field)
    # A populated candidate is not enough by itself: only a safely parsed URL or
    # numeric source relationship is considered verified grouping evidence.
    return SightingLink(url, title, reference, True, source_field)


def normalize_common_issue_type(row: dict[str, Any]) -> str:
    value, _ = _candidate_value(row, (
        "server_platf_ae.bug.article_type", "server_platf_ae.bug.ext_issue_type",
        "ips_type", "issue_type", "article_type", "problem_type", "type",
        "classification", "tenant.ips_type", "tenant.issue_type",
    ))
    lowered = value.casefold()
    if "question" in lowered:
        return "question"
    if any(token in lowered for token in ("debug", "defect", "bug")):
        return "debug"
    return "unknown"


def _bounded_content_text(value: Any, limit: int = 2000) -> str:
    """Extract text from known article-content fields while excluding attachments."""
    parts: list[str] = []

    def collect(item: Any) -> None:
        if len(" ".join(parts)) >= limit:
            return
        if isinstance(item, (str, int, float)):
            text = " ".join(safe_text(item).split())
            if text:
                parts.append(text)
        elif isinstance(item, list):
            for child in item:
                collect(child)
        elif isinstance(item, dict):
            for key, child in item.items():
                key_text = safe_text(key).casefold()
                if any(word in key_text for word in ("attachment", "payload", "binary", "filename", "mime", "image", "download")):
                    continue
                collect(child)

    collect(value)
    return " ".join(parts)[:limit]


def clean_hsd_text(value: Any, limit: int = 6000) -> str:
    """Remove rich-text markup so grouping uses the reported problem, not HTML/CSS."""
    text = html.unescape(safe_text(value)).replace("\xa0", " ")
    text = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    # HSD comments often begin with automatic routing/audit entries. They carry
    # assignment metadata and URLs, not customer symptoms or handling evidence.
    text = re.sub(
        r"\+{4}\d+\s+(?:sys_voc|sys_atpylot|ips_hsdes_brdg|sys_mule2hsd)\b.*?(?=\+{4}\d+|\Z)",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return " ".join(text.split())[:limit]


def _article_content_field(row: dict[str, Any], candidates: tuple[str, ...]) -> str:
    sources: list[dict[str, Any]] = [row]
    for name in ("fields", "attributes", "data"):
        nested = row.get(name)
        if isinstance(nested, dict):
            sources.append(nested)
    for candidate in candidates:
        parts = candidate.split(".")
        for source in sources:
            current: Any = source
            for part in parts:
                if not isinstance(current, dict):
                    break
                key = next((item for item in current if item.casefold() == part.casefold()), None)
                if key is None:
                    break
                current = current[key]
            else:
                text = _bounded_content_text(current)
                if text:
                    return text
    return ""


def _analysis_text_for_row(row: dict[str, Any], description: str) -> str:
    sections = (
        ("Customer description", description or _article_content_field(row, ("description", "problem_description", "issue_description"))),
        ("Failure signature", _article_content_field(row, ("failure_signature", "failure_signature_text", "symptom", "failure_symptom"))),
        ("Root cause", _article_content_field(row, ("root_cause", "root_cause_description", "cause", "analysis.root_cause"))),
        ("Comments", _article_content_field(row, ("comments", "comment", "discussion", "notes"))),
        ("Repro/debug", _article_content_field(row, ("repro", "reproduction_steps", "debug", "debug_notes", "investigation"))),
        ("Fix/workaround", _article_content_field(row, (
            "bug.fix_description", "fix_description", "workaround_description", "workaround",
            "server_platf_ae.bug.fix_description", "server_platf_ae.bug.workaround_description",
        ))),
        ("Customer history", _article_content_field(row, (
            "server_platf_ae.bug.ext_cust_blog_hist", "ext_cust_blog_hist", "customer_blog_history",
        ))),
        ("Internal sighting context", _article_content_field(row, ("int_sighting_context",))),
    )
    unique: set[str] = set()
    result: list[str] = []
    for label, text in sections:
        normalized = clean_hsd_text(text)
        if normalized and normalized.casefold() not in unique:
            unique.add(normalized.casefold())
            result.append(f"{label}: {normalized}")
    return "\n".join(result)[:6000]


def normalize_common_issue_row(row: dict[str, Any], eql_fields: dict[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("Common-issue search row must be an object")
    if eql_fields:
        row = dict(row)
        for logical_name, field_name in eql_fields.items():
            value, _ = _candidate_value(row, (field_name,))
            if value:
                row.setdefault(
                    {
                        "submittedDate": "submitted_date",
                        "sighting": "in_sighting",
                        "sightingTitle": "in_sighting_title",
                        "closeReason": "close_reason",
                    }.get(logical_name, logical_name),
                    value,
                )
    ips_id, _ = _candidate_value(row, ("id", "ips_id", "hsd_id", "article_id", "article.id"))
    title, _ = _candidate_value(row, ("title", "problem_title", "subject", "headline"))
    description, _ = _candidate_value(row, ("description", "problem_description", "issue_description"))
    customer_description = _article_content_field(
        row,
        (
            "customer_description", "customer_problem_description", "customer_issue_description",
            "tenant.customer_description", "server_platf_ae.bug.customer_description",
        ),
    ) or description
    customer_description = clean_hsd_text(customer_description)
    platform, _ = _candidate_value(row, (
        "platform", "platform_name", "tenant.platform", "tenant.platform_name", "platform.value",
    ))
    customer, _ = _candidate_value(row, (
        "customer_company", "tenant.customer_company", "server_platf_ae.bug.customer_company",
        "customer", "customer_name", "tenant.customer", "tenant.customer_name", "customer.company",
    ))
    owner, _ = _candidate_value(row, (
        "owner", "owner_name", "owner_user", "assigned_to", "assigned_to.name",
        "tenant.owner", "tenant.owner_name", "server_platf_ae.bug.owner",
    ))
    component, _ = _candidate_value(row, (
        "component", "component_name", "tenant.component", "tenant.component_name", "component.value",
    ))
    submitted_date, _ = _candidate_value(row, (
        "submitted_date", "submitted_on", "submitted_time", "created_at", "created_date",
    ))
    closed_date, _ = _candidate_value(row, (
        "closed_date", "closed_on", "closed_time", "completed_at", "completed_date",
        "resolved_at", "resolved_date", "end_date", "end_time", "last_updated_date", "updated_at",
    ))
    release, _ = _candidate_value(row, ("release", "release_affected", "server_platf_ae.bug.release"))
    project_name, _ = _candidate_value(row, (
        "customer_project_name", "tenant.customer_project_name", "server_platf_ae.bug.customer_project_name",
    ))
    priority, _ = _candidate_value(row, ("priority", "server_platf_ae.bug.ext_priority"))
    conclusion_type, _ = _candidate_value(row, ("conclusion_type", "server_platf_ae.bug.conclusion_type"))
    close_reason, _ = _candidate_value(row, (
        "close_reason", "close_reason_code", "resolution_reason", "bug.closed_reason",
        "bug.close_reason", "server_platf_ae.bug.close_reason",
    ))
    sighting = _normalize_sighting(row)
    issue = NormalizedCommonIssue(
        ips_id=ips_id,
        title=title,
        description=customer_description,
        customer_description=customer_description,
        analysis_text=_analysis_text_for_row(row, customer_description),
        platform=platform,
        customer=customer,
        owner=owner,
        component=component,
        ips_type=normalize_common_issue_type(row),
        release=release,
        customer_project_name=project_name,
        priority=priority,
        conclusion_type=conclusion_type,
        close_reason=close_reason,
        submitted_date=submitted_date[:10],
        closed_date=closed_date[:10],
        sighting_url=sighting.url,
        sighting_title=sighting.title,
        sighting_reference=sighting.reference,
        sighting_verified=sighting.verified,
        sighting_source_field=sighting.source_field,
        hsd_url=derive_hsd_url(ips_id),
    )
    return issue.to_dict()


def _title_tokens(value: str) -> tuple[str, ...]:
    ignored = {
        "the", "and", "with", "for", "from", "issue", "error", "failure", "problem", "问题", "失败",
        "http", "https", "www", "com", "intel", "hsdes", "appstore", "article", "legacy",
        "description", "comments", "repro", "debug", "root", "cause", "signature",
    }
    tokens: set[str] = set()
    for token in re.findall(r"[\w\u4e00-\u9fff]+", value.lower()):
        if len(token) <= 1 or token in ignored:
            continue
        # Ticket IDs, years, CSS units, and other copied rich-text artifacts
        # identify the source document rather than the hardware symptom.
        if token.isdigit() or re.fullmatch(r"\d+(?:px|pt|em|rem|vh|vw|%)", token):
            continue
        tokens.add(token)
    return tuple(sorted(tokens)[:8])


def common_issue_evidence(records: list[dict[str, Any]], evidence_tier: str) -> tuple[int, list[str]]:
    """Return transparent, conservative evidence indicators for a saved group."""
    references = {safe_text(record.get("sighting_reference")) for record in records if safe_text(record.get("sighting_reference"))}
    if evidence_tier == "强证据" and len(references) == 1:
        return 100, [f"共同已验证 SI/FW sighting：{next(iter(references))}"]
    if evidence_tier == "关联证据":
        return 75, [f"均有关联 int_sighting_url（{len(references)} 个不同链接）"]

    token_sets = [
        set(_title_tokens(safe_text(record.get("customer_description")) or safe_text(record.get("description"))))
        for record in records
    ]
    shared_tokens = sorted(set.intersection(*token_sets)) if token_sets else []
    signals = [f"共同问题关键词：{', '.join(shared_tokens[:6])}"] if shared_tokens else ["AI/规则依据问题正文归并；未发现共同 sighting"]
    score = 55 + min(20, len(shared_tokens) * 4)
    for label, field in (("平台一致", "platform"), ("组件一致", "component")):
        values = {safe_text(record.get(field)).casefold() for record in records if safe_text(record.get(field))}
        if len(values) == 1:
            signals.append(f"{label}：{next(iter(values))}")
            score += 8
    return min(score, 85), signals


def common_issue_aliases(value: Any, configured: Any) -> dict[str, tuple[str, ...]]:
    aliases = configured if isinstance(configured, dict) else COMMON_ISSUE_DEFAULTS["customerAliases"]
    normalized: dict[str, tuple[str, ...]] = {}
    for key, alternatives in aliases.items():
        values = alternatives if isinstance(alternatives, list) else [alternatives]
        safe_values = tuple(safe_text(item) for item in values if safe_text(item))
        if safe_values:
            normalized[safe_text(key).casefold()] = safe_values
    return normalized


def common_issue_platform_values(value: str, settings: dict[str, Any]) -> tuple[str, ...]:
    aliases = common_issue_aliases(value=None, configured=settings.get("platformAliases"))
    return aliases.get(value.casefold(), (value,))


def common_issue_customer_values(value: str, settings: dict[str, Any]) -> tuple[str, ...]:
    """Split user-entered customer alternatives and expand configured account aliases."""
    supplied = tuple(dict.fromkeys(
        item.strip() for item in re.split(r"[,，;；/]+", value) if item.strip()
    ))
    aliases = common_issue_aliases(value=None, configured=settings.get("customerAliases"))
    values = tuple(dict.fromkeys(
        alias for item in supplied for alias in aliases.get(item.casefold(), (item,))
    ))
    if len(values) > 20:
        raise ValueError("customer supports at most 20 values per analysis")
    return values


def _eql_equals_any(field: str, values: tuple[str, ...]) -> str:
    if len(values) == 1:
        return f"{field} = '{values[0]}'"
    return "(" + " OR ".join(f"{field} = '{value}'" for value in values) + ")"


def build_common_issue_groups(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservative fallback: group only shared sighting or customer-described symptoms."""
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    description_clusters: list[dict[str, Any]] = []
    for original in sorted(issues, key=lambda item: safe_text(item.get("ips_id"))):
        issue = dict(original)
        sighting_reference = safe_text(issue.get("sighting_reference"))
        if issue.get("sighting_verified") and sighting_reference:
            buckets.setdefault(("sighting", sighting_reference), []).append(issue)
            continue

        # Do not make a common-problem claim from a matching title alone.
        # The customer-reported description is the fallback's primary evidence.
        tokens = set(_title_tokens(safe_text(issue.get("customer_description")) or safe_text(issue.get("description"))))
        if len(tokens) < 2:
            continue
        matching_cluster = next(
            (
                cluster for cluster in description_clusters
                if len(tokens.intersection(cluster["shared_tokens"])) >= 2
            ),
            None,
        )
        if matching_cluster is None:
            description_clusters.append({"records": [issue], "shared_tokens": tokens})
        else:
            matching_cluster["records"].append(issue)
            matching_cluster["shared_tokens"].intersection_update(tokens)
    for cluster in description_clusters:
        shared_tokens = tuple(sorted(cluster["shared_tokens"]))
        if len(cluster["records"]) >= 2 and len(shared_tokens) >= 2:
            buckets[("customer_description", " ".join(shared_tokens))] = cluster["records"]

    # Preserve same-link groups as strong evidence.  IPS that each have an
    # int_sighting_url but no shared URL are still useful cross-team references,
    # so list them once as an association category rather than claiming a root
    # cause or duplicating them into a content group.
    distinct_int_sighting_records: list[dict[str, Any]] = []
    for key in list(buckets):
        records = buckets[key]
        if (
            key[0] == "sighting"
            and len(records) == 1
            and "int_sighting" in safe_text(records[0].get("sighting_source_field")).casefold()
        ):
            distinct_int_sighting_records.extend(buckets.pop(key))
    if len(distinct_int_sighting_records) >= 2:
        buckets[("int_sighting_related", "distinct")] = distinct_int_sighting_records

    groups: list[dict[str, Any]] = []
    for key in sorted(buckets):
        records = sorted(buckets[key], key=lambda item: (safe_text(item.get("ips_id")), safe_text(item.get("title"))))
        if len(records) < 2:
            continue
        if key[0] == "sighting":
            title = next((safe_text(item.get("sighting_title")) for item in records if safe_text(item.get("sighting_title"))), "")
            heading = f"共同 SI/FW Sighting：{title or key[1]}"
            tier = "强证据"
            reason = f"已验证的共同 sighting 关系：{key[1]}"
            explanation = f"这些记录都关联到已验证的 SI/FW sighting {key[1]}，因此可能反映同一已知问题或修复轨迹；仍需核对各 IPS 的实际症状。"
        elif key[0] == "int_sighting_related":
            heading = "有 int_sighting_url 的 IPS"
            tier = "关联证据"
            reason = "这些 IPS 都有关联的 int_sighting_url，但链接并不相同。"
            explanation = "这些 IPS 均关联到内部 sighting，是可供跨团队参考的处理线索；不同链接不代表它们具有相同根因，应继续根据问题描述和各自 sighting 内容核对。"
        else:
            heading = f"客户描述相似问题：{key[1]}"
            tier = "候选证据"
            reason = f"客户问题描述的共同关键词：{key[1]}"
            explanation = "这些记录的客户问题描述呈现相同症状或触发条件，但没有已验证的共同 sighting；它们仍是待人工确认的共性问题候选。"
        confidence_score, evidence_signals = common_issue_evidence(records, tier)
        groups.append(CommonIssueGroup(
            heading=heading,
            common_problem_explanation=explanation,
            evidence_tier=tier,
            grouping_key="|".join(key),
            records=[dict(record, grouping_reason=reason) for record in records],
        ).to_dict() | {
            "confidence_score": confidence_score,
            "evidence_signals": evidence_signals,
            "debug_count": sum(safe_text(record.get("ips_type")) == "debug" for record in records),
            "question_count": sum(safe_text(record.get("ips_type")) == "question" for record in records),
        })
    return groups


def validate_ai_common_issue_groups(
    value: Any, issues: list[dict[str, Any]], return_status: bool = False
) -> Any:
    fallback = build_common_issue_groups(issues)
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict) or set(parsed) != {"groups"} or not isinstance(parsed["groups"], list):
            raise ValueError("invalid top-level schema")
        known_ids = {safe_text(item.get("ips_id")) for item in issues if safe_text(item.get("ips_id"))}
        used_ids: set[str] = set()
        records_by_id = {safe_text(item.get("ips_id")): item for item in issues}
        groups: list[dict[str, Any]] = []
        for group in parsed["groups"]:
            if not isinstance(group, dict) or set(group) != {
                "heading", "common_problem_explanation", "evidence_tier", "ips_ids", "grouping_reason"
            }:
                raise ValueError("invalid group schema")
            if group["evidence_tier"] not in ("强证据", "关联证据", "候选证据") or not isinstance(group["ips_ids"], list):
                raise ValueError("invalid group values")
            heading = safe_text(group["heading"])
            explanation = safe_text(group["common_problem_explanation"])
            reason = safe_text(group["grouping_reason"])
            ids = [safe_text(item) for item in group["ips_ids"]]
            if not heading or not explanation or not reason or len(ids) < 2 or len(ids) != len(set(ids)):
                raise ValueError("invalid group text or duplicate ids")
            if any(item not in known_ids or item in used_ids for item in ids):
                raise ValueError("unknown or repeated IPS ID")
            used_ids.update(ids)
            records = [records_by_id[item] for item in ids]
            tier = group["evidence_tier"]
            references = {
                safe_text(record.get("sighting_reference"))
                for record in records
                if record.get("sighting_verified") and safe_text(record.get("sighting_reference"))
            }
            if tier == "强证据" and not (len(references) == 1 and len(references) == len(records)):
                tier = "候选证据"
            if tier == "关联证据" and not (
                len(references) > 1
                and len(references) == len(records)
                and all("int_sighting" in safe_text(record.get("sighting_source_field")).casefold() for record in records)
            ):
                tier = "候选证据"
            groups.append({
                "heading": heading,
                "common_problem_explanation": explanation,
                "evidence_tier": tier,
                "grouping_key": "ai|" + "|".join(ids),
                "records": [dict(record, grouping_reason=reason) for record in records],
            })
            groups[-1].update(dict(zip(
                ("confidence_score", "evidence_signals"),
                common_issue_evidence(groups[-1]["records"], tier),
            )))
            groups[-1]["debug_count"] = sum(
                safe_text(record.get("ips_type")) == "debug" for record in groups[-1]["records"]
            )
            groups[-1]["question_count"] = sum(
                safe_text(record.get("ips_type")) == "question" for record in groups[-1]["records"]
            )
        return (groups, True) if return_status else groups
    except (TypeError, ValueError, json.JSONDecodeError):
        return (fallback, False) if return_status else fallback


def enforce_int_sighting_association_group(
    groups: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reserve the distinct-int-sighting reference category even after AI grouping."""
    required = [
        group for group in build_common_issue_groups(issues)
        if safe_text(group.get("grouping_key")).startswith("int_sighting_related|")
    ]
    if not required:
        return groups
    reserved_ids = grouped_common_issue_ids(required)
    remaining: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict) or safe_text(group.get("grouping_key")).startswith("int_sighting_related|"):
            continue
        records = [
            record for record in group.get("records", [])
            if isinstance(record, dict) and safe_text(record.get("ips_id")) not in reserved_ids
        ]
        if len(records) < 2:
            continue
        updated = dict(group, records=records)
        score, signals = common_issue_evidence(records, safe_text(updated.get("evidence_tier")))
        updated["confidence_score"] = score
        updated["evidence_signals"] = signals
        updated["debug_count"] = sum(safe_text(record.get("ips_type")) == "debug" for record in records)
        updated["question_count"] = sum(safe_text(record.get("ips_type")) == "question" for record in records)
        remaining.append(updated)
    return remaining + required


def build_common_issue_eql(filters: CommonIssueFilters, settings: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Build EQL from already validated filters; values cannot contain EQL quotes."""
    fields = common_issue_eql_fields(settings)
    selected = list(dict.fromkeys(fields.values()))
    conditions = [
        f"{fields['submittedDate']} >= '{filters.submitted_start_date} 00:00:00'",
        f"{fields['submittedDate']} <= '{filters.submitted_end_date} 23:59:59'",
    ]
    platforms = common_issue_platform_values(filters.platform, settings) if filters.platform else ()
    if platforms:
        conditions.append(_eql_equals_any(fields["platform"], platforms))
    for logical_name, value in (("component", filters.component), ("title", filters.keywords)):
        if value:
            conditions.append(f"{fields[logical_name]} = '{value}'")
    customers = common_issue_customer_values(filters.customer, settings)
    if customers:
        conditions.append(_eql_equals_any(fields["customer"], customers))
    return f"select {','.join(selected)} where {' AND '.join(conditions)}", fields


def execute_common_issue_search(filters: CommonIssueFilters, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    filters = validate_common_issue_filters(filters.to_dict(), cfg)
    settings = common_issue_config(cfg)
    eql, _ = build_common_issue_eql(filters, settings)
    command = [
        "curl.exe", "--noproxy", "*", "--negotiate", "-u", ":", "-L", "-sS",
        "--request", "POST", "--header", "Content-Type: application/json",
        "--data", json.dumps({"eql": eql}, ensure_ascii=False),
        "https://hsdes-api.intel.com/rest/query/execution/eql?start_at=1",
    ]
    result = subprocess.run(
        command, cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=settings["requestTimeoutSeconds"], check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Common-issue HSD request failed (exit {result.returncode}): {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    rows: Any = payload
    if isinstance(payload, dict):
        rows = next((payload.get(name) for name in ("data", "results", "items") if isinstance(payload.get(name), list)), None)
    if not isinstance(rows, list):
        message = safe_text(payload.get("message")) if isinstance(payload, dict) else "unexpected response"
        raise RuntimeError(f"Common-issue HSD search returned no usable rows: {message}")
    return [row for row in rows if isinstance(row, dict)]


def _bounded_common_issue_records(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "ips_id", "ips_type", "title", "customer_description", "description", "analysis_text",
        "platform", "customer", "customer_project_name", "component", "release", "priority",
        "conclusion_type", "close_reason", "submitted_date",
        "sighting_url", "sighting_reference", "sighting_title", "sighting_verified",
    )
    return [
        {
            name: bool(issue.get(name)) if name == "sighting_verified" else safe_text(issue.get(name))[:4000 if name == "analysis_text" else 2000 if name == "description" else 500]
            for name in fields
        }
        for issue in issues[:200]
    ]


def _extract_json_object(text: str) -> str | None:
    """Return the first complete JSON object from bounded Copilot output."""
    text = safe_text(text)[:65536]
    for start in (index for index, character in enumerate(text) if character == "{"):
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            character = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
            elif character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:index + 1]
                    try:
                        if isinstance(json.loads(candidate), dict):
                            return candidate
                    except json.JSONDecodeError:
                        pass
                    break
    return None


def build_common_issue_ai_prompt(issues: list[dict[str, Any]]) -> str:
    records = _bounded_common_issue_records(issues)
    return f"""You are performing read-only common-issue grouping from the supplied normalized HSD records.
Do not use tools, skills, terminals, files, network access, SSH, or any hardware action. Do not flash, power-cycle,
use serial, run MLC, or control any device. Analyze only the JSON records below.

Return exactly one JSON object and no Markdown or prose. It must pass this strict schema exactly:
{{"groups":[{{"heading":"string","common_problem_explanation":"string","evidence_tier":"强证据 or 关联证据 or 候选证据","ips_ids":["known IPS ID"],"grouping_reason":"string"}}]}}

Return only a true common-problem group containing at least 2 IPS IDs; omit any singleton or unclustered IPS. Each
included ips_id may occur once at most. Do not invent IDs or facts. Make categories broad enough to cover the shared
problem pattern, rather than using one ticket title per group. The explanation must describe the common problem and
uncertainty, not merely a count. Prioritize ips_type=debug and unknown records. Question records are lower-priority
historical references, but may form a group when their descriptions have a clear shared symptom or verified sighting.
Start with customer_description/description: compare the customer-reported symptom, trigger or configuration, impact,
and observed failure signature. Use root cause, comments, and repro/debug details in analysis_text to decide whether
the cases are useful shared references. Categories may be moderately broad when the reported problem pattern is
meaningfully shared. A similar title, platform, component, customer, date, ticket ID, URL, or shared generic word
alone is insufficient to group IPS. Do not stop after only the most exact duplicate: create moderately broad candidate
groups whenever two or more records share a meaningful technical symptom, failure area, trigger, or handling pattern
in their supplied content. Do not claim a root cause unless the supplied record explicitly supports it. Use 强证据 only
for a verified common sighting, including a common int_sighting_url.
When two or more otherwise-unclustered records have int_sighting_url values that differ, return one separate
`有 int_sighting_url 的 IPS` group with tier `关联证据`; explain that the links differ and do not prove the same root cause.

Normalized records:
{json.dumps(records, ensure_ascii=False, separators=(",", ":"))}
"""


def enrich_common_issue_groups(
    issues: list[dict[str, Any]], cfg: dict[str, Any], settings: dict[str, Any]
) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
    fallback = build_common_issue_groups(issues)
    if not settings["aiEnrichmentEnabled"]:
        return fallback, "deterministic_fallback", {
            "status": "disabled",
            "limitation": "AI enrichment is disabled; deterministic grouping was used.",
        }
    if any(not safe_text(issue.get("ips_id")) for issue in issues):
        return fallback, "deterministic_fallback", {
            "status": "unavailable",
            "limitation": "Some normalized records have no IPS ID, so strict AI validation cannot safely cover them; deterministic grouping was used.",
        }
    copilot_cfg = cfg.get("copilot", {})
    if copilot_cfg.get("mode", "manual") != "subprocess" or copilot_cfg.get("stage2Mode", "subprocess") != "subprocess":
        return fallback, "deterministic_fallback", {
            "status": "manual_or_handoff",
            "limitation": "Copilot is configured for manual or handoff mode, so deterministic grouping was used.",
        }
    ai_cfg = merge_config(
        cfg,
        {"copilot": {"timeoutSeconds": settings["aiTimeoutSeconds"], "prependCommands": []}},
    )
    try:
        code, output = run_copilot(build_common_issue_ai_prompt(issues), ai_cfg)
    except Exception:
        return fallback, "deterministic_fallback", {
            "status": "unavailable",
            "limitation": "AI enrichment was unavailable; deterministic grouping was used.",
        }
    if code == 124:
        return fallback, "deterministic_fallback", {
            "status": "timeout",
            "limitation": "AI enrichment timed out; deterministic grouping was used.",
        }
    if code != 0:
        return fallback, "deterministic_fallback", {
            "status": "unavailable",
            "limitation": "AI enrichment was unavailable; deterministic grouping was used.",
        }
    response = _extract_json_object(output)
    groups, valid = validate_ai_common_issue_groups(response, issues, return_status=True)
    if not valid:
        return groups, "deterministic_fallback", {
            "status": "invalid_response",
            "limitation": "AI output did not pass strict JSON validation; deterministic grouping was used.",
        }
    return enforce_int_sighting_association_group(groups, issues), "ai_enriched", {"status": "validated", "limitation": ""}


def reference_content_signals(issue: dict[str, Any]) -> list[str]:
    analysis_text = safe_text(issue.get("analysis_text"))
    description = safe_text(issue.get("customer_description")) or safe_text(issue.get("description"))
    signals: list[str] = []
    if len(_title_tokens(description)) >= 2:
        signals.append("Clear customer symptom or impact description")
    if "Failure signature:" in analysis_text or "Repro/debug:" in analysis_text:
        signals.append("Failure signature, trigger, reproduction, or debug evidence")
    if any(label in analysis_text for label in ("Root cause:", "Fix/workaround:")):
        signals.append("Root cause, fix, or workaround evidence")
    return signals


def reference_internal_evidence_score(issue: dict[str, Any]) -> int:
    sighting = bool(issue.get("sighting_verified")) and "int_sighting" in safe_text(
        issue.get("sighting_source_field")
    ).casefold()
    sighting_context = safe_text(issue.get("int_sighting_context"))
    internal_close = safe_text(issue.get("close_reason")).casefold().startswith("internal_")
    return (10 if sighting else 0) + (7 if sighting and sighting_context else 0) + (3 if internal_close else 0)


def reference_maturity_score(issue: dict[str, Any]) -> int:
    analysis_text = safe_text(issue.get("analysis_text"))
    has_resolution = any(label in analysis_text for label in ("Root cause:", "Fix/workaround:"))
    has_debug_direction = "Repro/debug:" in analysis_text
    status = safe_text(issue.get("query_status")).casefold()
    if status in {"closed", "complete", "completed", "resolved"}:
        return 15 if has_resolution else (7 if has_debug_direction else 0)
    if status == "open":
        return 8 if (has_resolution or has_debug_direction) else 3
    return 0


def reference_applicability_score(issue: dict[str, Any]) -> int:
    fields = ("platform", "release", "component")
    score = sum(3 for field in fields if safe_text(issue.get(field)))
    return min(10, score + (1 if safe_text(issue.get("customer_project_name")) else 0))


def deterministic_reference_component_scores(issue: dict[str, Any]) -> tuple[int, int, int]:
    analysis_text = safe_text(issue.get("analysis_text"))
    description = safe_text(issue.get("customer_description")) or safe_text(issue.get("description"))
    has_problem = len(_title_tokens(description)) >= 2
    has_failure_or_repro = "Failure signature:" in analysis_text or "Repro/debug:" in analysis_text
    has_resolution = any(label in analysis_text for label in ("Root cause:", "Fix/workaround:"))
    problem_score = (12 if has_problem else 0) + (13 if has_failure_or_repro else 0)
    reuse_score = 30 if has_resolution else (15 if has_failure_or_repro else 0)
    return min(25, problem_score), reuse_score, reference_applicability_score(issue)


def deterministic_reference_assessments(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assessments: list[dict[str, Any]] = []
    for original in sorted(issues, key=lambda item: safe_text(item.get("ips_id"))):
        issue = dict(original)
        content_signals = reference_content_signals(issue)
        problem_score, reuse_score, applicability_score = deterministic_reference_component_scores(issue)
        internal_evidence_score = reference_internal_evidence_score(issue)
        maturity_score = reference_maturity_score(issue)
        sighting = internal_evidence_score >= 10
        internal_close = safe_text(issue.get("close_reason")).casefold().startswith("internal_")
        evidence: list[str] = []
        if sighting:
            evidence.append("Verified internal sighting link")
        if internal_close:
            evidence.append(f"Internal close reason: {safe_text(issue.get('close_reason'))}")
        evidence.extend(content_signals)
        reusable = problem_score >= 12 and reuse_score >= 10
        score = problem_score + reuse_score + internal_evidence_score + maturity_score + applicability_score
        if reusable and reuse_score >= 25 and maturity_score >= 8:
            level = "强烈推荐"
        elif reusable and score >= 45:
            level = "推荐参考"
        else:
            level = "暂不推荐"
        assessments.append({
            "ips_id": safe_text(issue.get("ips_id")),
            "recommendation_level": level,
            "reference_score": score,
            "scoring_source": "deterministic_fallback",
            "problem_score": problem_score,
            "reuse_score": reuse_score,
            "internal_evidence_score": internal_evidence_score,
            "maturity_score": maturity_score,
            "applicability_score": applicability_score,
            "content_score": problem_score + reuse_score + applicability_score,
            "summary": safe_text(issue.get("title")) or "Title unavailable",
            "reuse_reason": "; ".join(evidence) or "No internal association or reusable handling evidence recorded",
            "applicability": "Verify applicability against platform, version, configuration, and trigger conditions",
            "limitations": "" if reusable else "No clear problem pattern and reusable handling or debug evidence were recorded.",
            "evidence": evidence,
            "record": issue,
        })
    return assessments


def build_reference_ai_prompt(issues: list[dict[str, Any]]) -> str:
    records = _bounded_common_issue_records(issues)
    for record in records:
        record["description"] = safe_text(record.get("description"))[:1000]
        record["customer_description"] = safe_text(record.get("customer_description"))[:1000]
        record["analysis_text"] = safe_text(record.get("analysis_text"))[:1800]
    return f"""You are performing read-only IPS reference-value assessment from the supplied normalized HSD records.
Do not use tools, skills, terminals, files, network access, SSH, or any hardware action. Analyze only the JSON records below.

Return exactly one JSON object and no Markdown or prose. It must pass this strict schema exactly:
{{"recommendations":[{{"ips_id":"known IPS ID","problem_score":0,"reuse_score":0,"applicability_score":0,"recommendation_level":"强烈推荐 or 推荐参考 or 暂不推荐","summary":"string","reuse_reason":"string","applicability":"string","limitations":"string"}}]}}

Evaluate every supplied IPS candidate independently. Do not group, merge, compare, or require multiple IPS. The purpose is to select
an IPS that other engineers can reuse as a reference, not to claim that Query IPS have a common root cause.
Assign `problem_score` from 0 to 25 for a concrete technical symptom/failure, impact, and trigger/configuration. Assign
`reuse_score` from 0 to 30 for a reusable diagnosis, root cause, fix, workaround, reproduction, or debug direction. Assign
`applicability_score` from 0 to 10 only when the supplied platform, release, component, project, version, or configuration
meaningfully defines where the handling applies. The application independently computes up to 20 internal-evidence points and
up to 15 resolution-maturity points from verified fields and status; do not include them in your scores.
Use 强烈推荐 when the content has a concrete problem pattern, strong reusable handling, and a mature resolution or clear ongoing
debug direction; use 推荐参考 when it has a concrete problem pattern plus a useful debug or handling direction.
Do not reject solely because a formal root cause or environment field is absent: state an unavailable field as an applicability
limitation. Use 暂不推荐 only when the supplied content is genuinely limited to vague progress, routing metadata, a title-only match,
or no technical problem pattern.
Rank every candidate honestly; a candidate can still be a useful internal reference when its score is lower. State the specific
supplied evidence in `reuse_reason` and any uncertainty in `limitations`; do not invent facts.
Platform, release, component, project, and priority are applicability context, not proof of commonality.
Write `summary`, `reuse_reason`, `applicability`, and `limitations` in English.

Normalized records:
{json.dumps(records, ensure_ascii=False, separators=(",", ":"))}
"""


def validate_reference_ai_assessments(value: Any, issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    fallback = deterministic_reference_assessments(issues)
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        recommendations = parsed.get("recommendations") if isinstance(parsed, dict) and set(parsed) == {"recommendations"} else None
        if not isinstance(recommendations, list):
            raise ValueError("invalid top-level schema")
        issue_by_id = {safe_text(issue.get("ips_id")): issue for issue in issues}
        if len(recommendations) != len(issue_by_id):
            raise ValueError("every IPS must be assessed once")
        assessments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in recommendations:
            if not isinstance(item, dict) or set(item) != {
                "ips_id", "problem_score", "reuse_score", "applicability_score", "recommendation_level", "summary", "reuse_reason", "applicability", "limitations",
            }:
                raise ValueError("invalid recommendation schema")
            ips_id = safe_text(item["ips_id"])
            if ips_id not in issue_by_id or ips_id in seen:
                raise ValueError("unknown or duplicate IPS ID")
            seen.add(ips_id)
            level = safe_text(item["recommendation_level"])
            if level not in ("强烈推荐", "推荐参考", "暂不推荐"):
                raise ValueError("invalid recommendation level")
            problem_score = int(item["problem_score"])
            reuse_score = int(item["reuse_score"])
            applicability_score = int(item["applicability_score"])
            if not 0 <= problem_score <= 25 or not 0 <= reuse_score <= 30 or not 0 <= applicability_score <= 10:
                raise ValueError("invalid reference component score")
            if not all(safe_text(item[field]) for field in ("summary", "reuse_reason", "applicability", "limitations")):
                raise ValueError("recommendation explanation fields must be populated")
            issue = issue_by_id[ips_id]
            content_signals = reference_content_signals(issue)
            internal_evidence_score = reference_internal_evidence_score(issue)
            maturity_score = reference_maturity_score(issue)
            if problem_score < 12 or reuse_score < 10:
                level = "暂不推荐"
            elif level == "强烈推荐" and not (reuse_score >= 25 and maturity_score >= 8):
                level = "推荐参考"
            assessments.append({
                "ips_id": ips_id,
                "recommendation_level": level,
                "reference_score": problem_score + reuse_score + applicability_score + internal_evidence_score + maturity_score,
                "scoring_source": "ai",
                "problem_score": problem_score,
                "reuse_score": reuse_score,
                "applicability_score": applicability_score,
                "internal_evidence_score": internal_evidence_score,
                "maturity_score": maturity_score,
                "content_score": problem_score + reuse_score + applicability_score,
                "summary": safe_text(item["summary"]),
                "reuse_reason": safe_text(item["reuse_reason"]),
                "applicability": safe_text(item["applicability"]),
                "limitations": safe_text(item["limitations"]),
                "evidence": (
                    (["int_sighting_url 有有效内部链接"] if internal_evidence_score >= 10 else [])
                    + ([f"close_reason 为内部标签：{safe_text(issue.get('close_reason'))}"] if safe_text(issue.get("close_reason")).casefold().startswith("internal_") else [])
                    + content_signals
                ),
                "record": issue,
            })
        return assessments, True
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback, False


def enrich_reference_assessments(
    issues: list[dict[str, Any]], cfg: dict[str, Any], settings: dict[str, Any]
) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
    fallback = deterministic_reference_assessments(issues)
    if not issues:
        return fallback, "not_needed", {"status": "no_issues", "limitation": "No IPS was available for AI assessment."}
    if not settings["aiEnrichmentEnabled"]:
        return fallback, "deterministic_fallback", {"status": "disabled", "limitation": "AI reference assessment is disabled; deterministic rules were used."}
    copilot_cfg = cfg.get("copilot", {})
    if copilot_cfg.get("mode", "manual") != "subprocess" or copilot_cfg.get("stage2Mode", "subprocess") != "subprocess":
        return fallback, "deterministic_fallback", {"status": "manual_or_handoff", "limitation": "Copilot is configured for manual or handoff mode, so deterministic rules were used."}
    ai_cfg = merge_config(cfg, {"copilot": {"timeoutSeconds": settings["aiTimeoutSeconds"], "prependCommands": []}})
    assessments: list[dict[str, Any]] = []
    fallback_batches = 0
    fallback_reasons: dict[str, int] = {}
    batch_size = settings["referenceAiBatchSize"]
    for start in range(0, len(issues), batch_size):
        batch = issues[start:start + batch_size]
        try:
            code, output = run_copilot(build_reference_ai_prompt(batch), ai_cfg)
            if code == 0:
                batch_assessments, valid = validate_reference_ai_assessments(_extract_json_object(output), batch)
                reason = "invalid_response" if not valid else ""
            else:
                batch_assessments, valid = deterministic_reference_assessments(batch), False
                reason = "timeout" if code == 124 else f"exit_{code}"
        except Exception as exc:
            batch_assessments, valid = deterministic_reference_assessments(batch), False
            reason = type(exc).__name__
        assessments.extend(batch_assessments)
        if not valid:
            fallback_batches += 1
            fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1
    assessments.sort(key=lambda item: safe_text(item.get("ips_id")))
    if fallback_batches:
        return assessments, "partial_ai_enriched", {
            "status": "partial",
            "limitation": (
                f"AI assessment fell back to deterministic rules for {fallback_batches} of "
                f"{math.ceil(len(issues) / batch_size)} batches "
                f"({', '.join(f'{key}: {count}' for key, count in sorted(fallback_reasons.items()))})."
            ),
        }
    return assessments, "ai_enriched", {"status": "validated", "limitation": ""}


def reference_assessment_sort_key(assessment: dict[str, Any]) -> tuple[int, int, int, int, str]:
    record = assessment.get("record", {})
    record = record if isinstance(record, dict) else {}
    reference_date = safe_text(record.get("closed_date")) or safe_text(record.get("submitted_date"))
    try:
        date_rank = -date.fromisoformat(reference_date[:10]).toordinal()
    except ValueError:
        date_rank = 0
    return (
        -int(assessment.get("reference_score", 0)),
        -int(assessment.get("maturity_score", 0)),
        -int(assessment.get("reuse_score", 0)),
        date_rank,
        safe_text(assessment.get("ips_id")),
    )


def grouped_common_issue_ids(groups: list[dict[str, Any]]) -> set[str]:
    return {
        safe_text(record.get("ips_id"))
        for group in groups
        if isinstance(group, dict)
        for record in group.get("records", [])
        if isinstance(record, dict) and safe_text(record.get("ips_id"))
    }


class CommonIssueReportStore:
    """Persistence isolated from automatic Query tasks; common-issue analysis is read-only."""

    def __init__(self, report_directory: pathlib.Path) -> None:
        self.report_directory = report_directory.resolve()
        self.database_path = self.report_directory / "common_issue_reports.sqlite3"
        self._lock = threading.RLock()
        self.report_directory.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS common_issue_reports ("
                "id TEXT PRIMARY KEY, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
                "status TEXT NOT NULL, filters_json TEXT NOT NULL, report_path TEXT NOT NULL, error_text TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS common_issue_feedback ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL, grouping_key TEXT NOT NULL, "
                "action TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, "
                "FOREIGN KEY(report_id) REFERENCES common_issue_reports(id))"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_common_issue_feedback_report ON common_issue_feedback(report_id, grouping_key, created_at DESC)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.database_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, filters: CommonIssueFilters) -> dict[str, Any]:
        report_id = str(uuid.uuid4())
        report_path = self.report_directory / report_id / "report.json"
        now = time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO common_issue_reports (id,created_at,updated_at,status,filters_json,report_path) VALUES (?,?,?,?,?,?)",
                (report_id, now, now, "running", json.dumps(filters.to_dict(), ensure_ascii=False), str(report_path)),
            )
            conn.commit()
        return self.load(report_id)

    def update(self, report_id: str, status: str, report: dict[str, Any] | None = None, error_text: str = "") -> dict[str, Any]:
        record = self.load(report_id)
        if report is not None:
            write_json(pathlib.Path(record["report_path"]), report)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE common_issue_reports SET status=?,updated_at=?,error_text=? WHERE id=?",
                (status, time.time(), safe_text(error_text), report_id),
            )
            conn.commit()
        return self.load(report_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM common_issue_reports ORDER BY created_at DESC").fetchall()
        return [self._record(row, include_report=False) for row in rows]

    def load(self, report_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f-]{36}", report_id):
            raise FileNotFoundError("common issue report not found")
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM common_issue_reports WHERE id=?", (report_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("common issue report not found")
        return self._record(row, include_report=True)

    def add_feedback(self, report_id: str, grouping_key: str, action: str, note: str) -> dict[str, Any]:
        if action not in ("confirmed", "split", "excluded"):
            raise ValueError("feedback action must be confirmed, split, or excluded")
        grouping_key = safe_text(grouping_key)
        note = " ".join(safe_text(note).split())
        if not grouping_key or len(grouping_key) > 1000:
            raise ValueError("invalid grouping_key")
        if len(note) > 1000:
            raise ValueError("feedback note is too long")
        record = self.load(report_id)
        report = record.get("report", {})
        groups = report.get("groups", []) if isinstance(report, dict) else []
        if not any(isinstance(group, dict) and safe_text(group.get("grouping_key")) == grouping_key for group in groups):
            raise ValueError("common-issue group not found")
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO common_issue_feedback (report_id,grouping_key,action,note,created_at) VALUES (?,?,?,?,?)",
                (report_id, grouping_key, action, note, time.time()),
            )
            conn.commit()
        return self.load(report_id)

    def _feedback(self, report_id: str) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT grouping_key,action,note,created_at FROM common_issue_feedback WHERE report_id=? ORDER BY created_at DESC",
                (report_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _record(self, row: sqlite3.Row, include_report: bool) -> dict[str, Any]:
        record = dict(row)
        record["filters"] = json.loads(record.pop("filters_json"))
        if include_report and pathlib.Path(record["report_path"]).exists():
            record["report"] = read_json(pathlib.Path(record["report_path"]))
            record["report"]["feedback"] = self._feedback(record["id"])
        return record


COMMON_ISSUE_STORE: CommonIssueReportStore | None = None


def get_common_issue_store(cfg: dict[str, Any]) -> CommonIssueReportStore:
    global COMMON_ISSUE_STORE
    directory = pathlib.Path(common_issue_config(cfg)["reportDirectory"])
    if COMMON_ISSUE_STORE is None or COMMON_ISSUE_STORE.report_directory != directory.resolve():
        COMMON_ISSUE_STORE = CommonIssueReportStore(directory)
    return COMMON_ISSUE_STORE


def create_common_issue_report(filters: CommonIssueFilters, cfg: dict[str, Any], provider: Any = None) -> dict[str, Any]:
    store = get_common_issue_store(cfg)
    record = store.create(filters)
    try:
        rows = execute_common_issue_search(filters, cfg)
        settings = common_issue_config(cfg)
        eql_fields = common_issue_eql_fields(settings)
        issues = [normalize_common_issue_row(row, eql_fields) for row in rows][:filters.result_limit]
        if callable(provider):
            groups, valid = validate_ai_common_issue_groups(provider(issues), issues, return_status=True)
            analysis_mode = "ai_enriched" if valid else "deterministic_fallback"
            ai_enrichment = {
                "status": "validated_provider" if valid else "invalid_response",
                "limitation": "" if valid else "Injected AI output did not pass strict JSON validation; deterministic grouping was used.",
            }
        else:
            groups, analysis_mode, ai_enrichment = enrich_common_issue_groups(issues, cfg, settings)
        grouped_ids = grouped_common_issue_ids(groups)
        report = {
            "id": record["id"],
            "created_at": record["created_at"],
            "filters": filters.to_dict(),
            "issues": issues,
            "groups": groups,
            "grouped_issue_count": len(grouped_ids),
            "filtered_single_issue_count": max(0, len(issues) - len(grouped_ids)),
            "analysis_mode": analysis_mode,
            "ai_enrichment": ai_enrichment,
            "field_mapping_caveat": "HSD tenant schemas vary. Verify and adjust commonIssueAnalysis.eqlFields for the selected fields and filters; normalized fields are parsed defensively.",
            "read_only": True,
        }
        return store.update(record["id"], "completed", report)["report"]
    except Exception as exc:
        store.update(record["id"], "failed", error_text=f"{type(exc).__name__}: {exc}")
        raise


def report_url(report_base_url: str, path: str) -> str:
    base = report_base_url.rstrip("/")
    return f"{base}{path}" if base else ""


class TaskStore:
    """SQLite-backed shared state for automatic Query tasks and machine reservations."""

    def __init__(self, path: pathlib.Path, per_machine_concurrency: dict[str, Any] | None = None, recover_active: bool = True) -> None:
        self.path = path
        self.per_machine_concurrency = per_machine_concurrency or {"default": 1}
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize(recover_active)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self, recover_active: bool) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS query_tasks (
                    id TEXT PRIMARY KEY,
                    query_id TEXT NOT NULL,
                    creator_name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    status TEXT NOT NULL,
                    current_ips_id TEXT NOT NULL DEFAULT '',
                    current_round INTEGER NOT NULL DEFAULT 0,
                    interval_seconds INTEGER NOT NULL,
                    report_only INTEGER NOT NULL DEFAULT 0,
                    manager_recipients TEXT NOT NULL DEFAULT '',
                    report_base_url TEXT NOT NULL DEFAULT '',
                    output TEXT NOT NULL DEFAULT '',
                    cancellation_reason TEXT NOT NULL DEFAULT '',
                    processed_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    process_id INTEGER,
                    report_path TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS machine_locks (
                    machine_key TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    PRIMARY KEY (machine_key, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_query_tasks_status ON query_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_machine_locks_machine ON machine_locks(machine_key);
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(query_tasks)").fetchall()}
            if "report_only" not in columns:
                conn.execute("ALTER TABLE query_tasks ADD COLUMN report_only INTEGER NOT NULL DEFAULT 0")
            if recover_active:
                now = time.time()
                conn.execute(
                    "UPDATE query_tasks SET status='interrupted', completed_at=?, updated_at=?, "
                    "cancellation_reason=CASE WHEN cancellation_reason='' THEN ? ELSE cancellation_reason END "
                    "WHERE status IN ('queued','running','waiting_resource','cancelling')",
                    (now, now, "UI service restarted; automatic processing was not resumed."),
                )

    @staticmethod
    def _task(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        task = dict(row)
        try:
            task["processed"] = json.loads(task.pop("processed_json"))
        except (TypeError, json.JSONDecodeError):
            task["processed"] = {}
        return task

    def create_task(self, query_id: str, creator_name: str, interval_minutes: int, manager_recipients: str, report_base_url: str, report_only: bool = False) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO query_tasks (id,query_id,creator_name,created_at,updated_at,status,interval_seconds,report_only,manager_recipients,report_base_url) "
                "VALUES (?,?,?,?,?,'queued',?,?,?,?)",
                (task_id, query_id, creator_name, now, now, 0 if report_only else interval_minutes * 60, int(report_only), manager_recipients, report_base_url),
            )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as conn:
            return self._task(conn.execute("SELECT * FROM query_tasks WHERE id=?", (task_id,)).fetchone())

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM query_tasks ORDER BY created_at DESC").fetchall()
            return [self._task(row) for row in rows if row is not None]

    def find_active_query(self, query_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM query_tasks WHERE query_id=? AND status IN ('queued','running','waiting_resource','cancelling') "
                "ORDER BY created_at DESC LIMIT 1",
                (query_id,),
            ).fetchone()
            return self._task(row)

    def list_machine_locks(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT ml.machine_key,ml.task_id,ml.acquired_at,qt.query_id,qt.creator_name,qt.status,qt.current_ips_id "
                "FROM machine_locks ml LEFT JOIN query_tasks qt ON qt.id=ml.task_id ORDER BY ml.acquired_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def update(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "started_at", "completed_at", "current_ips_id", "current_round", "manager_recipients", "report_base_url", "cancellation_reason", "processed_json", "error_text", "process_id", "report_path"}
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return self.get_task(task_id) or {}
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(f"UPDATE query_tasks SET {assignments} WHERE id=?", (*values.values(), task_id))
        return self.get_task(task_id) or {}

    def append_output(self, task_id: str, text: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE query_tasks SET output=substr(output || ?, -200000), updated_at=? WHERE id=?",
                (f"[{timestamp}] {text.rstrip()}\n", time.time(), task_id),
            )

    def request_cancel(self, task_id: str, reason: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError("task not found")
        if task["status"] in TERMINAL_TASK_STATUSES:
            return task
        if task["status"] == "queued":
            return self.update(task_id, status="cancelled", completed_at=time.time(), cancellation_reason=reason, current_ips_id="")
        return self.update(task_id, status="cancelling", cancellation_reason=reason)

    def machine_limit(self, machine_key: str) -> int:
        value = self.per_machine_concurrency.get(machine_key, self.per_machine_concurrency.get("default", 1))
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def try_acquire_machine(self, task_id: str, machine_key: str) -> bool:
        machine_key = safe_text(machine_key)
        if not machine_key:
            raise ValueError("machine_key is required")
        with self._lock, closing(self._connect()) as conn:
            existing = conn.execute("SELECT 1 FROM machine_locks WHERE machine_key=? AND task_id=?", (machine_key, task_id)).fetchone()
            if existing:
                return True
            active = conn.execute("SELECT COUNT(*) FROM machine_locks WHERE machine_key=?", (machine_key,)).fetchone()[0]
            if active >= self.machine_limit(machine_key):
                return False
            conn.execute("INSERT INTO machine_locks (machine_key,task_id,acquired_at) VALUES (?,?,?)", (machine_key, task_id, time.time()))
            return True

    def release_machine(self, task_id: str, machine_key: str = "") -> None:
        with self._lock, closing(self._connect()) as conn:
            if machine_key:
                conn.execute("DELETE FROM machine_locks WHERE task_id=? AND machine_key=?", (task_id, machine_key))
            else:
                conn.execute("DELETE FROM machine_locks WHERE task_id=?", (task_id,))

    def cleanup(self, retention_days: int) -> None:
        if retention_days <= 0:
            return
        cutoff = time.time() - retention_days * 86400
        with self._lock, closing(self._connect()) as conn:
            conn.execute("DELETE FROM query_tasks WHERE completed_at IS NOT NULL AND completed_at < ?", (cutoff,))


def auto_round_dir(query_id: str, round_number: int, task_id: str = "") -> pathlib.Path:
    if round_number < 1:
        raise ValueError("round must be at least 1")
    base = auto_query_dir(query_id)
    return (base / f"task_{task_id}" if task_id else base) / f"round_{round_number}"


def auto_round_path(query_id: str, round_number: int, task_id: str = "") -> pathlib.Path:
    return auto_round_dir(query_id, round_number, task_id) / "round.json"


def write_auto_round(record: dict[str, Any]) -> None:
    write_json(auto_round_path(safe_text(record["query_id"]), int(record["round"]), safe_text(record.get("task_id"))), record)


def load_auto_round(query_id: str, round_number: int, task_id: str = "") -> dict[str, Any]:
    return read_json(auto_round_path(query_id, round_number, task_id))


def list_auto_rounds() -> list[dict[str, Any]]:
    if not AUTO_REPORTS_DIR.exists():
        return []
    records: list[dict[str, Any]] = []
    for round_path in AUTO_REPORTS_DIR.glob("query_*/**/round.json"):
        try:
            record = read_json(round_path)
            common = record.get("common_issue_analysis", {})
            common = common if isinstance(common, dict) else {}
            records.append({
                "task_id": safe_text(record.get("task_id")), "query_id": safe_text(record.get("query_id")),
                "round": int(record.get("round", 0)), "started_at": safe_text(record.get("started_at")),
                "completed_at": safe_text(record.get("completed_at")), "status": safe_text(record.get("status")),
                "item_count": len(record.get("items", [])),
                "query_ips_count": int(common.get("query_ips_total", common.get("total_ips", 0)) or 0),
            })
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda item: (item["started_at"], item["task_id"], item["round"]), reverse=True)


def manual_report_path(job_id: str) -> pathlib.Path:
    return MANUAL_REPORTS_DIR / f"{job_id}.json"


def write_manual_report(record: dict[str, Any]) -> None:
    write_json(manual_report_path(safe_text(record["id"])), record)


def load_manual_report(job_id: str) -> dict[str, Any]:
    return read_json(manual_report_path(job_id))


def normalize_report_center_summary(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "problem_analysis": safe_text(source.get("problem_analysis")),
        "diagnostic_results": safe_text(source.get("diagnostic_results")),
        "next_steps": [safe_text(item) for item in source.get("next_steps", []) if safe_text(item)] if isinstance(source.get("next_steps"), list) else [],
        "customer_information_needed": [safe_text(item) for item in source.get("customer_information_needed", []) if safe_text(item)] if isinstance(source.get("customer_information_needed"), list) else [],
        "risks_and_limitations": safe_text(source.get("risks_and_limitations")),
        "resource_request_path": safe_text(source.get("resource_request_path")),
        "resource_request_status": safe_text(source.get("resource_request_status")),
    }


def load_report_center_summary(path_text: str) -> dict[str, Any]:
    if not path_text:
        return normalize_report_center_summary({})
    try:
        return normalize_report_center_summary(read_json(KIT_ROOT / safe_report_path(path_text)))
    except (OSError, ValueError, json.JSONDecodeError):
        return normalize_report_center_summary({})


def resource_request_draft_path(record: dict[str, Any]) -> pathlib.Path:
    summary = normalize_report_center_summary(record.get("report_center_summary"))
    path = safe_report_path(summary["resource_request_path"])
    if pathlib.Path(path).name != "resource_request_draft.md":
        raise ValueError("invalid resource request path")
    return KIT_ROOT / path


def save_resource_request_details(
    job_id: str, expected_ddl: Any, resource: Any, duration: Any, manager_recipient: Any
) -> dict[str, Any]:
    ddl, resource, duration, manager = (
        safe_text(expected_ddl), safe_text(resource), safe_text(duration), safe_text(manager_recipient)
    )
    if not ddl or not resource or not duration or not manager:
        raise ValueError("期望 DDL、需占用的资源、预计占用时长和老板收件人均为必填项")
    record = load_manual_report(job_id)
    path = resource_request_draft_path(record)
    content = path.read_text(encoding="utf-8-sig")
    placeholders = {
        "<MANUAL_DDL>": ("期望 DDL：", ddl),
        "<MANUAL_RESOURCE>": ("预计占用：", resource),
        "<MANUAL_DURATION>": ("预计时长：", duration),
    }
    for token, (label, value) in placeholders.items():
        if token in content:
            content = content.replace(token, value)
            continue
        pattern = rf"(?m)^(\s*(?:[-*]\s+)?{re.escape(label)}).*$"
        content, replacements = re.subn(pattern, lambda match: f"{match.group(1)}{value}", content, count=1)
        if replacements != 1:
            raise ValueError(f"资源协调草稿缺少“{label}”字段，无法安全更新")
    path.write_text(content, encoding="utf-8")
    record["resource_request_details_saved"] = True
    record["resource_request_recipient"] = manager
    record["resource_request_details"] = {
        "expected_ddl": ddl,
        "resource_to_reserve": resource,
        "reservation_duration": duration,
    }
    write_manual_report(record)
    return {"path": str(path.relative_to(KIT_ROOT))}


def resource_request_email_content(record: dict[str, Any], report_link: str) -> tuple[str, str]:
    details = record.get("resource_request_details", {})
    details = details if isinstance(details, dict) else {}
    ips_id = safe_text(record.get("ips_id")) or "未填写"
    resource = safe_text(details.get("resource_to_reserve")) or "详见附件"
    ddl = safe_text(details.get("expected_ddl")) or "待确认"
    duration = safe_text(details.get("reservation_duration")) or "待确认"
    subject = f"[Copilot][HSD {ips_id}] 资源协调申请"
    body = (
        "您好，\n\n"
        f"因 IPS/HSD {ips_id} 验证需要，申请协助协调以下资源：\n"
        f"- 所需资源：{resource}\n"
        f"- 期望时间：{ddl}\n"
        f"- 预计占用：{duration}\n\n"
        "烦请协助确认是否可以安排。详细清单见附件；如时间需要调整，我们会同步更新验证排期。\n\n"
        f"查看申请：{report_link}\n"
        "谢谢。"
    )
    return subject, body


def list_manual_reports() -> list[dict[str, Any]]:
    if not MANUAL_REPORTS_DIR.exists():
        return []
    records: list[dict[str, Any]] = []
    for report_path in MANUAL_REPORTS_DIR.glob("*.json"):
        try:
            record = read_json(report_path)
            records.append(
                {
                    "id": safe_text(record.get("id")),
                    "ips_id": safe_text(record.get("ips_id")),
                    "task_type": safe_text(record.get("task_type")),
                    "ui_mode": safe_text(record.get("ui_mode")),
                    "submitted_by": safe_text(record.get("submitted_by")),
                    "recipient": safe_text(record.get("recipient")),
                    "status": safe_text(record.get("status")),
                    "created_at": float(record.get("created_at", 0)),
                    "completed_at": float(record.get("completed_at", 0)),
                }
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def list_task_center_records() -> list[dict[str, Any]]:
    """Combine persisted manual reports and Query tasks for the shared task center."""
    records: list[dict[str, Any]] = []
    for report in list_manual_reports():
        mode = "简洁模式" if report["ui_mode"] == "simple" else "计划审阅模式"
        records.append(
            {
                "id": report["id"],
                "source": "manual",
                "title": f"IPS/HSD {report['ips_id'] or '未填写'}",
                "mode": mode,
                "task_type": report["task_type"] or "未记录",
                "submitter": report["submitted_by"] or "未填写",
                "status": report["status"] or "未记录",
                "created_at": report["created_at"],
                "completed_at": report["completed_at"],
                "progress": "已结束" if report["status"] in TERMINAL_TASK_STATUSES else "正在执行",
                "detail_href": f"/reports/manual/{quote(report['id'])}",
            }
        )
    if TASK_MANAGER is not None:
        for task in TASK_MANAGER.list():
            records.append(
                {
                    "id": task["id"],
                    "source": "query",
                    "title": f"Query {task['query_id']}",
                    "mode": "全自动 Query",
                    "task_type": "仅共性报告" if task.get("report_only") else "定时处理 Open IPS",
                    "submitter": safe_text(task.get("creator_name")) or "未填写",
                    "status": safe_text(task.get("status")) or "未记录",
                    "created_at": float(task.get("created_at", 0)),
                    "completed_at": float(task.get("completed_at", 0)),
                    "progress": f"第 {int(task.get('current_round', 0))} 轮 · 当前 IPS {safe_text(task.get('current_ips_id')) or '—'}",
                    "detail_href": f"/tasks/{quote(task['id'])}",
                }
            )
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def is_registered_report_path(report_path: str) -> bool:
    for record in list_auto_rounds():
        try:
            round_record = load_auto_round(record["query_id"], record["round"], record["task_id"])
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if any(isinstance(item, dict) and safe_text(item.get("report_path")) == report_path for item in round_record.get("items", [])):
            return True
    return False


def execute_hsd_query(query_id: str, all_pages: bool = False) -> list[dict[str, Any]]:
    """Read one Saved Query page, or every page for the read-only reference report."""
    query_id = require_numeric_id(query_id, "query_id")
    start_at = 1
    rows: list[dict[str, Any]] = []
    while True:
        command = [
            "curl.exe", "--noproxy", "*", "--negotiate", "-u", ":", "-L", "-sS",
            f"https://hsdes-api.intel.com/rest/query/execution/{query_id}?start_at={start_at}",
        ]
        result = subprocess.run(
            command, cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"HSD query request failed (exit {result.returncode}): {result.stderr.strip()}")
        payload = json.loads(result.stdout)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            message = safe_text(payload.get("message")) if isinstance(payload, dict) else "unexpected response"
            raise RuntimeError(f"HSD query returned no data: {message}")
        page_rows = [row for row in data if isinstance(row, dict)]
        rows.extend(page_rows)
        total = int(payload.get("total", len(rows))) if isinstance(payload, dict) else len(rows)
        if not all_pages or not page_rows or len(rows) >= total:
            return rows
        start_at += len(page_rows)


def fetch_hsd_article_content(ips_id: str, timeout_seconds: int) -> dict[str, Any]:
    """Read one authenticated HSD article without persisting an individual artifact."""
    article_id = require_numeric_id(ips_id, "ips_id")
    command = [
        "curl.exe", "--noproxy", "*", "--negotiate", "-u", ":", "-L", "-sS",
        f"https://hsdes-api.intel.com/rest/article/{article_id}",
    ]
    try:
        result = subprocess.run(
            command, cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_seconds, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"HSD article {article_id} request failed: {type(exc).__name__}: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"HSD article {article_id} request failed (exit {result.returncode}): {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HSD article {article_id} returned invalid JSON: {exc}") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        message = safe_text(payload.get("message")) if isinstance(payload, dict) else "unexpected response"
        raise RuntimeError(f"HSD article {article_id} returned no usable data[0]: {message}")
    return data[0]


def _is_populated_article_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def select_auto_query_article_ids(unique_rows: dict[str, dict[str, Any]], max_count: int) -> list[str]:
    """Keep every Open IPS when possible, then fill the bounded set with newest terminal IPS."""
    all_ids = list(unique_rows)
    if len(all_ids) <= max_count:
        return all_ids

    def date_rank(ips_id: str, field: str) -> int:
        value = _reference_date(unique_rows[ips_id].get(field))
        return value.toordinal() if value else 0

    open_ids = sorted(
        (ips_id for ips_id in all_ids if safe_text(unique_rows[ips_id].get("status")).casefold() == "open"),
        key=lambda ips_id: (-date_rank(ips_id, "submitted_date"), ips_id),
    )
    terminal_ids = sorted(
        (ips_id for ips_id in all_ids if safe_text(unique_rows[ips_id].get("status")).casefold() != "open"),
        key=lambda ips_id: (-date_rank(ips_id, "closed_date"), -date_rank(ips_id, "submitted_date"), ips_id),
    )
    if len(open_ids) >= max_count:
        return open_ids[:max_count]
    return open_ids + terminal_ids[:max_count - len(open_ids)]


def enrich_auto_query_article_rows(
    rows: list[dict[str, Any]], cfg: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch each unique saved-Query IPS article concurrently, preserving Query status."""
    settings = common_issue_config(cfg)
    unique_rows: dict[str, dict[str, Any]] = {}
    nonnumeric_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ips_id, _ = _candidate_value(row, ("id", "ips_id", "hsd_id", "article_id", "article.id"))
        if not ips_id.isdigit():
            nonnumeric_rows += 1
            continue
        unique_rows.setdefault(ips_id, row)
    all_ids = list(unique_rows)
    max_count = settings["autoQueryArticleFetchMaxCount"]
    selected_ids = select_auto_query_article_ids(unique_rows, max_count)
    failures: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(settings["autoQueryArticleFetchConcurrency"], len(selected_ids) or 1)) as executor:
        futures = {
            executor.submit(fetch_hsd_article_content, ips_id, settings["autoQueryArticleFetchTimeoutSeconds"]): ips_id
            for ips_id in selected_ids
        }
        for future in as_completed(futures):
            ips_id = futures[future]
            try:
                details[ips_id] = future.result()
            except Exception as exc:
                failures[ips_id] = f"{type(exc).__name__}: {exc}"
    failed_ids = sorted(failures)
    failure_cap = 20
    limitations: list[str] = []
    if len(all_ids) > max_count:
        selected_open_count = sum(
            safe_text(unique_rows[ips_id].get("status")).casefold() == "open"
            for ips_id in selected_ids
        )
        limitations.append(
            f"Blocking limitation: Query returned {len(all_ids)} unique numeric IPS, exceeding the article fetch limit "
            f"of {max_count}; all {selected_open_count} "
            f"selected Open IPS were retained and remaining capacity was filled by newest terminal IPS, not all Query IPS."
        )
    if failed_ids:
        limitations.append(
            f"Problem content could not be retrieved for {len(failed_ids)} requested IPS; those rows remain read-only "
            "historical evidence with insufficient-content grouping where no saved content is available."
        )
    if nonnumeric_rows:
        limitations.append(f"{nonnumeric_rows} Query row(s) without a numeric IPS ID were not eligible for article fetch.")
    enriched_rows: list[dict[str, Any]] = []
    for ips_id in selected_ids:
        saved = unique_rows[ips_id]
        merged = dict(saved)
        for key, value in details.get(ips_id, {}).items():
            if key.casefold() not in ("status", "query_status") and _is_populated_article_value(value):
                merged[key] = value
        merged["query_status"] = safe_text(saved.get("status")).lower() or "unknown"
        merged["article_content_fetched"] = ips_id in details
        enriched_rows.append(merged)
    sighting_targets: dict[str, list[dict[str, Any]]] = {}
    for row in enriched_rows:
        normalized = normalize_common_issue_row(row)
        sighting_id = safe_text(normalized.get("sighting_reference"))
        if normalized.get("sighting_verified") and sighting_id.isdigit() and sighting_id != safe_text(normalized.get("ips_id")):
            sighting_targets.setdefault(sighting_id, []).append(row)
    all_sighting_ids = list(sighting_targets)
    selected_sighting_ids = all_sighting_ids[:settings["autoQuerySightingFetchMaxCount"]]
    sighting_details: dict[str, dict[str, Any]] = {}
    sighting_failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(settings["autoQueryArticleFetchConcurrency"], len(selected_sighting_ids) or 1)) as executor:
        futures = {
            executor.submit(fetch_hsd_article_content, sighting_id, settings["autoQueryArticleFetchTimeoutSeconds"]): sighting_id
            for sighting_id in selected_sighting_ids
        }
        for future in as_completed(futures):
            sighting_id = futures[future]
            try:
                sighting_details[sighting_id] = future.result()
            except Exception as exc:
                sighting_failures[sighting_id] = f"{type(exc).__name__}: {exc}"
    for sighting_id, linked_rows in sighting_targets.items():
        article = sighting_details.get(sighting_id)
        if not article:
            continue
        context = _analysis_text_for_row(article, _article_content_field(article, ("description", "problem_description")))
        for row in linked_rows:
            row["int_sighting_context"] = context
            row["int_sighting_content_fetched"] = True
    if len(all_sighting_ids) > len(selected_sighting_ids):
        limitations.append(
            f"Only {len(selected_sighting_ids)} of {len(all_sighting_ids)} unique int_sighting_url articles were fetched."
        )
    if sighting_failures:
        limitations.append(
            f"Internal sighting content could not be retrieved for {len(sighting_failures)} linked articles."
        )
    return enriched_rows, {
        "query_rows": len(rows),
        "unique_numeric_ips": len(all_ids),
        "requested": len(selected_ids),
        "fetched": len(details),
        "failed": len(failed_ids),
        "failed_ids": failed_ids[:failure_cap],
        "failed_errors": [
            {"ips_id": ips_id, "error": failures[ips_id]} for ips_id in failed_ids[:failure_cap]
        ],
        "failed_ids_truncated": len(failed_ids) > failure_cap,
        "failed_id_cap": failure_cap,
        "max_count": max_count,
        "skipped_by_limit": max(0, len(all_ids) - len(selected_ids)),
        "sighting_requested": len(selected_sighting_ids),
        "sighting_fetched": len(sighting_details),
        "sighting_failed": len(sighting_failures),
        "sighting_failed_ids": sorted(sighting_failures)[:failure_cap],
        "sighting_skipped_by_limit": max(0, len(all_sighting_ids) - len(selected_sighting_ids)),
        "limitation": " ".join(limitations),
    }


def build_auto_query_common_issue_analysis(
    rows: list[dict[str, Any]], cfg: dict[str, Any], content_fetch: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assess every saved-Query IPS independently; only Open IPS may enter the debug worker."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        issue = normalize_common_issue_row(row)
        ips_id = safe_text(issue.get("ips_id"))
        if not ips_id:
            continue
        issue["query_status"] = safe_text(row.get("query_status") or row.get("status")).lower() or "unknown"
        issue["article_content_fetched"] = bool(row.get("article_content_fetched"))
        by_id.setdefault(ips_id, issue)
    issues = list(by_id.values())
    settings = common_issue_config(cfg)
    candidate_issues = issues
    assessments, analysis_mode, ai_enrichment = enrich_reference_assessments(candidate_issues, cfg, settings)
    recommendations = sorted(
        assessments,
        key=reference_assessment_sort_key,
    )[:settings["referenceTopCount"]]
    fetch_summary = dict(content_fetch or {})
    fetch_summary.setdefault("query_rows", len(rows))
    fetch_summary.setdefault("unique_numeric_ips", len(issues))
    fetch_summary.setdefault("requested", 0)
    fetch_summary.setdefault("fetched", 0)
    fetch_summary.setdefault("failed", 0)
    fetch_summary.setdefault("failed_ids", [])
    fetch_summary.setdefault("failed_errors", [])
    fetch_summary.setdefault("failed_ids_truncated", False)
    fetch_summary.setdefault("failed_id_cap", 20)
    fetch_summary.setdefault("max_count", settings["autoQueryArticleFetchMaxCount"])
    fetch_summary.setdefault("skipped_by_limit", 0)
    fetch_summary.setdefault("sighting_requested", 0)
    fetch_summary.setdefault("sighting_fetched", 0)
    fetch_summary.setdefault("sighting_failed", 0)
    fetch_summary.setdefault("sighting_failed_ids", [])
    fetch_summary.setdefault("sighting_skipped_by_limit", 0)
    fetch_summary.setdefault("limitation", "Article content was not fetched for this analysis invocation.")
    analyzed_subset = bool(fetch_summary["skipped_by_limit"])
    return {
        "source": "analyzed_query_subset" if analyzed_subset else "all_query_ips",
        "query_ips_total": int(fetch_summary["unique_numeric_ips"]),
        "analyzed_ips": len(issues),
        "total_ips": len(issues),
        "open_ips": sum(safe_text(issue.get("query_status")).lower() == "open" for issue in issues),
        "candidate_assessments": assessments,
        "recommendations": recommendations,
        "candidate_count": len(candidate_issues),
        "assessed_candidate_count": len(assessments),
        "recommended_count": len(recommendations),
        "reference_top_count": settings["referenceTopCount"],
        "analysis_mode": analysis_mode,
        "ai_enrichment": ai_enrichment,
        "content_fetch": fetch_summary,
    }


def query_common_issue_context(analysis: dict[str, Any], ips_id: str) -> str:
    return ""


def machine_lock_prompt(task_id: str) -> str:
    command = f'py scripts\\ips_copilot_ui.py --task-lock --task-id "{task_id}" --machine-id "<registered-machine-id>" --action acquire --wait'
    release = f'py scripts\\ips_copilot_ui.py --task-lock --task-id "{task_id}" --machine-id "<registered-machine-id>" --action release'
    return f"""硬件资源协调（不可跳过）：完成非硬件预检和机器选择后、执行任何 SSH 写操作、flash、power cycle、串口控制或 MLC 前，使用最终选定的 inventory machine id 运行：`{command}`。命令等待数据库中该机器的容量；等待时不得执行硬件副作用。成功后才可进行硬件操作。无论成功、失败、取消或异常，必须在 finally 中运行：`{release}`。extract/consult 不得申请此锁。"""


def build_auto_execute_prompt(
    query_id: str, round_number: int, ips_id: str, task_id: str, report_base_url: str = "", common_issue_context: str = ""
) -> str:
    summary_path = f"out\\{ips_id}\\auto_run_summary_{task_id}.json"
    report_center_url = report_url(report_base_url, f"/reports/task/{task_id}/{query_id}/{round_number}/{ips_id}")
    history_context = "Query 上游仅独立筛选有参考价值的 IPS，不再提供跨 IPS 归并或历史复用上下文；按当前 IPS 独立完成判断。"
    return f"""请使用 ips-auto-flow skill，执行全自动 IPS 诊断任务。只处理 Query `{query_id}` 中当前 Open 的 IPS `{ips_id}`；平台、BKC 或机器不明确时必须 blocked，不得猜测或替代。Flash 失败后不得抓启动日志或运行 MLC。

{history_context}

{machine_lock_prompt(task_id)}

先读取 IPS 确认仍为 Open，完成提取、兼容机器和 BKC 选择。仅在问题需要硬件验证且全部前置检查通过时才进行硬件操作。产物保存在 `out\\{ips_id}\\`，并按 skill 向 owner 自动发送结果邮件。邮件既有正文结构保持不变，只在末尾额外增加一行 `报告中心：{report_center_url}`。无论完成、阻塞、跳过或失败，最后保存 UTF-8 JSON 摘要到 `{summary_path}`（不得包含凭据或绝对路径）：
```json
{{"query_id":"{query_id}","round":{round_number},"ips_id":"{ips_id}","title":"<title>","diagnostic_type":"<type>","status":"completed|blocked|skipped|failed","test_completed":false,"report_path":"out\\{ips_id}\\<report>.md","owner":"<owner>","owner_notification_status":"sent|draft|not_sent|failed","owner_email_body":"<body>","report_center_summary":{{"problem_analysis":"<现象、环境与可能根因>","diagnostic_results":"<详细步骤、结果、证据与结论>","next_steps":["<下一步>"],"customer_information_needed":["<待客户提供的信息>"],"risks_and_limitations":"<风险、限制和未验证假设>"}},"completed_at":"<ISO 8601>"}}
```
"""


def load_auto_summary(query_id: str, round_number: int, ips_id: str, task_id: str, job_status: str, job_output: str) -> dict[str, Any]:
    summary_path = KIT_ROOT / "out" / ips_id / f"auto_run_summary_{task_id}.json"
    fallback = {"query_id": query_id, "round": round_number, "ips_id": ips_id, "title": "", "diagnostic_type": "全自动诊断", "status": "cancelled" if job_status == "cancelled" else "failed" if job_status == "failed" else "completed", "test_completed": False, "report_path": "", "owner": "", "owner_notification_status": "not_sent", "owner_email_body": "", "report_center_summary": normalize_report_center_summary({}), "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        summary = read_json(summary_path)
        if safe_text(summary.get("query_id")) != query_id or int(summary.get("round")) != round_number or safe_text(summary.get("ips_id")) != ips_id:
            raise ValueError("summary identifiers do not match the current task")
        status = safe_text(summary.get("status")).lower()
        if status not in {"completed", "blocked", "skipped", "failed"}:
            raise ValueError("summary status is invalid")
        summary.update({"status": status, "test_completed": bool(summary.get("test_completed")), "title": safe_text(summary.get("title")), "diagnostic_type": safe_text(summary.get("diagnostic_type")) or "全自动诊断", "owner": safe_text(summary.get("owner")), "owner_notification_status": safe_text(summary.get("owner_notification_status")) or "not_sent", "owner_email_body": safe_text(summary.get("owner_email_body")), "report_center_summary": normalize_report_center_summary(summary.get("report_center_summary")), "completed_at": safe_text(summary.get("completed_at")) or fallback["completed_at"]})
        report_path = safe_text(summary.get("report_path"))
        summary["report_path"] = safe_report_path(report_path) if report_path else ""
        return summary
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        fallback["owner_email_body"] = f"自动化任务未生成可用摘要。\nUI 记录原因：{type(exc).__name__}: {exc}\n\nCopilot 输出：\n{job_output[-4000:]}"
        return fallback


def summarize_round(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"completed": 0, "blocked": 0, "skipped": 0, "failed": 0, "cancelled": 0}
    for item in items:
        status = safe_text(item.get("status")).lower()
        if status in counts:
            counts[status] += 1
    return counts


def send_round_notification(round_record: dict[str, Any], manager_recipients: str, report_base_url: str) -> None:
    recipients = safe_text(manager_recipients)
    if not recipients:
        round_record["manager_notification"] = {"status": "not_requested", "reason": "未填写汇总报告通知者。"}
        return
    summary_url = report_url(report_base_url, f"/reports/task/{round_record['task_id']}/{round_record['query_id']}/{round_record['round']}")
    if not summary_url:
        round_record["manager_notification"] = {"status": "not_sent", "reason": "未配置 server.reportBaseUrl，无法发送可访问的汇总报告链接。"}
        return
    counts = summarize_round(round_record["items"])
    common = round_record.get("common_issue_analysis", {})
    common_text = ""
    if isinstance(common, dict):
        common_text = f"\n全量 IPS 参考价值筛选：{common.get('total_ips', 0)} 条；推荐参考：{common.get('recommended_count', 0)} 条。"
    body = f"Query {round_record['query_id']} 第 {round_record['round']} 轮已完成。\n\n处理时间：{format_task_time(round_record['started_at'])} 至 {format_task_time(round_record['completed_at'])}\nOpen IPS：{len(round_record['items'])}\n完成：{counts['completed']}；阻塞：{counts['blocked']}；跳过：{counts['skipped']}；失败：{counts['failed']}{common_text}\n\n汇总报告：{summary_url}"
    command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(KIT_ROOT / "scripts" / "Send-OwnerNotification.ps1"), "-To", recipients, "-Subject", f"[Copilot][HSD] Query {round_record['query_id']} 第 {round_record['round']} 轮汇总已完成", "-Body", body, "-Send"]
    try:
        result = subprocess.run(command, cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        status = "sent" if result.returncode == 0 and "NOTIFICATION_SENT=True" in result.stdout else "failed"
        output = (result.stdout + result.stderr)[-4000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        status, output = "failed", f"{type(exc).__name__}: {exc}"
    round_record["manager_notification"] = {"status": status, "recipients": recipients, "summary_url": summary_url, "output": output}


class TaskManager:
    def __init__(self, cfg: dict[str, Any]) -> None:
        automation = cfg.get("automation", {})
        database_path = pathlib.Path(automation.get("taskDatabasePath", "out\\ui_task_manager.sqlite3"))
        if not database_path.is_absolute():
            database_path = KIT_ROOT / database_path
        self.cfg = cfg
        self.store = TaskStore(database_path, automation.get("perMachineConcurrency", {"default": 1}))
        self.store.cleanup(int(automation.get("retentionDays", 90)))
        self._events: dict[str, threading.Event] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def start(self, query_id: str, creator_name: str, interval_minutes: int, manager_recipients: str, report_only: bool = False) -> dict[str, Any]:
        query_id = require_numeric_id(query_id, "query_id")
        creator_name = safe_text(creator_name)
        if not creator_name:
            raise ValueError("creator_name is required")
        minimum = int(self.cfg.get("automation", {}).get("minimumIntervalMinutes", 60))
        if not report_only and interval_minutes < minimum:
            raise ValueError(f"interval_minutes must be at least {minimum}")
        copilot_cfg = self.cfg.get("copilot", {})
        if copilot_cfg.get("mode") != "subprocess" or copilot_cfg.get("stage2Mode") != "subprocess":
            raise ValueError("全自动模式要求 copilot.mode 和 copilot.stage2Mode 均为 subprocess。")
        with self._lock:
            existing = self.store.find_active_query(query_id)
            if existing:
                raise DuplicateQueryTaskError(existing)
            task = self.store.create_task(query_id, creator_name, interval_minutes, safe_text(manager_recipients), safe_text(self.cfg.get("server", {}).get("reportBaseUrl"),), report_only)
            event = threading.Event()
            self._events[task["id"]] = event
        threading.Thread(target=self._worker, args=(task["id"], event), daemon=True).start()
        return task

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_tasks()

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.store.get_task(task_id)

    def resources(self) -> list[dict[str, Any]]:
        return self.store.list_machine_locks()

    def cancel(self, task_id: str, reason: str = "Cancelled by user") -> dict[str, Any]:
        task = self.store.request_cancel(task_id, safe_text(reason) or "Cancelled by user")
        with self._lock:
            event = self._events.get(task_id)
            proc = self._processes.get(task_id)
        if event:
            event.set()
        if proc and proc.poll() is None:
            self._terminate_process(proc)
        return self.store.get_task(task_id) or task

    def _terminate_process(self, proc: subprocess.Popen[str]) -> None:
        grace = max(1, int(self.cfg.get("automation", {}).get("cancellationGraceSeconds", 15)))
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=grace)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            proc.kill()
        except OSError:
            pass

    def _worker(self, task_id: str, cancel_event: threading.Event) -> None:
        task = self.store.get_task(task_id)
        if task is None or task["status"] == "cancelled":
            return
        self.store.update(task_id, status="running", started_at=time.time())
        report_only = bool(task.get("report_only"))
        self.store.append_output(
            task_id,
            f"共性报告任务已启动：Query {task['query_id']}，仅执行一次只读分析，不处理 Open IPS。"
            if report_only
            else f"全自动任务已启动：Query {task['query_id']}，每 {task['interval_seconds'] // 60} 分钟轮询一次。",
        )
        try:
            while not cancel_event.is_set():
                task = self.store.get_task(task_id)
                if task is None:
                    return
                try:
                    rows = execute_hsd_query(task["query_id"], all_pages=report_only)
                    round_number = int(task["current_round"]) + 1
                    round_started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    self.store.update(task_id, current_round=round_number)
                    self.store.append_output(task_id, f"第 {round_number} 轮：先对 Query 返回的全部 IPS 执行只读文章内容抓取和参考价值筛选；每条 IPS 独立评估。")
                    enriched_rows, content_fetch = enrich_auto_query_article_rows(rows, self.cfg)
                    common_issue_analysis = build_auto_query_common_issue_analysis(enriched_rows, self.cfg, content_fetch)
                    open_ids = [] if report_only else sorted({safe_text(row.get("id")) for row in rows if safe_text(row.get("id")) and safe_text(row.get("status")).lower() == "open"})
                    round_record = {"task_id": task_id, "query_id": task["query_id"], "round": round_number, "started_at": round_started_at, "completed_at": "", "status": "running", "items": [], "common_issue_analysis": common_issue_analysis, "manager_notification": {"status": "pending"}}
                    write_auto_round(round_record)
                    limitation = safe_text(content_fetch.get("limitation"))
                    self.store.append_output(task_id, f"第 {round_number} 轮查询完成：IPS 正文抓取请求 {content_fetch['requested']}，成功 {content_fetch['fetched']}，失败 {content_fetch['failed']}；int_sighting_url 正文请求 {content_fetch.get('sighting_requested', 0)}，成功 {content_fetch.get('sighting_fetched', 0)}，失败 {content_fetch.get('sighting_failed', 0)}；Top IPS {common_issue_analysis['recommended_count']} 条，发现 {len(open_ids)} 个 Open IPS。{(' 限制：' + limitation) if limitation else ''}")
                    processed = task.get("processed", {})
                    for ips_id in open_ids:
                        if cancel_event.is_set():
                            break
                        if ips_id in processed:
                            continue
                        self.store.update(task_id, current_ips_id=ips_id, status="running")
                        self.store.append_output(task_id, f"开始处理 IPS {ips_id}。")
                        try:
                            common_context = query_common_issue_context(common_issue_analysis, ips_id)
                            code, output = run_copilot(build_auto_execute_prompt(task["query_id"], round_number, ips_id, task_id, task["report_base_url"], common_context), self.cfg, output_callback=lambda chunk: self.store.append_output(task_id, chunk), cancel_event=cancel_event, process_callback=lambda proc: self._set_process(task_id, proc))
                            job_status = "cancelled" if cancel_event.is_set() else "completed" if code == 0 else "failed"
                            item = load_auto_summary(task["query_id"], round_number, ips_id, task_id, job_status, output)
                        except Exception as exc:
                            item = {"query_id": task["query_id"], "round": round_number, "ips_id": ips_id, "title": "", "diagnostic_type": "全自动诊断", "status": "failed", "test_completed": False, "report_path": "", "owner": "", "owner_notification_status": "not_sent", "owner_email_body": f"UI 自动处理异常：{type(exc).__name__}: {exc}", "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                        finally:
                            self._clear_process(task_id)
                            self.store.release_machine(task_id)
                        round_record["items"].append(item)
                        write_auto_round(round_record)
                        processed[ips_id] = item.get("status", "failed")
                        self.store.update(task_id, processed_json=json.dumps(processed, ensure_ascii=False), current_ips_id="")
                        self.store.append_output(task_id, f"IPS {ips_id} 处理结束：{item['status']}。")
                    round_record["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    round_record["status"] = "cancelled" if cancel_event.is_set() else "completed"
                    if not cancel_event.is_set():
                        send_round_notification(round_record, task["manager_recipients"], task["report_base_url"])
                    else:
                        round_record["manager_notification"] = {"status": "not_sent", "reason": "任务已取消。"}
                    write_auto_round(round_record)
                    self.store.update(task_id, report_path=str(auto_round_path(task["query_id"], round_number, task_id).relative_to(KIT_ROOT)))
                except Exception as exc:
                    self.store.append_output(task_id, f"本轮查询或处理失败：{type(exc).__name__}: {exc}")
                if report_only:
                    break
                if not cancel_event.wait(task["interval_seconds"]):
                    continue
        finally:
            self.store.release_machine(task_id)
            current = self.store.get_task(task_id)
            if current and current["status"] not in TERMINAL_TASK_STATUSES:
                if cancel_event.is_set() or current["status"] == "cancelling":
                    self.store.update(task_id, status="cancelled", completed_at=time.time(), current_ips_id="")
                else:
                    self.store.update(task_id, status="completed", completed_at=time.time(), current_ips_id="")
            self.store.append_output(task_id, "全自动任务已停止。")
            with self._lock:
                self._events.pop(task_id, None)
                self._processes.pop(task_id, None)

    def _set_process(self, task_id: str, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes[task_id] = proc
        self.store.update(task_id, process_id=proc.pid)

    def _clear_process(self, task_id: str) -> None:
        with self._lock:
            self._processes.pop(task_id, None)
        self.store.update(task_id, process_id=None)


TASK_MANAGER: TaskManager | None = None

def task_type_label(form: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    explicit = safe_text(form.get("task_type_label"))
    if explicit:
        return explicit
    task_type = safe_text(form.get("task_type"))
    if cfg:
        for item in cfg.get("taskTypes", []):
            if item.get("id") == task_type:
                return f"{item.get('label', task_type)} - {item.get('description', '')}".strip()
    labels = {
        "extract_ips": "提取 IPS - 只提取 HSD/IPS 信息并生成分析，不执行硬件动作。",
        "consult": "问题咨询 - 基于 HSD/IPS 和备注生成咨询分析，不执行硬件动作。",
        "debug_repro": "Debug / 验证 - 用户确认后执行 BKC 匹配、烧录、抓日志、MLC 和报告。",
    }
    return labels.get(task_type, task_type)


def permission_label(form: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    explicit = safe_text(form.get("permission_label"))
    if explicit:
        return explicit
    level = safe_text(form.get("permission_level"))
    if cfg:
        for item in cfg.get("permissionLevels", []):
            if item.get("id") == level:
                return f"{item.get('label', level)} - {item.get('description', '')}".strip()
    labels = {
        "standard": "标准授权 - 执行前对高风险动作保持谨慎确认。",
        "trusted_plan": "信任已确认计划 - 对用户确认计划内的低风险命令尽量不反复询问。",
        "maximum": "最高授权 - 对用户确认计划内的命令尽量自主执行；不能绕过 Copilot CLI/OS 安全限制。",
    }
    return labels.get(level, level or "standard")


def initial_plan_text(form: dict[str, Any]) -> str:
    article_id = safe_text(form.get("ips_id"))
    automatic_machine_match = bool(form.get("auto_machine_match"))
    ssh_host = (
        "自动匹配（阶段2根据 IPS/HSD 平台环境选择）"
        if automatic_machine_match
        else safe_text(form.get("ssh_host"))
    )
    task_type = safe_text(form.get("task_type"))
    notes = safe_text(form.get("notes"))
    test_target = safe_text(form.get("test_target"))
    report_dir = f"out\\{article_id}" if article_id else "out\\<IPS_HSD_ID>"
    task_label = task_type_label(form)
    permission = permission_label(form)
    similar_ips = bool(form.get("search_similar_ips"))
    download_attachments = bool(form.get("download_attachments"))
    notify_recipient = safe_text(form.get("notification_recipient"))
    similar_step = "并检索相似 IPS/HSD 获取历史经验" if similar_ips else "不检索相似 IPS/HSD"
    attachment_step = "并下载/分析客户附件包（如有）" if download_attachments else "不下载客户附件"
    notify_step = (
        f"阶段2完成后自动发送给指定收件人 `{notify_recipient}`；邮件正文提供客户机器环境、客户问题、诊断结果、重点关注、下一步研究方向和完整报告路径"
        if notify_recipient
        else "不发送完成通知；用户未填写发送用户"
    )
    machine_selection_step = (
        "根据提取出的平台/机型、socket 拓扑和测试类型，读取 `config\\lab-machine-inventory.json` 自动选择兼容控制机；平台不明或冲突时停止并报告，不得猜测或跨平台替代。"
        if automatic_machine_match
        else f"使用用户手动选择的 SSH 控制机 `{ssh_host or '<未填写>'}`，并在硬件操作前验证该机与 IPS/HSD 平台匹配。"
    )

    if task_type == "debug_repro":
        planned_steps = """1. 阶段2开始后，读取 IPS/HSD {article_id} 的详细内容。
2. 提取问题、owner、BKC/软件版本、平台配置、客户复现步骤和历史评论。
3. {machine_selection_step}
4. {similar_step}。
5. {attachment_step}。
6. 根据 BKC 和平台匹配远端 .bin 镜像，并显示候选 bin、大小、SHA256。
7. 用户确认的情况下执行烧录；烧录失败则停止并诊断。
8. 烧录成功后抓取匹配的 CPU/BMC 串口启动日志。
9. 启动成功后运行 MLC 或用户指定测试：{test_target}。
10. 将 Markdown 报告、原始日志、测试结果和附件统一保存到 `{report_dir}`。
11. {notify_step}。""".format(
            article_id=article_id or "<IPS/HSD ID>",
            test_target=test_target or "根据 IPS/HSD 问题自动选择",
            machine_selection_step=machine_selection_step,
            similar_step=similar_step,
            attachment_step=attachment_step,
            notify_step=notify_step,
            report_dir=report_dir,
        )
    elif task_type == "consult":
        planned_steps = """1. 阶段2开始后，读取 IPS/HSD {article_id} 的详细内容。
2. 提取问题背景、owner、平台、BKC/软件版本、客户疑问和历史评论。
3. {similar_step}。
4. {attachment_step}。
5. 结合用户备注进行问题咨询分析。
6. 将 Markdown 咨询报告、HSD 提取结果和附件统一保存到 `{report_dir}`，并输出建议、可能原因、需要补充的信息和下一步建议。
7. {notify_step}。
8. 不执行烧录、power cycle、串口、MLC 或任何硬件动作。""".format(
            article_id=article_id or "<IPS/HSD ID>",
            similar_step=similar_step,
            attachment_step=attachment_step,
            notify_step=notify_step,
            report_dir=report_dir,
        )
    else:
        planned_steps = """1. 阶段2开始后，读取 IPS/HSD {article_id} 的详细内容。
2. 提取 title、owner、status、family/release/component、BKC/软件版本、问题描述、复现步骤、fix/root cause/workaround。
3. {similar_step}。
4. {attachment_step}。
5. 将 Markdown 分析报告、HSD 提取结果和附件统一保存到 `{report_dir}`，并输出结构化摘要。
6. {notify_step}。
7. 不执行烧录、power cycle、串口、MLC 或任何硬件动作。""".format(
            article_id=article_id or "<IPS/HSD ID>",
            similar_step=similar_step,
            attachment_step=attachment_step,
            notify_step=notify_step,
            report_dir=report_dir,
        )

    return f"""# 待确认任务计划

> 阶段一说明：本计划仅根据 UI 表单字段生成，尚未访问 HSD/IPS，尚未连接 SSH，也没有执行任何硬件动作。

## 用户输入

- IPS/HSD ID：{article_id}
- SSH 控制机：{ssh_host}
- 自动机器匹配：{"是" if automatic_machine_match else "否"}
- 功能类型 ID：{task_type}
- 功能类型说明：{task_label}
- 授权级别：{permission}
- 检索相似 IPS：{"是" if similar_ips else "否"}
- 下载并分析客户附件：{"是" if download_attachments else "否"}
- 发送用户：{notify_recipient or "<未填写；不发送通知>"}
- 测试目标：{test_target or "根据 HSD 问题自动选择"}
- 报告及任务产物目录：{report_dir}
- 补充信息：{notes or "无"}

## AI 对用户需求的理解

- 用户希望处理 IPS/HSD：{article_id or "<未填写>"}。
- 用户选择的功能是：{task_label or "<未选择>"}。
- 用户选择的授权级别是：{permission}。
- 用户选择{"需要" if similar_ips else "不需要"}检索相似 IPS/HSD 获取历史经验。
- 用户选择{"需要" if download_attachments else "不需要"}下载并分析客户附件。
- 阶段2{"会发送通知给指定用户" if notify_recipient else "不会发送通知，因为未填写发送用户"}。
- 用户指定或建议的 SSH 控制机是：{ssh_host or "<未填写>"}。
- 用户补充要求是：{notes or "无"}。

## 建议执行计划

{planned_steps}

## 安全检查

- 阶段1只生成计划，不能读取 HSD/IPS，不能 SSH，不能烧录，不能 power cycle，不能串口控制，不能运行 MLC。
- 阶段2执行硬件动作前必须由用户在 UI 中勾选确认。
- 授权级别只表达用户意图，不能绕过 Copilot CLI、操作系统、SSH、硬件设备或安全策略本身的权限限制。
- 烧录前确认 hostname/IP 与目标平台匹配。
- 烧录前显示并确认 bin 路径、大小和 SHA256。
- Flash 失败必须停止，不进入抓日志阶段。
- 保存完整原始日志后再分析。
"""


def build_plan_prompt(form: dict[str, Any], cfg: dict[str, Any]) -> str:
    text_template = initial_plan_text(form)
    task_label = task_type_label(form, cfg)
    permission = permission_label(form, cfg)
    similar_ips = "是" if form.get("search_similar_ips") else "否"
    download_attachments = "是" if form.get("download_attachments") else "否"
    notify_recipient = safe_text(form.get("notification_recipient"))
    automatic_machine_match = bool(form.get("auto_machine_match"))
    ssh_host = (
        "自动匹配（阶段2根据 IPS/HSD 平台环境选择）"
        if automatic_machine_match
        else safe_text(form.get("ssh_host"))
    )
    plan_only_text = cfg.get("defaults", {}).get(
        "planOnlyNoHardwareText",
        "阶段1只能根据UI字段生成计划，严禁访问HSD/SSH或执行硬件动作。",
    )
    return f"""请使用 ips-ui-plan-stage skill。

你现在处于【阶段1：只根据 UI 表单字段理解需求并生成执行计划】。

重要安全限制：
{plan_only_text}

请严格遵守：
1. 不要调用任何工具。
2. 不要访问 HSD database。
3. 不要 SSH 连接任何机器。
4. 不要读取 BKC 文件夹。
5. 不要烧录、power cycle、打开串口、运行 MLC。
6. 你只需要根据 UI 表单字段，思考用户想做什么，然后输出下一步执行计划。

UI 表单字段如下，请完整体现在计划中：

| 字段 | 值 |
| --- | --- |
| IPS/HSD ID | {safe_text(form.get("ips_id"))} |
| 自动机器匹配 | {"是" if automatic_machine_match else "否"} |
| SSH 控制机 | {ssh_host} |
| 功能类型 ID | {safe_text(form.get("task_type"))} |
| 功能类型说明 | {task_label} |
| 授权级别 | {permission} |
| 检索相似 IPS | {similar_ips} |
| 下载并分析客户附件 | {download_attachments} |
| 发送用户 | {notify_recipient or "<未填写；不发送通知>"} |
| 测试目标 | {safe_text(form.get("test_target"))} |

补充信息：
{safe_text(form.get("notes"))}

请完成：
1. 根据功能类型判断后续是否需要硬件动作。
2. 如果功能类型是“问题咨询/consult”，计划中必须明确：只在阶段2读取 IPS/HSD 并做分析建议，不需要烧录和实际测试。
3. 如果功能类型是“提取 IPS/extract_ips”，计划中必须明确：只在阶段2读取 IPS/HSD 并提取摘要，不需要烧录和实际测试。
4. 如果功能类型是“Debug / 验证/debug_repro”，计划中才可以包含 BKC 匹配、烧录、启动日志、MLC/指定测试。
5. 如果用户填写了 IPS/HSD ID、机器匹配模式、SSH 控制机、测试目标或备注，必须在计划中原样体现。
6. 如果用户选择自动机器匹配，计划中必须说明：阶段2读取 IPS/HSD 后，依据 `config\\lab-machine-inventory.json` 的平台别名、能力与阻断规则选择机器；平台未知或冲突时停止并报告，不得猜测或跨平台替代。
7. 如果用户选择了高授权或最高授权，计划中要说明：该授权只适用于阶段2中“用户已确认计划内”的命令，且不能绕过 Copilot CLI/OS/SSH/硬件安全限制。
8. 如果用户选择“检索相似 IPS”，计划中要包含：阶段2读取目标 IPS 后，基于 title/component/family/suspected_problem_area/关键词检索相似 IPS，提取可复用经验、root cause、workaround、fix 或评论线索。
9. 如果用户选择“下载并分析客户附件”，计划中要包含：阶段2解析 HSD 附件字段（ext_attach_url/download_attached_ips_files），尝试通过 Kerberos/curl 下载附件包，统一保存到 `out\\<IPS_HSD_ID>\\attachments\\`，解压并优先分析 Overview/README/summary/config/log 文件；如果无法下载或无权限，需要在报告中说明。
10. 如果“发送用户”已填写，计划中要包含：阶段2完成报告后调用通知脚本，以该邮箱或 Outlook 名称为收件人自动发送邮件（不使用 HSD owner 作为收件人）。邮件标题需要包含 `[Copilot][HSD]`、HSD ID、任务类型和简短状态。邮件正文必须是便于工作人员快速判断和跟进的独立摘要，而不是 Markdown 报告目录或路径列表：按“客户机器环境”“客户问题”“诊断结果”“重点关注”“下一步研究方向”“完整报告”六个标题组织。客户机器环境应提取平台/机型、拓扑、BKC/BIOS、OS、测试工具和关键配置；未获取的信息明确标注“未获取”。诊断结果必须说明复现/验证状态、最终结论和关键证据。重点关注必须列出风险、限制或尚未验证的假设。下一步研究方向必须给出可执行的后续验证或信息收集项。完整 Markdown 报告仍作为附件，并在正文末尾列出报告路径。如果未填写发送用户，计划中必须明确不发送通知。
11. 输出给使用者看的自然语言计划，可以使用 Markdown 表格/列表。

请不要输出 JSON。请输出清晰、可读、便于使用者检查和修改的中文文本。

输出结构参考：
{text_template}
"""


def choose_stage2_skill(plan_text: str, task_type: str = "") -> str:
    task_type = safe_text(task_type).lower()
    if task_type in ("consult", "extract_ips"):
        return "ips-consult-flow"
    if task_type == "debug_repro":
        return "ips-hsd-repro-flow"
    lowered = plan_text.lower()
    if "consult" in lowered or "问题咨询" in plan_text or "咨询" in plan_text:
        return "ips-consult-flow"
    if "extract_ips" in lowered or "提取 ips" in lowered or "提取ips" in lowered:
        return "ips-consult-flow"
    if "不执行硬件" in plan_text or "不需要烧录" in plan_text or "不运行 mlc" in lowered:
        return "ips-consult-flow"
    return "ips-hsd-repro-flow"


def build_execute_prompt(
    plan_text: str,
    cfg: dict[str, Any],
    permission: str = "",
    task_type: str = "",
    auto_machine_match: bool = False,
    ssh_host: str = "",
    report_base_url: str = "",
    notification_recipient: str = "",
) -> str:
    permission_text = permission or "未单独指定；以最终执行计划中的授权级别为准。"
    stage2_skill = choose_stage2_skill(plan_text, task_type)
    machine_instruction = (
        """用户启用了自动机器匹配。读取 IPS/HSD 提取出的平台/机型、socket 拓扑和测试类型后，必须读取 `docs\\lab_machine_inventory.md` 与 `config\\lab-machine-inventory.json`，选择平台兼容且具备所需能力的控制机。GNR/BHS 与 DMR/Oak Stream 不得互相替代；平台未知或冲突时停止并报告需要补充的信息。报告中记录最终选择的机器、理由和能力检查结果。"""
        if auto_machine_match
        else f"""用户手动选择的 SSH 控制机是：`{ssh_host or '<未填写>'}`。只能使用该机器，并在硬件操作前验证它与 IPS/HSD 的平台、BKC 和测试需求匹配；不匹配时停止并报告，不能自动切换机器。"""
    )
    report_center_url = report_url(report_base_url, "/reports/manual/{manual_report_id}")
    summary_path = "out\\manual_reports\\{manual_report_id}.summary.json"
    resource_request_instruction = ""
    if task_type == "debug_repro":
        resource_request_instruction = f"""
4a. 在提取 IPS/HSD、客户环境与测试诉求，并依据机器库存完成兼容性比对后、执行任何硬件动作前，生成 `out\\<IPS_HSD_ID>\\resource_request_draft.md`。此文件直接面向管理者，控制在一页内，使用以下固定结构：`# 资源协调申请`、`## 申请摘要`（最多 3 个短句，仅说明客户/IPS、验证目的和需要管理者协调的事项）、`## 所需资源`（用简短表格列出资源、必要规格、数量和当前缺口）、`## 时间安排`、`## 排期说明`。只有会影响资源决策的信息才可增加 `## 必要说明`，且最多 3 条；不要写寄存器、信号、日志、命令、调试过程或根因推测。必须依据已验证的 IPS 内容和机器匹配结果填写，不得臆测；未确认项写“待确认”。即使现有机器满足需求，也要明确写“当前已登记机器满足已知需求，暂不需要新增物品”。措辞应客观、礼貌、简洁，使用“申请协助协调”“烦请确认是否可安排”，避免命令式、夸大紧迫性或大段技术说明。草稿必须保留以下三行的精确占位符，供 UI 人工补充和重复更新：`期望 DDL：<MANUAL_DDL>`、`预计占用：<MANUAL_RESOURCE>`、`预计时长：<MANUAL_DURATION>`。排期说明仅写：如资源时间需要调整，我们会同步更新验证及客户反馈排期。草稿完成后不得自行发送通知；必须先写入第 13 步的报告中心摘要。UI 会在摘要与草稿路径持久化并可访问后，向任务提交人发送草稿链接。
"""
    return f"""请使用 {stage2_skill} skill，进入【阶段2：执行用户确认后的计划】。

用户已经在 UI 中完成二次确认，并确认下面文本是最终执行计划。

用户选择的执行授权级别：
{permission_text}

执行要求：
1. 按最终执行计划中的用户意图执行；如果某一步被用户删除或明确禁用，不要执行。
2. 如果这是 consult / 问题咨询任务：只读取 IPS/HSD 并生成咨询分析报告，不要 SSH、不要 BKC 匹配用于烧录、不要烧录、不要 power cycle、不要串口、不要 MLC。
3. 如果这是 debug_repro / Debug 验证任务：如果涉及烧录，必须先确认 hostname/IP、bin 路径、bin size、SHA256、EM100/PowerSplitter/COM 口状态。
4. {machine_instruction}
{resource_request_instruction}
5. {machine_lock_prompt("{resource_task_id}") if task_type == "debug_repro" else "这是 extract/consult 任务：不得申请硬件资源锁，也不得执行硬件操作。"}
6. Flash 失败必须停止并诊断，不允许继续抓启动日志。
7. 保存完整原始日志，再分析。
8. 从最终计划确定 IPS/HSD ID，并将 Markdown 报告、HSD 提取文件、附件、原始日志和测试结果统一保存到 `out\\<IPS_HSD_ID>\\`；不要直接将本次任务的产物保存到 `out\\` 根目录。报告包含 HSD 摘要、复现/咨询步骤、结果、解决程度和初步原因推测。
9. 如果最终计划要求检索相似 IPS/HSD：先读取目标 IPS，再基于 title/component/family/suspected_problem_area/关键词检索相似问题，提取可复用经验并写入报告；如果检索结果噪声大，需要说明筛选依据和不确定性。
10. 如果最终计划要求下载并分析客户附件：解析 HSD 附件字段，尝试下载附件包，保存到 `out\\<IPS_HSD_ID>\\attachments\\`，解压并优先分析 Overview/README/summary/config/log；如果失败，报告中说明失败原因和可手动下载的链接/字段。
11. 如果最终计划填写了“发送用户”：报告生成后调用 `scripts\\Send-OwnerNotification.ps1`，以该指定邮箱或 Outlook 名称为收件人并添加 `-Send` 自动发送通知；不得改用 HSD/IPS owner。邮件 Subject 需要包含 `[Copilot][HSD]`、HSD ID、任务类型和简短状态。邮件 Body 必须直接提供工作人员可阅读的诊断摘要，不能只写“结论摘要”和报告路径；使用以下固定结构：
   ```text
   HSD/IPS ID: <id>
   标题: <title>
   Owner: <owner>
   任务类型: <consult/extract/debug>

   客户机器环境
   - 平台/机型、socket/NUMA 或 DIMM 拓扑、BKC/BIOS、OS、测试工具/版本、关键配置；没有可靠证据的字段写“未获取”，不可猜测。

   客户问题
   - 客户现象、影响和明确诉求。

   诊断结果
   - 复现/验证状态、最终结论、支撑结论的关键证据，以及是否执行硬件动作。

   重点关注
   - 风险、限制、未验证假设、结果与客户环境的差异或需要人工决策的事项。

   下一步研究方向
   - 可执行的后续验证、配置对比、日志/信息收集或责任人跟进项；若无需后续动作，明确说明原因。

   完整报告
   - Markdown 报告已作为附件：<report path>
   ```
   内容要简明、面向行动，完整技术细节保留在 Markdown 附件中。若运行了 MLC，调用脚本时必须添加 `-IncludeMlcResults`，将完整 `host_mlc_results.log` 与报告一并附件；未运行 MLC 时不得添加此开关。正文末尾只额外增加一行 `报告中心：{report_center_url}`。未填写“发送用户”时，不调用通知脚本。
12. 如果授权级别为高授权或最高授权：对最终计划内、必要且低歧义的命令行步骤尽量连续执行，不要对每个普通命令反复询问；但仍必须遵守 Copilot CLI/OS/SSH/硬件安全限制，遇到破坏性、超出计划、目标不明确或高风险动作时应停止确认。
13. 完成诊断后，为报告中心保存 UTF-8 JSON 深度诊断摘要到 `{summary_path}`，不得包含凭据或绝对路径：
   ```json
   {{"problem_analysis":"问题现象、环境与可能根因；不确定项明确标注。","diagnostic_results":"已执行的步骤、结果、关键证据和最终结论。","next_steps":["可执行的后续研究或验证步骤"],"customer_information_needed":["客户仍需提供的日志、配置、版本、拓扑或复现信息"],"risks_and_limitations":"风险、限制、未验证假设及与客户环境的差异。","resource_request_path":"out\\<IPS_HSD_ID>\\resource_request_draft.md 或空字符串","resource_request_status":"needed|not_needed|blocked|not_applicable"}}
   ```
   没有待补充信息或后续动作时使用空数组并明确说明原因；不要仅保存报告路径或日志目录。

最终执行计划：
{plan_text}
"""


def run_copilot(
    prompt: str,
    cfg: dict[str, Any],
    job_id: str | None = None,
    output_callback: Any = None,
    cancel_event: threading.Event | None = None,
    process_callback: Any = None,
) -> tuple[int, str]:
    copilot_cfg = cfg.get("copilot", {})
    mode = copilot_cfg.get("mode", "manual")
    if mode != "subprocess":
        return 0, (
            "MANUAL MODE: 当前配置不会直接调用 Copilot CLI。\n"
            "请复制下面的 prompt 到 Copilot CLI 中执行，或将 config\\ips-copilot-ui.template.json "
            "中的 copilot.mode 改为 subprocess。\n\n"
            + prompt
        )

    command = list(copilot_cfg.get("command") or [])
    if not command:
        return 2, "copilot.command is empty."

    timeout = int(copilot_cfg.get("timeoutSeconds", 7200))
    pass_prompt = copilot_cfg.get("passPrompt", "stdin")
    cwd = copilot_cfg.get("workingDirectory", ".")
    cwd_path = (KIT_ROOT / cwd).resolve() if not os.path.isabs(cwd) else pathlib.Path(cwd)
    encoding = copilot_cfg.get("promptFileEncoding", "utf-8")
    prepend_commands = [safe_text(item) for item in copilot_cfg.get("prependCommands", []) if safe_text(item)]
    prompt_to_send = ("\n".join(prepend_commands) + "\n\n" + prompt) if prepend_commands else prompt

    prompt_file = None
    try:
        if "{prompt_file}" in " ".join(command) or pass_prompt == "promptFile":
            tmp = tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                suffix=".txt",
                prefix=f"copilot_prompt_{job_id}_",
                encoding=encoding,
            )
            tmp.write(prompt_to_send)
            tmp.close()
            prompt_file = tmp.name
            command = [part.replace("{prompt_file}", prompt_file) for part in command]
            if "{prompt_file}" not in " ".join(command):
                command.append(prompt_file)
            stdin_data = None
        elif pass_prompt == "argument":
            command.append(prompt_to_send)
            stdin_data = None
        else:
            stdin_data = prompt_to_send

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            command,
            cwd=str(cwd_path),
            stdin=subprocess.PIPE if stdin_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        if process_callback:
            process_callback(proc)
        output_queue: queue.Queue[str] = queue.Queue()

        def reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                output_queue.put(line)

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        if stdin_data is not None and proc.stdin is not None:
            proc.stdin.write(stdin_data)
            proc.stdin.close()

        output_parts: list[str] = []
        deadline = time.time() + timeout
        while True:
            try:
                while True:
                    chunk = output_queue.get_nowait()
                    output_parts.append(chunk)
                    if job_id:
                        append_job_output(job_id, chunk)
                    if output_callback:
                        output_callback(chunk)
            except queue.Empty:
                pass

            code = proc.poll()
            if code is not None:
                reader_thread.join(timeout=2)
                try:
                    while True:
                        chunk = output_queue.get_nowait()
                        output_parts.append(chunk)
                        if job_id:
                            append_job_output(job_id, chunk)
                        if output_callback:
                            output_callback(chunk)
                except queue.Empty:
                    pass
                return code, "".join(output_parts)

            if time.time() > deadline:
                proc.kill()
                return 124, "".join(output_parts) + "\nTIMEOUT: Copilot command exceeded timeout.\n"

            if cancel_event is not None and cancel_event.is_set():
                grace = max(1, int(cfg.get("automation", {}).get("cancellationGraceSeconds", 15)))
                try:
                    if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        proc.terminate()
                    proc.wait(timeout=grace)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        proc.kill()
                    except OSError:
                        pass
                return 130, "".join(output_parts) + "\nCANCELLED: Copilot command was terminated.\n"

            time.sleep(0.2)
    finally:
        if prompt_file and os.path.exists(prompt_file):
            try:
                os.remove(prompt_file)
            except OSError:
                pass


def append_job_output(job_id: str, text: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not None:
            job["output"] = job.get("output", "") + text
            job["updated_at"] = time.time()


def create_handoff(prompt: str, cfg: dict[str, Any], job_id: str) -> str:
    copilot_cfg = cfg.get("copilot", {})
    handoff_dir_text = copilot_cfg.get("handoffDirectory", "inbox\\ui_tasks")
    handoff_dir = (KIT_ROOT / handoff_dir_text).resolve() if not os.path.isabs(handoff_dir_text) else pathlib.Path(handoff_dir_text)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    task_path = handoff_dir / f"ui_stage2_task_{stamp}_{job_id[:8]}.md"
    task_path.write_text(prompt, encoding="utf-8")
    prepend_commands = [safe_text(item) for item in copilot_cfg.get("prependCommands", []) if safe_text(item)]
    prep_text = "\n".join(prepend_commands) if prepend_commands else "/allow-all"
    return f"""STAGE2_HANDOFF_CREATED

阶段二任务已保存，但没有在 UI 子进程中直接执行。

原因：
UI 通过 subprocess 启动的 Copilot CLI 可能没有当前会话的 shell/tool 权限，无法可靠执行 SSH、PowerShell、烧录、串口、MLC 等动作。

请在当前有工具权限的 Copilot CLI 会话中发送下面这句话：

{prep_text}

请读取并执行 UI 确认后的阶段二任务：{task_path}

任务文件：
{task_path}

如果你只想查看 prompt，也可以直接打开该文件。
"""


def update_manual_report(job: dict[str, Any]) -> None:
    report = job.get("manual_report")
    if not isinstance(report, dict):
        return
    report.update(
        {
            "status": safe_text(job.get("status")),
            "exit_code": job.get("exit_code"),
            "output": safe_text(job.get("output")),
            "completed_at": time.time() if job.get("status") in ("completed", "failed") else 0,
        }
    )
    summary = load_report_center_summary(safe_text(report.get("summary_path")))
    if any(summary.values()):
        report["report_center_summary"] = summary
    if report["status"] in ("completed", "failed"):
        report["report_artifact_error"] = manual_report_artifact_error(report)
    if report["status"] == "completed" and not report["report_artifact_error"]:
        send_resource_draft_notification(report)
    write_manual_report(report)


def send_resource_draft_notification(report: dict[str, Any]) -> None:
    """Notify only after the UI can resolve the persisted draft link."""
    if safe_text(report.get("task_type")) != "debug_repro":
        return
    if safe_text(report.get("resource_request_notification_status")) == "sent":
        return
    recipient = safe_text(report.get("recipient"))
    if not recipient:
        report["resource_request_notification_status"] = "not_requested"
        return
    report_base_url = safe_text(report.get("report_base_url"))
    if not report_base_url:
        report["resource_request_notification_status"] = "not_sent"
        report["resource_request_notification_error"] = "报告中心地址未记录，无法发送可访问的草稿链接。"
        return
    try:
        draft_path = resource_request_draft_path(report)
    except ValueError as exc:
        report["resource_request_notification_status"] = "not_sent"
        report["resource_request_notification_error"] = f"草稿路径无效：{exc}"
        return
    if not draft_path.is_file():
        report["resource_request_notification_status"] = "not_sent"
        report["resource_request_notification_error"] = "草稿文件不存在。"
        return
    job_id = safe_text(report.get("id"))
    link = report_url(report_base_url, f"/reports/manual/{job_id}/resource-request")
    result = subprocess.run(
        [
            "powershell", "-ExecutionPolicy", "Bypass", "-File",
            str(KIT_ROOT / "scripts" / "Send-OwnerNotification.ps1"),
            "-To", recipient,
            "-Subject", f"[Copilot][HSD {safe_text(report.get('ips_id'))}] 资源/物品清单草稿已生成",
            "-Body", (
                f"IPS/HSD {safe_text(report.get('ips_id'))} 的资源/物品清单草稿已生成，"
                f"请在报告中心补充并确认发送。\n\n草稿链接：{link}"
            ),
            "-Send",
        ],
        cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120, check=False,
    )
    if result.returncode != 0:
        report["resource_request_notification_status"] = "not_sent"
        report["resource_request_notification_error"] = (
            f"草稿通知发送失败（exit {result.returncode}）："
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
        return
    report["resource_request_notification_status"] = "sent"
    report["resource_request_notification_sent_at"] = time.time()
    report.pop("resource_request_notification_error", None)


def manual_report_artifact_error(report: dict[str, Any]) -> str:
    """Require the stage-2 summary before a completed task can claim a report exists."""
    if safe_text(report.get("workflow_phase")) == "plan":
        return ""
    summary_path = safe_text(report.get("summary_path"))
    if not summary_path:
        return "任务未记录报告中心摘要路径。"
    try:
        summary = normalize_report_center_summary(read_json(KIT_ROOT / safe_report_path(summary_path)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"阶段二未生成可读取的报告中心摘要：{type(exc).__name__}: {exc}"
    if not summary["problem_analysis"] or not summary["diagnostic_results"]:
        return "报告中心摘要缺少问题分析或详细诊断结果。"
    if safe_text(report.get("task_type")) == "debug_repro":
        try:
            draft_path = resource_request_draft_path({"report_center_summary": summary})
        except ValueError as exc:
            return f"Debug/验证任务的资源/物品清单草稿路径无效：{exc}"
        if not draft_path.is_file():
            return "Debug/验证任务未生成资源/物品清单草稿。"
    return ""


def start_job(
    kind: str,
    prompt: str,
    cfg: dict[str, Any],
    manual_report: dict[str, Any] | None = None,
    job_id: str = "",
) -> str:
    job_id = job_id or str(uuid.uuid4())
    prompt = prompt.replace("{resource_task_id}", job_id).replace("{manual_report_id}", job_id)
    copilot_cfg = cfg.get("copilot", {})
    if kind == "execute" and copilot_cfg.get("stage2Mode", "handoff") == "handoff":
        output = create_handoff(prompt, cfg, job_id)
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "kind": kind,
                "status": "completed",
                "exit_code": 0,
                "output": output,
                "prompt": prompt,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            if manual_report is not None:
                manual_report.update({"id": job_id, "status": "completed", "created_at": JOBS[job_id]["created_at"], "completed_at": JOBS[job_id]["updated_at"], "exit_code": 0, "output": output})
                JOBS[job_id]["manual_report"] = manual_report
                update_manual_report(JOBS[job_id])
        return job_id

    created_at = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "exit_code": None,
            "output": "",
            "prompt": prompt,
            "created_at": created_at,
            "updated_at": created_at,
        }
        if manual_report is not None:
            manual_report.update({"id": job_id, "summary_path": f"out\\manual_reports\\{job_id}.summary.json", "status": "running", "created_at": created_at, "completed_at": 0, "exit_code": None, "output": ""})
            JOBS[job_id]["manual_report"] = manual_report
            update_manual_report(JOBS[job_id])

    def worker() -> None:
        try:
            code, output = run_copilot(prompt, cfg, job_id)
            with JOBS_LOCK:
                job = JOBS[job_id]
                if not job.get("output"):
                    job["output"] = output
                artifact_error = ""
                if code == 0 and isinstance(job.get("manual_report"), dict):
                    artifact_error = manual_report_artifact_error(job["manual_report"])
                if artifact_error:
                    code = 1
                    job["output"] = job.get("output", "") + f"\nUI_REPORT_ARTIFACT_ERROR: {artifact_error}\n"
                job["exit_code"] = code
                job["status"] = "completed" if code == 0 else "failed"
                job["updated_at"] = time.time()
                update_manual_report(job)
        except Exception as exc:  # surface UI/backend errors rather than hiding them
            with JOBS_LOCK:
                job = JOBS[job_id]
                job["status"] = "failed"
                job["exit_code"] = 1
                job["output"] = job.get("output", "") + f"\nUI_BACKEND_ERROR: {type(exc).__name__}: {exc}\n"
                job["updated_at"] = time.time()
                update_manual_report(job)

    threading.Thread(target=worker, daemon=True).start()
    return job_id


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>IPS/HSD Copilot 工作台</title>
  <style>
    :root {
      --canvas: #f4f7fb;
      --surface: #ffffff;
      --surface-muted: #f8fafc;
      --sidebar: #0d1b38;
      --sidebar-muted: #9fb0d2;
      --text: #15213b;
      --muted: #64748b;
      --border: #dbe3ef;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --success: #0f9f6e;
      --warning: #c97708;
      --danger: #dc3d4f;
      --shadow: 0 8px 24px rgba(15, 35, 70, .08);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; min-width: 320px; background: var(--canvas); color: var(--text); font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; }
    body.dark {
      --canvas: #0c1428; --surface: #13203a; --surface-muted: #182744; --sidebar: #091126;
      --sidebar-muted: #9aacca; --text: #e5edf9; --muted: #aab9d1; --border: #2c3c5a;
      --primary: #5a91ff; --primary-hover: #79a7ff; --success: #35c993; --warning: #f0ae45;
      --danger: #fb7185; --shadow: 0 8px 28px rgba(0, 0, 0, .28);
    }
    .app-shell { display: grid; grid-template-columns: 252px minmax(0, 1fr); min-height: 100vh; }
    .sidebar { position: sticky; top: 0; height: 100vh; padding: 26px 16px; background: var(--sidebar); color: white; display: flex; flex-direction: column; }
    .brand { display: flex; align-items: center; gap: 11px; padding: 0 10px 28px; font-weight: 700; font-size: 16px; letter-spacing: .2px; }
    .brand-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: linear-gradient(135deg, #4f8dff, #63d6c4); box-shadow: 0 6px 16px rgba(68, 137, 255, .32); }
    .brand small { display: block; margin-top: 2px; color: var(--sidebar-muted); font-size: 11px; font-weight: 500; letter-spacing: .5px; }
    .nav-label { padding: 0 10px 9px; color: var(--sidebar-muted); font-size: 11px; font-weight: 700; letter-spacing: 1px; }
    .nav-link { display: flex; align-items: center; gap: 10px; padding: 10px; margin: 2px 0; border-radius: 8px; color: #dce8ff; text-decoration: none; font-size: 14px; transition: background .18s ease, transform .18s ease; }
    .nav-link:hover, .nav-link.active { background: rgba(126, 163, 230, .18); transform: translateX(2px); }
    .nav-link span { width: 19px; color: #86adff; text-align: center; }
    .sidebar-footer { margin-top: auto; padding: 16px 10px 0; border-top: 1px solid rgba(196, 215, 255, .14); color: var(--sidebar-muted); font-size: 12px; line-height: 1.6; }
    .main-content { width: min(1440px, 100%); margin: 0 auto; padding: 24px 34px 42px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
    .breadcrumb { color: var(--muted); font-size: 13px; }
    .connection { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--muted); }
    .connection-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--success); box-shadow: 0 0 0 4px color-mix(in srgb, var(--success) 15%, transparent); }
    .theme-toggle { border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: 8px; padding: 8px 11px; cursor: pointer; font-size: 13px; }
    .hero { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding: 26px 30px; border-radius: 16px; background: linear-gradient(120deg, #173d83, #2563b8 58%, #247c8e); color: white; box-shadow: var(--shadow); }
    .eyebrow { margin: 0 0 7px; color: #b9d6ff; font-size: 12px; font-weight: 700; letter-spacing: 1.1px; }
    h1 { margin: 0; font-size: clamp(25px, 3vw, 34px); letter-spacing: -.5px; }
    .subtitle { max-width: 680px; margin: 10px 0 0; color: #d7e8ff; line-height: 1.65; }
    .hero-badge { min-width: 160px; padding: 13px 16px; border: 1px solid rgba(255,255,255,.22); border-radius: 11px; background: rgba(8, 28, 73, .19); }
    .hero-badge strong { display: block; font-size: 13px; }
    .hero-badge span { color: #cae3ff; font-size: 12px; }
    .dashboard { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 20px 0; }
    .metric { min-height: 104px; padding: 18px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: 0 3px 12px rgba(15, 35, 70, .035); }
    .metric-label { color: var(--muted); font-size: 12px; font-weight: 600; }
    .metric-value { margin-top: 8px; color: var(--text); font-size: 25px; font-weight: 700; }
    .metric-note { display: block; margin-top: 5px; color: var(--muted); font-size: 12px; }
    .metric.running .metric-value { color: var(--primary); }
    .metric.success .metric-value { color: var(--success); }
    .metric.warning .metric-value { color: var(--warning); }
    .panel { max-width: none; margin-top: 18px; padding: 24px; border: 1px solid var(--border); border-radius: 13px; background: var(--surface); box-shadow: 0 3px 12px rgba(15, 35, 70, .035); }
    .panel h2 { margin: 0 0 20px; color: var(--text); font-size: 18px; }
    .panel h3 { margin: 24px 0 10px; font-size: 15px; }
    .panel-intro { margin: -11px 0 20px; color: var(--muted); font-size: 13px; line-height: 1.65; }
    .mode-picker { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .mode-card { position: relative; min-height: 148px; padding: 17px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface-muted); color: var(--text); text-align: left; box-shadow: none; }
    .mode-card:hover:not(:disabled) { border-color: color-mix(in srgb, var(--primary) 55%, var(--border)); background: var(--surface); }
    .mode-card.active { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, var(--surface)); box-shadow: inset 3px 0 0 var(--primary); }
    .mode-card strong, .mode-card span { display: block; }
    .mode-card strong { margin-bottom: 7px; font-size: 15px; }
    .mode-card span { color: var(--muted); font-size: 12px; font-weight: 400; line-height: 1.6; }
    .mode-card .mode-safety { margin-top: 13px; color: var(--primary); font-size: 10px; font-weight: 800; letter-spacing: .55px; text-transform: uppercase; }
    .mode-select-fallback { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
    .workflow-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 0 0 20px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--border); }
    .workflow-step { display: flex; align-items: center; gap: 10px; min-height: 58px; padding: 10px 13px; background: var(--surface-muted); color: var(--muted); }
    .workflow-step b { display: grid; place-items: center; flex: none; width: 25px; height: 25px; border: 1px solid currentColor; border-radius: 50%; font-size: 11px; }
    .workflow-step strong, .workflow-step small { display: block; }
    .workflow-step strong { color: var(--text); font-size: 12px; } .workflow-step small { margin-top: 2px; font-size: 11px; line-height: 1.35; }
    .workflow-step.active { background: color-mix(in srgb, var(--primary) 8%, var(--surface)); color: var(--primary); }
    .workflow-step.complete { color: var(--success); }
    .form-section { margin: 22px 0 0; padding: 19px 0 0; border-top: 1px solid var(--border); }
    .form-section:first-of-type { margin-top: 18px; }
    .form-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin: 0 0 13px; }
    .form-section-head h3 { margin: 0; font-size: 14px; } .form-section-head span { color: var(--muted); font-size: 12px; }
    .form-section .grid { max-width: none; }
    .grid { display: grid; grid-template-columns: 190px minmax(0, 1fr); gap: 13px 20px; max-width: 1120px; }
    label { padding-top: 10px; color: var(--text); font-size: 14px; font-weight: 650; }
    input, select, textarea { width: 100%; padding: 10px 11px; border: 1px solid var(--border); border-radius: 8px; outline: none; background: var(--surface-muted); color: var(--text); font-family: Consolas, "Microsoft YaHei", monospace; font-size: 13px; transition: border .18s ease, box-shadow .18s ease; }
    input:focus, select:focus, textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 16%, transparent); }
    input[type="checkbox"] { width: auto; accent-color: var(--primary); }
    textarea { min-height: 118px; resize: vertical; }
    button { margin-right: 8px; padding: 10px 14px; border: 1px solid transparent; border-radius: 8px; cursor: pointer; font-family: inherit; font-size: 13px; font-weight: 650; transition: transform .16s ease, box-shadow .16s ease, background .16s ease; }
    button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 5px 12px rgba(25, 63, 130, .16); }
    button.primary { background: var(--primary); color: white; }
    button.primary:hover { background: var(--primary-hover); }
    button.danger { background: var(--danger); color: white; }
    button.secondary { border-color: var(--border); background: var(--surface-muted); color: var(--text); }
    button:disabled { opacity: .45; cursor: not-allowed; }
    .status { display: inline-flex; align-items: center; min-height: 25px; padding: 3px 9px; border-radius: 999px; background: var(--surface-muted); color: var(--muted); font-size: 12px; font-weight: 700; }
    .warn { color: var(--warning); }
    .ok { background: color-mix(in srgb, var(--success) 13%, var(--surface)); color: var(--success); }
    .fail { background: color-mix(in srgb, var(--danger) 13%, var(--surface)); color: var(--danger); }
    .dispatch-notice { display: none; margin: 18px 0; padding: 17px 20px; border: 1px solid #75a7e8; border-left: 5px solid var(--primary); border-radius: 10px; background: linear-gradient(105deg, #eaf3ff, var(--surface) 72%); box-shadow: 0 10px 26px rgba(31, 93, 183, .12); }
    .dispatch-notice.visible { display: flex; align-items: flex-start; gap: 13px; }
    .dispatch-notice.error { border-color: #e3949a; border-left-color: var(--danger); background: linear-gradient(105deg, #fff0f1, var(--surface) 72%); }
    .dispatch-mark { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border-radius: 50%; background: var(--primary); color: #fff; font-weight: 900; }
    .dispatch-notice.error .dispatch-mark { background: var(--danger); }
    .dispatch-copy { min-width: 0; } .dispatch-copy strong { display: block; color: var(--text); font-size: 14px; } .dispatch-copy span { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; line-height: 1.55; }
    .dispatch-copy a { display: inline-block; margin-top: 7px; font-size: 12px; font-weight: 750; }
    pre { max-height: 440px; margin: 12px 0; padding: 15px; overflow: auto; border: 1px solid var(--border); border-radius: 9px; background: #101a30; color: #dbeafe; font-family: Consolas, monospace; font-size: 12px; line-height: 1.65; white-space: pre-wrap; }
    #planText { min-height: 360px; }
    .small { color: var(--muted); font-size: 12px; line-height: 1.6; }
    .row { margin: 16px 0 0; }
    .template-bar { display: grid; grid-template-columns: minmax(220px, 360px) auto 1fr; align-items: end; gap: 12px; }
    .template-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .template-actions button { margin-right: 0; }
    .hidden { display: none !important; }
    .auto-only { max-width: 1000px; }
    .report-link { margin-left: 12px; color: var(--primary); font-size: 13px; font-weight: 650; }
    .section-kicker { margin: -9px 0 18px; color: var(--muted); font-size: 13px; }
    .action-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--border); }
    .action-bar button { margin: 0; } .action-note { flex: 1 1 280px; color: var(--muted); font-size: 12px; line-height: 1.55; }
    .risk-panel { border-color: color-mix(in srgb, var(--warning) 48%, var(--border)); background: linear-gradient(120deg, color-mix(in srgb, var(--warning) 9%, var(--surface)), var(--surface) 62%); }
    .risk-panel .warn { margin: -10px 0 18px; line-height: 1.65; }
    .console-header { display: flex; align-items: center; justify-content: space-between; gap: 15px; padding-bottom: 14px; border-bottom: 1px solid var(--border); }
    .console-header h2 { margin: 0; } .console-header .status { flex: none; }
    .queue-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 13px; align-items: start; margin-top: 10px; padding: 15px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-muted); }
    .queue-item:first-child { margin-top: 0; } .queue-state { min-width: 74px; padding-top: 2px; color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .45px; text-transform: uppercase; }
    .queue-title { color: var(--text); font-size: 14px; font-weight: 700; } .queue-meta { margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.55; }
    .queue-item a { align-self: center; white-space: nowrap; font-size: 12px; }
    @media (max-width: 900px) {
      .app-shell { display: block; }
      .sidebar { position: relative; height: auto; padding: 16px; }
      .sidebar nav { display: none; }
      .sidebar-footer { display: none; }
      .brand { padding: 0; }
      .main-content { padding: 18px; }
      .dashboard { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .mode-picker { grid-template-columns: 1fr; }
    }
    @media (max-width: 620px) {
      .topbar, .hero { align-items: flex-start; flex-direction: column; }
      .dashboard { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; gap: 8px; }
      .grid > label { padding-top: 8px; }
      .template-bar { grid-template-columns: 1fr; align-items: stretch; }
      .panel { padding: 18px; }
      .hero { padding: 22px; }
      .workflow-steps { grid-template-columns: 1fr; }
      .form-section-head, .console-header { align-items: flex-start; flex-direction: column; }
      .queue-item { grid-template-columns: 1fr; gap: 6px; }
    }
  </style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark">◆</span><span>IPS Copilot<small>HARDWARE FLOW WORKBENCH</small></span></div>
    <nav>
      <div class="nav-label">工作台</div>
      <a class="nav-link active" href="/"><span>▣</span>任务工作台</a>
      <a class="nav-link" href="/tasks"><span>◷</span>任务中心</a>
      <a class="nav-link" href="/common-issues"><span>◎</span>共性问题分析</a>
      <a class="nav-link" href="/reports" target="_blank" rel="noopener"><span>▤</span>报告中心</a>
      <a class="nav-link" href="/guide"><span>?</span>用户指南</a>
    </nav>
    <div class="sidebar-footer">受控本地工具<br>请勿暴露到公网</div>
  </aside>
  <main class="main-content">
    <header class="topbar">
      <div><span class="breadcrumb">硬件流程 / IPS 与 HSD 自动化</span></div>
      <div class="connection"><span class="connection-dot"></span>服务已就绪 <button class="theme-toggle" type="button" onclick="toggleTheme()">切换主题</button></div>
    </header>
    <section class="hero" id="workspace">
      <div><p class="eyebrow">ENTERPRISE OPERATIONS WORKBENCH</p><h1>IPS/HSD Copilot 工作台</h1><p class="subtitle">以清晰的计划、受控执行和可追溯报告，支持两阶段手动流程及 HSD Query 自动化处理。</p></div>
      <div class="hero-badge"><strong id="modeSummary">简洁模式</strong><span>当前操作模式</span></div>
    </section>
    <section class="dashboard" aria-label="任务概览">
      <div class="metric"><span class="metric-label">当前模式</span><div class="metric-value" id="metricMode">简洁</div><span class="metric-note">按需切换执行方式</span></div>
      <div class="metric running"><span class="metric-label">运行中任务</span><div class="metric-value" id="metricRunning">0</div><span class="metric-note">包括手动执行、排队与资源等待</span></div>
      <div class="metric success"><span class="metric-label">已完成任务</span><div class="metric-value" id="metricCompleted">0</div><span class="metric-note">包括手动执行与 Query 任务</span></div>
      <div class="metric warning"><span class="metric-label">需要关注</span><div class="metric-value" id="metricAttention">0</div><span class="metric-note">手动失败及 Query 失败、取消或中断</span></div>
    </section>
    <section id="dispatchNotice" class="dispatch-notice" role="status" aria-live="polite" aria-atomic="true"></section>

  <div class="panel" id="mode-selection">
    <h2>选择工作方式</h2>
    <p class="panel-intro">选择后保留已输入内容。系统会在界面中显示与该模式相符的步骤和安全边界。</p>
    <select id="uiMode" class="mode-select-fallback" onchange="updateUiMode()" aria-label="UI 模式">
        <option value="simple">简洁模式：填写后直接开始执行</option>
        <option value="detailed">详细模式：先确认执行计划再执行</option>
        <option value="automatic">全自动模式：按 Query 定时处理 Open IPS</option>
    </select>
    <div class="mode-picker" role="radiogroup" aria-label="选择工作方式">
      <button type="button" class="mode-card" data-mode="simple" onclick="selectUiMode('simple')"><strong>简洁执行</strong><span>填写任务后按默认计划直接执行，适合目标和边界已经明确的工作。</span><span class="mode-safety">受控直接执行</span></button>
      <button type="button" class="mode-card" data-mode="detailed" onclick="selectUiMode('detailed')"><strong>计划审阅</strong><span>先生成并编辑计划，再进行明确的二次确认，适合调试和验证任务。</span><span class="mode-safety">两阶段安全流程</span></button>
      <button type="button" class="mode-card" data-mode="automatic" onclick="selectUiMode('automatic')"><strong>自动 Query</strong><span>为 HSD Saved Query 创建可追溯的持续任务，并协调机器资源锁。</span><span class="mode-safety">共享任务队列</span></button>
    </div>
  </div>

  <div class="panel manual-only" id="new-task">
    <h2>配置手动任务</h2>
    <p class="panel-intro">先定义要解决的问题和执行范围；详细模式将要求审阅计划后才能进入阶段二。</p>
    <div class="workflow-steps" aria-label="手动任务流程">
      <div class="workflow-step active"><b>1</b><div><strong>配置任务</strong><small>目标、机器与执行范围</small></div></div>
      <div class="workflow-step detailed-only"><b>2</b><div><strong>审阅计划</strong><small>生成并编辑阶段一结果</small></div></div>
      <div class="workflow-step"><b>3</b><div><strong>受控执行</strong><small>实时输出与报告留档</small></div></div>
    </div>
    <div class="template-bar">
      <div>
        <label for="taskTemplate" class="small">任务模板</label>
        <select id="taskTemplate" onchange="applyTaskTemplate()">
          <option value="custom">自定义任务</option>
          <option value="extract">仅提取 IPS 信息</option>
          <option value="consult">问题咨询（无硬件动作）</option>
          <option value="boot">启动验证（Debug / 验证）</option>
          <option value="mlc">跨 NUMA MLC 验证</option>
        </select>
      </div>
      <div class="template-actions">
        <button class="secondary" type="button" onclick="saveDraft()">保存草稿</button>
        <button class="secondary" type="button" onclick="clearDraft()">清除草稿</button>
      </div>
      <span id="draftStatus" class="small"></span>
    </div>
    <div class="form-section"><div class="form-section-head"><h3>任务来源与目标</h3><span>必填信息优先</span></div><div class="grid">
      <label for="ipsId">IPS/HSD ID</label>
      <input id="ipsId" placeholder="例如 14025984558">

      <label for="taskType">功能类型</label>
      <select id="taskType"></select>

      <label for="testTarget">测试目标</label>
      <input id="testTarget" placeholder="例如 跨NUMA MLC bandwidth_matrix / boot only / 指定命令">
    </div></div>

    <div class="form-section"><div class="form-section-head"><h3>执行范围与机器</h3><span>系统会在执行前验证匹配条件</span></div><div class="grid">
      <label for="autoMachineMatch">机器选择方式</label>
      <label style="font-weight: normal;"><input type="checkbox" id="autoMachineMatch" onchange="updateMachineSelection()"> 自动匹配机器（根据 IPS/HSD 提取的平台环境选择）</label>

      <label for="sshHost">SSH 控制机</label>
      <div>
        <select id="sshHost"></select>
        <div id="machineSelectionHint" class="small"></div>
      </div>

      <label for="permissionLevel">执行授权级别</label>
      <select id="permissionLevel"></select>

      <label for="searchSimilarIps">相似 IPS 检索</label>
      <label style="font-weight: normal;"><input type="checkbox" id="searchSimilarIps"> 检索相似 IPS 获取历史经验</label>

      <label for="downloadAttachments">客户附件</label>
      <label style="font-weight: normal;"><input type="checkbox" id="downloadAttachments"> 下载并分析客户附件</label>
    </div></div>

    <div class="form-section"><div class="form-section-head"><h3>通知与补充信息</h3><span>可选</span></div><div class="grid">
      <label for="submittedBy" class="simple-only">任务下发人</label>
      <input id="submittedBy" class="simple-only" placeholder="必填，例如 Zhang San">

      <label for="notificationRecipient">发送用户</label>
      <input id="notificationRecipient" placeholder="邮箱或 Outlook 名称；留空则不发送通知">

      <label for="notes">备注 / 补充信息</label>
      <textarea id="notes" placeholder="例如：只分析不烧录；需要 MLC v3.11b；需要对比 Directory Mode；抓日志 10 分钟"></textarea>
    </div></div>
    <div class="action-bar">
      <button id="simpleStartButton" class="primary" onclick="startSimple()">开始执行</button>
      <button class="secondary detailed-only" onclick="renderPlanPrompt()">预览阶段1 Prompt</button>
      <button class="primary detailed-only" onclick="startPlan()">生成执行计划</button>
      <span class="action-note">简洁模式将直接执行；详细模式先生成计划。所有结果都会写入报告中心。</span>
    </div>
  </div>

  <div class="panel detailed-only manual-only" id="plan-review">
    <div class="console-header"><div><p class="section-kicker">STEP 2 OF 3</p><h2>审阅阶段 1 计划</h2></div><span id="planStatus" class="status">未开始</span></div>
    <p class="panel-intro">先查看阶段 1 输出，再将需要保留的内容带入最终计划编辑框。</p>
    <pre id="planOutput"></pre>
    <div class="action-bar">
      <button class="secondary" onclick="copyText('planOutput')">复制阶段1输出</button>
      <button class="secondary" onclick="useOutputAsPlan()">将阶段1输出填入文本计划编辑框</button>
    </div>

    <h3>可编辑文本计划</h3>
    <textarea id="planText"></textarea>
    <div class="action-bar">
      <button class="secondary" onclick="resetPlanTemplate()">重置为默认文本计划模板</button>
      <span id="planEditStatus" class="small"></span>
    </div>
  </div>

  <div class="panel risk-panel detailed-only manual-only" id="execution-confirm">
    <p class="section-kicker">STEP 3 OF 3 · HARDWARE-AFFECTING ACTION</p>
    <h2>确认计划并受控执行</h2>
    <p class="warn">只有勾选确认并点击“确认并执行”后，UI 才会启动阶段二 Copilot subprocess，并在下方输出框实时显示信息。</p>
    <label><input type="checkbox" id="confirmCheck"> 我已经检查并确认最终文本计划。</label>
    <div class="action-bar">
      <button class="secondary" onclick="renderExecutePrompt()">预览阶段2 Prompt</button>
      <button id="executeButton" class="danger" type="button" onclick="startExecute()">确认并执行</button>
      <span class="action-note">执行过程、输出和最终结果均会保存至报告中心。</span>
    </div>
  </div>

  <div class="panel auto-only auto-run-only" id="automatic-tasks">
    <h2>全自动 Query 任务</h2>
    <p class="panel-intro">为一个 HSD Saved Query 创建独立、持久化的任务。系统会阻止相同活动 Query 重复运行，并在使用同一机器时协调资源锁。</p>
    <div class="grid">
      <label for="autoCreatorName">创建人姓名</label>
      <input id="autoCreatorName" placeholder="必填，例如 Zhang San">

      <label for="autoQueryId">HSD Query ID</label>
      <input id="autoQueryId" placeholder="例如 15019610126">

      <label for="autoIntervalMinutes">轮询间隔（分钟）</label>
      <input id="autoIntervalMinutes" type="number" min="60" step="1" value="60">

      <label for="autoManagerRecipients">汇总报告通知者</label>
      <input id="autoManagerRecipients" placeholder="Outlook 名称或邮箱；多个收件人以分号分隔">

      <label for="autoReportOnly">执行方式</label>
      <label><input id="autoReportOnly" type="checkbox" onchange="toggleAutoReportOnly()"> 仅生成共性报告</label>
    </div>
    <p id="autoReportOnlyHint" class="small">勾选后仅生成 Top IPS 参考报告：不处理 Open IPS、不轮询；如已填写汇总通知者，报告完成后仍会发送通知。</p>
    <div class="action-bar"><button id="autoStartButton" class="primary" type="button" onclick="startQueryTask()">创建并启动 Query 任务</button>
      <a class="report-link" href="/reports" target="_blank" rel="noopener">查看历史汇总报告</a>
      <span id="autoTaskStatus" class="small"></span></div>
  </div>

  <div class="panel auto-only auto-run-only" id="task-queue">
    <h2>共享 Query 任务管理</h2>
    <p class="small">所有浏览器会话看到相同的持久化状态。取消队列任务立即生效；相同活动 Query 不会重复创建。完整筛选、资源状态和任务详情请前往任务中心。</p>
    <div id="taskList" class="small">正在加载任务…</div>
  </div>

  <div class="panel manual-only" id="execution-console">
    <div class="console-header"><div><p class="section-kicker">EXECUTION CONSOLE</p><h2>实时执行输出</h2></div><span id="execStatus" class="status">未开始</span></div>
    <p class="panel-intro">此处保留完整技术输出，执行完成后可从报告中心查看结构化结果。</p>
    <pre id="execOutput"></pre>
    <div class="action-bar"><button class="secondary" onclick="copyText('execOutput')">复制阶段2输出</button></div>
  </div>
</main>
</div>

<script>
let appConfig = null;
let lastPlanJob = null;
let lastExecJob = null;
const DRAFT_KEY = "ips-copilot-ui-draft-v1";
const TASK_TEMPLATES = {
  extract: {task_type: "extract_ips", test_target: "仅提取 IPS/HSD 信息", notes: "仅生成结构化 IPS 摘要，不执行硬件动作。"},
  consult: {task_type: "consult", test_target: "问题咨询与建议", notes: "仅分析 HSD/IPS 内容、历史经验和需要补充的信息，不执行硬件动作。"},
  boot: {task_type: "debug_repro", test_target: "boot only", notes: "仅在确认计划后执行 BKC 匹配、烧录和启动日志验证；启动成功后不运行额外 MLC。"},
  mlc: {task_type: "debug_repro", test_target: "跨NUMA MLC bandwidth_matrix", notes: "验证启动成功后运行 MLC v3.11b 跨 NUMA bandwidth_matrix。"}
};

async function api(path, payload) {
  const opts = payload === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  };
  const res = await fetch(path, opts);
  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}

function formData() {
  const taskType = document.getElementById("taskType");
  const autoMachineMatch = document.getElementById("autoMachineMatch").checked;
  const sshHost = document.getElementById("sshHost");
  return {
    ui_mode: document.getElementById("uiMode").value,
    ips_id: document.getElementById("ipsId").value,
    auto_machine_match: autoMachineMatch,
    ssh_host: autoMachineMatch ? "" : sshHost.value,
    ssh_machine_label: autoMachineMatch ? "自动匹配" : (sshHost.options[sshHost.selectedIndex] ? sshHost.options[sshHost.selectedIndex].textContent : ""),
    task_type: taskType.value,
    task_type_label: taskType.options[taskType.selectedIndex] ? taskType.options[taskType.selectedIndex].textContent : taskType.value,
    permission_level: document.getElementById("permissionLevel").value,
    permission_label: document.getElementById("permissionLevel").options[document.getElementById("permissionLevel").selectedIndex] ? document.getElementById("permissionLevel").options[document.getElementById("permissionLevel").selectedIndex].textContent : document.getElementById("permissionLevel").value,
    search_similar_ips: document.getElementById("searchSimilarIps").checked,
    download_attachments: document.getElementById("downloadAttachments").checked,
    notify_owner: true,
    notification_recipient_mode: "specified_user",
    notification_recipient: document.getElementById("notificationRecipient").value,
    submitted_by: document.getElementById("submittedBy").value,
    notification_subject_prefix: "[Copilot][HSD]",
    test_target: document.getElementById("testTarget").value,
    notes: document.getElementById("notes").value
  };
}

function setStatus(id, status) {
  const el = document.getElementById(id);
  el.textContent = status;
  el.className = "status " + (status === "completed" ? "ok" : status === "failed" ? "fail" : "");
}

function showDispatchNotice(title, detail, link) {
  const notice = document.getElementById("dispatchNotice");
  notice.classList.remove("error");
  notice.replaceChildren();
  const mark = document.createElement("span");
  mark.className = "dispatch-mark";
  mark.textContent = "✓";
  const copy = document.createElement("div");
  copy.className = "dispatch-copy";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const description = document.createElement("span");
  description.textContent = detail;
  copy.append(heading, description);
  if (link) {
    const anchor = document.createElement("a");
    anchor.href = link.href;
    anchor.textContent = link.label;
    copy.appendChild(anchor);
  }
  notice.append(mark, copy);
  notice.classList.add("visible");
  notice.scrollIntoView({behavior: "smooth", block: "nearest"});
}

function showDispatchError(detail) {
  const notice = document.getElementById("dispatchNotice");
  notice.classList.add("visible", "error");
  notice.replaceChildren();
  const mark = document.createElement("span");
  mark.className = "dispatch-mark";
  mark.textContent = "!";
  const copy = document.createElement("div");
  copy.className = "dispatch-copy";
  const heading = document.createElement("strong");
  heading.textContent = "任务未下发";
  const description = document.createElement("span");
  description.textContent = detail;
  copy.append(heading, description);
  notice.append(mark, copy);
  notice.scrollIntoView({behavior: "smooth", block: "nearest"});
}

function setActionBusy(buttonId, busy, busyLabel) {
  const button = document.getElementById(buttonId);
  if (!button) return;
  if (busy) {
    button.dataset.idleLabel = button.textContent;
    button.textContent = busyLabel;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.idleLabel || button.textContent;
    button.disabled = false;
  }
}

async function loadConfig() {
  appConfig = await api("/api/config");
  const savedMode = localStorage.getItem("ips-copilot-ui-mode");
  const configuredMode = appConfig.defaults.uiMode || "simple";
  document.getElementById("uiMode").value = ["simple", "detailed", "automatic"].includes(savedMode)
    ? savedMode : (configuredMode || "simple");
  const sshHost = document.getElementById("sshHost");
  sshHost.innerHTML = "";
  for (const machine of appConfig.machineOptions) {
    const opt = document.createElement("option");
    opt.value = machine.value;
    opt.textContent = machine.label;
    sshHost.appendChild(opt);
  }
  sshHost.value = appConfig.defaults.sshHost || "";
  if (!sshHost.value && sshHost.options.length) sshHost.selectedIndex = 0;
  document.getElementById("autoMachineMatch").checked = !!appConfig.defaults.autoMachineMatch;
  document.getElementById("taskType").innerHTML = "";
  for (const item of appConfig.taskTypes) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label + " - " + item.description;
    document.getElementById("taskType").appendChild(opt);
  }
  document.getElementById("taskType").value = appConfig.defaults.taskType || "debug_repro";
  document.getElementById("permissionLevel").innerHTML = "";
  for (const item of appConfig.permissionLevels || []) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label + " - " + item.description;
    document.getElementById("permissionLevel").appendChild(opt);
  }
  document.getElementById("permissionLevel").value = appConfig.defaults.permissionLevel || "standard";
  document.getElementById("autoIntervalMinutes").min = appConfig.automation.minimumIntervalMinutes || 60;
  document.getElementById("autoIntervalMinutes").value = appConfig.automation.minimumIntervalMinutes || 60;
  document.getElementById("autoManagerRecipients").value = appConfig.automation.defaultManagerRecipients || "";
  updateUiMode();
  updateMachineSelection();
  resetPlanTemplate();
  restoreDraft();
  registerDraftAutosave();
  refreshTasks();
}

function saveDraft() {
  localStorage.setItem(DRAFT_KEY, JSON.stringify(formData()));
  document.getElementById("draftStatus").textContent = "草稿已保存在当前浏览器。";
}

function restoreDraft() {
  const raw = localStorage.getItem(DRAFT_KEY);
  if (!raw) return;
  try {
    const draft = JSON.parse(raw);
    const fields = ["ips_id", "ssh_host", "task_type", "permission_level", "test_target", "notification_recipient", "submitted_by", "notes"];
    const ids = {ips_id:"ipsId", ssh_host:"sshHost", task_type:"taskType", permission_level:"permissionLevel", test_target:"testTarget", notification_recipient:"notificationRecipient", submitted_by:"submittedBy", notes:"notes"};
    for (const field of fields) {
      if (draft[field] !== undefined && document.getElementById(ids[field])) document.getElementById(ids[field]).value = draft[field];
    }
    document.getElementById("autoMachineMatch").checked = !!draft.auto_machine_match;
    document.getElementById("searchSimilarIps").checked = !!draft.search_similar_ips;
    document.getElementById("downloadAttachments").checked = !!draft.download_attachments;
    updateMachineSelection();
    document.getElementById("draftStatus").textContent = "已恢复当前浏览器保存的草稿。";
  } catch (error) {
    localStorage.removeItem(DRAFT_KEY);
    document.getElementById("draftStatus").textContent = "已移除无法读取的草稿。";
  }
}

function clearDraft() {
  localStorage.removeItem(DRAFT_KEY);
  document.getElementById("draftStatus").textContent = "已清除浏览器草稿。";
}

function registerDraftAutosave() {
  for (const field of document.querySelectorAll("#new-task input, #new-task select, #new-task textarea")) {
    field.addEventListener("change", () => { if (document.getElementById("taskTemplate").value === "custom") saveDraft(); });
  }
}

function applyTaskTemplate() {
  const name = document.getElementById("taskTemplate").value;
  const template = TASK_TEMPLATES[name];
  if (!template) return;
  document.getElementById("taskType").value = template.task_type;
  document.getElementById("testTarget").value = template.test_target;
  document.getElementById("notes").value = template.notes;
  saveDraft();
  document.getElementById("draftStatus").textContent = "已加载模板，可继续修改后执行。";
}

function updateMachineSelection() {
  const automatic = document.getElementById("autoMachineMatch").checked;
  document.getElementById("sshHost").disabled = automatic;
  document.getElementById("machineSelectionHint").textContent = automatic
    ? "阶段2在提取 IPS/HSD 平台环境后，按已登记机器矩阵自动匹配；平台不明或冲突时会停止。"
    : "手动模式：阶段2只能使用此处选择的控制机，并会验证平台匹配。";
}

function updateUiMode() {
  const mode = document.getElementById("uiMode").value;
  const simple = mode === "simple";
  const automatic = mode === "automatic";
  for (const el of document.querySelectorAll(".manual-only")) {
    el.classList.toggle("hidden", automatic);
  }
  for (const el of document.querySelectorAll(".auto-run-only")) {
    el.classList.toggle("hidden", !automatic);
  }
  for (const el of document.querySelectorAll(".detailed-only")) {
    el.classList.toggle("hidden", simple || automatic);
  }
  for (const el of document.querySelectorAll(".simple-only")) {
    el.classList.toggle("hidden", !simple || automatic);
  }
  document.getElementById("simpleStartButton").classList.toggle("hidden", !simple || automatic);
  const labels = {simple: "简洁模式", detailed: "详细模式", automatic: "全自动模式"};
  document.getElementById("metricMode").textContent = labels[mode] || mode;
  document.getElementById("modeSummary").textContent = labels[mode] || mode;
  for (const card of document.querySelectorAll(".mode-card")) {
    const selected = card.dataset.mode === mode;
    card.classList.toggle("active", selected);
    card.setAttribute("aria-pressed", String(selected));
  }
  localStorage.setItem("ips-copilot-ui-mode", mode);
}

function selectUiMode(mode) {
  document.getElementById("uiMode").value = mode;
  updateUiMode();
}

function updateTaskMetrics(tasks, manualReports) {
  const active = new Set(["queued", "running", "waiting_resource", "cancelling"]);
  const attention = new Set(["failed", "cancelled", "interrupted"]);
  const manual = manualReports || [];
  document.getElementById("metricRunning").textContent = tasks.filter(task => active.has(task.status)).length + manual.filter(report => report.status === "running").length;
  document.getElementById("metricCompleted").textContent = tasks.filter(task => task.status === "completed").length + manual.filter(report => report.status === "completed").length;
  document.getElementById("metricAttention").textContent = tasks.filter(task => attention.has(task.status)).length + manual.filter(report => report.status === "failed").length;
}

function toggleTheme() {
  const dark = !document.body.classList.contains("dark");
  document.body.classList.toggle("dark", dark);
  localStorage.setItem("ips-copilot-ui-theme", dark ? "dark" : "light");
}

function restoreUiPreferences() {
  if (localStorage.getItem("ips-copilot-ui-theme") === "dark") document.body.classList.add("dark");
  const savedMode = localStorage.getItem("ips-copilot-ui-mode");
  if (savedMode && ["simple", "detailed", "automatic"].includes(savedMode)) {
    document.getElementById("uiMode").value = savedMode;
  }
}

async function refreshTasks() {
  const data = await api("/api/tasks");
  document.getElementById("taskList").innerHTML = data.tasks.length ? data.tasks.map(task => {
    const reason = task.cancellation_reason || task.error_text;
    return `<article class="queue-item"><div class="queue-state">${escapeHtml(task.status)}</div><div><div class="queue-title">Query ${escapeHtml(task.query_id)} · 第 ${Number(task.current_round || 0)} 轮</div><div class="queue-meta">创建人：${escapeHtml(task.creator_name)} · 当前 IPS：${escapeHtml(task.current_ips_id || "—")} · 创建：${new Date(task.created_at * 1000).toLocaleString()}${reason ? ` · 原因：${escapeHtml(reason)}` : ""}</div></div><a href="/tasks/${task.id}">查看详情</a></article>`;
  }).join("") : "尚无 Query 任务。";
  updateTaskMetrics(data.tasks, data.manual_reports);
}
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = value || ""; return div.innerHTML; }
async function startQueryTask() {
  const queryId = document.getElementById("autoQueryId").value.trim();
  const creatorName = document.getElementById("autoCreatorName").value.trim();
  const reportOnly = document.getElementById("autoReportOnly").checked;
  const intervalMinutes = reportOnly ? 0 : Number(document.getElementById("autoIntervalMinutes").value);
  const status = document.getElementById("autoTaskStatus");
  status.textContent = "";
  if (!creatorName) { alert("请输入创建人姓名。"); return; }
  if (!/^\d+$/.test(queryId)) { alert("请输入数字形式的 HSD Query ID。"); return; }
  setActionBusy("autoStartButton", true, "正在下发任务…");
  let dispatched = false;
  try {
    const task = await api("/api/tasks", {query_id: queryId, creator_name: creatorName, interval_minutes: intervalMinutes, manager_recipients: document.getElementById("autoManagerRecipients").value.trim(), report_only: reportOnly});
    status.textContent = `Query ${queryId} 已创建并开始执行。`;
    showDispatchNotice(`Query ${queryId} 已下发`, reportOnly ? "已创建一次性只读共性报告任务，正在开始分析。" : "已进入共享任务队列，系统将按设定间隔持续处理。", {href: `/tasks/${task.id}`, label: "打开任务详情"});
    dispatched = true;
    refreshTasks();
  } catch (error) {
    try {
      const detail = JSON.parse(error.message);
      if (detail.error === "duplicate_query" && detail.existing_task) {
        status.innerHTML = `Query ${queryId} 已有进行中的任务；原任务未被中断。<a href="/tasks/${detail.existing_task.id}">查看现有任务</a>`;
        showDispatchError(`Query ${queryId} 已有进行中的任务；未创建重复任务。`);
        alert(`Query ${queryId} 已有进行中的任务，原任务未被中断。`);
        return;
      }
    } catch (_) {
      // The standard API error text is not always JSON.
    }
    showDispatchError(`无法创建 Query 任务：${error.message}`);
    alert(`无法创建 Query 任务：${error.message}`);
  } finally {
    if (!dispatched) setActionBusy("autoStartButton", false);
  }
}
function toggleAutoReportOnly() {
  const reportOnly = document.getElementById("autoReportOnly").checked;
  document.getElementById("autoIntervalMinutes").disabled = reportOnly;
}
setInterval(() => { if (document.getElementById("taskList")) refreshTasks().catch(() => {}); }, 3000);

async function resetPlanTemplate() {
  const data = await api("/api/plan-template", formData());
  document.getElementById("planText").value = data.plan_text;
  document.getElementById("planEditStatus").textContent = "已生成默认文本计划模板。";
}

async function renderPlanPrompt() {
  const data = await api("/api/render-plan-prompt", formData());
  document.getElementById("planOutput").textContent = data.prompt;
  setStatus("planStatus", "prompt rendered");
}

async function startPlan() {
  const data = await api("/api/start-plan", formData());
  lastPlanJob = data.job_id;
  setStatus("planStatus", "running");
  pollJob(lastPlanJob, "planStatus", "planOutput");
}

async function renderExecutePrompt() {
  const form = formData();
  const data = await api("/api/render-execute-prompt", {
    plan_text: document.getElementById("planText").value,
    permission_label: form.permission_label,
    task_type: form.task_type,
    auto_machine_match: form.auto_machine_match,
    ssh_host: form.ssh_host,
  });
  document.getElementById("execOutput").textContent = data.prompt;
  setStatus("execStatus", "prompt rendered");
}

function validateExecutionConfirm() {
  if (!document.getElementById("confirmCheck").checked) {
    alert("请先勾选确认框。");
    return false;
  }
  if (!document.getElementById("planText").value.trim()) {
    alert("最终文本计划不能为空。");
    return false;
  }
  return true;
}

async function startExecute() {
  if (!validateExecutionConfirm()) return;
  const form = formData();
  setActionBusy("executeButton", true, "正在下发任务…");
  let dispatched = false;
  try {
    const data = await api("/api/start-execute", {
      ...form,
      plan_text: document.getElementById("planText").value,
      manual_report_id: lastPlanJob || "",
    });
    lastExecJob = data.job_id;
    setStatus("execStatus", "running");
    showDispatchNotice("任务已下发并开始执行", "阶段二已启动；实时输出与最终结果会写入报告中心。");
    dispatched = true;
    pollJob(lastExecJob, "execStatus", "execOutput");
  } catch (error) {
    showDispatchError(`无法下发任务：${error.message}`);
  } finally {
    if (!dispatched) setActionBusy("executeButton", false);
  }
}

async function startSimple() {
  const form = formData();
  if (!form.submitted_by.trim()) {
    alert("请填写任务下发人。");
    document.getElementById("submittedBy").focus();
    return;
  }
  setActionBusy("simpleStartButton", true, "正在下发任务…");
  let dispatched = false;
  try {
    const plan = await api("/api/plan-template", form);
    const data = await api("/api/start-execute", {
      ...form,
      plan_text: plan.plan_text,
    });
    lastExecJob = data.job_id;
    setStatus("execStatus", "running");
    document.getElementById("execOutput").textContent = "简洁模式已开始执行；结果完成后会登记到报告中心。";
    showDispatchNotice("任务已下发并开始执行", "默认执行计划已生成，正在受控执行。可在下方实时执行输出查看进度。");
    dispatched = true;
    pollJob(lastExecJob, "execStatus", "execOutput");
  } catch (error) {
    setStatus("execStatus", "failed");
    showDispatchError(`无法下发任务：${error.message}`);
  } finally {
    if (!dispatched) setActionBusy("simpleStartButton", false);
  }
}

async function pollJob(jobId, statusId, outputId) {
  while (true) {
    const data = await api("/api/job?id=" + encodeURIComponent(jobId));
    setStatus(statusId, data.status);
    document.getElementById(outputId).textContent = data.output || "";
    if (data.status === "completed" || data.status === "failed") {
      if (outputId === "planOutput" && data.status === "completed" && data.output) {
        document.getElementById("planText").value = data.output.trim();
        document.getElementById("planEditStatus").textContent = "阶段1输出已自动填入文本计划编辑框，可继续修改。";
      }
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
}

function useOutputAsPlan() {
  const output = document.getElementById("planOutput").textContent.trim();
  if (!output) return;
  const fenced = output.match(/```(?:markdown|text)?\s*([\s\S]*?)```/i);
  document.getElementById("planText").value = fenced ? fenced[1].trim() : output;
  document.getElementById("planEditStatus").textContent = "已填入阶段1输出，可继续手动修改。";
}

async function copyText(id) {
  await navigator.clipboard.writeText(document.getElementById(id).textContent);
}

restoreUiPreferences();
loadConfig().catch(err => {
  document.body.innerHTML = "<pre>UI 初始化失败：" + err.message + "</pre>";
});
</script>
</body>
</html>
"""


def report_layout(title: str, body: str, section: str = "报告中心", language: str = "zh-CN") -> str:
    is_english = language == "en"
    navigation = (
        '<a href="/">Workbench</a><a href="/tasks">Tasks</a><a href="/common-issues">Common Issues</a>'
        '<a href="/reports">Reports</a><a href="/guide">Guide</a>'
        if is_english else
        '<a href="/">工作台</a><a href="/tasks">任务中心</a><a href="/common-issues">共性问题分析</a>'
        '<a href="/reports">报告中心</a><a href="/guide">用户指南</a>'
    )
    return f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --canvas:#f4f7fb; --surface:#fff; --text:#15213b; --muted:#64748b; --border:#dbe3ef; --primary:#2563eb; --success:#0f9f6e; --warning:#c97708; --danger:#dc3d4f; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:linear-gradient(180deg,#eef4fc 0,#f4f7fb 280px); color:var(--text); font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px max(24px, calc((100vw - 1320px)/2)); background:#0d1b38; color:#e5efff; box-shadow:0 1px 0 rgba(255,255,255,.07); }}
    .brand {{ display:flex; align-items:center; gap:9px; font-size:14px; font-weight:700; letter-spacing:.2px; }}
    .brand-mark {{ display:grid; place-items:center; width:28px; height:28px; border-radius:8px; background:linear-gradient(135deg,#4f8dff,#63d6c4); }}
    .topbar nav {{ display:flex; flex-wrap:wrap; justify-content:flex-end; gap:5px; }}
    .topbar a {{ padding:6px 8px; border-radius:6px; color:#c9dcff; text-decoration:none; font-size:13px; }}
    .topbar a:hover {{ background:rgba(147,197,253,.13); color:white; text-decoration:none; }}
    main {{ width:min(1320px,100%); margin:0 auto; padding:28px 26px 46px; }}
    .hero {{ padding:25px 28px; border-radius:15px; background:linear-gradient(120deg,#173d83,#2563b8 60%,#247c8e); color:white; box-shadow:0 8px 24px rgba(15,35,70,.12); }}
    .eyebrow {{ margin:0 0 7px; color:#b9d6ff; font-size:11px; font-weight:700; letter-spacing:1px; }}
    h1 {{ margin:0; font-size:27px; letter-spacing:-.3px; }}
    h2 {{ margin:0 0 15px; font-size:18px; }}
    .muted {{ color:var(--muted); line-height:1.65; }}
    .hero .muted {{ margin:8px 0 0; color:#d7e8ff; }}
    .summary {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin:20px 0; }}
    .metric, .panel {{ border:1px solid var(--border); border-radius:12px; background:var(--surface); box-shadow:0 3px 12px rgba(15,35,70,.035); }}
    .metric {{ padding:17px; }}
    .metric-label {{ color:var(--muted); font-size:12px; font-weight:600; }}
    .metric-value {{ margin-top:7px; font-size:24px; font-weight:700; }}
    .panel {{ margin-top:18px; padding:23px; }}
    .report-section-label {{ margin:0 0 7px; color:#4d78af; font-size:10px; font-weight:800; letter-spacing:.75px; text-transform:uppercase; }}
    .report-summary-grid {{ display:grid; grid-template-columns:1.25fr 1fr; gap:14px; margin-top:18px; }}
    .report-summary-grid .panel {{ margin-top:0; }}
    .report-brief {{ border-color:#cadcf3; background:linear-gradient(145deg,#fff,#f5f9ff); }}
    .report-brief h2 {{ margin-bottom:9px; }} .report-brief p {{ margin:0; color:#40516d; line-height:1.7; }}
    .report-actions {{ display:grid; gap:12px; }}
    .report-action {{ padding:14px; border:1px solid #dbe6f4; border-radius:9px; background:#fbfdff; }}
    .report-action strong {{ display:block; margin-bottom:5px; color:#263b59; font-size:13px; }} .report-action p,.report-action ul {{ margin:0; color:#52627a; font-size:13px; line-height:1.6; }}
    .report-action ul {{ padding-left:18px; }}
    .technical-disclosure {{ margin-top:18px; border:1px solid var(--border); border-radius:10px; background:var(--surface); overflow:hidden; }}
    .technical-disclosure summary {{ padding:14px 16px; color:#315b91; font-size:13px; font-weight:750; cursor:pointer; }}
    .technical-disclosure[open] summary {{ border-bottom:1px solid var(--border); }} .technical-disclosure pre {{ max-height:520px; margin:0; border:0; border-radius:0; }}
    .common-group-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
    .common-group-head h2 {{ margin-bottom:7px; }} .common-group-head p {{ margin:0; }}
    .evidence-chip {{ flex:none; padding:6px 9px; border:1px solid #c9dcef; border-radius:999px; background:#f1f7ff; color:#235a9d; font-size:11px; font-weight:800; white-space:nowrap; }}
    .group-explanation {{ max-width:920px; margin:16px 0 0; padding:12px 14px; border-left:3px solid #77a8e8; background:#f7faff; color:#40516d; font-size:13px; line-height:1.65; }}
    .review-strip {{ display:flex; flex-wrap:wrap; gap:8px 16px; margin:14px 0 0; color:#52627a; font-size:12px; line-height:1.5; }}
    .review-strip strong {{ color:#344a6b; }}
    .notice {{ margin:16px 0; padding:12px 14px; border-radius:9px; background:#eef5ff; color:#24416f; font-size:13px; line-height:1.6; }}
    .notice.warning {{ background:#fff4df; color:#855300; }}
    .common-query-card {{ margin-top:20px; padding:26px; border:1px solid #cddcf5; border-radius:14px; background:linear-gradient(145deg,#fff 0%,#f7faff 100%); box-shadow:0 7px 20px rgba(32,78,145,.07); }}
    .common-query-heading {{ display:flex; align-items:flex-start; justify-content:space-between; gap:18px; margin-bottom:22px; }}
    .common-query-heading h2 {{ margin:0 0 5px; }}
    .common-query-heading p {{ margin:0; }}
    .common-query-badge {{ flex:none; padding:6px 10px; border-radius:999px; background:#e8f1ff; color:#215bb4; font-size:12px; font-weight:700; }}
    .common-query-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }}
    .common-query-field {{ display:grid; gap:7px; }}
    .common-query-field label {{ color:#344767; font-size:13px; font-weight:700; }}
    .common-query-field label span {{ margin-left:5px; color:var(--muted); font-weight:400; }}
    .common-query-field input {{ width:100%; min-height:40px; padding:9px 11px; border:1px solid #cbd8eb; border-radius:8px; background:#fff; color:var(--text); font:inherit; transition:border-color .18s,box-shadow .18s; }}
    .common-query-field input:focus {{ outline:0; border-color:#4d86e8; box-shadow:0 0 0 3px rgba(37,99,235,.14); }}
    .common-query-field input::placeholder {{ color:#94a3b8; }}
    .common-query-field.wide {{ grid-column:span 2; }}
    .common-date-range {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .common-query-actions {{ display:flex; align-items:center; gap:13px; margin-top:24px; padding-top:20px; border-top:1px solid #dbe5f3; }}
    .common-query-actions button {{ min-width:132px; min-height:42px; box-shadow:0 4px 10px rgba(37,99,235,.22); }}
    .common-query-actions .muted {{ font-size:13px; }}
    .filter {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; }}
    .filter input, .filter select {{ flex:1 1 180px; padding:9px 10px; border:1px solid var(--border); border-radius:8px; font:inherit; }}
    .task-grid {{ display:grid; gap:12px; }}
    .task-card {{ padding:16px; border:1px solid var(--border); border-radius:10px; background:#fbfdff; }}
    .task-card h3 {{ margin:0 0 8px; font-size:15px; }}
    .task-meta {{ display:flex; flex-wrap:wrap; gap:8px 16px; color:var(--muted); font-size:12px; line-height:1.6; }}
    .task-card pre {{ max-height:180px; margin-top:12px; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:13px; }}
    button {{ padding:9px 12px; border:1px solid var(--border); border-radius:8px; background:#fff; color:var(--text); font:inherit; font-weight:650; cursor:pointer; }}
    button.primary {{ border-color:var(--primary); background:var(--primary); color:white; }}
    button.danger {{ border-color:var(--danger); background:var(--danger); color:white; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; overflow:hidden; border:1px solid var(--border); border-radius:9px; }}
    th, td {{ padding:12px 13px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; font-size:13px; }}
    th {{ background:#f8fafc; color:#52617a; font-size:12px; letter-spacing:.15px; }}
    tr:last-child td {{ border-bottom:0; }}
    tbody tr:hover {{ background:#f8fbff; }}
    .status-badge {{ display:inline-flex; padding:4px 9px; border-radius:999px; background:#eef2f7; color:#52617a; font-size:12px; font-weight:700; }}
    .status-completed {{ background:#e7f8f0; color:var(--success); }}
    .status-blocked, .status-skipped {{ background:#fff4df; color:var(--warning); }}
    .status-failed, .status-cancelled, .status-interrupted {{ background:#ffebee; color:var(--danger); }}
    .reference-list {{ display:grid; gap:14px; }}
    .reference-card {{ padding:18px; border:1px solid #d6e2f1; border-radius:11px; background:linear-gradient(135deg,#fff,#f8fbff); }}
    .reference-section-head {{ position:relative; display:flex; align-items:flex-start; justify-content:space-between; gap:18px; margin-bottom:18px; }}
    .reference-section-head h2 {{ margin:0 0 5px; }}
    .reference-section-head .muted {{ margin:0; }}
    .criteria-disclosure {{ position:relative; flex:none; min-width:230px; max-width:360px; border:1px solid #d6e2f1; border-radius:9px; background:#f8fbff; }}
    .criteria-disclosure summary {{ padding:10px 12px; color:#1e5db7; font-size:13px; font-weight:700; cursor:pointer; }}
    .criteria-content {{ position:absolute; top:calc(100% + 6px); right:0; z-index:10; width:360px; padding:12px 14px; border:1px solid #d6e2f1; border-radius:9px; background:var(--surface); box-shadow:0 10px 24px rgba(15,35,70,.16); color:#40516d; font-size:12px; line-height:1.6; }}
    .criteria-content ul {{ margin:6px 0 0; padding-left:18px; }}
    .reference-card-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }}
    .reference-title {{ margin:0; font-size:16px; line-height:1.45; }}
    .reference-title a {{ color:var(--text); }}
    .reference-rank {{ display:inline-grid; place-items:center; min-width:30px; height:30px; margin-right:9px; border-radius:8px; background:#e7f0ff; color:#1e5db7; font-size:13px; font-weight:800; vertical-align:middle; }}
    .reference-score {{ flex:none; min-width:66px; padding:7px 9px; border-radius:9px; background:#123e82; color:#fff; text-align:center; }}
    .reference-score strong {{ display:block; font-size:18px; line-height:1; }}
    .reference-score span {{ display:block; margin-top:3px; color:#cde0ff; font-size:10px; font-weight:700; letter-spacing:.4px; }}
    .reference-meta {{ display:flex; flex-wrap:wrap; gap:7px; margin:11px 0; }}
    .reference-tag {{ padding:4px 8px; border-radius:999px; background:#eef3f9; color:#51627a; font-size:12px; font-weight:650; }}
    .reference-tag.internal {{ background:#e7f8f0; color:#087f58; }}
    .reference-tag.internal a {{ overflow-wrap:anywhere; }}
    .reference-summary {{ margin:0; color:#30415d; line-height:1.65; }}
    .reference-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:13px; }}
    .reference-detail {{ padding:10px 11px; border-radius:8px; background:#f4f7fb; color:#40516d; font-size:13px; line-height:1.55; }}
    .reference-detail strong {{ display:block; margin-bottom:3px; color:#253754; font-size:12px; }}
    .reference-limit {{ margin:11px 0 0; color:#7a5a1d; font-size:12px; line-height:1.5; }}
    pre {{ max-height:480px; margin:0; overflow:auto; padding:16px; border:1px solid var(--border); border-radius:9px; background:#101a30; color:#dbeafe; font-family:Consolas,monospace; font-size:12px; line-height:1.65; white-space:pre-wrap; }}
    a {{ color:var(--primary); font-weight:650; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .back-link {{ display:inline-block; margin-bottom:16px; font-size:13px; }}
    @media (max-width:700px) {{ .topbar {{ align-items:flex-start; flex-direction:column; padding:14px 18px; }} .topbar nav {{ justify-content:flex-start; gap:3px; }} main {{ padding:20px 14px 32px; }} .summary,.common-query-grid,.reference-grid,.report-summary-grid {{ grid-template-columns:1fr; }} .common-query-card,.panel {{ padding:16px; }} .common-query-heading,.common-query-actions,.reference-section-head,.common-group-head {{ align-items:flex-start; flex-direction:column; }} .common-query-field.wide {{ grid-column:auto; }} .common-date-range {{ grid-template-columns:1fr; }} .table-wrap {{ overflow-x:auto; }} .reference-card-head {{ flex-direction:column; }} .reference-score {{ align-self:flex-start; }} .criteria-disclosure {{ width:100%; max-width:none; }} .criteria-content {{ width:100%; }} }}
  </style>
</head>
<body><header class="topbar"><div class="brand"><span class="brand-mark">◆</span>IPS Copilot · {html.escape(section)}</div><nav>{navigation}</nav></header><main>{body}</main></body>
</html>"""


def status_summary(items: list[dict[str, Any]]) -> str:
    counts = summarize_round(items)
    return f"完成 {counts['completed']}；阻塞 {counts['blocked']}；跳过 {counts['skipped']}；失败 {counts['failed']}"


def report_status_badge(value: Any) -> str:
    text = safe_text(value) or "未记录"
    slug = re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-") or "unknown"
    return f'<span class="status-badge status-{html.escape(slug)}">{html.escape(text)}</span>'


def report_source_label(ui_mode: str) -> str:
    return {"simple": "简洁模式", "detailed": "详细模式"}.get(ui_mode, "手动模式")


def render_report_center_summary(value: Any) -> str:
    summary = normalize_report_center_summary(value)
    list_items = lambda items: "".join(f"<li>{html.escape(item)}</li>" for item in items) or "<li>无</li>"
    return f"""<section class="report-summary-grid">
<article class="panel report-brief"><p class="report-section-label">DIAGNOSTIC BRIEF</p><h2>问题分析</h2><p>{html.escape(summary["problem_analysis"]) or "未记录"}</p><h3>详细诊断结果</h3><p>{html.escape(summary["diagnostic_results"]) or "未记录"}</p></article>
<div class="report-actions"><article class="report-action"><strong>下一步研究方向</strong><ul>{list_items(summary["next_steps"])}</ul></article>
<article class="report-action"><strong>客户待补充信息</strong><ul>{list_items(summary["customer_information_needed"])}</ul></article>
<article class="report-action"><strong>风险与限制</strong><p>{html.escape(summary["risks_and_limitations"]) or "未记录"}</p></article></div>
</section>"""


def _common_issue_link(url: Any, label: Any) -> str:
    safe_url = _valid_sighting_url(safe_text(url))
    text = html.escape(safe_text(label) or "—")
    return f'<a href="{html.escape(safe_url, quote=True)}" target="_blank" rel="noopener">{text}</a>' if safe_url else text


def common_issue_analysis_summary(report: dict[str, Any]) -> str:
    if safe_text(report.get("analysis_mode")) == "ai_enriched":
        return "analysis_mode: ai_enriched；AI enrichment passed strict JSON validation."
    enrichment = report.get("ai_enrichment", {})
    limitation = safe_text(enrichment.get("limitation")) if isinstance(enrichment, dict) else ""
    return f"analysis_mode: deterministic_fallback；{limitation or 'Deterministic grouping was used.'}"


def common_issue_feedback_label(report: dict[str, Any], grouping_key: Any) -> str:
    feedback = report.get("feedback", [])
    if not isinstance(feedback, list):
        return ""
    latest = next(
        (
            item for item in feedback
            if isinstance(item, dict) and safe_text(item.get("grouping_key")) == safe_text(grouping_key)
        ),
        None,
    )
    if not latest:
        return "尚未人工确认"
    labels = {"confirmed": "人工确认同类", "split": "人工要求拆分", "excluded": "人工排除"}
    label = labels.get(safe_text(latest.get("action")), "已记录人工反馈")
    note = safe_text(latest.get("note"))
    return f"{label}{'：' + note if note else ''}"


def render_common_issue_report_content(report: dict[str, Any]) -> str:
    groups = report.get("groups", [])
    if not isinstance(groups, list):
        groups = []
    sections: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        rows: list[str] = []
        for record in group.get("records", []):
            if not isinstance(record, dict):
                continue
            rows.append(
                "<tr>"
                f"<td>{_common_issue_link(record.get('hsd_url'), record.get('ips_id'))}</td>"
                f"<td>{html.escape(safe_text(record.get('title')) or '未获取')}</td>"
                f"<td>{html.escape(safe_text(record.get('customer')) or '未获取')}</td>"
                f"<td>{html.escape(safe_text(record.get('component')) or '未获取')}</td>"
                f"<td>{_common_issue_link(record.get('sighting_url'), record.get('sighting_url') or '—')}</td>"
                f"<td>{html.escape(safe_text(record.get('sighting_title')) or '未获取')}</td>"
                f"<td>{html.escape(safe_text(record.get('grouping_reason')) or '未记录')}</td></tr>"
            )
        sections.append(
            f"""<section class="panel"><div class="common-group-head"><div><p class="report-section-label">COMMON ISSUE GROUP</p><h2>{html.escape(safe_text(group.get('heading')) or '未命名分组')}</h2><p class="muted">归并问题：{len(rows)} 个 IPS · Debug：{int(group.get('debug_count', 0) or 0)} · Question：{int(group.get('question_count', 0) or 0)}</p></div><span class="evidence-chip">{html.escape(safe_text(group.get('evidence_tier')) or '候选证据')} · {int(group.get('confidence_score', 0) or 0)}/100</span></div>
<p class="group-explanation">{html.escape(safe_text(group.get('common_problem_explanation')) or '未记录')}</p>
<div class="review-strip"><span><strong>人工反馈：</strong>{html.escape(common_issue_feedback_label(report, group.get('grouping_key')))}</span><span>每条记录保留独立证据，不表示已确认共享根因。</span></div>
<details class="technical-disclosure"><summary>查看 {len(rows)} 条 IPS 记录详情</summary><div class="table-wrap"><table><thead><tr><th>IPS ID</th><th>Title</th><th>Customer</th><th>Component</th><th>SI/FW Sighting URL</th><th>Sighting Title</th><th>归并为一类的原因</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="7" class="muted">没有可显示的问题。</td></tr>'}</tbody></table></div></details></section>"""
        )
    if sections:
        return "".join(sections)
    filtered = int(report.get("filtered_single_issue_count", 0))
    return f'<section class="panel"><p class="muted">没有包含至少 2 条 IPS 的共性问题；已自动过滤 {filtered} 条单独问题。</p></section>'


def render_common_issue_page(cfg: dict[str, Any]) -> str:
    settings = common_issue_config(cfg)
    history = get_common_issue_store(cfg).list()
    history_rows = "".join(
        f'<tr><td>{format_task_time(record["created_at"])}</td><td>{html.escape(safe_text(record["status"]))}</td>'
        f'<td>{html.escape(safe_text(record["filters"].get("platform")) or "—")}</td>'
        f'<td>{html.escape(safe_text(record["filters"].get("customer")) or "—")}</td>'
        f'<td><a href="/common-issues/reports/{html.escape(record["id"])}">查看报告</a></td></tr>'
        for record in history
    ) or '<tr><td colspan="5" class="muted">尚无历史分析报告。</td></tr>'
    return report_layout(
        "共性问题 AI 分析",
        f"""<section class="hero"><p class="eyebrow">READ-ONLY COMMON ISSUE ANALYSIS</p><h1>共性问题 AI 分析</h1>
<p class="muted">仅检索和归并 HSD/IPS 记录；配置允许时，Copilot 只会在记录规范化后进行只读文本归并，绝不执行 SSH、烧录、供电、串口或任何硬件动作。</p></section>
<section class="common-query-card"><div class="common-query-heading"><div><h2>筛选范围</h2><p class="muted">按提交日期检索；平台、客户、组件或关键词至少填写一项。</p></div><span class="common-query-badge">只读分析 · 最长 {settings["maxDateRangeDays"]} 天</span></div>
<div class="common-query-grid">
<div class="common-query-field"><label for="commonPlatform">平台 <span>Platform</span></label><input id="commonPlatform" maxlength="160" placeholder="例如 BHS"></div>
<div class="common-query-field"><label for="commonCustomer">客户 <span>Customer；可多选</span></label><input id="commonCustomer" maxlength="160" placeholder="例如 MagInfra / Lenovo / H3C"></div>
<div class="common-query-field wide"><label>提交日期范围 <span>必填</span></label><div class="common-date-range"><input id="commonStart" type="date" required aria-label="提交开始日期"><input id="commonEnd" type="date" required aria-label="提交结束日期"></div></div>
<div class="common-query-field"><label for="commonComponent">组件 <span>可选</span></label><input id="commonComponent" maxlength="160" placeholder="例如 platform.bios"></div>
<div class="common-query-field"><label for="commonKeywords">关键词 <span>可选</span></label><input id="commonKeywords" maxlength="160" placeholder="例如 memory training"></div>
<div class="common-query-field"><label for="commonLimit">最大结果数</label><input id="commonLimit" type="number" min="1" max="{settings["maxResultLimit"]}" value="{settings["defaultResultLimit"]}"></div>
</div><div class="common-query-actions"><button class="primary" onclick="searchCommonIssues()">开始分析</button><span id="commonStatus" class="muted">结果会按共性问题分组，并保留证据说明。</span></div></section>
<div id="commonResult"></div>
<section class="panel"><h2>历史分析</h2><div class="table-wrap"><table><thead><tr><th>创建时间</th><th>状态</th><th>平台</th><th>客户</th><th>报告</th></tr></thead><tbody>{history_rows}</tbody></table></div></section>
<script>
function commonEscape(value) {{ const node = document.createElement("div"); node.textContent = value || ""; return node.innerHTML; }}
function commonLink(url, text) {{ try {{ const parsed = new URL(url); return (parsed.protocol === "http:" || parsed.protocol === "https:") ? `<a target="_blank" rel="noopener" href="${{commonEscape(url)}}">${{commonEscape(text || "—")}}</a>` : commonEscape(text || "—"); }} catch (_) {{ return commonEscape(text || "—"); }} }}
function commonRows(group) {{ return (group.records || []).map(record => `<tr><td>${{commonLink(record.hsd_url, record.ips_id)}}</td><td>${{commonEscape(record.title || "未获取")}}</td><td>${{commonEscape(record.customer || "未获取")}}</td><td>${{commonEscape(record.component || "未获取")}}</td><td>${{commonLink(record.sighting_url, record.sighting_url || "—")}}</td><td>${{commonEscape(record.sighting_title || "未获取")}}</td><td>${{commonEscape(record.grouping_reason || "未记录")}}</td></tr>`).join(""); }}
function commonAnalysisStatus(report) {{ if (report.analysis_mode === "ai_enriched") return "analysis_mode: ai_enriched；AI enrichment passed strict JSON validation."; const info = report.ai_enrichment || {{}}; return `analysis_mode: deterministic_fallback；${{info.limitation || "Deterministic grouping was used."}}`; }}
function commonFeedbackLabel(report, key) {{ const feedback = (report.feedback || []).find(item => item.grouping_key === key); if (!feedback) return "尚未人工确认"; const labels = {{confirmed:"人工确认同类",split:"人工要求拆分",excluded:"人工排除"}}; return labels[feedback.action] + (feedback.note ? "：" + feedback.note : ""); }}
function commonFeedbackButtons(report, group) {{ return `<div class="actions"><button onclick="saveCommonFeedback('${{commonEscape(report.id)}}','${{commonEscape(group.grouping_key)}}','confirmed')">确认同类</button><button onclick="saveCommonFeedback('${{commonEscape(report.id)}}','${{commonEscape(group.grouping_key)}}','split')">建议拆分</button><button onclick="saveCommonFeedback('${{commonEscape(report.id)}}','${{commonEscape(group.grouping_key)}}','excluded')">排除本组</button></div>`; }}
function commonGroupCard(report, group) {{ const count = (group.records || []).length; return `<section class="panel"><div class="common-group-head"><div><p class="report-section-label">COMMON ISSUE GROUP</p><h2>${{commonEscape(group.heading)}}</h2><p class="muted">归并问题：${{count}} 个 IPS · Debug：${{Number(group.debug_count || 0)}} · Question：${{Number(group.question_count || 0)}}</p></div><span class="evidence-chip">${{commonEscape(group.evidence_tier || "候选证据")}} · ${{Number(group.confidence_score || 0)}}/100</span></div><p class="group-explanation">${{commonEscape(group.common_problem_explanation || "未记录")}}</p><div class="review-strip"><span><strong>人工反馈：</strong>${{commonEscape(commonFeedbackLabel(report, group.grouping_key))}}</span><span>每条记录保留独立证据，不表示已确认共享根因。</span></div>${{commonFeedbackButtons(report, group)}}<details class="technical-disclosure"><summary>查看 ${{count}} 条 IPS 记录详情</summary><div class="table-wrap"><table><thead><tr><th>IPS ID</th><th>Title</th><th>Customer</th><th>Component</th><th>SI/FW Sighting URL</th><th>Sighting Title</th><th>归并为一类的原因</th></tr></thead><tbody>${{commonRows(group) || '<tr><td colspan="7">没有可显示的问题。</td></tr>'}}</tbody></table></div></details></section>`; }}
function commonResult(report) {{ const groups = (report.groups || []).map(group => commonGroupCard(report, group)).join("") || '<section class="panel">查询未返回可归并的问题。</section>'; return `<section class="panel"><p class="muted">${{commonEscape(commonAnalysisStatus(report))}}</p></section>${{groups}}`; }}
async function saveCommonFeedback(reportId, groupingKey, action) {{ const note = window.prompt("可选：补充确认、拆分或排除的原因（最多 1000 字符）", ""); if (note === null) return; const response = await fetch(`/api/common-issues/reports/${{reportId}}/feedback`, {{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{grouping_key:groupingKey,action,note}})}}); const body = await response.json(); if (!response.ok) {{ alert(body.error || "保存反馈失败"); return; }} document.getElementById("commonResult").innerHTML = commonResult(body); }}
async function searchCommonIssues() {{
  const status = document.getElementById("commonStatus"); status.textContent = "正在执行只读检索…";
  const payload = {{platform:commonPlatform.value, customer:commonCustomer.value, submitted_start_date:commonStart.value, submitted_end_date:commonEnd.value, component:commonComponent.value, keywords:commonKeywords.value, result_limit:commonLimit.value}};
  try {{ const response = await fetch("/api/common-issues/search", {{method:"POST", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(payload)}}); const body = await response.json(); if (!response.ok) throw new Error(body.error || "请求失败"); document.getElementById("commonResult").innerHTML = commonResult(body); status.innerHTML = `已生成 <a href="/common-issues/reports/${{body.id}}">可保存的分析报告</a>。`; }}
  catch (error) {{ status.textContent = "分析失败：" + error.message; }}
}}
</script>""",
        section="共性问题分析",
    )


def render_common_issue_report(report_id: str, cfg: dict[str, Any]) -> str:
    record = get_common_issue_store(cfg).load(report_id)
    report = record.get("report")
    if not isinstance(report, dict):
        raise FileNotFoundError("common issue report data is not available")
    return report_layout(
        "共性问题分析报告",
        f"""<a class="back-link" href="/common-issues">← 返回共性问题分析</a>
<section class="hero"><p class="eyebrow">COMMON ISSUE REPORT</p><h1>共性问题分析报告</h1>
<p class="muted">状态：{html.escape(safe_text(record.get("status")))}；创建时间：{format_task_time(record.get("created_at"))}；只读分析，无硬件动作。</p>
<p class="muted">{html.escape(common_issue_analysis_summary(report))}</p></section>
<section class="panel"><h2>检索条件</h2><pre>{html.escape(json.dumps(report.get("filters", {}), ensure_ascii=False, indent=2))}</pre>
<p class="muted">{html.escape(safe_text(report.get("field_mapping_caveat")))}</p></section>
{render_common_issue_report_content(report)}""",
        section="共性问题分析",
    )


def report_sort_timestamp(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(safe_text(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def render_report_index() -> str:
    auto_records = list_auto_rounds()
    manual_records = list_manual_reports()
    common_records = COMMON_ISSUE_STORE.list() if COMMON_ISSUE_STORE else []
    rows: list[tuple[float, str]] = []
    for record in manual_records:
        rows.append(
            (record["created_at"], "<tr>"
            f"<td>{report_source_label(record['ui_mode'])}</td><td>IPS {html.escape(record['ips_id']) or '未填写'}</td>"
            f"<td>{html.escape(record['task_type']) or '未选择'}</td>"
            f"<td>{format_task_time(record['created_at'])}</td><td>{format_task_time(record['completed_at'])}</td>"
            f"<td>{report_status_badge(record['status'])}</td><td>{recipient_email_links(record['recipient'])}</td>"
            f'<td><a href="/reports/manual/{html.escape(record["id"])}">查看详情</a></td></tr>')
        )
    for record in auto_records:
        query_id = html.escape(record["query_id"])
        task_id = html.escape(record["task_id"])
        round_number = record["round"]
        report_href = (
            f"/reports/task/{task_id}/{query_id}/{round_number}"
            if task_id
            else f"/reports/{query_id}/{round_number}"
        )
        top_ips_href = f"{report_href}/top-ips"
        rows.append(
            (report_sort_timestamp(record["started_at"]), "<tr>"
            f"<td>全自动化 Query 模式</td><td>Query {query_id}</td><td>第 {round_number} 轮</td>"
            f"<td>{format_task_time(record['started_at'])}</td><td>{format_task_time(record['completed_at'])}</td>"
            f"<td>{report_status_badge(record['status'])}</td><td>{record['query_ips_count']} 个 Query IPS / {record['item_count']} 个 Open 已处理</td>"
            f'<td><a href="{report_href}">执行报告</a> · <a href="{top_ips_href}">Top IPS</a></td></tr>')
        )
    for record in common_records:
        rows.append(
            (record["created_at"], "<tr>"
            f"<td>共性问题 AI 分析</td><td>{html.escape(safe_text(record['filters'].get('platform')) or '多条件检索')}</td><td>只读归并</td>"
            f"<td>{format_task_time(record['created_at'])}</td><td>{format_task_time(record['updated_at'])}</td>"
            f"<td>{report_status_badge(record['status'])}</td><td>—</td>"
            f'<td><a href="/common-issues/reports/{html.escape(record["id"])}">查看报告</a></td></tr>')
        )
    table = "".join(markup for _, markup in sorted(rows, key=lambda item: item[0], reverse=True)) or '<tr><td colspan="8" class="muted">尚无处理报告。</td></tr>'
    query_count = len({record["query_id"] for record in auto_records})
    completed_count = sum(record["status"] == "completed" for record in auto_records + manual_records)
    return report_layout(
        "报告中心",
        f"""<section class="hero"><p class="eyebrow">REPORT ARCHIVE</p><h1>报告中心</h1>
<p class="muted">简洁模式、详细模式和全自动 Query 的处理记录均会在本机保存，重启 UI 后仍可浏览。</p></section>
<section class="summary"><div class="metric"><span class="metric-label">处理记录</span><div class="metric-value">{len(auto_records) + len(manual_records)}</div></div>
<div class="metric"><span class="metric-label">关联 Query</span><div class="metric-value">{query_count}</div></div>
<div class="metric"><span class="metric-label">完成轮次</span><div class="metric-value">{completed_count + sum(record["status"] == "completed" for record in common_records)}</div></div></section>
<section class="panel"><h2>处理历史</h2><div class="table-wrap"><table><thead><tr><th>来源</th><th>任务 / IPS</th><th>类型 / 轮次</th><th>开始时间</th><th>完成时间</th><th>状态</th><th>收件人 / IPS 数</th><th>报告</th></tr></thead>
<tbody>{table}</tbody></table></div></section>""",
    )


def render_manual_report(job_id: str) -> str:
    record = load_manual_report(job_id)
    summary = normalize_report_center_summary(record.get("report_center_summary"))
    artifact_error = safe_text(record.get("report_artifact_error")) or manual_report_artifact_error(record)
    resource_request_path = summary["resource_request_path"]
    resource_request_link = (
        f'<section class="panel"><h2>资源/物品清单协调草稿</h2><p><a href="/reports/manual/{html.escape(job_id)}/resource-request">打开 AI 生成的资源协调草稿</a></p></section>'
        if resource_request_path else ""
    )
    return report_layout(
        f"手动任务 {job_id[:8]} 报告",
        f"""<a class="back-link" href="/reports">← 返回报告中心</a>
<section class="hero"><p class="eyebrow">MANUAL EXECUTION REPORT</p><h1>手动任务处理报告</h1>
<p class="muted">简洁模式或详细模式的执行记录。</p></section>
<section class="panel"><h2>任务摘要</h2><div class="table-wrap"><table><tbody>
<tr><th>IPS/HSD ID</th><td>{html.escape(safe_text(record.get('ips_id')) or '未填写')}</td></tr>
<tr><th>任务类型</th><td>{html.escape(safe_text(record.get('task_type')) or '未选择')}</td></tr>
<tr><th>执行模式</th><td>{html.escape(safe_text(record.get('ui_mode')) or '未记录')}</td></tr>
<tr><th>发送用户</th><td>{recipient_email_links(record.get('recipient'))}</td></tr>
<tr><th>执行状态</th><td>{report_status_badge(record.get('status'))}</td></tr>
<tr><th>开始时间</th><td>{format_task_time(record.get('created_at'))}</td></tr>
<tr><th>完成时间</th><td>{format_task_time(record.get('completed_at'))}</td></tr>
</tbody></table></div></section>
{f'<section class="notice warning"><strong>报告产物未完成：</strong>{html.escape(artifact_error)} 请重新执行任务，确保阶段二写入报告中心摘要与资源/物品清单草稿。</section>' if artifact_error else ''}
{render_report_center_summary(record.get('report_center_summary'))}
{resource_request_link}
<details class="technical-disclosure"><summary>查看最终执行计划</summary><pre>{html.escape(safe_text(record.get('plan_text')))}</pre></details>
<details class="technical-disclosure"><summary>查看完整执行输出</summary><pre>{html.escape(safe_text(record.get('output')) or '任务仍在运行，暂未产生输出。')}</pre></details>""",
    )


def render_manager_draft(content: str) -> str:
    """Render the constrained manager draft without exposing raw Markdown syntax."""
    lines = content.splitlines()
    parts: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("# "):
            parts.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            parts.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("|") and "|" in line[1:]:
            table_lines: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                    table_lines.append(cells)
                index += 1
            if table_lines:
                header, *rows = table_lines
                parts.append(
                    '<div class="table-wrap"><table><thead><tr>'
                    + "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
                    + "</tr></thead><tbody>"
                    + "".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in rows)
                    + "</tbody></table></div>"
                )
            continue
        elif re.match(r"^[-*]\s+", line):
            items: list[str] = []
            while index < len(lines) and re.match(r"^[-*]\s+", lines[index].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[index].strip()))
                index += 1
            parts.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>")
            continue
        else:
            parts.append(f"<p>{html.escape(line)}</p>")
        index += 1
    return "".join(parts)


def render_resource_request_review(job_id: str) -> str:
    record = load_manual_report(job_id)
    draft_path = resource_request_draft_path(record)
    draft = draft_path.read_text(encoding="utf-8-sig")
    escaped_job_id = html.escape(job_id)
    saved_details = record.get("resource_request_details", {})
    saved_details = saved_details if isinstance(saved_details, dict) else {}
    details_saved = bool(record.get("resource_request_details_saved"))
    def input_value(field: str) -> str:
        return html.escape(safe_text(saved_details.get(field)), quote=True)
    return report_layout(
        f"IPS {safe_text(record.get('ips_id'))} 物品清单申请",
        f"""<a class="back-link" href="/reports/manual/{escaped_job_id}">← 返回手动报告</a>
<style>
.request-hero {{ padding-bottom:22px; }}
.request-steps {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:18px; }}
.request-step {{ padding:7px 11px; border:1px solid #ccdaec; border-radius:999px; background:#fff; color:#52647d; font-size:12px; font-weight:700; }}
.request-step.active {{ border-color:#8bb5f3; background:#eaf3ff; color:#1e5db7; }}
.request-workspace {{ display:grid; grid-template-columns:minmax(0,1.55fr) minmax(300px,.75fr); gap:18px; align-items:start; }}
.request-preview {{ min-width:0; }}
.request-preview-head {{ display:flex; justify-content:space-between; gap:16px; align-items:center; margin-bottom:18px; }}
.request-preview-head h2,.request-form h2 {{ margin:0; }}
.request-badge {{ padding:6px 9px; border-radius:8px; background:#edf4ff; color:#1e5db7; font-size:11px; font-weight:800; }}
.manager-draft h1 {{ margin:0 0 18px; font-size:22px; }} .manager-draft h2 {{ margin:24px 0 10px; padding-left:10px; border-left:3px solid #2563eb; font-size:16px; }}
.manager-draft p,.manager-draft li {{ color:#40516d; line-height:1.65; }} .manager-draft ul {{ padding-left:20px; }}
.request-form {{ position:sticky; top:18px; }}
.request-form-intro {{ margin:8px 0 18px; }}
.field-group {{ margin-bottom:15px; }}
.field-group label {{ display:block; margin-bottom:6px; color:#263a57; font-size:12px; font-weight:800; }}
.field-group input,.field-group textarea {{ width:100%; box-sizing:border-box; }}
.field-group textarea {{ min-height:84px; resize:vertical; }}
.request-actions {{ display:grid; gap:9px; margin-top:20px; }}
.request-actions button {{ width:100%; justify-content:center; }}
.request-status {{ min-height:20px; margin:12px 0 0; }}
@media (max-width:850px) {{ .request-workspace {{ grid-template-columns:1fr; }} .request-form {{ position:static; }} }}
</style>
<section class="hero request-hero"><p class="eyebrow">RESOURCE COORDINATION</p><h1>资源协调申请</h1><p class="muted">IPS/HSD {html.escape(safe_text(record.get('ips_id')) or '未记录')} · 仅保留管理者做决定所需的资源、时间和排期信息。</p>
<div class="request-steps"><span class="request-step active">1&nbsp; 审核摘要</span><span class="request-step {'active' if details_saved else ''}">2&nbsp; 补充安排</span><span class="request-step">3&nbsp; 确认发送</span></div></section>
<div class="request-workspace">
<section class="panel request-preview"><div class="request-preview-head"><h2>发送内容预览</h2><span class="request-badge">简洁管理版</span></div><div class="manager-draft">{render_manager_draft(draft)}</div></section>
<aside class="panel request-form"><h2>补充并发送</h2><p class="muted request-form-intro">填写管理者需要确认的信息，保存后再发送。</p>
<div class="field-group"><label for="expectedDdl">期望完成时间</label><input id="expectedDdl" type="date" value="{input_value('expected_ddl')}"></div>
<div class="field-group"><label for="resourceToReserve">需要协调的资源</label><textarea id="resourceToReserve" placeholder="例如：BHS 验证服务器 1 台及串口调试资源">{html.escape(safe_text(saved_details.get('resource_to_reserve')))}</textarea></div>
<div class="field-group"><label for="reservationDuration">预计占用时长</label><input id="reservationDuration" value="{input_value('reservation_duration')}" placeholder="例如：2 个工作日"></div>
<div class="field-group"><label for="managerRecipient">收件人</label><input id="managerRecipient" value="{html.escape(safe_text(record.get('resource_request_recipient')), quote=True)}" placeholder="邮箱或 Outlook 名称"></div>
<div class="request-actions"><button class="secondary" id="saveButton" type="button" onclick="saveDetails()">保存并更新预览</button><button class="primary" id="sendButton" type="button" onclick="sendRequest()" {'disabled' if not details_saved else ''}>确认发送</button></div><p id="status" class="small request-status" role="status" aria-live="polite"></p></aside>
</div>
<script>
const jobId = {json.dumps(job_id)};
async function request(path, body) {{ const response = await fetch(path, {{method:"POST", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(body)}}); const text = await response.text(); if (!response.ok) throw new Error(text); return JSON.parse(text); }}
function reviewElements() {{ return {{saveButton: document.getElementById("saveButton"), sendButton: document.getElementById("sendButton"), status: document.getElementById("status"), expectedDdl: document.getElementById("expectedDdl"), resourceToReserve: document.getElementById("resourceToReserve"), reservationDuration: document.getElementById("reservationDuration"), managerRecipient: document.getElementById("managerRecipient")}}; }}
async function saveDetails() {{ const elements = reviewElements(); elements.saveButton.disabled=true; elements.status.textContent="正在保存申请信息…"; try {{ await request(`/api/reports/manual/${{encodeURIComponent(jobId)}}/resource-request/details`, {{expected_ddl:elements.expectedDdl.value, resource_to_reserve:elements.resourceToReserve.value, reservation_duration:elements.reservationDuration.value, manager_recipient:elements.managerRecipient.value}}); elements.status.textContent="已保存，正在更新发送预览…"; window.setTimeout(() => window.location.reload(), 350); }} catch (error) {{ elements.saveButton.disabled=false; elements.status.textContent=`保存失败：${{error.message}}`; }} }}
async function sendRequest() {{ if (!confirm("确认发送这份简洁版资源协调申请吗？")) return; const elements = reviewElements(); elements.sendButton.disabled=true; elements.status.textContent="正在发送资源协调申请…"; try {{ await request(`/api/reports/manual/${{encodeURIComponent(jobId)}}/resource-request/send`, {{}}); elements.status.textContent="资源协调申请已发送。"; }} catch (error) {{ elements.sendButton.disabled=false; elements.status.textContent=`发送失败：${{error.message}}`; }} }}
</script>""",
        section="资源/物品清单申请",
    )


def _reference_display_status(value: Any) -> str:
    status = safe_text(value).casefold()
    if status == "open":
        return "OPEN"
    if status in {"closed", "complete", "completed", "resolved", "implemented", "verified"}:
        return "COMPLETED"
    return (safe_text(value) or "UNKNOWN").upper()


def _reference_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(safe_text(value)[:10])
    except ValueError:
        return None


def render_auto_common_issue_analysis(value: Any) -> str:
    analysis = value if isinstance(value, dict) else {}
    top_references = analysis.get("recommendations", [])
    if not isinstance(top_references, list):
        top_references = []
    candidate_assessments = analysis.get("candidate_assessments", [])
    candidate_assessments = candidate_assessments if isinstance(candidate_assessments, list) else []

    def reference_cards(items: list[dict[str, Any]]) -> str:
        cards: list[str] = []
        for rank, assessment in enumerate(items, start=1):
            record = assessment.get("record", {})
            record = record if isinstance(record, dict) else {}
            status = _reference_display_status(record.get("query_status"))
            score = max(0, min(100, int(assessment.get("reference_score", 0) or 0)))
            internal_tags = []
            if safe_text(record.get("sighting_url")):
                sighting_url = safe_text(record.get("sighting_url"))
                internal_tags.append(
                    f'<span class="reference-tag internal">Internal link · '
                    f'{_common_issue_link(sighting_url, sighting_url)}</span>'
                )
            if safe_text(record.get("close_reason")):
                internal_tags.append(
                    f'<span class="reference-tag internal">{html.escape(safe_text(record.get("close_reason")))}</span>'
                )
            cards.append(
                f"""<article class="reference-card{' featured-reference' if rank == 1 else ''}">
<div class="reference-card-head"><div><h3 class="reference-title"><span class="reference-rank">#{rank}</span>{_common_issue_link(record.get("hsd_url"), assessment.get("ips_id"))} · {html.escape(safe_text(record.get("title")) or "Title unavailable")}</h3>
<div class="reference-meta">{report_status_badge(status)}{''.join(internal_tags)}</div></div>
<div class="reference-score"><strong>{score}</strong><span>OF 100</span><i class="score-meter" style="--score:{score}%"></i></div></div>
<p class="reference-summary">{html.escape(safe_text(assessment.get("summary")) or "Summary unavailable")}</p>
<div class="reference-grid"><div class="reference-detail"><strong>Reference value</strong>{html.escape(safe_text(assessment.get("reuse_reason")) or "Not recorded")}</div>
<div class="reference-detail"><strong>Applicability</strong>{html.escape(safe_text(assessment.get("applicability")) or "Not recorded")}</div></div>
</article>"""
            )
        return "".join(cards)

    def is_matrix_candidate(assessment: Any) -> bool:
        if not isinstance(assessment, dict):
            return False
        record = assessment.get("record", {})
        record = record if isinstance(record, dict) else {}
        status = safe_text(record.get("query_status")).casefold()
        return bool(status)

    def smallest_next_check(assessment: dict[str, Any], record: dict[str, Any]) -> str:
        match = re.search(r"^Repro/debug:\s*(.+)$", safe_text(record.get("analysis_text")), re.MULTILINE)
        if match:
            return match.group(1)
        return safe_text(assessment.get("reuse_reason")) or "No next check recorded"

    matrix_assessments = sorted(
        (assessment for assessment in candidate_assessments if is_matrix_candidate(assessment)),
        key=reference_assessment_sort_key,
    )
    domains = sorted({
        safe_text((assessment.get("record") or {}).get("component")) or "Unspecified"
        for assessment in matrix_assessments if isinstance(assessment, dict)
    }, key=str.casefold)

    def table_rows(items: list[dict[str, Any]]) -> str:
        rows: list[str] = []
        for assessment in items:
            record = assessment.get("record", {})
            record = record if isinstance(record, dict) else {}
            status = safe_text(record.get("query_status")).casefold()
            display_status = _reference_display_status(status)
            created = safe_text(record.get("submitted_date")) or "—"
            closed = safe_text(record.get("closed_date")) or "—"
            aging = f"{max(0, (date.today() - created_date).days)}d" if (
                status == "open" and (created_date := _reference_date(record.get("submitted_date")))
            ) else "—"
            domain = safe_text(record.get("component")) or "Unspecified"
            owner = safe_text(record.get("owner")) or "Unassigned"
            customer = safe_text(record.get("customer")) or "Unspecified"
            record_date = created if status == "open" else closed
            searchable = " ".join((
                safe_text(assessment.get("ips_id")), safe_text(record.get("title")),
                safe_text(assessment.get("summary")), domain, owner, customer,
            ))
            score = int(assessment.get("reference_score", 0) or 0)
            sighting_url = safe_text(record.get("sighting_url"))
            rows.append(
                f'<tr data-domain="{html.escape(domain, quote=True)}" data-status="{display_status.lower()}" data-date="{html.escape(record_date, quote=True)}" '
                f'data-search="{html.escape(searchable, quote=True)}"><td class="score-cell">{score}</td>'
                f'<td class="hsd-cell">{_common_issue_link(record.get("hsd_url"), assessment.get("ips_id"))}</td>'
                f'<td><span class="matrix-status {display_status.lower()}">{display_status}</span></td>'
                f'<td>{aging}</td><td>{html.escape(created)}</td><td>{html.escape(closed)}</td>'
                f'<td>{html.escape(owner)}</td><td>{html.escape(customer)}</td><td>{html.escape(domain)}</td><td class="finding-cell">{html.escape(safe_text(assessment.get("summary")) or "Summary unavailable")}</td>'
                f'<td class="next-check-cell">{html.escape(smallest_next_check(assessment, record))}</td>'
                f'<td class="link-cell">{_common_issue_link(sighting_url, sighting_url)}</td></tr>'
            )
        return "".join(rows)
    top_cards = reference_cards([item for item in top_references if isinstance(item, dict)])
    matrix_rows = table_rows(matrix_assessments)
    open_count = sum(
        1 for assessment in matrix_assessments
        if safe_text((assessment.get("record") or {}).get("query_status")).casefold() == "open"
    )
    completed_count = len(matrix_assessments) - open_count
    top_score = max(
        (int(assessment.get("reference_score", 0) or 0) for assessment in top_references if isinstance(assessment, dict)),
        default=0,
    )
    domain_options = "".join(
        f'<option value="{html.escape(domain, quote=True)}">{html.escape(domain)}</option>' for domain in domains
    )
    top_empty = '<p class="empty-state">No ranked IPS references are available for this round.</p>' if not top_cards else ""
    matrix_empty = '<tr class="empty-row"><td colspan="12">No IPS records are available for this Query round.</td></tr>' if not matrix_rows else ""
    return f"""<style>
.top-ips-hero {{ position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:28px; align-items:end; overflow:hidden; border:1px solid rgba(147,197,253,.32); border-radius:18px; background:radial-gradient(circle at 87% 10%,rgba(88,224,199,.32),transparent 24%),linear-gradient(125deg,#102a62 0%,#18478d 54%,#176877 100%); box-shadow:0 16px 34px rgba(18,53,110,.15); }}
.top-ips-hero::after {{ content:""; position:absolute; right:-50px; bottom:-80px; width:260px; height:260px; border:1px solid rgba(187,239,255,.2); border-radius:50%; box-shadow:0 0 0 22px rgba(187,239,255,.06),0 0 0 45px rgba(187,239,255,.035); pointer-events:none; }}
.report-kicker {{ margin:0 0 9px; color:#b9d6ff; font-size:11px; font-weight:800; letter-spacing:1.35px; }}
.top-ips-hero h1 {{ max-width:760px; font-size:32px; line-height:1.16; letter-spacing:-.65px; }}
.report-note {{ max-width:720px; margin:12px 0 0; color:#d9e9ff; font-size:14px; line-height:1.65; }}
.signal-ledger {{ position:relative; z-index:1; display:grid; grid-template-columns:repeat(3,minmax(76px,1fr)); min-width:300px; border:1px solid rgba(255,255,255,.25); border-radius:12px; background:rgba(5,25,68,.28); box-shadow:inset 0 1px 0 rgba(255,255,255,.1); }}
.signal-ledger div {{ padding:14px 13px; }} .signal-ledger div + div {{ border-left:1px solid rgba(255,255,255,.17); }} .signal-ledger strong,.signal-ledger span {{ display:block; }} .signal-ledger strong {{ font-size:22px; line-height:1; letter-spacing:-.4px; }} .signal-ledger span {{ margin-top:5px; color:#cceaff; font-size:10px; font-weight:700; line-height:1.25; text-transform:uppercase; letter-spacing:.35px; }}
.top-reference-panel {{ padding:25px; border-color:#cbdcf3; background:linear-gradient(150deg,#fff 0%,#f7faff 100%); box-shadow:0 10px 24px rgba(25,66,126,.06); }}
.top-report-tabs {{ display:flex; gap:7px; margin:18px 0; padding:5px; border:1px solid #cbdcf3; border-radius:11px; background:#edf4fc; }}
.top-report-tab {{ flex:1; min-height:42px; padding:9px 14px; border:1px solid transparent; border-radius:7px; background:transparent; color:#4b6382; font:inherit; font-size:13px; font-weight:750; cursor:pointer; }}
.top-report-tab:hover {{ background:rgba(255,255,255,.62); color:#234d85; }} .top-report-tab[aria-selected="true"] {{ border-color:#cbdcf3; background:#fff; color:#123e82; box-shadow:0 2px 6px rgba(24,63,117,.08); }}
.top-report-view[hidden] {{ display:none; }}
.section-kicker {{ margin:0 0 6px; color:#4d78af; font-size:10px; font-weight:800; letter-spacing:.8px; text-transform:uppercase; }} .top-reference-panel .reference-section-head {{ margin-bottom:20px; }} .top-reference-panel .reference-section-head h2 {{ font-size:20px; letter-spacing:-.2px; }}
.top-reference-panel .criteria-disclosure {{ min-width:150px; border-color:#cbdcf3; background:#fff; }} .top-reference-panel .criteria-content p {{ margin:6px 0; }} .top-reference-panel .criteria-content strong {{ color:#183d75; }}
.top-reference-panel .reference-list {{ gap:12px; }} .top-reference-panel .reference-card {{ padding:19px 20px; border-color:#d6e3f2; border-radius:12px; background:#fff; box-shadow:0 2px 8px rgba(24,63,117,.035); transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease; }}
.top-reference-panel .featured-reference {{ position:relative; border-color:#9dc9e9; background:linear-gradient(105deg,#f1f9ff 0%,#fff 42%); }} .top-reference-panel .featured-reference::before {{ content:"TOP SIGNAL"; position:absolute; top:-1px; left:18px; padding:4px 8px; border-radius:0 0 6px 6px; background:#176877; color:#e5fffb; font-size:9px; font-weight:800; letter-spacing:.7px; }} .top-reference-panel .featured-reference .reference-card-head {{ padding-top:8px; }}
.top-reference-panel .reference-card:hover {{ border-color:#9fc0ed; box-shadow:0 10px 22px rgba(22,72,142,.09); transform:translateY(-1px); }} .top-reference-panel .reference-title {{ color:#112f61; font-size:16px; }}
.top-reference-panel .reference-title a {{ color:#113b7a; }} .top-reference-panel .reference-rank {{ background:#e8f1ff; color:#1757ad; }}
.top-reference-panel .reference-score {{ min-width:76px; padding:9px 10px 8px; border-radius:10px; background:linear-gradient(145deg,#143d80,#1d5db7); box-shadow:0 5px 11px rgba(24,72,147,.18); }} .top-reference-panel .score-meter {{ display:block; height:3px; margin-top:7px; border-radius:999px; background:linear-gradient(90deg,#6ee7d5 var(--score),rgba(255,255,255,.24) var(--score)); }}
.top-reference-panel .reference-summary {{ margin-top:3px; color:#314867; font-size:14px; line-height:1.7; }} .top-reference-panel .reference-detail {{ padding:11px 12px; border:1px solid #edf2f8; background:#f7faff; }}
.top-reference-panel .reference-tag {{ border:1px solid transparent; }} .top-reference-panel .reference-tag.internal {{ border-color:#d1f0df; }}
.matrix-panel {{ padding:0; overflow:hidden; border-color:#d5e2f1; box-shadow:0 10px 24px rgba(25,66,126,.055); }} .matrix-header {{ display:flex; justify-content:space-between; gap:24px; padding:24px 25px 18px; border-bottom:1px solid var(--border); background:linear-gradient(110deg,#fff,#fbfdff); }}
.matrix-header h2 {{ margin:0; font-size:20px; letter-spacing:-.2px; }} .matrix-header p {{ margin:6px 0 0; }} .matrix-summary {{ display:flex; flex-wrap:wrap; justify-content:flex-end; align-content:center; gap:7px; }} .matrix-summary > span,.matrix-count {{ align-self:center; padding:6px 10px; border:1px solid #d7e3f2; border-radius:999px; background:#f5f9fd; color:#526c8c; font-size:12px; font-weight:700; white-space:nowrap; }} .matrix-summary > span:first-child {{ border-color:#bfe7d5; background:#effaf5; color:#087f58; }}
.matrix-controls {{ display:grid; grid-template-columns:minmax(0,.72fr) minmax(0,.72fr) minmax(0,.72fr) minmax(0,1.45fr) auto; gap:12px; padding:17px 25px; background:#f7faff; border-bottom:1px solid var(--border); }}
.matrix-field {{ display:grid; min-width:0; gap:6px; }} .matrix-field label {{ color:#4b6382; font-size:10px; font-weight:800; letter-spacing:.55px; text-transform:uppercase; }}
.matrix-field select,.matrix-field input,.matrix-reset {{ min-width:0; min-height:41px; padding:9px 11px; border:1px solid #c7d8ec; border-radius:8px; background:#fff; color:var(--text); font:inherit; box-shadow:0 1px 2px rgba(19,58,110,.025); }}
.matrix-field select,.matrix-field input {{ width:100%; }}
.matrix-field select:focus,.matrix-field input:focus,.matrix-reset:focus {{ outline:3px solid rgba(37,99,235,.18); outline-offset:1px; border-color:#4380df; }} .matrix-field input::placeholder {{ color:#8da0b9; }}
.matrix-reset {{ align-self:end; padding-inline:15px; color:#31506f; cursor:pointer; font-weight:750; }} .matrix-reset:hover {{ border-color:#9bbbe4; background:#edf5ff; }} .matrix-table-wrap {{ overflow-x:auto; }}
.matrix-table {{ table-layout:fixed; border:0; border-radius:0; }} .matrix-table th {{ padding:13px 9px; background:#eaf2f8; color:#345576; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.35px; }}
.matrix-table td {{ min-width:0; padding:12px 9px; color:#263750; font-size:12px; overflow-wrap:anywhere; word-break:break-word; }} .matrix-table tbody tr:nth-child(even) {{ background:#fbfdff; }} .matrix-table tbody tr:hover {{ background:#eef6ff; }}
.matrix-table tr[hidden] {{ display:none; }} .score-cell {{ color:#123e82; font-weight:800; white-space:nowrap; }} .score-cell .reference-rank {{ margin-right:7px; }}
.hsd-cell a {{ display:block; color:#1859a6; overflow-wrap:anywhere; }} .finding-cell,.next-check-cell {{ overflow-wrap:anywhere; line-height:1.5; }} .link-cell {{ overflow-wrap:anywhere; }}
.matrix-status {{ display:inline-flex; padding:4px 8px; border:1px solid currentColor; border-radius:4px; font-size:10px; font-weight:800; letter-spacing:.35px; white-space:nowrap; word-break:normal; }} .matrix-status.open {{ color:#087f58; background:#effaf5; }} .matrix-status.completed {{ color:#315f9d; background:#eef5ff; }}
.empty-state {{ margin:0; padding:20px 25px; color:var(--muted); }} .empty-row td {{ padding:28px; color:var(--muted); text-align:center; }}
@media (prefers-reduced-motion:reduce) {{ .top-reference-panel .reference-card {{ transition:none; }} .top-reference-panel .reference-card:hover {{ transform:none; }} }}
@media (max-width:850px) {{ .top-ips-hero {{ grid-template-columns:1fr; }} .signal-ledger {{ width:max-content; }} .matrix-controls {{ grid-template-columns:1fr 1fr; }} }}
@media (max-width:560px) {{ .top-ips-hero h1 {{ font-size:26px; }} .signal-ledger {{ width:100%; min-width:0; }} .signal-ledger div {{ padding:13px 10px; }} .top-report-tabs {{ flex-direction:column; }} .matrix-header {{ display:block; }} .matrix-summary {{ justify-content:flex-start; margin-top:10px; }} .matrix-controls {{ grid-template-columns:1fr; }} .top-reference-panel {{ padding:18px; }} .top-reference-panel .reference-card {{ padding:16px; }} }}
</style>
<section class="hero top-ips-hero"><div><p class="report-kicker">TOP IPS REFERENCE REPORT</p><h1>Ranked IPS references for Query {html.escape(safe_text(analysis.get("query_id")))}</h1>
<p class="report-note">A focused view of the highest-ranked references, followed by all analyzed IPS records from this query.</p></div>
<div class="signal-ledger" aria-label="Report scope"><div><strong>{len(top_references)}</strong><span>ranked references</span></div><div><strong>{open_count}</strong><span>open signals</span></div><div><strong>{top_score}</strong><span>top score</span></div></div></section>
<div class="top-report-tabs" role="tablist" aria-label="Top IPS report view">
<button class="top-report-tab" id="topReferencesTab" type="button" role="tab" aria-selected="true" aria-controls="topReferencesView">Top IPS references</button>
<button class="top-report-tab" id="matrixTab" type="button" role="tab" aria-selected="false" aria-controls="matrixView">Detailed IPS matrix</button></div>
<section class="panel top-reference-panel top-report-view" id="topReferencesView" role="tabpanel" aria-labelledby="topReferencesTab"><div class="reference-section-head"><div><p class="section-kicker">REFERENCE QUEUE</p><h2>Top {int(analysis.get("reference_top_count", 20))} IPS</h2><p class="muted">Ranked results from the existing evaluation. Scoring and eligibility rules are unchanged.</p></div><details class="criteria-disclosure"><summary>Ranking rules</summary><div class="criteria-content"><strong>Independent record review</strong><p>Each IPS is evaluated on its own evidence; a shared root cause is not inferred from this list.</p><ul><li>Problem pattern and reusable handling</li><li>Verified internal evidence and resolution maturity</li><li>Applicability across platform, release, and component</li></ul></div></details></div>
{top_empty}<div class="reference-list">{top_cards}</div></section>
<section class="panel matrix-panel top-report-view" id="matrixView" role="tabpanel" aria-labelledby="matrixTab" hidden><div class="matrix-header"><div><p class="section-kicker">TRIAGE LEDGER</p><h2>Detailed IPS Matrix</h2><p class="muted">All analyzed IPS records. The Completed filter includes closed, complete, completed, resolved, implemented, and verified records.</p></div><div class="matrix-summary"><span>{open_count} Open</span><span>{completed_count} completed</span><output id="matrixCount" class="matrix-count" aria-live="polite"></output></div></div>
<div class="matrix-controls"><div class="matrix-field"><label for="dateFilter">Date range</label><select id="dateFilter"><option value="">All dates</option><option value="7">Last 7 days</option><option value="14">Last 14 days</option><option value="30">Last 30 days</option><option value="60">Last 2 months</option></select></div>
<div class="matrix-field"><label for="domainFilter">Cluster</label><select id="domainFilter"><option value="">All clusters</option>{domain_options}</select></div>
<div class="matrix-field"><label for="statusFilter">Status</label><select id="statusFilter"><option value="">All statuses</option><option value="open">Open</option><option value="completed">Completed</option></select></div>
<div class="matrix-field"><label for="matrixSearch">Search</label><input id="matrixSearch" type="search" placeholder="HSD, finding, or cluster"></div><button type="button" class="matrix-reset" id="matrixReset">Reset</button></div>
<div class="matrix-table-wrap"><table class="matrix-table"><colgroup><col style="width:5%"><col style="width:8%"><col style="width:8%"><col style="width:5%"><col style="width:8%"><col style="width:8%"><col style="width:8%"><col style="width:9%"><col style="width:8%"><col style="width:14%"><col style="width:12%"><col style="width:9%"></colgroup><thead><tr><th>Score</th><th>HSD</th><th>Status</th><th>Aging</th><th>Created</th><th>End</th><th>Owner</th><th>Customer company</th><th>Cluster</th><th>Reusable finding</th><th>Smallest next check</th><th>Internal link</th></tr></thead><tbody id="matrixRows">{matrix_rows}{matrix_empty}</tbody></table></div></section>
<script>
const dateFilter = document.getElementById("dateFilter");
const domainFilter = document.getElementById("domainFilter");
const statusFilter = document.getElementById("statusFilter");
const matrixSearch = document.getElementById("matrixSearch");
const matrixCount = document.getElementById("matrixCount");
const matrixRows = [...document.querySelectorAll("#matrixRows tr:not(.empty-row)")];
const topReferencesTab = document.getElementById("topReferencesTab");
const matrixTab = document.getElementById("matrixTab");
const topReferencesView = document.getElementById("topReferencesView");
const matrixView = document.getElementById("matrixView");
function showTopReportView(view) {{ const isMatrix = view === "matrix"; topReferencesView.hidden = isMatrix; matrixView.hidden = !isMatrix; topReferencesTab.setAttribute("aria-selected", String(!isMatrix)); matrixTab.setAttribute("aria-selected", String(isMatrix)); (isMatrix ? matrixTab : topReferencesTab).focus(); }}
topReferencesTab.addEventListener("click", () => showTopReportView("references"));
matrixTab.addEventListener("click", () => showTopReportView("matrix"));
function filterMatrix() {{ const days = Number(dateFilter.value); const cutoff = days ? new Date(Date.now() - days * 86400000) : null; const domain = domainFilter.value; const status = statusFilter.value; const search = matrixSearch.value.trim().toLowerCase(); let visible = 0; matrixRows.forEach(row => {{ const recordDate = row.dataset.date ? new Date(`${{row.dataset.date}}T00:00:00`) : null; const dateMatch = !cutoff || (recordDate && !Number.isNaN(recordDate.valueOf()) && recordDate >= cutoff); const match = dateMatch && (!domain || row.dataset.domain === domain) && (!status || row.dataset.status === status) && (!search || row.dataset.search.toLowerCase().includes(search)); row.hidden = !match; if (match) visible += 1; }}); matrixCount.textContent = `${{visible}} record${{visible === 1 ? "" : "s"}}`; }}
[dateFilter, domainFilter, statusFilter, matrixSearch].forEach(control => {{ control.addEventListener("input", filterMatrix); control.addEventListener("change", filterMatrix); }});
document.getElementById("matrixReset").addEventListener("click", () => {{ dateFilter.value = ""; domainFilter.value = ""; statusFilter.value = ""; matrixSearch.value = ""; filterMatrix(); }});
filterMatrix();
</script>"""


def render_top_ips_report(query_id: str, round_number: int, task_id: str = "") -> str:
    record = load_auto_round(query_id, round_number, task_id)
    round_href = (
        f"/reports/task/{html.escape(task_id)}/{html.escape(query_id)}/{round_number}"
        if task_id
        else f"/reports/{html.escape(query_id)}/{round_number}"
    )
    analysis = record.get("common_issue_analysis", {})
    analysis = analysis if isinstance(analysis, dict) else {}
    analysis = dict(analysis)
    analysis["query_id"] = query_id
    return report_layout(
        f"Query {query_id} Top IPS Reference Report",
        f"""<a class="back-link" href="{round_href}">← Back to query report</a>
{render_auto_common_issue_analysis(analysis)}""",
        section="Top IPS Report",
        language="en",
    )


def render_round_report(query_id: str, round_number: int, task_id: str = "") -> str:
    record = load_auto_round(query_id, round_number, task_id)
    items = record.get("items", [])
    if not isinstance(items, list):
        raise ValueError("round items must be a list")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ips_id = html.escape(safe_text(item.get("ips_id")))
        detail_href = (
            f"/reports/task/{html.escape(task_id)}/{html.escape(query_id)}/{round_number}/{ips_id}"
            if task_id
            else f"/reports/{html.escape(query_id)}/{round_number}/{ips_id}"
        )
        rows.append(
            "<tr>"
            f"<td>{ips_id}</td><td>{html.escape(safe_text(item.get('title')) or '未获取')}</td>"
            f"<td>{html.escape(safe_text(item.get('diagnostic_type')))}</td>"
            f"<td>{'是' if item.get('test_completed') else '否'}</td>"
            f"<td>{report_status_badge(item.get('status'))}</td>"
            f'<td><a href="{detail_href}">查看详情</a></td></tr>'
        )
    table = "".join(rows) or '<tr><td colspan="6" class="muted">本轮没有 Open IPS。</td></tr>'
    notification = record.get("manager_notification", {})
    notification_text = report_status_badge(notification.get("status")) if isinstance(notification, dict) else report_status_badge("未记录")
    top_ips_href = (
        f"/reports/task/{html.escape(task_id)}/{html.escape(query_id)}/{round_number}/top-ips"
        if task_id
        else f"/reports/{html.escape(query_id)}/{round_number}/top-ips"
    )
    return report_layout(
        f"Query {query_id} 第 {round_number} 轮处理报告",
        f"""<a class="back-link" href="/reports">← 返回历史汇总</a>
<section class="hero"><p class="eyebrow">QUERY ROUND REPORT</p><h1>Query {html.escape(query_id)} · 第 {round_number} 轮处理报告</h1>
<p class="muted">任务：{html.escape(task_id) or '旧记录'} · 处理时间：{format_task_time(record.get('started_at'))} 至 {format_task_time(record.get('completed_at')) if record.get('completed_at') else '进行中'}</p></section>
<section class="summary"><div class="metric"><span class="metric-label">整体状态</span><div class="metric-value">{report_status_badge(record.get('status'))}</div></div>
<div class="metric"><span class="metric-label">处理结果</span><div class="metric-value">{len(items)}</div><span class="muted">{status_summary(items)}</span></div>
<div class="metric"><span class="metric-label">管理通知</span><div class="metric-value">{notification_text}</div></div></section>
<section class="panel"><h2>AI Top IPS 参考报告</h2><p class="muted">独立查看本轮 AI 从全部 Query IPS 中筛选出的跨团队参考案例。</p><div class="actions"><a href="{top_ips_href}">打开 Top IPS 参考报告</a></div></section>
<section class="panel"><h2>IPS 处理明细</h2><div class="table-wrap"><table><thead><tr><th>IPS ID</th><th>IPS 关键标题</th><th>诊断类型</th><th>是否完成测试</th><th>处理状态</th><th>详细报告</th></tr></thead>
<tbody>{table}</tbody></table></div></section>
""",
    )


def render_report_detail(query_id: str, round_number: int, ips_id: str, task_id: str = "") -> str:
    record = load_auto_round(query_id, round_number, task_id)
    item = next(
        (
            candidate for candidate in record.get("items", [])
            if isinstance(candidate, dict) and safe_text(candidate.get("ips_id")) == ips_id
        ),
        None,
    )
    if item is None:
        raise FileNotFoundError("IPS report not found")
    report_path = safe_text(item.get("report_path"))
    report_link = f'<a href="/report-file?path={quote(report_path)}">打开 Markdown 报告</a>' if report_path else "未生成"
    round_href = (
        f"/reports/task/{html.escape(task_id)}/{html.escape(query_id)}/{round_number}"
        if task_id
        else f"/reports/{html.escape(query_id)}/{round_number}"
    )
    return report_layout(
        f"IPS {ips_id} 自动化处理详情",
        f"""<a class="back-link" href="{round_href}">← 返回本轮汇总</a>
<section class="hero"><p class="eyebrow">IPS EXECUTION DETAIL</p><h1>IPS {html.escape(ips_id)} 自动化处理详情</h1>
<p class="muted">查看诊断结果、通知状态和关联 Markdown 报告。</p></section>
<section class="panel"><h2>处理摘要</h2><div class="table-wrap"><table><tbody>
<tr><th>关键标题</th><td>{html.escape(safe_text(item.get('title')) or '未获取')}</td></tr>
<tr><th>诊断类型</th><td>{html.escape(safe_text(item.get('diagnostic_type')))}</td></tr>
<tr><th>处理状态</th><td>{report_status_badge(item.get('status'))}</td></tr>
<tr><th>是否完成测试</th><td>{'是' if item.get('test_completed') else '否'}</td></tr>
<tr><th>Owner</th><td>{html.escape(safe_text(item.get('owner')) or '未获取')}</td></tr>
<tr><th>Owner 邮件状态</th><td>{html.escape(safe_text(item.get('owner_notification_status')))}</td></tr>
<tr><th>Markdown 报告</th><td>{report_link}</td></tr>
</tbody></table></div></section>
{render_report_center_summary(item.get('report_center_summary'))}
<section class="panel"><h2>Owner 邮件正文</h2><pre>{html.escape(safe_text(item.get('owner_email_body')) or '未记录')}</pre></section>""",
    )


def format_task_time(value: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except (TypeError, ValueError):
        pass
    text = safe_text(value)
    if not text:
        return "未记录"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def recipient_email_links(value: Any) -> str:
    """Render only complete email addresses as safe mailto links."""
    text = safe_text(value)
    if not text:
        return "未发送"
    parts = re.split(r"([,;，；\s]+)", text)
    rendered: list[str] = []
    for part in parts:
        if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", part):
            rendered.append(f'<a href="mailto:{html.escape(quote(part, safe="@._+-"), quote=True)}">{html.escape(part)}</a>')
        else:
            rendered.append(html.escape(part))
    return "".join(rendered)


def render_task_detail(task: dict[str, Any]) -> str:
    report_path = safe_text(task.get("report_path"))
    report_link = f'<a href="/reports/task/{html.escape(task["id"])}/{html.escape(task["query_id"])}/{task["current_round"]}">查看当前轮次报告</a>' if report_path else "尚未生成"
    return report_layout(
        f"Query {task['query_id']} 任务详情",
        f"""<a class="back-link" href="/tasks">← 返回任务中心</a>
<section class="hero"><p class="eyebrow">QUERY TASK DETAIL</p><h1>Query {html.escape(task['query_id'])} 任务详情</h1>
<p class="muted">创建人：{html.escape(task['creator_name'])} · 创建时间：{format_task_time(task.get('created_at'))}</p></section>
<section class="summary"><div class="metric"><span class="metric-label">任务状态</span><div class="metric-value">{report_status_badge(task.get('status'))}</div></div>
<div class="metric"><span class="metric-label">当前轮次</span><div class="metric-value">{task.get('current_round', 0)}</div></div>
<div class="metric"><span class="metric-label">当前 IPS</span><div class="metric-value">{html.escape(safe_text(task.get('current_ips_id')) or '—')}</div></div></section>
<section class="panel"><h2>任务参数</h2><div class="table-wrap"><table><tbody>
<tr><th>任务 ID</th><td>{html.escape(task['id'])}</td></tr>
<tr><th>运行方式</th><td>{'仅生成共性报告（单次只读）' if task.get('report_only') else f"每 {int(task.get('interval_seconds', 0)) // 60} 分钟轮询并处理 Open IPS"}</td></tr>
<tr><th>汇总通知者</th><td>{recipient_email_links(task.get('manager_recipients')) if safe_text(task.get('manager_recipients')) else '未填写'}</td></tr>
<tr><th>取消/失败原因</th><td>{html.escape(safe_text(task.get('cancellation_reason')) or safe_text(task.get('error_text')) or '无')}</td></tr>
<tr><th>报告</th><td>{report_link}</td></tr>
</tbody></table></div></section>
<section class="panel"><h2>实时输出</h2><pre>{html.escape(safe_text(task.get('output')) or '尚无输出。')}</pre></section>""",
        section="任务中心",
    )


def render_task_center() -> str:
    return report_layout(
        "任务中心",
        """<section class="hero"><p class="eyebrow">SHARED TASK OPERATIONS</p><h1>任务中心</h1>
<p class="muted">集中查看简洁执行、计划审阅和全自动 Query 任务的状态、进度与报告；此页面仅用于跟踪任务。</p></section>
<section class="summary"><div class="metric"><span class="metric-label">活动任务</span><div class="metric-value" id="activeCount">0</div></div><div class="metric"><span class="metric-label">已完成任务</span><div class="metric-value" id="completedCount">0</div></div><div class="metric"><span class="metric-label">资源占用</span><div class="metric-value" id="resourceCount">0</div></div></section>
<section class="panel"><h2>全部任务</h2><div class="filter"><input id="search" placeholder="按 IPS/HSD、Query、下发人或当前 IPS 搜索" oninput="renderTasks()"><select id="sourceFilter" onchange="renderTasks()"><option value="">全部方式</option><option value="manual">手动任务</option><option value="query">全自动 Query</option></select><select id="statusFilter" onchange="renderTasks()"><option value="">全部状态</option><option value="queued">排队</option><option value="running">运行中</option><option value="waiting_resource">等待资源</option><option value="completed">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="interrupted">已中断</option></select></div><div id="taskList" class="task-grid">正在加载任务…</div></section>
<section class="panel"><h2>硬件资源状态</h2><p class="muted">仅展示已被自动任务锁定的已登记控制机；不显示连接凭据或敏感配置。</p><div id="resourceList" class="task-grid">正在加载资源状态…</div></section>
<script>
let tasks = [];
const activeStatuses = new Set(["queued", "running", "waiting_resource", "cancelling"]);
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = value || ""; return div.innerHTML; }
function badge(status) { return `<span class="status-badge status-${escapeHtml(status)}">${escapeHtml(status || "未记录")}</span>`; }
async function request(path, payload) { const response = await fetch(path, payload ? {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)} : {}); const body = await response.json(); if (!response.ok) { const error = new Error(body.message || body.error || "请求失败"); error.body = body; throw error; } return body; }
function taskCard(task) { return `<article class="task-card"><h3>${escapeHtml(task.title)} · ${badge(task.status)}</h3><div class="task-meta"><span>方式：${escapeHtml(task.mode)}</span><span>任务类型：${escapeHtml(task.task_type)}</span><span>下发人：${escapeHtml(task.submitter)}</span><span>${escapeHtml(task.progress)}</span><span>创建时间：${new Date(task.created_at * 1000).toLocaleString()}</span></div><div class="actions"><a href="${task.detail_href}">查看详情与报告</a></div></article>`; }
function renderTasks() { const term = document.getElementById("search").value.trim().toLowerCase(); const source = document.getElementById("sourceFilter").value; const status = document.getElementById("statusFilter").value; const filtered = tasks.filter(task => (!source || task.source === source) && (!status || task.status === status) && (!term || [task.title,task.mode,task.task_type,task.submitter,task.progress].join(" ").toLowerCase().includes(term))); document.getElementById("taskList").innerHTML = filtered.length ? filtered.map(taskCard).join("") : "<p class='muted'>没有符合条件的任务。</p>"; }
async function loadTasks() { const data = await request("/api/task-center"); tasks = data.tasks; document.getElementById("activeCount").textContent = tasks.filter(task => activeStatuses.has(task.status)).length; document.getElementById("completedCount").textContent = tasks.filter(task => task.status === "completed").length; renderTasks(); }
async function loadResources() { const data = await request("/api/resources"); document.getElementById("resourceCount").textContent = data.resources.length; document.getElementById("resourceList").innerHTML = data.resources.length ? data.resources.map(resource => `<article class="task-card"><h3>${escapeHtml(resource.machine_key)}</h3><div class="task-meta"><span>Query：${escapeHtml(resource.query_id || "—")}</span><span>创建人：${escapeHtml(resource.creator_name || "—")}</span><span>当前 IPS：${escapeHtml(resource.current_ips_id || "—")}</span><span>${badge(resource.status)}</span></div></article>`).join("") : "<p class='muted'>当前没有自动任务占用硬件资源。</p>"; }
Promise.all([loadTasks(), loadResources()]).catch(error => { document.getElementById("taskList").textContent = error.message; }); setInterval(() => { loadTasks().catch(() => {}); loadResources().catch(() => {}); }, 3000);
</script>""",
        section="任务中心",
    )


def render_user_guide() -> str:
    return report_layout(
        "用户指南",
        """        <section class="hero"><p class="eyebrow">GET STARTED SAFELY</p><h1>用户指南</h1><p class="muted">帮助新用户选择工作模式、完成配置、创建任务并理解安全限制。</p></section>
        <section class="panel"><h2>选择工作模式</h2><div class="table-wrap"><table><thead><tr><th>模式</th><th>适用场景</th><th>操作方式</th></tr></thead><tbody><tr><td>简洁模式</td><td>已有明确任务，愿意按默认计划直接执行</td><td>填写 IPS/HSD ID 与测试目标，点击开始执行。</td></tr><tr><td>详细模式</td><td>需要审阅、修改并确认执行计划</td><td>先生成阶段 1 计划，编辑后勾选确认，再启动阶段 2。</td></tr><tr><td>自动 Query</td><td>需要持续处理同一 HSD Query 的 Open IPS</td><td>前往任务中心创建任务；系统会阻止相同活动 Query 重复运行。</td></tr></tbody></table></div></section>
        <section class="panel"><h2>标准操作步骤</h2><ol><li>在工作台选择简洁或详细模式，填写任务信息。</li><li>详细模式下，仅阶段 1 生成计划，不访问 HSD、不连接 SSH、也不执行硬件动作。</li><li>检查阶段 2 计划；涉及烧录、供电、串口或 MLC 时必须明确确认。</li><li>在执行控制台查看输出，在报告中心查看保存的结果。</li></ol></section>
<section class="panel"><h2>Query 任务与资源协调</h2><p>任务中心展示所有创建人的任务、运行状态、当前 IPS 和硬件资源锁。相同 Query 在活动状态下只允许一个任务；请进入已有任务查看进展，而不是重复创建。</p><p>资源等待表示其他自动任务正在使用相同已登记控制机。等待期间不会执行硬件副作用。</p></section>
<section class="panel"><h2>安全边界与常见问题</h2><div class="notice warning">咨询和提取任务不应烧录、开关机、控制串口或运行 MLC。Debug/验证任务必须在 BKC、平台和机器匹配后才允许硬件动作；烧录失败后不得继续抓启动日志或运行 MLC。</div><p>完整部署、配置和网络访问说明请参阅 <code>docs\\ips_copilot_ui.md</code>；Git 拉取和服务器更新请参阅 <code>docs\\git_usage_guide.md</code>。</p></section>""",
        section="用户指南",
    )


class Handler(BaseHTTPRequestHandler):
    cfg: dict[str, Any] = {}

    def _send_json(self, data: Any, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _report_base_url(self) -> str:
        host = safe_text(self.headers.get("Host"))
        if re.fullmatch(r"[A-Za-z0-9.:-]+", host):
            return f"http://{host}"
        return safe_text(self.cfg.get("server", {}).get("reportBaseUrl"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_text(HTML_PAGE, content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/tasks":
            self._send_text(render_task_center(), content_type="text/html; charset=utf-8")
            return
        task_page_match = re.fullmatch(r"/tasks/([0-9a-f-]+)", parsed.path)
        if task_page_match:
            task = TASK_MANAGER.get(task_page_match.group(1)) if TASK_MANAGER else None
            if task is None:
                self._send_text("任务不存在或已被清理。", status=404)
            else:
                self._send_text(render_task_detail(task), content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/guide":
            self._send_text(render_user_guide(), content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/common-issues":
            self._send_text(render_common_issue_page(self.cfg), content_type="text/html; charset=utf-8")
            return
        common_report_page_match = re.fullmatch(r"/common-issues/reports/([0-9a-f-]{36})", parsed.path)
        if common_report_page_match:
            try:
                self._send_text(render_common_issue_report(common_report_page_match.group(1), self.cfg), content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"报告不存在或无法读取：{exc}", status=404)
            return
        if parsed.path == "/reports":
            self._send_text(render_report_index(), content_type="text/html; charset=utf-8")
            return
        manual_report_match = re.fullmatch(r"/reports/manual/([0-9a-f-]+)", parsed.path)
        if manual_report_match:
            try:
                self._send_text(render_manual_report(manual_report_match.group(1)), content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"报告不存在或无法读取：{exc}", status=404)
            return
        manual_resource_request_match = re.fullmatch(r"/reports/manual/([0-9a-f-]+)/resource-request", parsed.path)
        if manual_resource_request_match:
            try:
                self._send_text(render_resource_request_review(manual_resource_request_match.group(1)), content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"资源协调草稿不存在或无法读取：{exc}", status=404)
            return
        task_top_ips_match = re.fullmatch(r"/reports/task/([0-9a-f-]+)/(\d+)/(\d+)/top-ips", parsed.path)
        if task_top_ips_match:
            try:
                task_id, query_id, round_text = task_top_ips_match.groups()
                self._send_text(render_top_ips_report(query_id, int(round_text), task_id), content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"Top IPS 报告不存在或无法读取：{exc}", status=404)
            return
        top_ips_match = re.fullmatch(r"/reports/(\d+)/(\d+)/top-ips", parsed.path)
        if top_ips_match:
            try:
                query_id, round_text = top_ips_match.groups()
                self._send_text(render_top_ips_report(query_id, int(round_text)), content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"Top IPS 报告不存在或无法读取：{exc}", status=404)
            return
        task_report_match = re.fullmatch(r"/reports/task/([0-9a-f-]+)/(\d+)/(\d+)(?:/(\d+))?", parsed.path)
        if task_report_match:
            try:
                task_id, query_id, round_text, ips_id = task_report_match.groups()
                page = (
                    render_report_detail(query_id, int(round_text), ips_id, task_id)
                    if ips_id
                    else render_round_report(query_id, int(round_text), task_id)
                )
                self._send_text(page, content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"报告不存在或无法读取：{exc}", status=404)
            return
        report_match = re.fullmatch(r"/reports/(\d+)/(\d+)(?:/(\d+))?", parsed.path)
        if report_match:
            try:
                query_id, round_text, ips_id = report_match.groups()
                page = (
                    render_report_detail(query_id, int(round_text), ips_id)
                    if ips_id
                    else render_round_report(query_id, int(round_text))
                )
                self._send_text(page, content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"报告不存在或无法读取：{exc}", status=404)
            return
        if parsed.path == "/report-file":
            try:
                report_path = safe_report_path(parse_qs(parsed.query).get("path", [""])[0])
                if not is_registered_report_path(report_path):
                    raise ValueError("report file is not registered in an automatic report")
                content = (KIT_ROOT / report_path).read_text(encoding="utf-8-sig")
                self._send_text(content, content_type="text/markdown; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError) as exc:
                self._send_text(f"报告文件不存在或无法读取：{exc}", status=404)
            return
        if parsed.path == "/api/config":
            public_cfg = {
                "defaults": self.cfg.get("defaults", {}),
                "taskTypes": self.cfg.get("taskTypes", []),
                "permissionLevels": self.cfg.get("permissionLevels", []),
                "machineOptions": self.cfg.get("_machine_options", []),
                "automation": self.cfg.get("automation", {}),
                "copilotMode": self.cfg.get("copilot", {}).get("mode", "manual"),
            }
            self._send_json(public_cfg)
            return
        if parsed.path == "/api/job":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job is None:
                    self._send_json({"error": "job not found"}, status=404)
                    return
                self._send_json(job)
                return
        if parsed.path == "/api/common-issues/reports":
            self._send_json({"reports": get_common_issue_store(self.cfg).list()})
            return
        common_report_api_match = re.fullmatch(r"/api/common-issues/reports/([0-9a-f-]{36})", parsed.path)
        if common_report_api_match:
            try:
                self._send_json(get_common_issue_store(self.cfg).load(common_report_api_match.group(1)))
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=404)
            return
        if parsed.path == "/api/tasks":
            if TASK_MANAGER is None:
                self._send_json({"error": "task manager is unavailable"}, status=503)
            else:
                self._send_json({"tasks": TASK_MANAGER.list(), "manual_reports": list_manual_reports()})
            return
        if parsed.path == "/api/task-center":
            self._send_json({"tasks": list_task_center_records()})
            return
        if parsed.path == "/api/resources":
            if TASK_MANAGER is None:
                self._send_json({"error": "task manager is unavailable"}, status=503)
            else:
                self._send_json({"resources": TASK_MANAGER.resources()})
            return
        task_match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)", parsed.path)
        if task_match:
            task = TASK_MANAGER.get(task_match.group(1)) if TASK_MANAGER else None
            if task is None:
                self._send_json({"error": "task not found"}, status=404)
            else:
                self._send_json(task)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        try:
            common_feedback_match = re.fullmatch(r"/api/common-issues/reports/([0-9a-f-]{36})/feedback", self.path)
            if common_feedback_match:
                body = self._read_json()
                updated = get_common_issue_store(self.cfg).add_feedback(
                    common_feedback_match.group(1),
                    safe_text(body.get("grouping_key")),
                    safe_text(body.get("action")),
                    safe_text(body.get("note")),
                )
                self._send_json(updated.get("report", {}))
                return
            if self.path == "/api/common-issues/search":
                filters = validate_common_issue_filters(self._read_json(), self.cfg)
                self._send_json(create_common_issue_report(filters, self.cfg))
                return
            if self.path in ("/api/plan-template", "/api/plan-skeleton"):
                body = self._read_json()
                self._send_json({"plan_text": initial_plan_text(body)})
                return
            if self.path == "/api/render-plan-prompt":
                body = self._read_json()
                self._send_json({"prompt": build_plan_prompt(body, self.cfg)})
                return
            if self.path == "/api/start-plan":
                body = self._read_json()
                prompt = build_plan_prompt(body, self.cfg)
                job_id = start_job(
                    "plan",
                    prompt,
                    self.cfg,
                    {
                        "ips_id": safe_text(body.get("ips_id")),
                        "task_type": safe_text(body.get("task_type")),
                        "ui_mode": "detailed",
                        "workflow_phase": "plan",
                        "submitted_by": "",
                        "recipient": safe_text(body.get("notification_recipient")),
                        "plan_text": "",
                    },
                )
                self._send_json({"job_id": job_id})
                return
            if self.path == "/api/render-execute-prompt":
                body = self._read_json()
                plan_text = safe_text(body.get("plan_text"))
                permission = safe_text(body.get("permission_label"))
                task_type = safe_text(body.get("task_type"))
                auto_machine_match = bool(body.get("auto_machine_match"))
                ssh_host = safe_text(body.get("ssh_host"))
                if not plan_text:
                    raise ValueError("plan_text is required")
                self._send_json(
                    {
                        "prompt": build_execute_prompt(
                            plan_text,
                            self.cfg,
                            permission,
                            task_type,
                            auto_machine_match,
                            ssh_host,
                            self._report_base_url(),
                            safe_text(body.get("notification_recipient")),
                        )
                    }
                )
                return
            if self.path == "/api/start-execute":
                body = self._read_json()
                plan_text = safe_text(body.get("plan_text"))
                permission = safe_text(body.get("permission_label"))
                task_type = safe_text(body.get("task_type"))
                auto_machine_match = bool(body.get("auto_machine_match"))
                ssh_host = safe_text(body.get("ssh_host"))
                if not plan_text:
                    raise ValueError("plan_text is required")
                if safe_text(body.get("ui_mode")) == "simple" and not safe_text(body.get("submitted_by")):
                    raise ValueError("简洁模式必须填写任务下发人")
                prompt = build_execute_prompt(
                    plan_text,
                    self.cfg,
                    permission,
                    task_type,
                    auto_machine_match,
                    ssh_host,
                    self._report_base_url(),
                    safe_text(body.get("notification_recipient")),
                )
                existing_report_id = safe_text(body.get("manual_report_id"))
                if existing_report_id:
                    if not re.fullmatch(r"[0-9a-f-]+", existing_report_id):
                        raise ValueError("invalid manual_report_id")
                    manual_report = load_manual_report(existing_report_id)
                    manual_report.update(
                        {
                            "ips_id": safe_text(body.get("ips_id")),
                            "task_type": task_type,
                            "ui_mode": safe_text(body.get("ui_mode")),
                            "workflow_phase": "execute",
                            "submitted_by": safe_text(body.get("submitted_by")),
                            "recipient": safe_text(body.get("notification_recipient")),
                            "resource_request_recipient": safe_text(body.get("resource_request_recipient")),
                            "plan_text": plan_text,
                            "report_base_url": self._report_base_url(),
                        }
                    )
                else:
                    manual_report = {
                        "ips_id": safe_text(body.get("ips_id")),
                        "task_type": task_type,
                        "ui_mode": safe_text(body.get("ui_mode")),
                        "workflow_phase": "execute",
                        "submitted_by": safe_text(body.get("submitted_by")),
                        "recipient": safe_text(body.get("notification_recipient")),
                        "resource_request_recipient": safe_text(body.get("resource_request_recipient")),
                        "plan_text": plan_text,
                        "report_base_url": self._report_base_url(),
                    }
                job_id = start_job("execute", prompt, self.cfg, manual_report, existing_report_id)
                self._send_json({"job_id": job_id})
                return
            resource_details_match = re.fullmatch(r"/api/reports/manual/([0-9a-f-]+)/resource-request/details", self.path)
            if resource_details_match:
                body = self._read_json()
                self._send_json(save_resource_request_details(
                    resource_details_match.group(1),
                    body.get("expected_ddl"),
                    body.get("resource_to_reserve"),
                    body.get("reservation_duration"),
                    body.get("manager_recipient"),
                ))
                return
            resource_send_match = re.fullmatch(r"/api/reports/manual/([0-9a-f-]+)/resource-request/send", self.path)
            if resource_send_match:
                job_id = resource_send_match.group(1)
                record = load_manual_report(job_id)
                if not record.get("resource_request_details_saved"):
                    raise ValueError("请先保存 DDL、资源和预计时长")
                attachment = resource_request_draft_path(record)
                recipient = safe_text(record.get("resource_request_recipient"))
                if not recipient:
                    raise ValueError("未填写物品清单申请收件人")
                link = f"{self._report_base_url()}/reports/manual/{job_id}/resource-request"
                subject, body = resource_request_email_content(record, link)
                result = subprocess.run(
                    [
                        "powershell", "-ExecutionPolicy", "Bypass", "-File",
                        str(KIT_ROOT / "scripts" / "Send-OwnerNotification.ps1"),
                        "-To", recipient, "-Subject", subject, "-Body", body,
                        "-Attachments", str(attachment), "-Send",
                    ],
                    cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120, check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"物品清单申请邮件发送失败（exit {result.returncode}）：{result.stderr.strip() or result.stdout.strip()}")
                record["resource_request_email_status"] = "sent"
                record["resource_request_email_sent_at"] = time.time()
                write_manual_report(record)
                self._send_json({"status": "sent"})
                return
            if self.path == "/api/tasks":
                body = self._read_json()
                query_id = safe_text(body.get("query_id"))
                report_only = body.get("report_only") is True
                interval_minutes = 0 if report_only else int(body.get("interval_minutes"))
                manager_recipients = safe_text(body.get("manager_recipients"))
                creator_name = safe_text(body.get("creator_name"))
                if TASK_MANAGER is None:
                    raise RuntimeError("task manager is unavailable")
                self._send_json(TASK_MANAGER.start(query_id, creator_name, interval_minutes, manager_recipients, report_only))
                return
            cancel_match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)/cancel", self.path)
            if cancel_match:
                body = self._read_json()
                if TASK_MANAGER is None:
                    raise RuntimeError("task manager is unavailable")
                self._send_json(TASK_MANAGER.cancel(cancel_match.group(1), safe_text(body.get("reason"))))
                return
            self._send_json({"error": "not found"}, status=404)
        except DuplicateQueryTaskError as exc:
            self._send_json(
                {
                    "error": "duplicate_query",
                    "message": "相同 Query 已有活动任务，未创建重复任务。",
                    "existing_task": exc.task,
                },
                status=409,
            )
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=400)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def task_lock_command(cfg: dict[str, Any], task_id: str, machine_id: str, action: str, wait: bool) -> int:
    inventory_path = pathlib.Path(cfg.get("machineMatching", {}).get("inventoryPath", "config\\lab-machine-inventory.json"))
    if not inventory_path.is_absolute():
        inventory_path = KIT_ROOT / inventory_path
    try:
        inventory = read_json(inventory_path)
        registered_machine_ids = {safe_text(machine.get("id")) for machine in inventory.get("machines", []) if isinstance(machine, dict)}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MACHINE_LOCK_INVENTORY_ERROR={type(exc).__name__}: {exc}")
        return 2
    if machine_id not in registered_machine_ids:
        print(f"MACHINE_LOCK_UNKNOWN_MACHINE={machine_id}")
        return 2
    automation = cfg.get("automation", {})
    database_path = pathlib.Path(automation.get("taskDatabasePath", "out\\ui_task_manager.sqlite3"))
    if not database_path.is_absolute():
        database_path = KIT_ROOT / database_path
    store = TaskStore(database_path, automation.get("perMachineConcurrency", {"default": 1}), recover_active=False)
    if action == "release":
        store.release_machine(task_id, machine_id)
        print(f"MACHINE_LOCK_RELEASED={machine_id}")
        return 0
    deadline = time.time() + int(automation.get("machineLockWaitSeconds", 3600)) if wait else time.time()
    while True:
        task = store.get_task(task_id)
        if task and task["status"] in ("cancelling", "cancelled", "interrupted"):
            print("MACHINE_LOCK_CANCELLED")
            return 2
        if store.try_acquire_machine(task_id, machine_id):
            if task and task["status"] == "waiting_resource":
                store.update(task_id, status="running")
            print(f"MACHINE_LOCK_ACQUIRED={machine_id}")
            return 0
        if task and task["status"] == "running":
            store.update(task_id, status="waiting_resource")
        if not wait or time.time() >= deadline:
            print(f"MACHINE_LOCK_UNAVAILABLE={machine_id}")
            return 75
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start portable IPS/HSD Copilot UI.")
    parser.add_argument("--config", default=str(KIT_ROOT / "config" / "ips-copilot-ui.template.json"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--copilot-mode", choices=["manual", "subprocess"])
    parser.add_argument("--task-lock", action="store_true", help="Acquire or release a persisted hardware machine reservation.")
    parser.add_argument("--task-id")
    parser.add_argument("--machine-id")
    parser.add_argument("--action", choices=["acquire", "release"])
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()

    cfg_path = pathlib.Path(args.config).resolve()
    cfg = load_config(cfg_path)
    cfg["_machine_options"] = load_machine_options(cfg)
    if args.host:
        deep_set(cfg, "server.host", args.host)
    if args.port:
        deep_set(cfg, "server.port", args.port)
    if args.no_browser:
        deep_set(cfg, "server.openBrowser", False)
    if args.copilot_mode:
        deep_set(cfg, "copilot.mode", args.copilot_mode)
    if args.task_lock:
        if not args.task_id or not args.machine_id or not args.action:
            parser.error("--task-lock requires --task-id, --machine-id, and --action")
        return task_lock_command(cfg, args.task_id, args.machine_id, args.action, args.wait)

    host = cfg.get("server", {}).get("host", "127.0.0.1")
    port = int(cfg.get("server", {}).get("port", 8765))
    Handler.cfg = cfg
    global TASK_MANAGER
    TASK_MANAGER = TaskManager(cfg)
    get_common_issue_store(cfg)

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"IPS/HSD Copilot UI started: {url}")
    print(f"Config: {cfg_path}")
    print(f"Copilot mode: {cfg.get('copilot', {}).get('mode', 'manual')}")
    print("Press Ctrl+C to stop.")
    if cfg.get("server", {}).get("openBrowser", True):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping UI.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
