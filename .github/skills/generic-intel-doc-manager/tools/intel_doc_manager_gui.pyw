#!/usr/bin/env python3
r"""
Intel Document Manager (GUI)
============================
Double-click this .pyw to launch a small GUI for managing locally-cached
Intel cdrdv2 documents.

Features
--------
1. Dependency self-check (tkinter, playwright) on startup,
   with one-click pip install via the Intel proxy when something is missing.
2. **Folder Scan** region: recursively scans this tool's folder (or a chosen
    folder) for Intel-named documents and lists them by Doc ID / Name / Version.
3. **Doc-ID region**: user can type any Intel document ID and download it.
   A curated *Common Documents* table lets the user pick by description
   without remembering IDs.

This file is self-contained. All HTTPS / Playwright / cdrdv2 logic is
inlined into ``IntelDocEngine`` below; there is no dependency on any
other helper script.  A single persistent Chrome/Edge ``BrowserContext`` is
reused for every download in a GUI session, so the cold-start SSO
redirect chain is paid ONCE per launch instead of per document.
"""

from __future__ import annotations

import atexit
import datetime as dt
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
# Persistent browser profiles (cookies / SSO tokens / session storage) live in
# the user's home dir so they survive across runs and are shared across all
# documents downloaded in any session. The tool detects installed browser
# folders under LOCALAPPDATA, prefers Chrome when both Chrome and Edge exist,
# then launches a private tool-owned profile for the selected browser.
PROFILE_BASE_DIR = (Path.home() / ".intel_doc_downloader").resolve()
INTEL_PROXY = "http://child-prc.intel.com:913"
__version__ = "0.1.0"

# Packages we expect on the system. tkinter ships with CPython on Windows so
# we don't pip-install it, but we still check it (if it's missing the GUI
# itself would have failed to import already).
REQUIRED_PACKAGES: list[tuple[str, str, str]] = [
    # (import_name, pip_name, friendly_label)
    ("playwright",      "playwright",      "playwright (Chrome/Edge automation for cdrdv2 SSO downloads)"),
]


@dataclass(frozen=True)
class BrowserChoice:
    key: str
    label: str
    channel: str
    system_user_data_dir: Path
    executable_paths: tuple[Path, ...]
    profile_dir: Path


def _local_appdata() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata)
    return Path.home() / "AppData" / "Local"


def _program_files() -> tuple[Path, ...]:
    paths: list[Path] = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        value = os.environ.get(env_name)
        if value:
            path = Path(value)
            if path not in paths:
                paths.append(path)
    return tuple(paths)


def _browser_candidates() -> list[BrowserChoice]:
    local_appdata = _local_appdata()
    program_files = _program_files()
    chrome_exes = tuple(
        [local_appdata / "Google" / "Chrome" / "Application" / "chrome.exe"]
        + [root / "Google" / "Chrome" / "Application" / "chrome.exe" for root in program_files]
    )
    edge_exes = tuple(
        [local_appdata / "Microsoft" / "Edge" / "Application" / "msedge.exe"]
        + [root / "Microsoft" / "Edge" / "Application" / "msedge.exe" for root in program_files]
    )
    return [
        BrowserChoice(
            key="chrome",
            label="Google Chrome",
            channel="chrome",
            system_user_data_dir=local_appdata / "Google" / "Chrome" / "User Data",
            executable_paths=chrome_exes,
            profile_dir=PROFILE_BASE_DIR / "chrome_profile",
        ),
        BrowserChoice(
            key="edge",
            label="Microsoft Edge",
            channel="msedge",
            system_user_data_dir=local_appdata / "Microsoft" / "Edge" / "User Data",
            executable_paths=edge_exes,
            profile_dir=PROFILE_BASE_DIR / "edge_profile",
        ),
    ]


def _browser_available(browser: BrowserChoice) -> bool:
    return browser.system_user_data_dir.exists() or any(
        path.exists() for path in browser.executable_paths
    )


def select_supported_browser() -> BrowserChoice:
    for browser in _browser_candidates():
        if _browser_available(browser):
            return browser
    searched_lines: list[str] = []
    for browser in _browser_candidates():
        searched_lines.append(f"- {browser.system_user_data_dir}")
        searched_lines.extend(f"- {path}" for path in browser.executable_paths)
    searched = "\n".join(searched_lines)
    raise RuntimeError(
        "No supported browser installation/profile found. Install/sign in with "
        "Google Chrome or Microsoft Edge, then retry.\n\nChecked:\n"
        f"{searched}"
    )


_AUTH_COOKIE_NAMES = ("estsauthpersistent", "estsauth", "estsauthlight")


def _profile_cookie_db(profile_dir: Path) -> Path | None:
    for cookie_db in (
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
    ):
        if cookie_db.exists():
            return cookie_db
    return None


def _cookie_db_has_auth_cookie(cookie_db: Path) -> bool:
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="intel_doc_cookies_", delete=False) as temp_file:
            temp_name = temp_file.name
        shutil.copy2(cookie_db, temp_name)
        with sqlite3.connect(temp_name) as conn:
            placeholders = ",".join("?" for _ in _AUTH_COOKIE_NAMES)
            row = conn.execute(
                f"SELECT 1 FROM cookies WHERE lower(name) IN ({placeholders}) LIMIT 1",
                _AUTH_COOKIE_NAMES,
            ).fetchone()
            return row is not None
    except Exception:
        return False
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass


def _profile_has_sso_cookie(profile_dir: Path) -> bool:
    cookie_db = _profile_cookie_db(profile_dir)
    if cookie_db is None:
        return False
    return _cookie_db_has_auth_cookie(cookie_db)


def _clear_cookie_db_auth_cookies(cookie_db: Path) -> None:
    try:
        with sqlite3.connect(cookie_db) as conn:
            placeholders = ",".join("?" for _ in _AUTH_COOKIE_NAMES)
            conn.execute(
                f"DELETE FROM cookies WHERE lower(name) IN ({placeholders})",
                _AUTH_COOKIE_NAMES,
            )
            conn.commit()
    except Exception:
        pass


def _clear_profile_sso_cookies(profile_dir: Path) -> None:
    for cookie_db in (
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
    ):
        if cookie_db.exists():
            _clear_cookie_db_auth_cookies(cookie_db)


def _login_ready_marker(profile_dir: Path) -> Path:
    return profile_dir / ".intel_doc_login_ready"


def _profile_has_ready_sso(profile_dir: Path) -> bool:
    return _login_ready_marker(profile_dir).exists() and _profile_has_sso_cookie(profile_dir)


def _mark_profile_login_ready(profile_dir: Path) -> None:
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        _login_ready_marker(profile_dir).write_text(str(dt.datetime.now()), encoding="utf-8")
    except Exception:
        pass


def _clear_profile_login_ready(profile_dir: Path) -> None:
    try:
        _login_ready_marker(profile_dir).unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Curated common documents
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommonDoc:
    doc_id: str
    platform: str
    category: str
    title: str


COMMON_DOCUMENTS: list[CommonDoc] = [
    #sym:COMMON_DOCUMENTS
    # ===== Oak Stream (OKS / Diamond Rapids) =====
        # -- BMC --
        CommonDoc("824508", "OKS", "BMC",        "Beyond SMM OKS Architecture Specification"),
        CommonDoc("864991", "OKS", "BMC",        "Diamond Rapids OOB Accessible Registers"),
        # -- BWG --
        CommonDoc("823668", "OKS", "BWG",        "Intel Confidential Computing BIOS Developer's Guide"),
        CommonDoc("839071", "OKS", "BWG",        "Diamond Rapids Server Platform BIOS Developer's Guide"),
        # -- CXL --
        CommonDoc("869657", "OKS", "CXL",        "Oak Stream CXL Supplemental Validation Guide"),
        # -- Dashboard --
        CommonDoc("863599", "OKS", "Dashboard",        "OKS Dashboard"),
        # -- Debug --
        CommonDoc("835693", "OKS", "Debug",        "OKS Power-On & Reset Issue Debug Handbook"),
        CommonDoc("859423", "OKS", "Debug",        "OKS Power-On Checklist"),
        # -- EDS --
        CommonDoc("792359", "OKS", "EDS",        "Diamond Rapids Processor Architecture Specification"),
        CommonDoc("793272", "OKS", "EDS",        "Diamond Rapids Processor Registers Specification"),
        # -- HeatMap --
        CommonDoc("873155", "OKS", "HeatMap",        "Diamond Rapids Processor Test Capability"),
        # -- Memory --
        CommonDoc("867684", "OKS", "Memory",        "Diamond Rapids DDR Memory Validation Guide"),
        # -- MoW --
        CommonDoc("820238", "OKS", "MoW",        "Oak Stream MoW"),
        # -- PDG --
        CommonDoc("788196", "OKS", "PDG",        "Oak Stream 16-Channel Platform Design Guide"),
        CommonDoc("813596", "OKS", "PDG",        "Oak Stream 8-Channel Platform Design Guide"),
        CommonDoc("843581", "OKS", "Board",       "Oak Stream 16-Channel 2S in 19-Inch Design Feasibility"),
        CommonDoc("820599", "OKS", "Board",       "Oak Stream 16-Channel Platform Aggregator Board Design Archive"),
        CommonDoc("787006", "OKS", "Board",       "Oak Stream 16-Channel Platform Electrical Specification"),
        CommonDoc("823065", "OKS", "Board",       "Oak Stream 16-Channel Platform Johnson City 1 Design Archive"),
        CommonDoc("636258", "OKS", "Board",       "Oak Stream 16-Channel Platform Johnson City 2 Design Archive"),
        CommonDoc("636260", "OKS", "Board",       "Oak Stream 16-Channel Platform Pin List"),
        CommonDoc("827452", "OKS", "Board",       "Oak Stream 16-Channel Platform Marketing Development Platform 1 Design Archive"),
        CommonDoc("828483", "OKS", "Board",       "Oak Stream 16-Channel Platform Marketing Development Platform 2 Design Archive"),
        CommonDoc("786521", "OKS", "Board",       "Oak Stream 16-Channel Platform Thermal Mechanical Specification"),
        CommonDoc("821026", "OKS", "Board",       "Oak Stream Diamond Rapids 16-Channel Mackinaw City Design Archive"),
        CommonDoc("821025", "OKS", "Board",       "Oak Stream Platforms System Boards Design Archive"),
        CommonDoc("636262", "OKS", "Board",       "Oak Stream Platforms DC-SCM 2.1 Design Archive Enabling"),
        # -- RAS --
        CommonDoc("846674", "OKS", "RAS",        "Oak Stream RAS Technology Integration & Validation Guide"),
        # -- Sighting --
        CommonDoc("862869", "OKS", "Sighting",        "Diamond Rapids Sightings Report"),
        # -- Snapshot --
        CommonDoc("820874", "OKS", "Snapshot",        "CNDA Snapshot - Intel Xeon Oak Stream"),
        # -- SPI --
        CommonDoc("820596", "OKS", "SPI",        "Oak Stream Platform SPI Programming Guide"),
        # -- Tools --
        CommonDoc("821387", "OKS", "Tools",        "CScripts for Oak Stream Platforms"),
        CommonDoc("871932", "OKS", "Tools",        "Intel Remote FPGA Access Tool for Server Platforms"),
        CommonDoc("524152", "OKS", "Tools",        "SelfTest 7 - Windows x64"),
        CommonDoc("630398", "OKS", "Tools",        "Server Security Toolkit"),
        CommonDoc("803838", "OKS", "Tools",        "Signal Integrity Clock Jitter Tool"),
        CommonDoc("782966", "OKS", "Tools",        "Signal Integrity Integrated Channel Analysis Tool (ICAT) Suite for Windows"),
        CommonDoc("600218", "OKS", "Tools",        "Signal Integrity Intel Passive Component Checker Tool"),
        CommonDoc("619648", "OKS", "Tools",        "Signal Integrity Intel Platform Clock Jitter Analysis Tool"),
        CommonDoc("852568", "OKS", "Tools",        "Almondsville Thermal Mechanical Test Vehicle (TMTV) Application Note"),
        CommonDoc("917977", "OKS", "Tools",        "Diamond Rapids CPU Crash Log Content Decode Definition"),
        CommonDoc("917972", "OKS", "Tools",        "Diamond Rapids CPU Crash Log Quick Start Guide"),
        CommonDoc("620497", "OKS", "Tools",        "Memory Assistant for Intel Xeon Platforms"),
        CommonDoc("914412", "OKS", "Tools",        "Oak Stream Platform DDR Electrical Validation Tools and Methodology"),
        CommonDoc("913382", "OKS", "Tools",        "Oak Stream Platform Intel IO Margin Tool for Windows User Guide"),
        CommonDoc("871016", "OKS", "Tools",        "Oak Stream Platform Intel IO Margin Tool for Windows"),
        CommonDoc("871015", "OKS", "Tools",        "Oak Stream Platform Margin Testing"),
        CommonDoc("913381", "OKS", "Tools",        "Oak Stream Target Loader Rank Margining Tool (RMT)"),

    # ===== Birch Stream (BHS / GNR / SRF) =====
        # -- BMC --
        CommonDoc("634865", "BHS", "BMC",        "Memory-Mapped BMC Interface (MMBI)"),
        CommonDoc("779401", "BHS", "BMC",        "Birch Stream Memory-Mapped BMC Interface (MMBI)"),
        # -- Board --
        CommonDoc("636245", "BHS", "Board",        "Birch Stream-AP Pin List"),
        CommonDoc("636246", "BHS", "Board",        "Avenue City Design Archive"),
        CommonDoc("642710", "BHS", "Board",        "Birch Stream-SP Platform Design Archive (Beechnut City)"),
        CommonDoc("642711", "BHS", "Board",        "Birch Stream-SP Pin List"),
        # -- BWG --
        CommonDoc("647898", "BHS", "BWG",        "Birch Stream Platform BIOS Writers Guide"),
        # -- Debug --
        CommonDoc("616634", "BHS", "Debug",        "Intel Crash Log Technology (GNR / shared)"),
        CommonDoc("726890", "BHS", "Debug",        "Birch Stream Platform Issue Debug Handbook"),
        CommonDoc("772419", "BHS", "Debug",        "Enhanced Warning Log Spec"),
        CommonDoc("776519", "BHS", "Debug",        "BHS DDR5 and MRC Issue Debug Handbook"),
        CommonDoc("776833", "BHS", "Debug",        "BHS PCIe IIO Issue Debug Handbook"),
        CommonDoc("788995", "BHS", "Debug",        "BHS Intel UPI Debug Handbook"),
        # -- EDS --
        CommonDoc("637776", "BHS", "EDS",        "Granite Rapids Processor Registers Specification (EDS-R)"),
        CommonDoc("639866", "BHS", "EDS",        "Granite Rapids Processor Architecture Specification (EDS-A)"),
        CommonDoc("736624", "BHS", "EDS",        "Sierra Forest Processor Architecture Specification"),
        CommonDoc("737845", "BHS", "EDS",        "Sierra Forest Processor EDS Vol 2"),
        CommonDoc("779546", "BHS", "EDS",        "Clearwater Forest Processor Architecture Specification"),
        CommonDoc("783269", "BHS", "EDS",        "Clearwater Forest Processor Register Specification"),
        # -- HeatMap --
        CommonDoc("767399", "BHS", "HeatMap",        "Granite Rapids Platform Test Capability Heat Map"),
        CommonDoc("781726", "BHS", "HeatMap",        "SRF SP Heat Map"),
        # -- Memory --
        CommonDoc("845972", "BHS", "Memory",        "DC-Certified DDR5 - Xeon 6900P"),
        CommonDoc("845974", "BHS", "Memory",        "DC-Certified DDR5 - Xeon 6700P"),
        CommonDoc("847669", "BHS", "Memory",        "BHS 6-Channel DDR5 Memory Guide"),
        CommonDoc("848986", "BHS", "Memory",        "DC-Certified DDR5 - Xeon 6900E"),
        CommonDoc("865066", "BHS", "Memory",        "DC-Certified DDR5 - Xeon 6700E"),
        # -- MoW --
        CommonDoc("645322", "BHS", "MoW",        "Birch Stream MoW"),
        # -- Other --
        CommonDoc("635356", "BHS", "Other",        "Birch Stream-AP Platform Electrical Specification"),
        CommonDoc("639662", "BHS", "Other",        "Birch Stream-AP Platform Thermal Mechanical Specification"),
        CommonDoc("640801", "BHS", "Other",        "Birch Stream-SP Server and Granite Rapids Workstation Platforms Thermal Mechanical Specification"),
        CommonDoc("645781", "BHS", "Other",        "Birch Stream-SP Platform Electrical Specification"),
        CommonDoc("648416", "BHS", "Other",        "Birch Stream Self Boot Enabling Guide"),
        CommonDoc("749361", "BHS", "Other",        "Birch Stream Seamless Update Architecture Overview"),
        CommonDoc("762752", "BHS", "Other",        "Birch Stream Platform Signal Integrity Collateral List"),
        CommonDoc("819861", "BHS", "Other",        "Intel Xeon 6 Processors - Birch Stream Platform Performance and Power Optimization Guide"),
        CommonDoc("826015", "BHS", "Other",        "Performance Differences for Open-Page / Close-Page Policy"),
        CommonDoc("826021", "BHS", "Other",        "Intel MRT for BHS Technical Article"),
        CommonDoc("826894", "BHS", "Other",        "Birch Stream Platform Performance and Power Optimization Overview"),
        CommonDoc("826934", "BHS", "Other",        "Intel Xeon 6 Processors - Performance and Power Profiles - Default, Latency-Optimized Mode, and Other Options Technical Article"),
        # -- PDG --
        CommonDoc("633502", "BHS", "PDG",        "Birch Stream-SP Platform Design Guide"),
        CommonDoc("635354", "BHS", "PDG",        "Birch Stream-AP Platform Design Guide"),
        # -- RAS --
        CommonDoc("633972", "BHS", "RAS",        "Intel Seamless Update RAS Offload Spec"),
        CommonDoc("724564", "BHS", "RAS",        "Data Center Cloud DCDC RAS Offload"),
        CommonDoc("728644", "BHS", "RAS",        "Birch Stream Error Architecture and RAS"),
        CommonDoc("734308", "BHS", "RAS",        "Intel Seamless Birch Stream RasOffload Firmware Design Spec"),
        CommonDoc("742874", "BHS", "RAS",        "Birch Stream RAS Technology IVG"),
        CommonDoc("752114", "BHS", "RAS",        "BHS FW Deep Dive - RAS Offload"),
        CommonDoc("819352", "BHS", "RAS",        "BHS PRW SRF-SP RAS Test Plan"),
        CommonDoc("833837", "BHS", "RAS",        "BHS RAS Offload for Beyond SMM FW DevGuide"),
        # -- Sighting --
        CommonDoc("748867", "BHS", "Sighting",        "GNR Sighting Report"),
        CommonDoc("766980", "BHS", "Sighting",        "SRF-SP Sighting Report"),
        # -- Snapshot --
        CommonDoc("861272", "BHS", "Snapshot",        "CNDA Snapshot - Intel Xeon Birch Stream"),
        # -- SPI --
        CommonDoc("642713", "BHS", "SPI",        "Birch Stream Platform SPI Programming Guide"),
        # -- Test --
        CommonDoc("639663", "BHS", "Test",        "Orffs Corner and Gusty Bay Thermal/Mechanical Test Vehicle (TMTV) Application Guide"),
        CommonDoc("639664", "BHS", "Test",        "Orffs Corner Thermal Mechanical Test Vehicle (TMTV) Models and User Guide"),
        CommonDoc("815188", "BHS", "Test",        "Confidential Computing IVG for BHS"),
        CommonDoc("819351", "BHS", "Test",        "BHS PRW SRF-SP BIOS Test Plan"),
        CommonDoc("819356", "BHS", "Test",        "BHS PRW SRF-SP Intel SST Test Plan"),
        # -- Tools --
        CommonDoc("610667", "BHS", "Tools",        "PEI 5.0 (PCIe 5.0 Error Injection) Card"),
        CommonDoc("615177", "BHS", "Tools",        "Users Guide"),
        CommonDoc("637673", "BHS", "Tools",        "Linux*"),
        CommonDoc("637674", "BHS", "Tools",        "Windows* /"),
        CommonDoc("685970", "BHS", "Tools",        "BHS FITm User Guide"),
        CommonDoc("686308", "BHS", "Tools",        "BHS CScripts"),
        CommonDoc("726376", "BHS", "Tools",        "Birch Stream Platform Power-On Debug Handbook Tool Package Scripts"),
        CommonDoc("766100", "BHS", "Tools",        "Stitched RMT Available, Target Loader RMT (EFI)"),
        CommonDoc("766287", "BHS", "Tools",        "Intel IO Margin Tool"),
        CommonDoc("767303", "BHS", "Tools",        "User Guide"),
        CommonDoc("774184", "BHS", "Tools",        "User Guide"),
        CommonDoc("774192", "BHS", "Tools",        "Intel IO Margin Tool"),
        CommonDoc("789161", "BHS", "Tools",        "Autonomous Crash Dump (ACD)"),

    # ===== Eagle Stream (EGS / SPR / EMR) =====
        # -- BWG --
        CommonDoc("613938", "EGS", "BWG",        "SPR/EMR BIOS Writers Guide"),
        # -- Debug --
        CommonDoc("638982", "EGS", "Debug",        "EGS Crash Log"),
        CommonDoc("709596", "EGS", "Debug",        "SPR Debug Handbook - Memory"),
        CommonDoc("709598", "EGS", "Debug",        "SPR Debug Handbook - System Hang"),
        CommonDoc("709599", "EGS", "Debug",        "SPR Debug Handbook - IIO/PCIe"),
        # -- EDS --
        CommonDoc("606161", "EGS", "EDS",        "Emmitsburg PCH EDS"),
        CommonDoc("611488", "EGS", "EDS",        "SPR EDS Vol 1"),
        CommonDoc("612246", "EGS", "EDS",        "SPR EDS Vol 2 (EDS-R)"),
        CommonDoc("613206", "EGS", "EDS",        "SPR EDS Vol 3 (Electrical)"),
        # -- Memory --
        CommonDoc("795715", "EGS", "Memory",        "EMR DDR5 Memory Compatibility List"),
        CommonDoc("830379", "EGS", "Memory",        "Intel DC Certified DDR5 - 5th Gen Xeon"),
        # -- MoW --
        CommonDoc("610915", "EGS", "MoW",        "Eagle Stream MoW"),
        # -- PDG --
        CommonDoc("610826", "EGS", "PDG",        "Eagle Stream PDG"),
        # -- RAS --
        CommonDoc("610170", "EGS", "RAS",        "Intel Server 7/10nm RAS BIOS Spec"),
        CommonDoc("614168", "EGS", "RAS",        "EGS RAS Tech Integration & Validation Guide (older)"),
        CommonDoc("631674", "EGS", "RAS",        "EGS SPR RAS DDR5 HBM2e"),
        CommonDoc("638563", "EGS", "RAS",        "Eagle Stream Platform RAS Tech Integration & Validation Guide"),
        CommonDoc("644521", "EGS", "RAS",        "EGS PCIe / IIO RAS"),
        CommonDoc("644522", "EGS", "RAS",        "EGS Memory RAS Part I & II"),
        # -- Sighting --
        CommonDoc("631201", "EGS", "Sighting",        "Sapphire Rapids-SP Sightings Report"),
        CommonDoc("751262", "EGS", "Sighting",        "EMR-SP Sighting Report"),
        # -- Snapshot --
        CommonDoc("753311", "EGS", "Snapshot",        "CNDA Snapshot - Intel Xeon Eagle Stream"),
        # -- Test --
        CommonDoc("785240", "EGS", "Test",        "EGS TDX Test Plan"),
        # -- Tools --
        CommonDoc("630113", "EGS", "Tools",        "EagleStream CScripts"),

    # ===== Whitley / ICX =====
        # -- BWG --
        CommonDoc("594768", "Whitley", "BWG",        "3rd Gen Intel Xeon Scalable BWG"),
        # -- EDS --
        CommonDoc("547817", "Whitley", "EDS",        "Intel C620 Series Chipset PCH EDS"),
        CommonDoc("574451", "Whitley", "EDS",        "ICX-SP EDS Vol 1"),
        CommonDoc("574942", "Whitley", "EDS",        "ICX EDS Vol 2"),
        CommonDoc("575291", "Whitley", "EDS",        "ICX EDS Vol 3"),
        # -- MoW --
        CommonDoc("575523", "Whitley", "MoW",        "Whitley Cedar Island MoW"),
        # -- PDG --
        CommonDoc("574174", "Whitley", "PDG",        "Whitley PDG"),

    # ===== Generic =====
        # -- BMC --
        CommonDoc("641273", "Generic", "BMC",        "Intel Intelligent Power Node Manager External Interface Spec"),
        CommonDoc("648590", "Generic", "BMC",        "Intel System Management Specification"),
        # -- BWG --
        CommonDoc("630774", "Generic", "BWG",        "Intel SPS 6.0 ME BIOS Specification"),
        # -- Tools --
        CommonDoc("710389", "Generic", "Tools",        "Intel Platform Monitoring Technology (PMT) External Spec"),
        CommonDoc("779074", "Generic", "Tools",        "TPMI Software Platform Specification"),
    ] 
_COMMON_DOCUMENT_IDS = {doc.doc_id for doc in COMMON_DOCUMENTS}


# ---------------------------------------------------------------------------
# Intel filename classifier (lightweight; mirrors the downloader's logic)
# ---------------------------------------------------------------------------

_DOC_ID_RE  = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_REV_RE     = re.compile(
    # Captures versions like 'Rev_1_0', 'Rev 1.0', 'Rev-1', 'Rev1_0_BETA'.
    # The inner class includes '_' so multi-part versions don't get cut off.
    r"Rev[_\s\-]*([0-9A-Za-z](?:[0-9A-Za-z._\-]*[0-9A-Za-z])?)",
    re.IGNORECASE,
)
_DATE_CAL_RE = re.compile(r"(\d{4}[-_]\d{2}[-_]\d{2}|\d{8})")
_DATE_WW_RE  = re.compile(
    # Captures WW tokens, optionally with a sub-revision before the year,
    # e.g. 'WW21_2026', 'WW21_1_2026', 'WW21.2.2026', '2026_WW21_1'.
    r"(WW\s*\d{1,2}(?:[._\-\s]+\d{1,3})?[._\-\s]+\d{4}"
    r"|\d{4}[._\-\s]+WW\s*\d{1,2}(?:[._\-\s]+\d{1,3})?)",
    re.IGNORECASE,
)


# Platform / category taxonomy (shared by COMMON_DOCUMENTS and local scan).
# Detection rules below are intentionally small and ordered so we end up with a
# manageable category set (see _CATEGORY_RULES). For platform we look at brand
# tokens; everything we cannot classify falls into 'Generic'.
# NOTE: Python treats '_' as a word char, so plain ``\b`` won't break between
# '_' and 'OKS' inside '_OKS_'. We use alnum lookarounds instead.
_LB = r"(?<![A-Za-z0-9])"   # alnum left boundary (treats _ - . space as sep)
_RB = r"(?![A-Za-z0-9])"

_PLATFORM_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("OKS",     re.compile(rf"(?i){_LB}(?:OKS|DMR|Diamond[_\s\-]*Rapids|Oak[_\s\-]*Stream){_RB}")),
    ("BHS",     re.compile(rf"(?i){_LB}(?:BHS|GNR|Granite[_\s\-]*Rapids|SRF|Sierra[_\s\-]*Forest|CWF|Clearwater[_\s\-]*Forest|Birch[_\s\-]*Stream|Birchstream){_RB}")),
    ("EMR",     re.compile(rf"(?i){_LB}(?:EMR|Emerald[_\s\-]*Rapids){_RB}")),
    ("EGS",     re.compile(rf"(?i){_LB}(?:EGS|SPR|Sapphire[_\s\-]*Rapids|Eagle[_\s\-]*Stream){_RB}")),
    ("Whitley", re.compile(rf"(?i){_LB}(?:Whitley|ICX|Ice[_\s\-]*Lake){_RB}")),
]

_COMMON_PLATFORM_ORDER: dict[str, int] = {
    "OKS": 0,
    "EGS": 1,
    "BHS": 2,
    "Whitley": 3,
    "Generic": 4,
}


def common_platform_label(platform: str) -> str:
    return "EGS" if platform == "EMR" else platform


def common_doc_sort_key(doc: CommonDoc) -> tuple[int, str, str, int, str]:
    platform = common_platform_label(doc.platform)
    return (
        _COMMON_PLATFORM_ORDER.get(platform, 99),
        platform,
        doc.category.lower(),
        int(doc.doc_id),
        doc.title.lower(),
    )

# Order matters: BMC and RAS are checked first so user-stated overrides win.
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("BMC",       re.compile(rf"(?i){_LB}(?:OOB|BMC|MMBI|RunBMC|OpenBMC){_RB}")),
    ("RAS",       re.compile(rf"(?i){_LB}(?:RAS|RasOffload|Ras[_\s\-]*Offload|Error[_\s\-]*Arch){_RB}|RasOffload")),
    ("MoW",       re.compile(rf"(?i){_LB}(?:MoW|Monthly){_RB}")),
    ("HeatMap",   re.compile(r"(?i)Heat[_\s\-]*Map")),
    ("EDS",       re.compile(rf"(?i){_LB}EDS(?:[_\s\-]*(?:[ARE]|Vol[_\s\-]*\w+))?{_RB}")),
    ("BWG",       re.compile(rf"(?i){_LB}BWG{_RB}|BIOS\s*Writer'?s?\s*Guide|BIOS\s*Developer'?s?\s*Guide")),
    ("PDG",       re.compile(rf"(?i){_LB}PDG{_RB}|Platform\s*Design\s*Guide")),
    ("CXL",       re.compile(rf"(?i){_LB}CXL{_RB}")),
    ("Memory",    re.compile(r"(?i)Mem(?:ory)?[_\s\-]*Guide|MEM[_\s\-]*IVG|DC[_\s\-]*Certified.*DDR|Memory[_\s\-]*Compatibility")),
    ("Tools",     re.compile(rf"(?i)CScripts?|{_LB}FITm{_RB}|{_LB}RAK{_RB}|Simics")),
    ("Debug",     re.compile(r"(?i)Debug[_\s\-]*Handbook|Crash[_\s\-]*Log|Crashlog|POST.*Error[_\s\-]*Code|Enhanced[_\s\-]*Warning")),
    ("Test",      re.compile(rf"(?i)Test[_\s\-]*Plan|{_LB}TDX{_RB}.*Test")),
    ("Board",     re.compile(rf"(?i)Schematics?|{_LB}BOM{_RB}|Change[_\s\-]*List|Deviation")),
    ("SDM",       re.compile(rf"(?i)sdm[_\s\-]*vol|{_LB}SDM{_RB}")),
    ("Snapshot",  re.compile(rf"(?i)CNDA.*Snapshot|{_LB}Snapshot{_RB}")),
    ("Sighting",  re.compile(r"(?i)Sighting")),
    ("Dashboard", re.compile(r"(?i)Dashboard")),
]


def detect_platform(name: str) -> str:
    """Return the canonical platform tag for a filename, or 'Generic'."""
    for tag, pat in _PLATFORM_RULES:
        if pat.search(name):
            return tag
    return "Generic"


def detect_category(name: str) -> str:
    """Return the canonical category tag for a filename, or 'Other'.

    Rules are applied in priority order (BMC and RAS win over more specific
    tokens, per user requirement).
    """
    for tag, pat in _CATEGORY_RULES:
        if pat.search(name):
            return tag
    return "Other"


@dataclass
class ScannedDoc:
    file_path: Path
    doc_id: str
    doc_name: str
    version: str
    is_date_version: bool
    platform: str = "Generic"
    category: str = "Other"


_IGNORED_SCAN_SUFFIXES = {".txt"}
_COMMON_TITLE_STOPWORDS = {
    "a", "an", "and", "for", "of", "the", "to", "with",
    "guide", "intel", "linux", "platform", "processor", "processors",
    "user", "users", "windows",
}


def _normalized_match_text(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z]+", " ", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def _common_title_is_specific(normalized_title: str) -> bool:
    tokens = normalized_title.split()
    meaningful = [token for token in tokens if token not in _COMMON_TITLE_STOPWORDS]
    return len(tokens) >= 2 and len(normalized_title) >= 12 and bool(meaningful)


def _common_title_candidates() -> list[tuple[str, tuple[str, ...], CommonDoc]]:
    candidates: list[tuple[str, tuple[str, ...], CommonDoc]] = []
    for doc in COMMON_DOCUMENTS:
        normalized_title = _normalized_match_text(doc.title)
        if _common_title_is_specific(normalized_title):
            candidates.append((normalized_title, tuple(normalized_title.split()), doc))
    return sorted(candidates, key=lambda item: (len(item[1]), len(item[0])), reverse=True)


def _tokens_appear_in_order(needles: tuple[str, ...], haystack: list[str]) -> bool:
    pos = 0
    for token in haystack:
        if pos < len(needles) and token == needles[pos]:
            pos += 1
    return pos == len(needles)


def _extract_version(text: str) -> tuple[str, tuple[int, int], bool]:
    rev = _REV_RE.search(text)
    if rev:
        return rev.group(1).strip(), rev.span(0), False
    date = _DATE_CAL_RE.search(text) or _DATE_WW_RE.search(text)
    if date:
        return date.group(1).strip(), date.span(0), True
    return "", (0, 0), False


def _match_common_document_by_title(name: str) -> CommonDoc | None:
    normalized_stem = _normalized_match_text(Path(name).stem)
    normalized_name = f" {normalized_stem} "
    name_tokens = normalized_stem.split()
    for normalized_title, title_tokens, doc in _common_title_candidates():
        if f" {normalized_title} " in normalized_name:
            return doc
        if _tokens_appear_in_order(title_tokens, name_tokens):
            return doc
    return None


def classify_filename(name: str) -> ScannedDoc | None:
    """Parse a filename into (doc_id, name, version).

    Prefer a standalone 6-digit ID in the filename. If there is no ID, fall
    back to matching a specific common-document title in the filename.
    """
    stem = Path(name).stem
    id_match = _DOC_ID_RE.search(stem)
    if not id_match:
        common_doc = _match_common_document_by_title(name)
        if common_doc is None:
            return None
        version, token_span, is_date = _extract_version(stem)
        leftover = stem
        if version:
            s, e = token_span
            leftover = leftover[:s] + " " + leftover[e:]
        doc_name = re.sub(r"[\s_\-]+", " ", leftover).strip(" _-") or common_doc.title
        return ScannedDoc(
            Path(name), common_doc.doc_id, doc_name, version, is_date,
            platform=common_platform_label(common_doc.platform),
            category=common_doc.category,
        )
    doc_id = id_match.group(1)
    id_start, id_end = id_match.span(0)
    masked = stem[:id_start] + " " * (id_end - id_start) + stem[id_end:]

    version, token_span, is_date = _extract_version(masked)
    if not version:
        # No rev/date token, but we DO have a doc_id -> still keep it
        # (user rule: only files without a doc_id are ignored).
        token_span = (id_end, id_end)

    leftover = stem
    for s, e in sorted([id_match.span(0), token_span], reverse=True):
        leftover = leftover[:s] + " " + leftover[e:]
    doc_name = re.sub(r"[\s_\-]+", " ", leftover).strip(" _-") or doc_id
    return ScannedDoc(
        Path(name), doc_id, doc_name, version, is_date,
        platform=detect_platform(name),
        category=detect_category(name),
    )


def scan_folder(
    folder: Path,
    *,
    exclude_doc_ids: set[str] | None = None,
) -> dict[str, list[ScannedDoc]]:
    """Recursively scan a folder; return {doc_id: [ScannedDoc, ...]}."""
    grouped: dict[str, list[ScannedDoc]] = {}
    if not folder.exists() or not folder.is_dir():
        return grouped
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in _IGNORED_SCAN_SUFFIXES:
            continue
        parsed = classify_filename(path.name)
        if parsed is None:
            continue
        if exclude_doc_ids is not None and parsed.doc_id in exclude_doc_ids:
            continue
        scanned = ScannedDoc(path, parsed.doc_id, parsed.doc_name,
                             parsed.version, parsed.is_date_version,
                             parsed.platform, parsed.category)
        grouped.setdefault(scanned.doc_id, []).append(scanned)
    return grouped


def _version_key(version: str) -> tuple:
    parts: list[tuple[int, Any]] = []
    for part in re.split(r"([0-9]+)", version or ""):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    return tuple(parts)


def _date_key(version: str) -> tuple[int, int, int]:
    """Sort key for date-style version tokens.

    Returns ``(valid, ordinal, subrev)`` so newer dates -> larger tuple.
    Sub-revision rule: for the same year+WW, a higher sub-rev (e.g.
    ``WW21_2_2026``) is considered newer than a lower sub-rev
    (``WW21_1_2026``), and any sub-rev is newer than no sub-rev
    (``WW21_2026`` -> subrev 0).
    """
    text = (version or "").strip()
    cal = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", text) \
          or re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", text)
    if cal:
        try:
            return (1, dt.date(int(cal.group(1)), int(cal.group(2)), int(cal.group(3))).toordinal(), 0)
        except ValueError:
            return (0, 0, 0)
    # Match WW token with optional sub-revision before the year, e.g.
    #   WW21_2026          -> week=21, year=2026, subrev=0
    #   WW21_1_2026        -> week=21, year=2026, subrev=1
    #   WW21.2.2026        -> week=21, year=2026, subrev=2
    #   2026_WW21          -> week=21, year=2026, subrev=0
    ww = re.search(r"(?i)WW\s*(\d{1,2})(?:[._\-\s]+(\d{1,3}))?[._\-\s]+(\d{4})", text)
    if ww:
        try:
            week = int(ww.group(1))
            subrev = int(ww.group(2)) if ww.group(2) else 0
            year = int(ww.group(3))
            ordinal = dt.date.fromisocalendar(year, week, 1).toordinal()
            return (1, ordinal, subrev)
        except (ValueError, IndexError):
            return (0, 0, 0)
    ww2 = re.search(r"(?i)(\d{4})[._\-\s]+WW\s*(\d{1,2})(?:[._\-\s]+(\d{1,3}))?", text)
    if ww2:
        try:
            year = int(ww2.group(1))
            week = int(ww2.group(2))
            subrev = int(ww2.group(3)) if ww2.group(3) else 0
            ordinal = dt.date.fromisocalendar(year, week, 1).toordinal()
            return (1, ordinal, subrev)
        except (ValueError, IndexError):
            return (0, 0, 0)
    return (0, 0, 0)


def pick_latest_local(docs: list[ScannedDoc]) -> ScannedDoc:
    if len(docs) == 1:
        return docs[0]
    dated = [d for d in docs if d.is_date_version]
    if dated:
        return max(dated, key=lambda d: _date_key(d.version))
    return max(docs, key=lambda d: _version_key(d.version))


# ---------------------------------------------------------------------------
# Dependency preflight (runs BEFORE the GUI is shown)
# ---------------------------------------------------------------------------

def _missing_packages() -> list[tuple[str, str, str]]:
    missing: list[tuple[str, str, str]] = []
    for import_name, pip_name, label in REQUIRED_PACKAGES:
        try:
            __import__(import_name)
        except ImportError:
            missing.append((import_name, pip_name, label))
    return missing


def _pip_install(pip_name: str, log_cb: Callable[[str], None]) -> bool:
    """Install a package via pip + Intel proxy and stream output live."""
    cmd = [sys.executable, "-m", "pip", "install",
           f"--proxy={INTEL_PROXY}", pip_name]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as error:  # noqa: BLE001
        log_cb(f"failed to launch pip: {error}\n")
        return False

    output_queue: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                output_queue.put(line)
        except Exception as error:  # noqa: BLE001
            output_queue.put(f"[pip output reader error: {error}]\n")
        finally:
            output_queue.put(None)

    threading.Thread(target=reader, name="PipInstallOutput", daemon=True).start()

    last_output = time.monotonic()
    reader_done = False
    while True:
        try:
            item = output_queue.get(timeout=0.2)
            if item is None:
                reader_done = True
            else:
                log_cb(item)
                last_output = time.monotonic()
        except queue.Empty:
            pass

        if proc.poll() is not None and reader_done:
            break

        now = time.monotonic()
        if now - last_output >= 10.0:
            log_cb("[pip still running; waiting for more output...]\n")
            last_output = now

    return proc.returncode == 0


def preflight_dependencies() -> bool:
    """Show a modal dialog for mandatory dependencies.

    Returns True only after required packages are available. Playwright is
    mandatory for the browser-based Intel SSO/download flow.
    """
    missing = _missing_packages()
    if not missing:
        return True

    root = tk.Tk()
    root.title("Intel Document Manager - dependency check")
    root.geometry("520x360")
    root.minsize(520, 360)
    root.configure(bg="#F3F5F9")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    proceed = {"v": False}

    ttk.Label(root, text="Playwright is required before this tool can start.",
              font=("Segoe UI Semibold", 11), background="#F3F5F9").pack(
        anchor="w", padx=16, pady=(14, 6))

    ttk.Label(root,
              text="Please click Install to download the required browser automation package via the Intel proxy.",
              font=("Segoe UI", 9), background="#F3F5F9",
              foreground="#4B5563", wraplength=480, justify="left").pack(
        anchor="w", padx=16, pady=(0, 8))

    list_frame = tk.Frame(root, bg="#FFFFFF", highlightbackground="#D6DBE3",
                          highlightthickness=1)
    list_frame.pack(fill="x", padx=16, pady=(0, 10))
    for _, _, label in missing:
        tk.Label(list_frame, text=" - " + label, anchor="w",
                 bg="#FFFFFF", fg="#1F2933",
                 font=("Segoe UI", 10)).pack(fill="x", padx=10, pady=2)

    log = scrolledtext.ScrolledText(root, height=7, wrap=tk.WORD,
                                    font=("Consolas", 9),
                                    bg="#1E2530", fg="#DCE3EC")
    log.pack(fill="both", expand=True, padx=16, pady=(0, 10))
    log.insert(tk.END, f"Will install via Intel proxy: {INTEL_PROXY}\n\n")

    status_var = tk.StringVar(value="Waiting for Install.")
    ttk.Label(root, textvariable=status_var, background="#F3F5F9",
              foreground="#4B5563", font=("Segoe UI", 9)).pack(
        anchor="w", padx=16, pady=(0, 8))

    btn_row = ttk.Frame(root)
    btn_row.pack(fill="x", padx=16, pady=(0, 14))

    def append_log(text: str) -> None:
        def write() -> None:
            try:
                log.insert(tk.END, text)
                log.see(tk.END)
            except Exception:
                pass
        root.after(0, write)

    def set_status(text: str) -> None:
        root.after(0, lambda: status_var.set(text))

    def do_install() -> None:
        install_btn.configure(state="disabled")
        exit_btn.configure(state="disabled")

        def worker() -> None:
            ok_all = True
            for _, pip_name, label in missing:
                set_status(f"Installing {label}...")
                append_log(f"\n>>> {sys.executable} -m pip install --proxy={INTEL_PROXY} {pip_name}\n")
                ok = _pip_install(pip_name, append_log)
                append_log(("OK" if ok else "FAILED") + f" - {label}\n")
                if not ok:
                    ok_all = False

            # Verify imports succeed.
            set_status("Verifying installed packages...")
            still_missing = _missing_packages()
            if still_missing:
                append_log("\nStill missing after install: "
                           + ", ".join(n for n, _, _ in still_missing) + "\n")
                set_status("Install did not complete. Retry or exit.")
                root.after(0, lambda: messagebox.showerror(
                    "Dependencies",
                    "Playwright is still missing. This tool cannot start until it is installed.\n\n"
                    "See the live pip log, then retry Install or click Exit.",
                    parent=root,
                ))
                root.after(0, lambda: install_btn.configure(state="normal"))
                root.after(0, lambda: exit_btn.configure(state="normal"))
                return

            append_log("\nAll dependencies installed successfully.\n")
            if ok_all:
                proceed["v"] = True
                set_status("Dependencies installed successfully.")
                root.after(400, root.destroy)
            else:
                set_status("Install failed. Retry or exit.")
                root.after(0, lambda: messagebox.showwarning(
                    "Dependencies",
                    "Playwright failed to install. This tool cannot start without it.\n\n"
                    "See the live pip log, then retry Install or click Exit.",
                    parent=root,
                ))
                root.after(0, lambda: install_btn.configure(state="normal"))
                root.after(0, lambda: exit_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    install_btn = tk.Button(btn_row, text="Install Playwright", command=do_install,
                            bg="#16A34A", fg="#FFFFFF",
                            activebackground="#15803D", activeforeground="#FFFFFF",
                            relief="flat", padx=16, pady=6,
                            font=("Segoe UI Semibold", 10), cursor="hand2")
    install_btn.pack(side="left")

    def do_exit() -> None:
        proceed["v"] = False
        root.destroy()
    exit_btn = ttk.Button(btn_row, text="Exit", command=do_exit)
    exit_btn.pack(side="left", padx=8)

    root.mainloop()
    return proceed["v"]


# ---------------------------------------------------------------------------
# Self-contained Intel cdrdv2 download engine (Playwright + persistent browser)
# ---------------------------------------------------------------------------

_AAD_HOSTS = (
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "login.windows.net",
    "login.microsoftonline.us",
    "sts.intel.com",
    "adfs.intel.com",
)
_AAD_BUTTON_SELECTORS = (
    "input#idSIButton9",
    "input[type=submit][value='Yes']",
    "input[type=submit][value='Continue']",
    "input[type=submit][value='Next']",
    "input[type=submit][value='Submit']",
    "button[type=submit]",
    "button:has-text('Yes')",
    "button:has-text('Continue')",
    "button:has-text('Stay signed in')",
    "button:has-text('Next')",
)


def _is_auth_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(host in lowered for host in _AAD_HOSTS)


def _auto_dismiss_aad(ctx) -> bool:
    """Click any AAD interstitial (KMSI 'Stay signed in?' / 'Yes' / 'Next'
    / 'Submit') on any page/frame currently in ``ctx`` that is on a known
    auth host. Also ticks the KMSI checkbox first so 'Yes' issues a
    persistent cookie (avoiding re-login on every launch). Returns True if
    something was clicked."""
    try:
        pages = list(ctx.pages)
    except Exception:
        return False
    for pg in pages:
        try:
            frames = list(pg.frames)
        except Exception:
            continue
        for fr in frames:
            try:
                url = (fr.url or "").lower()
            except Exception:
                continue
            if not any(h in url for h in _AAD_HOSTS):
                continue
            # Tick KMSI checkbox so Yes -> persistent ESTSAUTHPERSISTENT.
            try:
                cb = fr.locator("input#KmsiCheckboxField")
                if cb.count() > 0 and not cb.is_checked():
                    cb.check(timeout=1500)
            except Exception:
                pass
            for sel in _AAD_BUTTON_SELECTORS:
                try:
                    loc = fr.locator(sel)
                    if loc.count() == 0:
                        continue
                    target = loc.first
                    if not target.is_visible():
                        continue
                    target.click(timeout=2000)
                    return True
                except Exception:
                    continue
            # JS form-submit fallback for SAML 'Working...' pages.
            try:
                submitted = fr.evaluate(
                    "() => { const f = document.forms && "
                    "document.forms[0]; if (f) { f.submit(); "
                    "return true; } return false; }"
                )
                if submitted:
                    return True
            except Exception:
                pass
    return False


class IntelDocEngine:
    """Runs all Playwright browser operations on ONE dedicated worker thread,
    reusing a single ``BrowserContext`` across every download in this GUI
    session. SSO/cookie warm-up therefore happens ONCE on first use; every
    subsequent download is a warm navigation on the existing context."""

    BASE_URL = "https://cdrdv2.intel.com/v1/dl/getContent"
    # With per-second polling + auto-dismiss of AAD interstitials, downloads
    # that succeed typically start within a few seconds. 20s is enough head-
    # room; the engine will auto-retry once if the first attempt times out.
    FIRST_TIMEOUT_MS = 20_000
    NEXT_TIMEOUT_MS = 20_000

    def __init__(self, browser: BrowserChoice) -> None:
        self.browser = browser
        self.profile_dir = browser.profile_dir
        self._jobs: queue.Queue[Any] = queue.Queue()
        self._worker = threading.Thread(target=self._run_loop, daemon=True,
                                        name="IntelDocEngine")
        self._playwright = None
        self._context = None
        self._page = None
        self._first_done = False
        self._kmsi_clicked = False
        self._started = False
        self._first_run_headed = False

    # ---- public, called from Tk thread ----
    def submit(self, doc_id: str, out_dir: Path,
               log_cb: Callable[[str], None],
               done_cb: Callable[[str, str], None],
               force: bool = False) -> None:
        """Queue a download. ``log_cb`` is invoked from the worker thread for
        each log line. ``done_cb(outcome, filename_or_msg)`` is invoked when
        the job completes (outcome: 'updated' / 'current' / 'failed').
        If ``force`` is True, always download and overwrite any existing
        file at the suggested filename (no 'already have' shortcut)."""
        if not self._started:
            self._started = True
            self._worker.start()
        self._jobs.put((doc_id, out_dir, log_cb, done_cb, force))

    def shutdown(self) -> None:
        if self._started:
            self._jobs.put(None)  # poison pill -> worker tears down browser

    # ---- worker thread ----
    def _run_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                self._teardown()
                return
            doc_id, out_dir, log_cb, done_cb, force = job
            outcome, msg = "failed", ""
            try:
                outcome, msg = self._do_download(doc_id, out_dir, log_cb,
                                                 force=force)
            except Exception as error:  # noqa: BLE001
                msg = f"{type(error).__name__}: {error}"
                try:
                    log_cb(f"  ERROR: {msg}\n")
                except Exception:
                    pass
            try:
                done_cb(outcome, msg)
            except Exception:
                pass

    def _ensure_started(self, log_cb: Callable[[str], None]) -> None:
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright  # type: ignore
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        # Clean stale lock files left by a previous run that crashed.
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lp = self.profile_dir / lock_name
            try:
                if lp.exists() or lp.is_symlink():
                    lp.unlink()
            except Exception:
                pass
        # Detect first-time use by looking for a real Intel SSO cookie, not
        # merely for a Cookies DB. A partial login can create the DB before
        # authentication completes.
        first_run = not _profile_has_ready_sso(self.profile_dir)
        if first_run:
            log_cb("  no existing SSO session detected -- opening a VISIBLE "
                   f"{self.browser.label} window for first-time sign-in.\n"
                   "  Sign in to Intel SSO in the window that appears; the "
                   "download will start automatically when ready.\n"
                   "  (Subsequent runs will be silent/headless.)\n")
        else:
            log_cb(f"  starting persistent {self.browser.label} "
                   "(headless; reused for every download this session)...\n")
        log_cb(f"  selected browser: {self.browser.label} "
               f"({self.browser.system_user_data_dir})\n")
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel=self.browser.channel,
            headless=not first_run,
            accept_downloads=True,
            ignore_https_errors=True,
            timeout=30_000,
        )
        self._page = (self._context.pages[0]
                      if self._context.pages
                      else self._context.new_page())
        # When we had to launch headed, give the user more time to type
        # credentials / approve MFA before the per-attempt timeout fires.
        self._first_run_headed = first_run

    def _try_auto_kmsi(self) -> bool:
        """Delegate to the module-level helper but track whether we ever
        clicked something (used by diagnostics)."""
        if self._context is None:
            return False
        clicked = _auto_dismiss_aad(self._context)
        if clicked:
            self._kmsi_clicked = True
        return clicked

    def _page_diag(self) -> str:
        """Short string describing where the main page is parked, for
        diagnostics when no download has arrived yet."""
        if self._page is None:
            return ""
        try:
            url = self._page.url or ""
        except Exception:
            url = ""
        try:
            title = self._page.title() or ""
        except Exception:
            title = ""
        # Trim very long URLs (AAD URLs often exceed 500 chars).
        if len(url) > 140:
            url = url[:140] + "..."
        return f"{title!r} {url}".strip()

    def _do_download(self, doc_id: str, out_dir: Path,
                     log_cb: Callable[[str], None],
                     force: bool = False) -> tuple[str, str]:
        self._ensure_started(log_cb)
        from playwright.sync_api import (  # type: ignore
            Error as PWError, TimeoutError as PWTimeout,
        )

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        url = f"{self.BASE_URL}/{doc_id}?explicitVersion=true"
        per_attempt_s = ((self.FIRST_TIMEOUT_MS if not self._first_done
                          else self.NEXT_TIMEOUT_MS) / 1000.0)
        # First-ever run in a fresh profile: the browser is visible and the user
        # must sign in interactively. Give them several minutes.
        if self._first_run_headed and not self._first_done:
            per_attempt_s = 300.0
        # Cap auto-click spam per attempt: SAML pages can regenerate their
        # URL on every refresh so URL-based loop detection is unreliable.
        MAX_CLICKS_PER_ATTEMPT = 5
        MAX_ATTEMPTS = 2

        download = None
        last_diag_sig = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            click_note = ("manual sign-in mode"
                      if self._first_run_headed
                      else f"max {MAX_CLICKS_PER_ATTEMPT} auto-clicks")
            log_cb(f"  attempt {attempt}/{MAX_ATTEMPTS}: navigating to "
                 f"cdrdv2 for {doc_id} (timeout {int(per_attempt_s)}s, "
                 f"{click_note})...\n")
            t0 = time.monotonic()
            deadline = t0 + per_attempt_s

            # Flush any stale page state from the previous download (e.g.
            # a SAML form from the previous doc that, if re-submitted by
            # our auto-dismiss JS fallback, would re-trigger the wrong
            # download). about:blank kills all in-page forms/scripts.
            try:
                self._page.goto("about:blank",
                                wait_until="commit", timeout=5_000)
            except Exception:
                pass

            # Kick off the navigation. With a download response, goto() throws
            # "Download is starting" almost immediately -- expected and ignored.
            try:
                self._page.goto(url, wait_until="commit", timeout=8_000)
            except PWError as goto_err:
                if "Download is starting" not in str(goto_err):
                    pass

            kmsi_attempts = 0
            last_diag_t = 0.0
            last_click_t = 0.0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                slice_ms = int(min(1.0, max(0.2, remaining)) * 1000)
                try:
                    with self._page.expect_download(timeout=slice_ms) as info:
                        pass
                    download = info.value
                    break
                except PWTimeout:
                    now = time.monotonic()
                    # Click an interstitial at most every 3s, and at most
                    # MAX_CLICKS_PER_ATTEMPT times per attempt.
                    if (not self._first_run_headed
                            and kmsi_attempts < MAX_CLICKS_PER_ATTEMPT
                            and (now - last_click_t) >= 3.0):
                        if self._try_auto_kmsi():
                            kmsi_attempts += 1
                            last_click_t = now
                            log_cb(f"  clicked interstitial "
                                   f"(attempt {kmsi_attempts}/"
                                   f"{MAX_CLICKS_PER_ATTEMPT})\n")
                    if (kmsi_attempts == MAX_CLICKS_PER_ATTEMPT
                            and (now - last_click_t) < 1.5):
                        log_cb("  reached auto-click cap; will keep "
                               "waiting for the download passively.\n")
                    # Diagnose where the browser is parked, every ~5s.
                    if now - last_diag_t >= 5.0:
                        last_diag_t = now
                        diag = self._page_diag()
                        if diag and diag != last_diag_sig:
                            last_diag_sig = diag
                            log_cb(f"  [{int(now - t0)}s] stuck on: "
                                   f"{diag}\n")
                    continue
                except PWError as poll_err:
                    return "failed", f"{type(poll_err).__name__}: {poll_err}"

            if download is not None:
                break
            if attempt < MAX_ATTEMPTS:
                log_cb(f"  attempt {attempt} timed out after "
                       f"{int(per_attempt_s)}s; retrying...\n")

        if download is None:
            return "failed", (f"timeout after "
                              f"{MAX_ATTEMPTS} x {int(per_attempt_s)}s "
                              f"(no download event; last page: "
                              f"{last_diag_sig})")

        self._first_done = True
        elapsed = time.monotonic() - t0

        # Sanitize filename and decide outcome.
        filename = download.suggested_filename or f"{doc_id}.bin"
        filename = re.sub(r'[\\/:*?"<>|]', "_", filename).strip() or f"{doc_id}.bin"

        # Defensive: cdrdv2 filenames always start with the numeric doc id
        # (e.g. '792359_DMR_EDS-A_Rev_1_15.pdf'). If a stale form re-fired
        # the previous job's download, we'd see the wrong id here -- reject
        # rather than silently mis-reporting it as 'already have'.
        head = filename.split("_", 1)[0]
        if head.isdigit() and head != str(doc_id):
            try:
                download.cancel()
            except Exception:
                pass
            return "failed", (f"download mismatch: requested {doc_id} "
                              f"but got {filename} (stale page state?)")

        target = out_dir / filename

        if target.exists() and not force:
            try:
                download.cancel()
            except Exception:
                pass
            log_cb(f"  already have latest version: {filename} "
                   f"({elapsed:.1f}s)\n")
            return "current", filename

        if target.exists() and force:
            log_cb(f"  force download: overwriting existing "
                   f"{filename}...\n")

        try:
            log_cb(f"  download started ({elapsed:.1f}s to first byte); "
                   f"writing {filename}...\n")
            t_save = time.monotonic()
            download.save_as(str(target))
            save_elapsed = time.monotonic() - t_save
        except Exception as save_err:
            return "failed", f"save_as: {save_err}"
        try:
            size_mb = target.stat().st_size / (1024 * 1024)
            log_cb(f"  saved {filename} -- {size_mb:.1f} MB "
                   f"in {save_elapsed:.1f}s "
                   f"({(size_mb / save_elapsed) if save_elapsed > 0.1 else 0:.1f} MB/s)\n")
        except Exception:
            log_cb(f"  saved {filename} ({save_elapsed:.1f}s)\n")
        return "updated", filename

    def _teardown(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._playwright = None


# ---------------------------------------------------------------------------
# GUI -> engine adapter (replaces the old subprocess-based run_downloader)
# ---------------------------------------------------------------------------

def run_download(engine: IntelDocEngine, doc_id: str, out_dir: str,
                 log_widget: scrolledtext.ScrolledText, root: tk.Tk,
                 on_done: Callable[[str, str], None],
                 force: bool = False) -> None:
    """Submit one download to the shared engine. Log lines and the final
    outcome are marshalled back onto the Tk thread."""

    def append(text: str) -> None:
        log_widget.configure(state="normal")
        log_widget.insert(tk.END, text)
        log_widget.see(tk.END)

    def log_cb(line: str) -> None:
        root.after(0, append, line)

    def done_cb(outcome: str, msg: str) -> None:
        def finish() -> None:
            append(f"  [{outcome}] {msg}\n")
            on_done(outcome, msg)
        root.after(0, finish)

    engine.submit(doc_id, Path(out_dir), log_cb, done_cb, force=force)


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------

CHECK_ON = "\u2611"
CHECK_OFF = "\u2610"


def build_gui(browser: BrowserChoice) -> int:
    root = tk.Tk()
    root.title(f"Intel Document Manager v{__version__}")
    root.geometry("1280x860")

    # One engine per GUI session: reuses a single persistent browser context
    # so SSO / KMSI happens at most once per launch. The reference is mutable
    # so the manual re-login action can restart the browser context cleanly.
    engine_ref: dict[str, IntelDocEngine] = {"engine": IntelDocEngine(browser)}
    atexit.register(lambda: engine_ref["engine"].shutdown())

    def _on_close() -> None:
        try:
            engine_ref["engine"].shutdown()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.minsize(960, 680)
    root.configure(bg="#F3F5F9")

    # ---- styles ----
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    COLOR_BG, COLOR_CARD, COLOR_BORDER = "#F3F5F9", "#FFFFFF", "#D6DBE3"
    COLOR_PRIMARY, COLOR_PRIMARY_H = "#0068B5", "#004E8C"
    COLOR_TEXT, COLOR_MUTED = "#1F2933", "#5B6B7C"
    COLOR_STRIPE, COLOR_TICK = "#F7F9FC", "#DFF0FB"
    FONT_BODY = ("Segoe UI", 10)
    FONT_SECTION = ("Segoe UI Semibold", 10)
    FONT_MONO = ("Consolas", 9)
    style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=FONT_BODY)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("Card.TFrame", background=COLOR_CARD)
    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=FONT_BODY)
    style.configure("Card.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT, font=FONT_BODY)
    style.configure("Section.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT, font=FONT_SECTION)
    style.configure("Muted.TLabel", background=COLOR_CARD, foreground=COLOR_MUTED, font=("Segoe UI", 9))
    style.configure("Title.TLabel", background=COLOR_BG, foreground=COLOR_PRIMARY,
                    font=("Segoe UI Semibold", 16))
    style.configure("TButton", padding=(12, 6), font=FONT_BODY,
                    background="#E5EAF1", foreground=COLOR_TEXT, borderwidth=0)
    style.map("TButton", background=[("active", "#D5DCE6"), ("pressed", "#C7D0DC")])
    style.configure("Primary.TButton", padding=(16, 8),
                    font=("Segoe UI Semibold", 10),
                    background=COLOR_PRIMARY, foreground="white", borderwidth=0)
    style.map("Primary.TButton",
              background=[("active", COLOR_PRIMARY_H), ("pressed", COLOR_PRIMARY_H)],
              foreground=[("disabled", "#DDDDDD")])
    style.configure("Compact.TButton", padding=(10, 4),
                    font=("Segoe UI Semibold", 9),
                    background=COLOR_PRIMARY, foreground="white", borderwidth=0)
    style.map("Compact.TButton",
              background=[("active", COLOR_PRIMARY_H), ("pressed", COLOR_PRIMARY_H)],
              foreground=[("disabled", "#DDDDDD")])
    style.configure("Success.TButton", padding=(12, 6),
                    font=("Segoe UI Semibold", 10),
                    background="#107C41", foreground="white", borderwidth=0)
    style.map("Success.TButton",
              background=[("active", "#0E6F3A"), ("pressed", "#0B5F31")],
              foreground=[("disabled", "#DDDDDD")])
    style.configure("TNotebook", background=COLOR_BG, borderwidth=0, tabmargins=(8, 6, 8, 0))
    style.configure("TNotebook.Tab", padding=(20, 10),
                    font=("Segoe UI Semibold", 10),
                    background="#E5EAF1", foreground=COLOR_MUTED, borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", COLOR_CARD), ("active", "#EEF2F7")],
              foreground=[("selected", COLOR_PRIMARY), ("active", COLOR_TEXT)])
    style.configure("Treeview", rowheight=20, fieldbackground=COLOR_CARD,
                    background=COLOR_CARD, foreground=COLOR_TEXT, borderwidth=0, font=FONT_BODY)
    style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10),
                    background="#E5EAF1", foreground=COLOR_TEXT, padding=3, borderwidth=0)
    style.map("Treeview", background=[("selected", COLOR_PRIMARY)],
              foreground=[("selected", "white")])

    def make_card(parent: tk.Widget, **pack_kwargs: Any) -> ttk.Frame:
        outer = tk.Frame(parent, bg=COLOR_BORDER, padx=1, pady=1)
        outer.pack(**pack_kwargs)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=6)
        inner.pack(fill="both", expand=True)
        return inner

    status_var = tk.StringVar(value="Ready.")

    # ---- header ----
    header = ttk.Frame(root, padding=(20, 14, 20, 4))
    header.pack(fill="x")

    header_left = ttk.Frame(header)
    header_left.pack(side="left", fill="x", expand=True)
    ttk.Label(header_left, text="Intel Document Manager", style="Title.TLabel").pack(anchor="w")
    ttk.Label(header_left,
              text=("Scan local folders for Intel docs, refresh outdated revisions, "
                    "or fetch a Doc ID directly from cdrdv2."),
              foreground=COLOR_MUTED).pack(anchor="w")

    def do_relogin() -> None:
        if not messagebox.askyesno(
            "Re-login browser",
            "Use this when your web login password has expired, or when "
            "downloads keep failing because the saved browser credential is stale.\n\n"
            "This will close the current downloader browser session and open a "
            "new browser sign-in window to refresh credentials.\n\n"
            "Confirm to re-login now.",
            parent=root,
        ):
            return
        try:
            engine_ref["engine"].shutdown()
        except Exception:
            pass
        _clear_profile_login_ready(browser.profile_dir)
        _clear_profile_sso_cookies(browser.profile_dir)
        status_var.set("Opening browser sign-in...")
        if first_time_login_setup(browser, relogin=True):
            engine_ref["engine"] = IntelDocEngine(browser)
            status_var.set("Browser credentials refreshed.")
            messagebox.showinfo("Re-login browser", "Browser credentials refreshed.", parent=root)
        else:
            engine_ref["engine"] = IntelDocEngine(browser)
            status_var.set("Browser re-login was cancelled or incomplete.")

    header_actions = ttk.Frame(header)
    header_actions.pack(side="right", anchor="ne", padx=(16, 0))
    ttk.Button(header_actions, text="Re-login Browser", style="Success.TButton",
               command=do_relogin).pack(anchor="center")
    ttk.Label(
        header_actions,
        text="Use when password expired or downloads keep failing.",
        foreground=COLOR_MUTED,
        justify="center",
    ).pack(anchor="center", pady=(3, 0))

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=20, pady=(10, 6))

    # ======================================================================
    # TAB 1 - Folder Scan & Update
    # Layout uses a vertical PanedWindow so the Update Log is always visible
    # below the Scan Folder pane (the user can drag the splitter to resize).
    # ======================================================================
    tab_scan = ttk.Frame(notebook, padding=10)
    notebook.add(tab_scan, text="  Folder Scan & Update  ")

    info1 = make_card(tab_scan, fill="x")
    ttk.Label(info1, style="Card.TLabel", wraplength=1180, justify="left",
              text=("Recursively scans the chosen folder for Intel-named documents "
                  "(standalone 6-digit Doc ID, or a matching common-document title; "
                  "Rev/date tag optional). Tick rows and click "
                    "'Update' to fetch newer revisions from cdrdv2.intel.com.")
              ).pack(anchor="w")

    # Vertical splitter: scan area (top) / log area (bottom)
    paned = ttk.PanedWindow(tab_scan, orient="vertical")
    paned.pack(fill="both", expand=True, pady=(10, 0))

    # --- Scan pane ---
    scan_pane = tk.Frame(paned, bg=COLOR_BORDER, padx=1, pady=1)
    scan_card = ttk.Frame(scan_pane, style="Card.TFrame", padding=6)
    scan_card.pack(fill="both", expand=True)
    paned.add(scan_pane, weight=1)

    ttk.Label(scan_card, text="Scan Folder", style="Section.TLabel").pack(anchor="w")

    path_row = ttk.Frame(scan_card, style="Card.TFrame")
    path_row.pack(side="top", fill="x", pady=(2, 2))
    path_var = tk.StringVar(value=str(SCRIPT_DIR))
    # Shorter, fixed-width path entry instead of full-width expanding entry.
    entry = ttk.Entry(path_row, textvariable=path_var, width=55)
    entry.pack(side="left", padx=(0, 6))

    count_var = tk.StringVar(value="No folder scanned yet.")
    scan_state: dict[str, Any] = {"folder": None, "grouped": {}, "latest": {}}
    checked: set[str] = set()

    ttk.Label(scan_card, textvariable=count_var, style="Muted.TLabel"
              ).pack(side="bottom", anchor="w", pady=(2, 0))

    tree_holder = ttk.Frame(scan_card, style="Card.TFrame")
    tree_holder.pack(side="top", fill="both", expand=True, pady=(3, 3))

    columns = ("chk", "platform", "category", "file", "doc_id", "version", "folder")
    tree = ttk.Treeview(tree_holder, columns=columns, show="headings",
                        selectmode="none", height=8)
    headings = [
        ("chk",      CHECK_OFF, 36),
        ("platform", "Platform", 80),
        ("category", "Category", 100),
        ("file",     "Doc Name", 320),
        ("doc_id",   "Doc ID",   80),
        ("version",  "Reversion", 90),
        ("folder",   "File path (double-click to open)", 320),
    ]
    for col, text, width in headings:
        anchor = "center" if col == "chk" else "w"
        tree.heading(col, text=text, anchor=anchor)
        tree.column(col, width=width, anchor=anchor,
                    stretch=(col in ("file", "folder")))
    tree.tag_configure("odd", background=COLOR_STRIPE)
    tree.tag_configure("even", background=COLOR_CARD)
    tree.tag_configure("ticked", background=COLOR_TICK)
    vsb = ttk.Scrollbar(tree_holder, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    tree_holder.rowconfigure(0, weight=1)
    tree_holder.columnconfigure(0, weight=1)

    def row_tag(doc_id: str, index: int) -> str:
        if doc_id in checked:
            return "ticked"
        return "odd" if index % 2 else "even"

    def refresh_row(doc_id: str) -> None:
        idx = tree.index(doc_id)
        values = list(tree.item(doc_id, "values"))
        values[0] = CHECK_ON if doc_id in checked else CHECK_OFF
        tree.item(doc_id, values=values, tags=(row_tag(doc_id, idx),))

    def update_header_tick() -> None:
        ids = tree.get_children()
        tree.heading("chk",
                     text=CHECK_ON if (ids and all(d in checked for d in ids)) else CHECK_OFF,
                     anchor="center")

    def toggle(doc_id: str) -> None:
        if doc_id in checked:
            checked.discard(doc_id)
        else:
            checked.add(doc_id)
        refresh_row(doc_id)
        update_header_tick()

    def set_all(state_on: bool) -> None:
        for d in tree.get_children():
            if state_on:
                checked.add(d)
            else:
                checked.discard(d)
            refresh_row(d)
        update_header_tick()

    def do_scan() -> None:
        folder_str = path_var.get().strip()
        if not folder_str:
            messagebox.showwarning("Folder Scan", "Please choose a folder first.",
                                   parent=root)
            return
        folder = Path(folder_str)
        if not folder.is_dir():
            messagebox.showerror("Folder Scan", f"Not a directory:\n{folder}",
                                 parent=root)
            return
        status_var.set(f"Scanning {folder}...")
        root.update_idletasks()
        grouped = scan_folder(folder)
        scan_state["folder"] = folder
        scan_state["grouped"] = grouped
        scan_state["latest"] = {d: pick_latest_local(v) for d, v in grouped.items()}
        tree.delete(*tree.get_children())
        checked.clear()
        for i, (doc_id, docs) in enumerate(sorted(grouped.items())):
            latest = scan_state["latest"][doc_id]
            tag = "odd" if i % 2 else "even"
            tree.insert("", "end", iid=doc_id, values=(
                CHECK_OFF, latest.platform, latest.category,
                latest.file_path.name, doc_id, latest.version,
                str(latest.file_path.parent),
            ), tags=(tag,))
        update_header_tick()
        count_var.set(f"{len(grouped)} unique Doc IDs  |  "
                      f"{sum(len(d) for d in grouped.values())} files matched")
        status_var.set(f"Scan complete: found {len(grouped)} unique Doc IDs in {folder}.")

    def browse() -> None:
        chosen = filedialog.askdirectory(title="Choose folder to scan",
                                         initialdir=path_var.get() or str(SCRIPT_DIR))
        if chosen:
            path_var.set(chosen)
            do_scan()

    def do_update(force: bool = False) -> None:
        if not checked:
            messagebox.showwarning("Folder Scan",
                                   "Tick at least one row first.", parent=root)
            return
        folder = scan_state["folder"]
        if not folder:
            messagebox.showerror("Folder Scan", "Scan a folder first.", parent=root)
            return
        chosen = [d for d in tree.get_children() if d in checked]
        verb = "Force-download" if force else "Update"
        if not messagebox.askyesno(
            f"Confirm {verb.lower()}",
            (f"{verb} {len(chosen)} document(s) into:\n{folder}\n\n"
             + ("This will overwrite local copies with the latest\n"
                "version from cdrdv2 (no version check).\n\nProceed?"
                if force else "Proceed?")),
            parent=root,
        ):
            return
        update_batch["updated"].clear()
        update_batch["current"].clear()
        update_batch["failed"].clear()
        update_batch_total["n"] = len(chosen)
        for doc_id in chosen:
            # Always write the updated copy into the SAME folder where the
            # existing local file lives (so we overwrite-in-place rather
            # than dropping a stray copy in the scan root). Applies to both
            # regular Update and Force Download.
            latest = scan_state["latest"].get(doc_id)
            target_dir = latest.file_path.parent if latest is not None else folder
            update_queue.put((doc_id, target_dir, force))
        pump_queue()

    # Buttons live on the same row as the path entry now: Browse, Rescan, Update.
    ttk.Button(path_row, text="Browse...", command=browse).pack(side="left", padx=(0, 4))
    ttk.Button(path_row, text="Rescan", command=do_scan).pack(side="left", padx=(0, 4))
    ttk.Button(path_row, text="Update", style="Primary.TButton",
               command=lambda: do_update(False)).pack(side="left", padx=(0, 4))
    ttk.Button(path_row, text="Force Download",
               command=lambda: do_update(True)).pack(side="left")
    entry.bind("<Return>", lambda _e: do_scan())

    def on_click(event: Any) -> None:
        region = tree.identify_region(event.x, event.y)
        col = tree.identify_column(event.x)
        if region == "heading" and col == "#1":
            ids = tree.get_children()
            set_all(not (ids and all(d in checked for d in ids)))
            return
        if region != "cell":
            return
        row = tree.identify_row(event.y)
        if row:
            toggle(row)

    tree.bind("<Button-1>", on_click)

    def on_double_click(event: Any) -> None:
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row = tree.identify_row(event.y)
        if not row:
            return
        latest = scan_state.get("latest", {}).get(row)
        if latest is None:
            return
        folder = latest.file_path.parent
        try:
            if sys.platform.startswith("win"):
                # /select, highlights the file in Explorer.
                subprocess.Popen(["explorer", "/select,",
                                  str(latest.file_path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(latest.file_path)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("Open folder",
                                 f"Failed to open:\n{folder}\n\n{error}",
                                 parent=root)

    tree.bind("<Double-Button-1>", on_double_click)

    # --- Log pane ---
    log_pane = tk.Frame(paned, bg=COLOR_BORDER, padx=1, pady=1)
    log_card = ttk.Frame(log_pane, style="Card.TFrame", padding=6)
    log_card.pack(fill="both", expand=True)
    paned.add(log_pane, weight=2)

    ttk.Label(log_card, text="Update log", style="Section.TLabel").pack(anchor="w")
    log_scan = scrolledtext.ScrolledText(log_card, height=16, wrap=tk.WORD,
                                          font=FONT_MONO, bg="#1E2530", fg="#DCE3EC",
                                          insertbackground="white", borderwidth=0, relief="flat")
    log_scan.pack(fill="both", expand=True, pady=(3, 0))
    log_scan.insert(tk.END, "Update log will appear here.\n")

    # ---- Update queue / runner ----
    update_queue: queue.Queue[tuple[str, Path, bool]] = queue.Queue()
    update_busy = {"v": False}
    update_batch: dict[str, list[tuple[str, str]]] = {
        "updated": [], "current": [], "failed": [],
    }
    update_batch_total = {"n": 0}

    def doc_label(doc_id: str) -> str:
        latest = scan_state.get("latest", {}).get(doc_id) if scan_state else None
        if latest is not None:
            return f"{doc_id}  ({latest.file_path.name})"
        return doc_id

    def emit_update_summary() -> None:
        total = update_batch_total["n"]
        upd = update_batch["updated"]
        cur = update_batch["current"]
        fail = update_batch["failed"]
        log_scan.configure(state="normal")
        log_scan.insert(tk.END,
                        f"\n========== Update summary ({total} doc(s)) ==========\n")
        log_scan.insert(tk.END,
                        f"Updated        : {len(upd)}\n")
        for _, name in upd:
            log_scan.insert(tk.END, f"    + {name}\n")
        log_scan.insert(tk.END,
                        f"No need update : {len(cur)}\n")
        for _, name in cur:
            log_scan.insert(tk.END, f"    = {name}\n")
        log_scan.insert(tk.END,
                        f"Failed         : {len(fail)}\n")
        for _, name in fail:
            log_scan.insert(tk.END, f"    ! {name}\n")
        log_scan.insert(tk.END,
                        "===================================================\n")
        log_scan.see(tk.END)

    def pump_queue() -> None:
        if update_busy["v"]:
            return
        if update_queue.empty():
            return
        update_busy["v"] = True
        doc_id, folder, force = update_queue.get()
        log_scan.configure(state="normal")
        prefix = "force " if force else ""
        log_scan.insert(tk.END, f"\n--- {prefix}{doc_id} ---\n")
        log_scan.see(tk.END)
        status_var.set(f"{'Force-d' if force else 'U'}pdating {doc_id}...")
        name = doc_label(doc_id)

        def on_done(outcome: str, _msg: str) -> None:
            update_batch[outcome].append((doc_id, name))
            status_var.set(f"{doc_id} -> {outcome}")
            update_busy["v"] = False
            if update_queue.empty():
                emit_update_summary()
                try:
                    do_scan()
                except Exception:
                    pass
            else:
                pump_queue()

        run_download(engine_ref["engine"], doc_id, str(folder), log_scan, root, on_done,
                     force=force)

    # Auto-scan the tool's folder on startup.
    root.after(150, do_scan)

    # ======================================================================
    # TAB 2 - Common Documents Download
    # Layout (top -> bottom):
    #   1. Common Documents (filter + Download Selected + Save to + table) -- expands
    #   2. Manual Download by DOC ID (shares the Save-to from the top)
    #   3. Download log (compact, bottom)
    # ======================================================================
    tab_id = ttk.Frame(notebook, padding=10)
    notebook.add(tab_id, text="  Common Document Download  ")

    out_var = tk.StringVar(value=str(SCRIPT_DIR))
    id_busy = {"v": False}
    # Each queue item: (doc_id, friendly_name, is_batch, out_dir)
    id_queue: queue.Queue[tuple[str, str, bool, str]] = queue.Queue()
    common_title_map: dict[str, str] = {d.doc_id: d.title for d in COMMON_DOCUMENTS}
    common_doc_map: dict[str, CommonDoc] = {d.doc_id: d for d in COMMON_DOCUMENTS}
    download_batch: dict[str, list[tuple[str, str]]] = {
        "updated": [], "current": [], "failed": [],
    }
    download_batch_total = {"n": 0, "done": 0}
    doc_id_var = tk.StringVar()
    common_checked: set[str] = set()  # doc_ids ticked in the common-doc table

    # Vertical splitter: common-doc table on top, manual + log on the bottom.
    id_paned = ttk.PanedWindow(tab_id, orient="vertical")
    id_paned.pack(fill="both", expand=True)

    # ---- 1. Common documents (top pane, expands) ----
    common_pane = tk.Frame(id_paned, bg=COLOR_BORDER, padx=1, pady=1)
    common_card = ttk.Frame(common_pane, style="Card.TFrame", padding=6)
    common_card.pack(fill="both", expand=True)
    id_paned.add(common_pane, weight=1)
    head = ttk.Frame(common_card, style="Card.TFrame")
    head.pack(fill="x")
    ttk.Label(head, text="Common Documents", style="Section.TLabel").pack(side="left")
    ttk.Label(head, style="Muted.TLabel",
              text=f"  {len(COMMON_DOCUMENTS)} curated entries. "
                   "Click rows to tick; tick header to toggle all visible."
              ).pack(side="left")

    filter_row = ttk.Frame(common_card, style="Card.TFrame")
    filter_row.pack(fill="x", pady=(6, 6))

    ttk.Label(filter_row, text="Filter:", style="Card.TLabel").pack(side="left", padx=(0, 6))
    filter_var = tk.StringVar()
    filter_entry = ttk.Entry(filter_row, textvariable=filter_var, width=28)
    filter_entry.pack(side="left", padx=(0, 8))

    platform_var = tk.StringVar(value="All")
    platforms = ["All"] + sorted(
        {common_platform_label(d.platform) for d in COMMON_DOCUMENTS},
        key=lambda platform: (_COMMON_PLATFORM_ORDER.get(platform, 99), platform),
    )
    ttk.Label(filter_row, text="Platform:", style="Card.TLabel").pack(side="left", padx=(0, 4))
    ttk.Combobox(filter_row, textvariable=platform_var, values=platforms,
                 state="readonly", width=8).pack(side="left", padx=(0, 8))

    cat_var = tk.StringVar(value="All")
    categories = ["All"] + sorted({d.category for d in COMMON_DOCUMENTS})
    ttk.Label(filter_row, text="Category:", style="Card.TLabel").pack(side="left", padx=(0, 4))
    ttk.Combobox(filter_row, textvariable=cat_var, values=categories,
                 state="readonly", width=12).pack(side="left", padx=(0, 8))

    # Download Selected button + Save-to entry, all on the filter row.
    download_btn = ttk.Button(filter_row, text="Download Selected",
                              style="Compact.TButton")
    download_btn.pack(side="left", padx=(8, 8))
    organize_btn = ttk.Button(filter_row, text="Download & Organize",
                              style="Compact.TButton")
    organize_btn.pack(side="left", padx=(0, 8))
    ttk.Label(filter_row, text="Save to:", style="Card.TLabel").pack(side="left", padx=(0, 4))
    ttk.Entry(filter_row, textvariable=out_var).pack(side="left", fill="x",
                                                      expand=True, padx=(0, 4))
    ttk.Button(filter_row, text="Browse...",
               command=lambda: out_var.set(filedialog.askdirectory(
                   title="Choose output folder",
                   initialdir=out_var.get()) or out_var.get())
               ).pack(side="left")

    common_tree_holder = ttk.Frame(common_card, style="Card.TFrame")
    common_tree_holder.pack(side="top", fill="both", expand=True)
    common_columns = ("chk", "platform", "category", "doc_id", "title")
    common_tree = ttk.Treeview(common_tree_holder, columns=common_columns,
                                show="headings", selectmode="none", height=6)
    for col, text, width, anchor, stretch in [
        ("chk",      CHECK_OFF,   50, "center", False),
        ("platform", "Platform", 140, "center", False),
        ("category", "Category", 180, "w",      False),
        ("doc_id",   "Doc ID",   140, "w",      False),
        ("title",    "Doc Name", 520, "w",      True),
    ]:
        common_tree.heading(col, text=text, anchor=anchor)
        common_tree.column(col, width=width, anchor=anchor, stretch=stretch)
    common_tree.tag_configure("odd", background=COLOR_STRIPE)
    common_tree.tag_configure("even", background=COLOR_CARD)
    common_tree.tag_configure("ticked", background=COLOR_TICK)
    common_vsb = ttk.Scrollbar(common_tree_holder, orient="vertical",
                                command=common_tree.yview)
    common_tree.configure(yscrollcommand=common_vsb.set)
    common_tree.grid(row=0, column=0, sticky="nsew")
    common_vsb.grid(row=0, column=1, sticky="ns")
    common_tree_holder.rowconfigure(0, weight=1)
    common_tree_holder.columnconfigure(0, weight=1)

    # iid -> doc_id mapping (iid contains the unique counter)
    common_iid_to_doc: dict[str, str] = {}

    def common_row_tag(iid: str, index: int) -> str:
        doc_id = common_iid_to_doc.get(iid, "")
        if doc_id in common_checked:
            return "ticked"
        return "odd" if index % 2 else "even"

    def common_refresh_row(iid: str) -> None:
        idx = common_tree.index(iid)
        values = list(common_tree.item(iid, "values"))
        doc_id = common_iid_to_doc.get(iid, "")
        values[0] = CHECK_ON if doc_id in common_checked else CHECK_OFF
        common_tree.item(iid, values=values, tags=(common_row_tag(iid, idx),))

    def common_update_header_tick() -> None:
        iids = common_tree.get_children()
        all_on = bool(iids) and all(
            common_iid_to_doc.get(iid, "") in common_checked for iid in iids
        )
        common_tree.heading("chk",
                            text=CHECK_ON if all_on else CHECK_OFF,
                            anchor="center")

    def common_toggle(iid: str) -> None:
        doc_id = common_iid_to_doc.get(iid)
        if not doc_id:
            return
        if doc_id in common_checked:
            common_checked.discard(doc_id)
        else:
            common_checked.add(doc_id)
        common_refresh_row(iid)
        common_update_header_tick()

    def common_set_all_visible(state_on: bool) -> None:
        for iid in common_tree.get_children():
            doc_id = common_iid_to_doc.get(iid, "")
            if not doc_id:
                continue
            if state_on:
                common_checked.add(doc_id)
            else:
                common_checked.discard(doc_id)
            common_refresh_row(iid)
        common_update_header_tick()

    def refresh_common_list(*_args: Any) -> None:
        keyword = filter_var.get().strip().lower()
        plat = platform_var.get()
        cat = cat_var.get()
        common_tree.delete(*common_tree.get_children())
        common_iid_to_doc.clear()
        i = 0
        for doc in sorted(COMMON_DOCUMENTS, key=common_doc_sort_key):
            display_platform = common_platform_label(doc.platform)
            if plat != "All" and display_platform != plat:
                continue
            if cat != "All" and doc.category != cat:
                continue
            if keyword:
                blob = f"{doc.doc_id} {display_platform} {doc.category} {doc.title}".lower()
                if keyword not in blob:
                    continue
            iid = f"{doc.doc_id}::{i}"
            common_iid_to_doc[iid] = doc.doc_id
            tag = "ticked" if doc.doc_id in common_checked else (
                "odd" if i % 2 else "even"
            )
            chk = CHECK_ON if doc.doc_id in common_checked else CHECK_OFF
            common_tree.insert("", "end", iid=iid,
                               values=(chk, display_platform, doc.category,
                                       doc.doc_id, doc.title),
                               tags=(tag,))
            i += 1
        common_update_header_tick()

    def common_download_dir(doc_id: str, base_dir: str, organize: bool) -> str:
        if not organize:
            return base_dir
        doc = common_doc_map.get(doc_id)
        if doc is None:
            return base_dir
        platform = common_platform_label(doc.platform)
        return str(Path(base_dir) / platform / doc.category)

    filter_var.trace_add("write", refresh_common_list)
    platform_var.trace_add("write", refresh_common_list)
    cat_var.trace_add("write", refresh_common_list)
    refresh_common_list()

    def on_common_click(event: Any) -> None:
        region = common_tree.identify_region(event.x, event.y)
        col = common_tree.identify_column(event.x)
        if region == "heading" and col == "#1":
            iids = common_tree.get_children()
            all_on = bool(iids) and all(
                common_iid_to_doc.get(iid, "") in common_checked for iid in iids
            )
            common_set_all_visible(not all_on)
            return
        if region != "cell":
            return
        iid = common_tree.identify_row(event.y)
        if iid:
            common_toggle(iid)

    common_tree.bind("<Button-1>", on_common_click)

    def download_selected_common(organize: bool = False) -> None:
        if not common_checked:
            messagebox.showwarning("Common Documents",
                                   "Tick at least one row first.", parent=root)
            return
        # Preserve filter order so the batch is predictable.
        ordered: list[str] = []
        seen: set[str] = set()
        for iid in common_tree.get_children():
            doc_id = common_iid_to_doc.get(iid, "")
            if doc_id in common_checked and doc_id not in seen:
                ordered.append(doc_id)
                seen.add(doc_id)
        # Also include any ticked docs that are currently filtered out.
        for doc_id in common_checked:
            if doc_id not in seen:
                ordered.append(doc_id)
                seen.add(doc_id)

        out_dir = out_var.get().strip() or str(SCRIPT_DIR)
        target_hint = "\n\nDocuments will be saved under platform/category subfolders." if organize else ""
        if not messagebox.askyesno(
            "Confirm download" if not organize else "Confirm download and organize",
            f"Download {len(ordered)} common document(s) into:\n{out_dir}{target_hint}\n\nProceed?",
            parent=root,
        ):
            return
        download_batch["updated"].clear()
        download_batch["current"].clear()
        download_batch["failed"].clear()
        download_batch_total["n"] = len(ordered)
        download_batch_total["done"] = 0
        for doc_id in ordered:
            title = common_title_map.get(doc_id, "")
            name = f"{doc_id}  {title}" if title else doc_id
            target_dir = common_download_dir(doc_id, out_dir, organize)
            id_queue.put((doc_id, name, True, target_dir))
        pump_id_queue()

    download_btn.configure(command=download_selected_common)
    organize_btn.configure(command=lambda: download_selected_common(True))

    # ---- Bottom pane: Manual download + Log ----
    bottom_pane = tk.Frame(id_paned, bg=COLOR_BORDER, padx=1, pady=1)
    bottom_card = ttk.Frame(bottom_pane, style="Card.TFrame", padding=6)
    bottom_card.pack(fill="both", expand=True)
    id_paned.add(bottom_pane, weight=2)

    # ---- 2. Manual Download by DOC ID (shares Save-to) ----
    ttk.Label(bottom_card, text="Manual Download by DOC ID",
              style="Section.TLabel").pack(anchor="w")
    id_row = ttk.Frame(bottom_card, style="Card.TFrame")
    id_row.pack(fill="x", pady=(6, 0))
    ttk.Label(id_row, text="Doc ID:", style="Card.TLabel").pack(side="left", padx=(0, 6))
    id_entry = ttk.Entry(id_row, textvariable=doc_id_var, width=18,
                         font=("Segoe UI", 11))
    id_entry.pack(side="left", padx=(0, 10))
    ttk.Button(id_row, text="Download", style="Primary.TButton",
               command=lambda: submit_doc_id(doc_id_var.get())).pack(side="left")
    id_entry.bind("<Return>", lambda _e: submit_doc_id(doc_id_var.get()))

    # ---- 3. Download log (fills the rest of the bottom pane) ----
    ttk.Label(bottom_card, text="Download log",
              style="Section.TLabel").pack(anchor="w", pady=(6, 0))
    log_id = scrolledtext.ScrolledText(bottom_card, height=4, wrap=tk.WORD,
                                        font=FONT_MONO, bg="#1E2530", fg="#DCE3EC",
                                        insertbackground="white",
                                        borderwidth=0, relief="flat")
    log_id.pack(fill="both", expand=True, pady=(4, 0))

    def emit_download_summary() -> None:
        total = download_batch_total["n"]
        upd = download_batch["updated"]
        cur = download_batch["current"]
        fail = download_batch["failed"]
        log_id.configure(state="normal")
        log_id.insert(tk.END,
                      f"\n========== Download summary ({total} doc(s)) ==========\n")
        log_id.insert(tk.END, f"Downloaded   : {len(upd)}\n")
        for _, name in upd:
            log_id.insert(tk.END, f"    + {name}\n")
        log_id.insert(tk.END, f"Already have : {len(cur)}\n")
        for _, name in cur:
            log_id.insert(tk.END, f"    = {name}\n")
        log_id.insert(tk.END, f"Failed       : {len(fail)}\n")
        for _, name in fail:
            log_id.insert(tk.END, f"    ! {name}\n")
        log_id.insert(tk.END,
                      "=====================================================\n")
        log_id.see(tk.END)

    def pump_id_queue() -> None:
        if id_busy["v"]:
            return
        if id_queue.empty():
            return
        id_busy["v"] = True
        doc_id, name, is_batch, out_dir = id_queue.get()
        log_id.configure(state="normal")
        log_id.insert(tk.END, f"\n--- {doc_id} -> {out_dir} ---\n")
        log_id.see(tk.END)
        status_var.set(f"Downloading {doc_id}...")

        def on_done(outcome: str, _msg: str) -> None:
            if is_batch:
                download_batch[outcome].append((doc_id, name))
                download_batch_total["done"] += 1
            else:
                # Manual single-shot: print inline one-liner.
                mark = {"updated": "OK (downloaded)",
                        "current": "OK (already have latest)",
                        "failed": "FAILED"}[outcome]
                log_id.configure(state="normal")
                log_id.insert(tk.END, f"[{mark}] {doc_id}\n")
                log_id.see(tk.END)
            status_var.set(f"{doc_id}: {outcome}")
            id_busy["v"] = False
            if not id_queue.empty():
                pump_id_queue()
            else:
                if is_batch and download_batch_total["done"] >= download_batch_total["n"] \
                        and download_batch_total["n"] > 0:
                    emit_download_summary()
        run_download(engine_ref["engine"], doc_id, out_dir, log_id, root, on_done)

    def submit_doc_id(doc_id: str) -> None:
        doc_id = doc_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", doc_id):
            messagebox.showerror("Doc ID",
                                 "Enter a valid Intel cdrdv2 document number.",
                                 parent=root)
            return
        id_queue.put((doc_id, doc_id, False, out_var.get().strip() or str(SCRIPT_DIR)))
        pump_id_queue()

    # ---- status bar ----
    status_bar = ttk.Label(root, textvariable=status_var,
                           background="#E5EAF1", foreground=COLOR_TEXT,
                           padding=(10, 6), anchor="w")
    status_bar.pack(side="bottom", fill="x")

    root.mainloop()
    return 0


def first_time_login_setup(browser: BrowserChoice, *, relogin: bool = False) -> bool:
    """First-time/re-login UX: if there is no ready SSO session, show a popup,
    open a visible browser window pointed at cdrdv2, and wait until a real SSO
    cookie is detected. Returns True when the user continues after detection.
    Returns False if the user cancels. No-op (returns True) once a real SSO
    cookie exists, unless relogin=True forces a fresh browser credential check.
    """
    if not relogin and _profile_has_ready_sso(browser.profile_dir):
        return True

    import tkinter as tk
    from tkinter import ttk
    import threading

    state = {
        "ready": False,
        "cancelled": False,
        "browser_started": False,
        "browser_closed": False,
        "login_detected": False,
        "user_confirmed": False,
        "validating": False,
        "validation_failed": None,
        "error": None,
    }
    pw_obj: dict = {"ctx": None, "pw": None}

    def pw_worker() -> None:
        try:
            from playwright.sync_api import sync_playwright
            browser.profile_dir.mkdir(parents=True, exist_ok=True)
            if relogin:
                _clear_profile_sso_cookies(browser.profile_dir)
            pw = sync_playwright().start()
            pw_obj["pw"] = pw
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(browser.profile_dir),
                channel=browser.channel,
                headless=False,
                accept_downloads=True,
            )
            pw_obj["ctx"] = ctx
            if relogin:
                try:
                    ctx.clear_cookies()
                except Exception:
                    pass
            page = ctx.new_page()
            try:
                page.goto("https://cdrdv2.intel.com/",
                          wait_until="domcontentloaded",
                          timeout=60_000)
            except Exception:
                # Even if goto throws, the window is open -- user can navigate.
                pass
            state["browser_started"] = True
            # Idle loop. Do not auto-click AAD buttons during manual first-time
            # login: doing so can fight the password/MFA screens and make the
            # browser appear to switch pages while the user is typing.
            # Poll for a real SSO cookie and close the browser automatically
            # once login has completed.
            while not state["cancelled"] and not state["login_detected"]:
                try:
                    if page.is_closed():
                        break
                    try:
                        current_url = (page.url or "").lower()
                    except Exception:
                        current_url = ""
                    try:
                        cookies = ctx.cookies()
                    except Exception:
                        cookies = []
                    has_auth = any(
                        (c.get("name") or "").lower() in _AUTH_COOKIE_NAMES
                        for c in cookies
                    )
                    has_persistent = any(
                        (c.get("name") or "").lower() == "estsauthpersistent"
                        for c in cookies
                    )
                    if has_auth and not any(host in current_url for host in _AAD_HOSTS):
                        state["validation_failed"] = None
                        state["has_persistent"] = has_persistent
                        _mark_profile_login_ready(browser.profile_dir)
                        state["login_detected"] = True
                        break
                    page.wait_for_timeout(1000)
                except Exception:
                    break
            if not state["login_detected"] and not state["cancelled"]:
                state["browser_closed"] = True
        except Exception as error:  # noqa: BLE001
            state["error"] = str(error)
        finally:
            try:
                if pw_obj["ctx"] is not None:
                    pw_obj["ctx"].close()
            except Exception:
                pass
            try:
                if pw_obj["pw"] is not None:
                    pw_obj["pw"].stop()
            except Exception:
                pass

    root = tk.Tk()
    root.title("Intel Doc Manager -- Re-login" if relogin
               else "Intel Doc Manager -- First-time sign-in")
    try:
        root.geometry("780x460")
        root.minsize(780, 460)
    except Exception:
        pass

    if relogin:
        msg = (
            "Re-login browser credentials.\n\n"
            f"Using {browser.label}.\n\n"
            "Use this flow when your Intel web password expired, or downloads keep failing.\n"
            "The old browser cookies were cleared for this tool profile.\n\n"
            "Please finish Intel SSO manually in the browser window, including password "
            "and MFA if prompted. The tool will detect successful sign-in and close "
            "the browser automatically. After that, click the button below to continue."
        )
    else:
        msg = (
            "First-time setup detected.\n\n"
            f"Using {browser.label}.\n\n"
            "Please finish Intel SSO manually in the browser window,\n"
            "including password and MFA if prompted.\n\n"
            "The tool will detect successful sign-in and close the browser automatically.\n"
            "After that, click the button below to continue."
        )
    ttk.Label(root, text=msg, justify="left", padding=20,
              font=("Segoe UI", 12), wraplength=720).pack(anchor="w", fill="x")

    note = (
        "If you see a \"Something went wrong!\" page, just ignore it and "
        "continue signing in."
    )
    ttk.Label(root, text=note, justify="left", padding=(20, 0, 20, 12),
              foreground="#0B63CE", font=("Segoe UI Semibold", 11),
              wraplength=720).pack(anchor="w", fill="x")

    status_var = tk.StringVar(value="Opening browser...")
    ttk.Label(root, textvariable=status_var, padding=(20, 0),
              foreground="#555",
              font=("Segoe UI", 10), wraplength=720).pack(anchor="w", fill="x")

    btn_frame = ttk.Frame(root, padding=20)
    btn_frame.pack(fill="x", side="bottom")

    def on_done() -> None:
        if state.get("login_detected"):
            state["ready"] = True
            try:
                root.destroy()
            except Exception:
                pass
            return
        if state.get("browser_closed"):
            state["validation_failed"] = (
                "Browser was closed before sign-in completed. Please cancel "
                "and restart the tool to open the sign-in browser again."
            )
            return
        state["validation_failed"] = (
            "Sign-in has not been detected yet. Please finish login in the "
            "browser and wait for this button to become enabled."
        )

    def on_cancel() -> None:
        state["cancelled"] = True
        try:
            root.destroy()
        except Exception:
            pass

    done_btn = ttk.Button(btn_frame, text="I've signed in -- continue",
                          command=on_done, state="disabled")
    done_btn.pack(side="right", padx=4)
    ttk.Button(btn_frame, text="Cancel",
               command=on_cancel).pack(side="right", padx=4)

    # Intercept window-close as cancel.
    root.protocol("WM_DELETE_WINDOW", on_cancel)

    def tick() -> None:
        if state.get("ready"):
            try:
                root.destroy()
            except Exception:
                pass
            return
        if state.get("error"):
            status_var.set(f"Error: {state['error']}")
            done_btn.config(state="disabled")
        elif state.get("browser_closed"):
            status_var.set("Browser was closed before sign-in completed. "
                           "Click Cancel and restart the program.")
            done_btn.config(state="disabled")
        elif state.get("validating"):
            status_var.set("Checking SSO cookies...")
            done_btn.config(state="disabled")
        elif state.get("login_detected"):
            status_var.set("Sign-in detected. Browser closed automatically. "
                           "Click continue to enter the tool.")
            done_btn.config(state="normal")
        elif state.get("validation_failed"):
            status_var.set(state["validation_failed"])
            done_btn.config(state="disabled")
        elif state.get("browser_started"):
            status_var.set("Browser is open. Finish sign-in; the continue "
                           "button will enable automatically after detection.")
            done_btn.config(state="disabled")
        else:
            status_var.set("Opening browser...")
        try:
            if root.winfo_exists():
                root.after(500, tick)
        except Exception:
            pass

    root.after(100, tick)

    worker = threading.Thread(target=pw_worker, name="FirstTimeLogin",
                              daemon=True)
    worker.start()

    root.mainloop()

    # Signal worker to stop and wait for it (so the browser window closes).
    if not state["ready"]:
        state["cancelled"] = True
    worker.join(timeout=10)

    return bool(state["ready"]) and not state["cancelled"]


def main() -> int:
    # Step 1: dependency preflight.
    try:
        if not preflight_dependencies():
            return 1
    except Exception as error:  # noqa: BLE001
        # If preflight itself crashes (no tkinter), nothing we can do.
        try:
            print(f"Preflight failed: {error}", file=sys.stderr)
        except Exception:
            pass
        return 2
    # Step 2: select a supported local browser. Prefer Chrome when both Chrome
    # and Edge profile folders exist, then fall back to Edge.
    try:
        browser = select_supported_browser()
    except Exception as error:  # noqa: BLE001
        try:
            messagebox.showerror("No supported browser found", str(error))
        except Exception:
            print(f"No supported browser found: {error}", file=sys.stderr)
        return 4
    # Step 3: first-time SSO sign-in (only on a fresh profile).
    try:
        if not first_time_login_setup(browser):
            # User cancelled the first-time sign-in.
            return 3
    except Exception as error:  # noqa: BLE001
        # Non-fatal: fall through to the GUI and let the engine's own
        # headed fallback take over if cookies are still missing.
        try:
            print(f"First-time setup error: {error}", file=sys.stderr)
        except Exception:
            pass
    # Step 4: main GUI.
    return build_gui(browser)


if __name__ == "__main__":
    sys.exit(main())
