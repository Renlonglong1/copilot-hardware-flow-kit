#!/usr/bin/env python3
"""Command-line Intel document manager.

This CUI intentionally reuses the GUI tool's browser profile, SSO cookie
checks, curated common-document list, and Playwright download engine. Keep the
business logic in intel_doc_manager_gui.pyw so GUI and CUI behavior stays in
sync.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
GUI_SCRIPT = SCRIPT_DIR / "intel_doc_manager_gui.pyw"
__version__ = "0.1.0"


def _load_gui_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("intel_doc_manager_gui_core", str(GUI_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Unable to load GUI core from {GUI_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


gui = _load_gui_module()


def _print_log(line: str) -> None:
    print(line, end="", flush=True)


def _select_browser() -> Any:
    browser = gui.select_supported_browser()
    print(f"Selected browser: {browser.label}")
    print(f"Tool profile: {browser.profile_dir}")
    return browser


def _ensure_playwright_available() -> None:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            "Python package 'playwright' is required. Install with:\n"
            "  python -m pip install --proxy=http://child-prc.intel.com:913 playwright"
        ) from error


def _ensure_login(browser: Any) -> None:
    if not gui.first_time_login_setup(browser):
        raise RuntimeError("Login was cancelled or incomplete.")


def _relogin(browser: Any) -> None:
    print("Refreshing browser credentials...")
    gui._clear_profile_login_ready(browser.profile_dir)
    gui._clear_profile_sso_cookies(browser.profile_dir)
    if not gui.first_time_login_setup(browser, relogin=True):
        raise RuntimeError("Re-login was cancelled or incomplete.")
    print("Browser credentials refreshed.")


class SyncDownloader:
    def __init__(self, browser: Any) -> None:
        self.engine = gui.IntelDocEngine(browser)

    def close(self) -> None:
        self.engine.shutdown()
        worker = getattr(self.engine, "_worker", None)
        if worker is not None and getattr(self.engine, "_started", False):
            worker.join(timeout=20)

    def download_one(self, doc_id: str, out_dir: Path, *, force: bool = False) -> tuple[str, str]:
        done = threading.Event()
        result: dict[str, str] = {"outcome": "failed", "message": ""}

        def done_cb(outcome: str, message: str) -> None:
            result["outcome"] = outcome
            result["message"] = message
            done.set()

        self.engine.submit(str(doc_id), Path(out_dir), _print_log, done_cb, force=force)
        done.wait()
        print(f"  [{result['outcome']}] {result['message']}")
        return result["outcome"], result["message"]


def _summarize(results: list[tuple[str, str, str]]) -> int:
    updated = [row for row in results if row[1] == "updated"]
    current = [row for row in results if row[1] == "current"]
    failed = [row for row in results if row[1] == "failed"]
    print("\nSummary")
    print(f"  updated/downloaded: {len(updated)}")
    print(f"  already current:    {len(current)}")
    print(f"  failed:             {len(failed)}")
    if failed:
        print("\nFailed documents:")
        for doc_id, _outcome, message in failed:
            print(f"  {doc_id}: {message}")
        return 1
    return 0


def _normalize_doc_ids(values: Iterable[str]) -> list[str]:
    doc_ids: list[str] = []
    for value in values:
        for part in value.replace(",", " ").split():
            stripped = part.strip()
            if stripped:
                doc_ids.append(stripped)
    return doc_ids


def _common_docs_by_filter(platform: str | None, category: str | None) -> list[Any]:
    docs = list(gui.COMMON_DOCUMENTS)
    if platform:
        docs = [doc for doc in docs if doc.platform.lower() == platform.lower()]
    if category:
        docs = [doc for doc in docs if doc.category.lower() == category.lower()]
    return docs


def _common_download_dir(doc: Any, base_dir: str, organize: bool) -> str:
    if not organize:
        return base_dir
    platform = gui.common_platform_label(doc.platform)
    return str(Path(base_dir) / platform / doc.category)


def _scan_folder_without_txt(folder: Path) -> dict[str, list[Any]]:
    grouped = gui.scan_folder(folder)
    return {
        doc_id: [doc for doc in docs if doc.file_path.suffix.lower() != ".txt"]
        for doc_id, docs in grouped.items()
        if any(doc.file_path.suffix.lower() != ".txt" for doc in docs)
    }


def cmd_list_common(args: argparse.Namespace) -> int:
    docs = _common_docs_by_filter(args.platform, args.category)
    for doc in docs:
        print(f"{doc.doc_id}\t{doc.platform}\t{doc.category}\t{doc.title}")
    print(f"\nTotal: {len(docs)} common documents")
    return 0


def cmd_relogin(_args: argparse.Namespace) -> int:
    _ensure_playwright_available()
    browser = _select_browser()
    _relogin(browser)
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    _ensure_playwright_available()
    doc_ids = _normalize_doc_ids(args.doc_id)
    if not doc_ids:
        raise RuntimeError("At least one --doc-id is required.")
    out_dir = Path(args.out).resolve()
    browser = _select_browser()
    if args.relogin:
        _relogin(browser)
    else:
        _ensure_login(browser)
    downloader = SyncDownloader(browser)
    results: list[tuple[str, str, str]] = []
    try:
        for doc_id in doc_ids:
            print(f"\nDownloading Doc ID {doc_id} -> {out_dir}")
            outcome, message = downloader.download_one(doc_id, out_dir, force=args.force)
            results.append((doc_id, outcome, message))
    finally:
        downloader.close()
    return _summarize(results)


def cmd_download_common(args: argparse.Namespace) -> int:
    _ensure_playwright_available()
    if args.doc_id:
        requested = set(_normalize_doc_ids(args.doc_id))
        docs = [doc for doc in gui.COMMON_DOCUMENTS if doc.doc_id in requested]
        missing = sorted(requested - {doc.doc_id for doc in docs})
        if missing:
            raise RuntimeError(f"Doc IDs are not in COMMON_DOCUMENTS: {', '.join(missing)}")
    else:
        docs = _common_docs_by_filter(args.platform, args.category)
    if args.limit is not None:
        docs = docs[: args.limit]
    if not docs:
        raise RuntimeError("No common documents matched the requested filters.")
    out_dir = Path(args.out).resolve()
    print(f"Matched {len(docs)} common documents.")
    if args.organize:
        print("Saving documents under platform/category subfolders.")
    browser = _select_browser()
    if args.relogin:
        _relogin(browser)
    else:
        _ensure_login(browser)
    downloader = SyncDownloader(browser)
    results: list[tuple[str, str, str]] = []
    try:
        for doc in docs:
            target_dir = _common_download_dir(doc, str(out_dir), args.organize)
            print(f"\nDownloading {doc.doc_id} ({doc.platform}/{doc.category}) {doc.title} -> {target_dir}")
            outcome, message = downloader.download_one(doc.doc_id, Path(target_dir), force=args.force)
            results.append((doc.doc_id, outcome, message))
    finally:
        downloader.close()
    return _summarize(results)


def cmd_update_folder(args: argparse.Namespace) -> int:
    _ensure_playwright_available()
    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        raise RuntimeError(f"Not a directory: {folder}")
    print(f"Scanning folder: {folder}")
    grouped = _scan_folder_without_txt(folder)
    latest = {doc_id: gui.pick_latest_local(items) for doc_id, items in grouped.items()}
    doc_ids = sorted(latest)
    if args.doc_id:
        requested = set(_normalize_doc_ids(args.doc_id))
        doc_ids = [doc_id for doc_id in doc_ids if doc_id in requested]
        missing = sorted(requested - set(doc_ids))
        if missing:
            print(f"Warning: requested Doc IDs not found in scan: {', '.join(missing)}")
    if args.limit is not None:
        doc_ids = doc_ids[: args.limit]
    if not doc_ids:
        raise RuntimeError("No Intel Doc IDs found to update.")
    print(f"Found {len(grouped)} unique Doc IDs; updating {len(doc_ids)}.")
    browser = _select_browser()
    if args.relogin:
        _relogin(browser)
    else:
        _ensure_login(browser)
    downloader = SyncDownloader(browser)
    results: list[tuple[str, str, str]] = []
    try:
        for doc_id in doc_ids:
            target_dir = latest[doc_id].file_path.parent
            print(f"\nUpdating Doc ID {doc_id} -> {target_dir}")
            outcome, message = downloader.download_one(doc_id, target_dir, force=args.force)
            results.append((doc_id, outcome, message))
    finally:
        downloader.close()
    return _summarize(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CUI wrapper for Intel cdrdv2 document downloads. Shares cookies and logic with the GUI tool.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-common", help="Print the curated common document list.")
    p.add_argument("--platform", help="Filter by platform, e.g. OKS, BHS, EGS.")
    p.add_argument("--category", help="Filter by category, e.g. EDS, RAS, BWG.")
    p.set_defaults(func=cmd_list_common)

    p = sub.add_parser("relogin", help="Refresh browser SSO credentials shared with the GUI tool.")
    p.set_defaults(func=cmd_relogin)

    p = sub.add_parser("download", help="Download one or more Doc IDs.")
    p.add_argument("--doc-id", nargs="+", required=True, help="Doc IDs, space- or comma-separated.")
    p.add_argument("--out", default=str(SCRIPT_DIR), help="Output directory.")
    p.add_argument("--force", action="store_true", help="Overwrite existing latest file instead of reporting current.")
    p.add_argument("--relogin", action="store_true", help="Refresh browser credentials before downloading.")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("download-common", help="Download curated common documents, optionally organized by platform/category.")
    p.add_argument("--out", default=str(SCRIPT_DIR), help="Output directory.")
    p.add_argument("--platform", help="Filter by platform, e.g. OKS, BHS, EGS.")
    p.add_argument("--category", help="Filter by category, e.g. EDS, RAS, BWG.")
    p.add_argument("--doc-id", nargs="+", help="Only download these common-list Doc IDs.")
    p.add_argument("--limit", type=int, help="Limit number of matched documents, useful for validation.")
    p.add_argument("--organize", action="store_true", help="Save into platform/category subfolders like the GUI's Download & Organize.")
    p.add_argument("--force", action="store_true", help="Overwrite existing latest files.")
    p.add_argument("--relogin", action="store_true", help="Refresh browser credentials before downloading.")
    p.set_defaults(func=cmd_download_common)

    p = sub.add_parser("update-folder", help="Scan a folder and update every discovered Intel Doc ID.")
    p.add_argument("--folder", required=True, help="Folder to recursively scan for local Intel documents.")
    p.add_argument("--doc-id", nargs="+", help="Only update these scanned Doc IDs.")
    p.add_argument("--limit", type=int, help="Limit number of scanned documents, useful for validation.")
    p.add_argument("--force", action="store_true", help="Force download even if the latest filename already exists.")
    p.add_argument("--relogin", action="store_true", help="Refresh browser credentials before updating.")
    p.set_defaults(func=cmd_update_folder)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as error:  # noqa: BLE001
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())