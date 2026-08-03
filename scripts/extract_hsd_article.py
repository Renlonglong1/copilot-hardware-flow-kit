import argparse
import json
import re
from pathlib import Path


def strip_html(value):
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description="Extract useful fields from an HSD article JSON response.")
    parser.add_argument("--raw", required=True, help="Path to raw HSD JSON response.")
    parser.add_argument("--article-id", required=True, help="HSD article ID.")
    parser.add_argument("--json-out", required=True, help="Path to write extracted JSON.")
    parser.add_argument("--text-out", required=True, help="Path to write readable extracted text.")
    args = parser.parse_args()

    raw_path = Path(args.raw)
    payload = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    rows = payload.get("data", [])
    if not rows:
        raise SystemExit("NO_DATA_IN_RESPONSE")
    row = rows[0]

    needles = [
        "description",
        "status",
        "title",
        "owner",
        "family",
        "component",
        "reason",
        "submitted",
        "updated",
        "comment",
        "blog",
        "hist",
        "customer",
        "fail",
        "error",
        "bios",
        "bmc",
        "ifwi",
        "bkc",
        "log",
        "root",
        "cause",
        "attach",
        "file",
        "overview",
    ]
    field_matches = {
        needle: [key for key in sorted(row) if needle.lower() in key.lower()]
        for needle in needles
    }

    basic_keys = [
        "id",
        "title",
        "tenant",
        "subject",
        "status",
        "owner",
        "family",
        "component",
        "reason",
        "submitted_date",
        "updated_date",
        "bug.verified_date",
        "bug.fix_description",
        "server_platf_ae.bug.ext_account_geo",
        "server_platf_ae.bug.ext_priority",
        "server_platf_ae.bug.current_owner_org",
        "server_platf_ae.bug.reproducibility",
        "server_platf_ae.bug.root_cause",
        "server_platf_ae.bug.failure_signature",
        "server_platf_ae.bug.platform",
        "server_platf_ae.bug.project",
    ]

    text_candidate_keys = [
        "description",
        "comments",
        "server_platf_ae.bug.ext_cust_blog_hist",
        "server_platf_ae.bug.ext_cust_blog",
        "server_platf_ae.bug.ext_cust_blog_hist_rich",
        "server_platf_ae.bug.ext_cust_blog_rich",
        "bug.fix_description",
        "server_platf_ae.bug.failure_signature",
        "server_platf_ae.bug.root_cause",
        "server_platf_ae.bug.repro_steps",
        "server_platf_ae.bug.debug_notes",
        "server_platf_ae.bug.download_attached_ips_files",
        "server_platf_ae.bug.ext_attach_url",
        "server_platf_ae.bug.upload_attach_to_ips",
    ]

    basic = {key: row.get(key) for key in basic_keys if key in row}
    text_fields = {
        key: strip_html(row.get(key))
        for key in text_candidate_keys
        if key in row and strip_html(row.get(key))
    }

    interesting = {}
    for key in sorted(row):
        lower = key.lower()
        if any(term in lower for term in ["description", "comment", "blog", "hist", "root_cause", "failure", "repro", "debug", "log", "bios", "bmc", "ifwi", "bkc", "fix", "attach", "file", "overview"]):
            value = strip_html(row.get(key))
            if value and value.lower() not in {"none", "null"}:
                interesting[key] = value[:4000]

    extracted = {
        "article_id": args.article_id,
        "field_count": len(row),
        "basic": basic,
        "text_fields": text_fields,
        "interesting_fields": interesting,
        "field_matches": field_matches,
    }

    json_out = Path(args.json_out)
    text_out = Path(args.text_out)
    json_out.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"ARTICLE {args.article_id}", "BASIC"]
    for key, value in basic.items():
        lines.append(f"{key}: {value}")
    lines.append("\nTEXT_FIELDS")
    for key, value in text_fields.items():
        lines.append(f"\n--- {key} ---\n{value[:12000]}")
    lines.append("\nINTERESTING_FIELD_KEYS")
    for key in interesting:
        lines.append(key)
    text_out.write_text("\n".join(lines), encoding="utf-8")

    print(f"FIELD_COUNT={len(row)}")
    print("TEXT_KEYS=" + ",".join(text_fields.keys()))
    print("INTERESTING_KEYS=" + ",".join(interesting.keys()))


if __name__ == "__main__":
    main()
