#!/usr/bin/env python3
"""Self-contained unified CUI for BIOS knob, FITm softstrap, BootGuard, and DAM operations.

This file is the automation entry point for AI agents. It contains the FITm
softstrap/BootGuard editor core and the BiosKnobsDataBin decoder/patcher core
inline, so it does not import or call any other project tool script.
"""

from __future__ import annotations

import argparse
import csv
import json
import lzma
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__version__ = "0.1.0"

DESCRIPTOR_SIGNATURE = b"\x5a\xa5\xf0\x0f"
REGION_NAMES = {0: "descriptor", 1: "bios", 2: "imd", 3: "gbe", 4: "pdr", 14: "pfr", 15: "reserved"}
ENABLE_VALUES = {0: "Disabled", 1: "Enabled"}
DISABLE_VALUES = {0: "Enabled", 1: "Disabled"}
BOOL_VALUES = {0: "0", 1: "1"}
FLASH_DENSITY_VALUES = {0: "512 KB", 1: "1 MB", 2: "2 MB", 3: "4 MB", 4: "8 MB", 5: "16 MB", 6: "32 MB", 7: "64 MB", 8: "128 MB", 15: "Second flash component not present"}
SPI_FREQ_VALUES = {0: "16.6 MHz", 1: "20 MHz", 2: "25 MHz", 3: "33.3 MHz", 4: "40 MHz", 5: "50 MHz", 6: "Reserved", 7: "Reserved"}
ESPI_FREQ_VALUES = {0: "20 MHz", 1: "25 MHz", 2: "33 MHz", 3: "50 MHz", 4: "66.67 MHz", 5: "Reserved", 6: "Reserved", 7: "Reserved"}
IO_MODE_VALUES = {0: "Single IO Mode", 1: "Single and Dual IO Mode", 2: "Single and Quad IO Mode", 3: "Single, Dual and Quad IO"}
AC_DC_VALUES = {0: "DC coupling", 1: "AC coupling"}
IIO_STACK_VALUES = {0: "PCIe/CXL", 1: "Intel UPI", 2: "Reserved defaults PCIe/CXL", 3: "Mixed mode"}
READ_ONLY_FIELDS = {"fit4.recordlength", "btg.contenttype", "btg.length", "btg.version", "btg.cvtype", "btg.crc8"}

MCU_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
MCU_LINE_COMMENT_RE = re.compile(r"//.*?$|;.*?$", re.MULTILINE)
MCU_HEX_LITERAL_RE = re.compile(r"(?i)\b0x([0-9a-f]+)\b")
MCU_HEX_SUFFIX_RE = re.compile(r"(?i)\b([0-9a-f]+)h\b")
MCU_DECIMAL_LITERAL_RE = re.compile(r"\b\d+\b")
MCU_DIRECTIVE_RE = re.compile(r"(?i)\b(db|dw|dd|dq)\b")
MCU_DIRECTIVE_WIDTHS = {"db": 1, "dw": 2, "dd": 4, "dq": 8}


def _strip_mcu_inc_comments(text: str) -> str:
    text = MCU_BLOCK_COMMENT_RE.sub("", text)
    text = MCU_LINE_COMMENT_RE.sub("", text)
    return text


def _mcu_literal_width(token: str) -> int:
    digits = token.lower().removeprefix("0x").removesuffix("h")
    if not digits:
        raise ValueError(f"Invalid numeric literal: {token!r}")
    return max(1, (len(digits) + 1) // 2)


def _mcu_emit_little_endian(value: int, width: int) -> bytes:
    if value < 0:
        raise ValueError("Negative MCU literals are not supported")
    return value.to_bytes(width, byteorder="little", signed=False)


def _parse_mcu_inc_line_literals(line: str) -> list[tuple[int, int]]:
    directive_match = MCU_DIRECTIVE_RE.search(line)
    directive_width = MCU_DIRECTIVE_WIDTHS.get(directive_match.group(1).lower()) if directive_match else None
    literals: list[tuple[int, int]] = []

    for match in MCU_HEX_LITERAL_RE.finditer(line):
        token = match.group(0)
        value = int(match.group(1), 16)
        literals.append((value, directive_width or _mcu_literal_width(token)))
    if literals:
        return literals

    for match in MCU_HEX_SUFFIX_RE.finditer(line):
        token = match.group(0)
        value = int(match.group(1), 16)
        literals.append((value, directive_width or _mcu_literal_width(token)))
    if literals:
        return literals

    if directive_width:
        for match in MCU_DECIMAL_LITERAL_RE.finditer(line):
            literals.append((int(match.group(0), 10), directive_width))
    return literals


def convert_mcu_inc_to_bin(input_path: str | Path) -> tuple[bytes, dict[str, int]]:
    source = Path(input_path)
    text = source.read_text(encoding="utf-8", errors="replace")
    text = _strip_mcu_inc_comments(text)
    output = bytearray()
    stats = {"lines_scanned": 0, "literals_found": 0, "bytes_emitted": 0}
    for raw_line in text.splitlines():
        stats["lines_scanned"] += 1
        for value, width in _parse_mcu_inc_line_literals(raw_line):
            output.extend(_mcu_emit_little_endian(value, width))
            stats["literals_found"] += 1
    stats["bytes_emitted"] = len(output)
    if not output:
        raise ValueError(f"No MCU numeric literals were found in {source}")
    return bytes(output), stats


def convert_mcu_bin_to_inc(input_path: str | Path) -> tuple[str, dict[str, int]]:
    source = Path(input_path)
    data = source.read_bytes()
    if not data:
        raise ValueError(f"Input MCU binary is empty: {source}")
    if len(data) % 4 != 0:
        raise ValueError(f"Input MCU binary size must be DWORD-aligned, got {len(data)} bytes")
    lines = []
    for offset in range(0, len(data), 4):
        value = int.from_bytes(data[offset:offset + 4], byteorder="little", signed=False)
        lines.append(f"dd {value:09x}h")
    stats = {"bytes_read": len(data), "dwords_emitted": len(lines), "lines_emitted": len(lines)}
    return "\n".join(lines) + "\n", stats

@dataclass(frozen=True)
class FieldDef:
    name: str
    group: str
    register: str
    bit_low: int
    bit_high: int
    description: str
    values: dict[int, str] | None = None
    warning: str | None = None
    platforms: tuple[str, ...] = ("oks", "bhs", "unknown")

@dataclass
class Region:
    index: int
    name: str
    raw: int
    base: int
    limit: int
    size: int
    enabled: bool

@dataclass
class DecodedValue:
    name: str
    offset: int
    size: int
    raw_register: int
    value: int
    decoded: str | None
    description: str
    warning: str | None = None

@dataclass
class BtgCrcStatus:
    offset: int
    stored: int
    calculated: int
    valid: bool

@dataclass
class MicrocodeEntry:
    index: int
    fit_entry_offset: int
    fit_address: int
    offset: int
    size: int
    version: int
    header_version: int | None = None
    update_revision: int | None = None
    date_raw: int | None = None
    date_text: str | None = None
    processor_signature: int | None = None
    processor_flags: int | None = None
    checksum: int | None = None
    loader_revision: int | None = None
    data_size: int | None = None
    total_size: int | None = None
    checksum_valid: bool | None = None
    cpuid: dict[str, int] | None = None
    status: str = "decoded"

FIELD_DEFS: dict[str, FieldDef] = {}

def normalize_platform(platform: str | None) -> str:
    text = str(platform or "unknown").strip().lower()
    if text in ("oakstream", "oak stream", "oks"):
        return "oks"
    if text in ("birchstream", "birch stream", "bhs"):
        return "bhs"
    return "unknown"

def add_field(name: str, group: str, register: str, bit_low: int, bit_high: int, description: str, values: dict[int, str] | None = None, warning: str | None = None, platforms: tuple[str, ...] | None = None) -> None:
    FIELD_DEFS[name.lower()] = FieldDef(name, group, register, bit_low, bit_high, description, values, warning, tuple(platforms or ("oks", "bhs", "unknown")))

def field_supported(field: FieldDef, platform: str | None) -> bool:
    platform_key = normalize_platform(platform)
    return platform_key in field.platforms or (platform_key == "unknown" and "unknown" in field.platforms)

def build_field_db() -> None:
    if FIELD_DEFS:
        return
    add_field("flcomp.Component0Density", "flcomp", "FLCOMP", 0, 3, "Flash component 0 density", FLASH_DENSITY_VALUES)
    add_field("flcomp.Component1Density", "flcomp", "FLCOMP", 4, 7, "Flash component 1 density", FLASH_DENSITY_VALUES)
    add_field("flcomp.ReadClockFrequency", "flcomp", "FLCOMP", 17, 19, "SPI read clock frequency", SPI_FREQ_VALUES)
    add_field("flcomp.FastReadSupport", "flcomp", "FLCOMP", 20, 20, "Fast Read 1-1-1 support", ENABLE_VALUES)
    add_field("flcomp.FastReadClockFrequency", "flcomp", "FLCOMP", 21, 23, "Fast read clock frequency", SPI_FREQ_VALUES)
    add_field("flcomp.WriteEraseClockFrequency", "flcomp", "FLCOMP", 24, 26, "Write and erase clock frequency", SPI_FREQ_VALUES)
    add_field("flcomp.ReadIdStatusClockFrequency", "flcomp", "FLCOMP", 27, 29, "Read ID/status clock frequency", SPI_FREQ_VALUES)
    soft = [
        ("strap0.AG3EDefaultValue", "IBLStrap0", 25, 25, "AG3E default value when RTC SRAM is invalid", BOOL_VALUES),
        ("strap1.DualOutputReadEnable", "IBLStrap1", 0, 0, "Dual output read enable", ENABLE_VALUES),
        ("strap1.QuadOutputReadEnable", "IBLStrap1", 2, 2, "Quad output read enable", ENABLE_VALUES),
        ("strap2.eSPIBusFrequencyDevice0", "IBLStrap2", 3, 5, "eSPI bus frequency for device 0/BMC", ESPI_FREQ_VALUES),
        ("strap2.eSPICRCCheckDisableDevice0", "IBLStrap2", 8, 8, "eSPI CRC check disable for device 0", DISABLE_VALUES),
        ("strap2.eSPIMaxIOModeDevice0", "IBLStrap2", 10, 11, "eSPI maximum IO mode for device 0", IO_MODE_VALUES),
        ("strap2.eSPIDevice1Enable", "IBLStrap2", 12, 12, "Enable eSPI secondary device 1", ENABLE_VALUES),
        ("strap2.IgnoreCS1DeviceAbsence", "IBLStrap2", 13, 13, "Ignore CS1 device absence", ENABLE_VALUES),
        ("strap2.eSPIBusFrequencyDevice1", "IBLStrap2", 16, 18, "eSPI bus frequency for device 1", ESPI_FREQ_VALUES),
        ("strap2.eSPIMaxIOModeDevice1", "IBLStrap2", 19, 20, "eSPI maximum IO mode for device 1", IO_MODE_VALUES),
        ("strap2.eSPIVWChannelDisableDevice1", "IBLStrap2", 23, 23, "eSPI VW channel force disable for device 1", DISABLE_VALUES),
        ("strap2.eSPILPCChannelDisableDevice1", "IBLStrap2", 24, 24, "eSPI LPC/peripheral channel force disable for device 1", DISABLE_VALUES),
        ("strap2.eSPIOOBChannelDisableDevice1", "IBLStrap2", 25, 25, "eSPI OOB channel force disable for device 1", DISABLE_VALUES),
        ("strap3.eSPICRCCheckDisableDevice1", "IBLStrap3", 6, 6, "eSPI CRC check disable for device 1", DISABLE_VALUES),
        ("strap3.eSPILowFrequencyModeDisable", "IBLStrap3", 11, 11, "eSPI low frequency divider-by-8 mode disable", DISABLE_VALUES),
        ("strap3.RTCProfile", "IBLStrap3", 13, 16, "RTC profile", {1: "I2C RTC industry standard dRTC", 15: "eSPI RTC"}),
        ("strap3.HostSMBusFrequency", "IBLStrap3", 17, 18, "Host SMBus frequency", {0: "100 kHz", 1: "400 kHz"}),
        ("strap3.SPITPMClockFrequency", "IBLStrap3", 19, 21, "SPI TPM clock frequency", {**SPI_FREQ_VALUES, 7: "100 MHz (not Platform POR)"}),
        ("strap3.TPMOverSPIBusEnabled", "IBLStrap3", 28, 28, "TPM over SPI bus enabled", ENABLE_VALUES),
        ("strap4.SysResetDebounceDisable", "IBLStrap4", 9, 9, "Disable 16 ms SYS_RESET_N debounce", DISABLE_VALUES),
    ]
    for item in soft:
        add_field(item[0], "softstrap", item[1], item[2], item[3], item[4], item[5])
    oks_soft = [
        ("strap3.MMBIWindowSize", "IBLStrap3", 22, 24, "OKS MMBI Window Size", {0: "8MB", 1: "64MB", 2: "64KB"}),
        ("strap3.TPMOverESPIBusEnabled", "IBLStrap3", 27, 27, "OKS TPM over eSPI bus enabled", ENABLE_VALUES),
        ("strap3.eSPIDisabled", "IBLStrap3", 29, 29, "OKS eSPI disabled", DISABLE_VALUES),
        ("strap4.SPITPMFlash0RxDelay", "IBLStrap4", 10, 13, "OKS SPI TPM CS#1 Rx delay in io_clk ticks", None),
        ("strap4.SPIFlash0RxDelay", "IBLStrap4", 14, 17, "OKS SPI flash CS#0 Rx delay in io_clk ticks", None),
        ("strap4.SPIFlash1RxDelay", "IBLStrap4", 18, 21, "OKS SPI flash CS#1 Rx delay in io_clk ticks", None),
        ("strap4.eSPIDevice0RxDelay", "IBLStrap4", 22, 25, "OKS eSPI device CS#0 Rx delay in io_clk ticks", None),
        ("strap4.eSPIDevice1RxDelay", "IBLStrap4", 26, 29, "OKS eSPI device CS#1 Rx delay in io_clk ticks", None),
        ("strap5.ParentSocketReadyDelay", "IBLStrap5", 0, 9, "OKS PARENT_SKT_RDY_DELAY in milliseconds", None),
        ("strap5.ChildSocketReadyResponseTimeout", "IBLStrap5", 10, 19, "OKS CHILD_SKT_RDY_RESPONSE_TIMEOUT in milliseconds", None),
        ("strap5.CrossSocketTimeout", "IBLStrap5", 20, 25, "OKS CROSS_SKT_TIMEOUT in seconds", None),
    ]
    for item in oks_soft:
        add_field(item[0], "softstrap", item[1], item[2], item[3], item[4], item[5], platforms=("oks", "unknown"))
    bhs_soft = [
        ("strap3.SPIFlash0RxDelay", "IBLStrap3", 22, 24, "BHS SPI Flash 0 Rx Delay in io_clk ticks", None),
        ("strap3.eSPIDevice0RxDelay", "IBLStrap3", 25, 27, "BHS eSPI Device 0 Rx Delay in ticks", None),
        ("strap4.BhsSPIFlash1RxDelay", "IBLStrap4", 3, 5, "BHS SPI Flash 1 Rx Delay in io_clk ticks", None),
        ("strap4.BhsESPIDevice1RxDelay", "IBLStrap4", 6, 8, "BHS eSPI Device 1 Rx Delay in ticks", None),
    ]
    for item in bhs_soft:
        add_field(item[0], "softstrap", item[1], item[2], item[3], item[4], item[5], platforms=("bhs",))
    for strap in range(6, 14):
        cpu = strap - 6
        add_field(f"strap{strap}.CPU{cpu}_IMH0_BMCINIT", "softstrap", f"IBLStrap{strap}", 0, 0, f"OKS CPU{cpu} IMH0 BMC assisted init", ENABLE_VALUES, platforms=("oks", "unknown"))
        add_field(f"strap{strap}.CPU{cpu}_IMH0_ON_PACKAGE_STORAGE", "softstrap", f"IBLStrap{strap}", 1, 1, f"OKS CPU{cpu} IMH0 allow writes to on-package NVRAM", ENABLE_VALUES, platforms=("oks", "unknown"))
        for stack in range(8):
            low = 32 + stack * 2
            add_field(f"strap{strap}.CPU{cpu}_IIO{stack}_STACK_IO_MODE", "softstrap", f"IBLStrap{strap}", low, low + 1, f"OKS CPU{cpu} IIO{stack} stack IO mode", IIO_STACK_VALUES, platforms=("oks", "unknown"))
        for stack in range(8):
            bit = 48 + stack
            add_field(f"strap{strap}.CPU{cpu}_IIO{stack}_STACK_COUPLING_MODE", "softstrap", f"IBLStrap{strap}", bit, bit, f"OKS CPU{cpu} IIO{stack} stack coupling mode", AC_DC_VALUES, platforms=("oks", "unknown"))
    add_field("fit4.RecordLength", "btg", "FIT4_HEADER", 0, 31, "FIT4 record length in bytes. This is not a CPU debug policy bit.")
    add_field("btg.Dam", "btg", "BTG_CPU_DEMOTED_DEBUG_POLICY", 0, 0, "Delayed Authentication Mode debug policy bit", ENABLE_VALUES, "Intel recommends DAM disabled for production platforms")
    add_field("btg.Consent", "btg", "BTG_CPU_DEMOTED_DEBUG_POLICY", 1, 1, "CONSENT debug policy bit", ENABLE_VALUES)
    add_field("btg.S3mTrace", "btg", "BTG_CPU_DEMOTED_DEBUG_POLICY", 2, 2, "S3M Trace debug policy bit", ENABLE_VALUES)
    add_field("btg.NpkUtilizeITHBuffer", "btg", "BTG_CPU_DEMOTED_DEBUG_POLICY", 5, 5, "Store traces in ITH buffer", ENABLE_VALUES)
    for name, register, low, high, desc in [
        ("btg.ContentType", "BTG_CONTENT_TYPE", 0, 31, "BTGC content type signature. Expected little-endian 0x43475442 ('BTGC')."),
        ("btg.Length", "BTG_LENGTH", 0, 31, "BTGC content length field"),
        ("btg.Version", "BTG_VERSION", 0, 15, "BTGC version field"),
        ("btg.CvType", "BTG_CV_TYPE", 0, 7, "BTGC CV type field"),
        ("btg.Crc8", "BTG_CRC8", 0, 7, "BTGC CRC8 byte"),
    ]:
        add_field(name, "btg", register, low, high, desc)
    restrictions = [("ForceAnchorCoveBoot", 0), ("DisableCpuDebugging", 1), ("DisableBspInitialization", 2), ("ProtectBiosEnvironment", 3), ("BypassBootPolicy", 4), ("S3xResumeType", 5), ("BtgEnabled", 6), ("BootPolicyInvalid", 7), ("CseToAcmCopyDone", 14), ("AcmOkToProceed", 15)]
    for name, bit in restrictions:
        values = ENABLE_VALUES
        warning = None
        desc = name.replace("Cpu", " CPU ").replace("Bsp", " BSP ") + " policy bit"
        platforms = ("oks", "bhs", "unknown")
        if name == "DisableCpuDebugging":
            values = {0: "CPU debugging allowed", 1: "CPU debugging disabled"}
            warning = "Intel recommends disabling CPU debug for production platforms"
            desc = "Disable CPU probemode/ITP debug modes. This is the FITm btg:DisableCpuDebugging setting."
            platforms = ("oks", "unknown")
        if name == "DisableBspInitialization":
            values = {0: "BSP INIT normal", 1: "BSP INIT disabled/error"}
            desc = "Treat BSP INIT as error"
            platforms = ("oks", "unknown")
        add_field(f"btg.{name}", "btg", "BTG_POLICY_RESTRICTIONS", bit, bit, desc, values, warning, platforms=platforms)
    add_field("btg.BtGuardCpuDebuging", "btg", "BTG_POLICY_RESTRICTIONS", 1, 1, "BHS BtGuardCpuDebuging config view. The stored FIT4 bit is disable_cpu_debug, so 0 means CPU debugging enabled.", {0: "Enabled", 1: "Disabled"}, "Intel recommends disabling CPU debug for production platforms", platforms=("bhs",))
    add_field("btg.BtGuardBspInitialization", "btg", "BTG_POLICY_RESTRICTIONS", 2, 2, "BHS BtGuardBspInitialization config view. The stored FIT4 bit is disable_bsp_initialization, so 0 means BSP initialization enabled.", {0: "Enabled", 1: "Disabled/error"}, platforms=("bhs",))
    for name, low, high, desc, values in [
        ("MeasuredBoot", 0, 0, "Measured boot policy bit", ENABLE_VALUES), ("VerifiedBoot", 1, 1, "Verified boot policy bit", ENABLE_VALUES),
        ("Hap", 2, 2, "HAP policy bit", ENABLE_VALUES), ("TxtSupported", 3, 3, "TXT supported policy bit", ENABLE_VALUES),
        ("TpmDeactivated", 8, 8, "TPM deactivated policy bit", ENABLE_VALUES), ("OemUnlock", 9, 9, "OEM unlock bit", ENABLE_VALUES),
        ("FwSubtype", 10, 12, "Firmware subtype field", None), ("FwType", 13, 15, "Firmware type field", None),
    ]:
        add_field(f"btg.{name}", "btg", "BTG_POLICY_TYPE", low, high, desc, values)
    for name, reg, low, high, desc in [
        ("AcmSvn", "BTG_POLICY_SVN", 0, 3, "ACM security version number"), ("KmSvn", "BTG_POLICY_SVN", 4, 7, "Key Manifest security version number"),
        ("BpSvn", "BTG_POLICY_SVN", 8, 13, "Boot Policy Manifest security version number"), ("SignatureAlgorithmLowBit", "BTG_POLICY_SVN", 15, 15, "Low bit of signature algorithm"),
        ("SignatureAlgorithmHighBits", "BTG_POLICY_KEY_TYPE", 0, 1, "Upper bits of signature algorithm"), ("KeyManifestId", "BTG_POLICY_KEY_TYPE", 2, 5, "Key Manifest identifier"),
        ("OemKeyHashAlg", "BTG_POLICY_KEY_TYPE", 6, 8, "OEM key hash algorithm"), ("BtgRevision", "BTG_POLICY_KEY_TYPE", 9, 13, "BTG revision field"),
    ]:
        add_field(f"btg.{name}", "btg", reg, low, high, desc)
    add_reserved_softstrap_gaps()

def add_reserved_softstrap_gaps() -> None:
    for strap in range(14):
        register = f"IBLStrap{strap}"
        width = 32 if strap <= 5 else 64
        intervals = sorted((f.bit_low, f.bit_high) for f in FIELD_DEFS.values() if f.group == "softstrap" and f.register == register and "oks" in f.platforms)
        next_bit = 0
        for low, high in intervals:
            if low > next_bit:
                add_reserved_field(strap, next_bit, low - 1, platforms=("oks", "unknown"))
            next_bit = max(next_bit, high + 1)
        if next_bit < width:
            add_reserved_field(strap, next_bit, width - 1, platforms=("oks", "unknown"))

    for strap in range(5):
        register = f"IBLStrap{strap}"
        intervals = sorted((f.bit_low, f.bit_high) for f in FIELD_DEFS.values() if f.group == "softstrap" and f.register == register and "bhs" in f.platforms)
        next_bit = 0
        for low, high in intervals:
            if low > next_bit:
                add_reserved_field(strap, next_bit, low - 1, platforms=("bhs",))
            next_bit = max(next_bit, high + 1)
        if next_bit < 32:
            add_reserved_field(strap, next_bit, 31, platforms=("bhs",))

def add_reserved_field(strap: int, low: int, high: int, platforms: tuple[str, ...] | None = None) -> None:
    suffix = str(low) if low == high else f"{high}_{low}"
    text = str(low) if low == high else f"{high}:{low}"
    prefix = "BhsReservedBits" if platforms == ("bhs",) else "ReservedBits"
    add_field(f"strap{strap}.{prefix}{suffix}", "softstrap", f"IBLStrap{strap}", low, high, f"Reserved or currently undocumented softstrap bit range {text}", platforms=platforms)

def all_fields(platform: str | None = None) -> list[FieldDef]:
    order = {"btg": 0, "softstrap": 1, "flcomp": 2}
    fields = [field for field in FIELD_DEFS.values() if platform is None or field_supported(field, platform)]
    return sorted(fields, key=lambda f: (order.get(f.group, 99), f.register, f.bit_low, f.name.lower()))

def find_field(name: str, platform: str | None = None) -> FieldDef:
    try:
        field = FIELD_DEFS[name.lower()]
    except KeyError as exc:
        raise KeyError(f"Unknown field '{name}'. Use list-fields to see supported fields.") from exc
    if platform is not None and not field_supported(field, platform):
        raise KeyError(f"Field '{name}' is not supported for platform {platform}.")
    return field

def parse_int(text: str | int) -> int:
    return text if isinstance(text, int) else int(str(text).replace("_", ""), 0)

def get_bits(value: int, low: int, high: int) -> int:
    return (value >> low) & ((1 << (high - low + 1)) - 1)

def set_bits(value: int, low: int, high: int, new_value: int) -> int:
    width = high - low + 1
    if new_value < 0 or new_value >= (1 << width):
        raise ValueError(f"Value {new_value:#x} does not fit in {width} bits")
    mask = ((1 << width) - 1) << low
    return (value & ~mask) | (new_value << low)

def crc8_ccitt_init1(data: bytes) -> int:
    crc = 0x01
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xff if crc & 0x80 else (crc << 1) & 0xff
    return crc

class OksBiosImage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = bytearray(self.path.read_bytes())
        self._btg_offset: int | None = None
        self._platform_key: str | None = None
        self._layout_name: str | None = None
    def u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]
    def put_int(self, offset: int, size: int, value: int) -> None:
        self.data[offset:offset + size] = value.to_bytes(size, "little")
    @property
    def has_descriptor(self) -> bool:
        return len(self.data) >= 0x20 and bytes(self.data[0x10:0x14]) == DESCRIPTOR_SIGNATURE
    def descriptor_bases(self) -> dict[str, int]:
        if not self.has_descriptor:
            raise ValueError("Intel flash descriptor signature was not found at offset 0x10")
        flmap0 = self.u32(0x14); flmap1 = self.u32(0x18)
        return {"fcba": (flmap0 & 0xff) * 0x10, "frba": ((flmap0 >> 16) & 0xff) * 0x10, "fmba": (flmap1 & 0xff) * 0x10, "fpsba": ((flmap1 >> 16) & 0xff) * 0x10, "flmap0": flmap0, "flmap1": flmap1}
    def regions(self) -> list[Region]:
        frba = self.descriptor_bases()["frba"]
        regions = []
        for index in range(16):
            raw = self.u32(frba + index * 4); base_units = raw & 0x7fff; limit_units = (raw >> 16) & 0x7fff
            disabled_marker = base_units == 0x7fff and limit_units == 0
            enabled = not disabled_marker and raw != 0xffffffff and limit_units >= base_units
            base = base_units << 12; limit = (limit_units << 12) | 0xfff
            size = limit - base + 1 if enabled and limit >= base else 0
            regions.append(Region(index, REGION_NAMES.get(index, f"region{index}"), raw, base, limit, size, enabled))
        return regions
    def region(self, name_or_index: str | int) -> Region:
        for region in self.regions():
            if region.index == name_or_index or region.name.lower() == str(name_or_index).lower():
                return region
        raise KeyError(f"Region not found: {name_or_index}")
    def region_bytes(self, name_or_index: str | int) -> bytes:
        region = self.region(name_or_index)
        if not region.enabled or region.size <= 0:
            raise ValueError(f"Region not available: {name_or_index}")
        return bytes(self.data[region.base:region.limit + 1])
    def replace_region_bytes(self, name_or_index: str | int, replacement: bytes) -> Region:
        region = self.region(name_or_index)
        if not region.enabled or region.size <= 0:
            raise ValueError(f"Region not available: {name_or_index}")
        replacement = bytes(replacement)
        if len(replacement) > region.size:
            raise ValueError(f"Replacement size {len(replacement)} exceeds region size {region.size}")
        self.data[region.base:region.limit + 1] = replacement.ljust(region.size, b"\xff")
        return region
    def imd_payload(self) -> bytes:
        if not self.has_descriptor:
            return b""
        try:
            region = self.region("imd")
        except Exception:
            return b""
        if not region.enabled or region.size <= 0:
            return b""
        return bytes(self.data[region.base:region.limit + 1])
    def detect_layout_name(self) -> str | None:
        if self._layout_name is not None:
            return self._layout_name
        payload = self.imd_payload()
        for marker in (b"OakStream", b"BirchStream"):
            if marker in payload:
                self._layout_name = marker.decode("ascii")
                return self._layout_name
        blob = bytes(self.data[:min(len(self.data), 0x200000)])
        for marker in (b"OakStream", b"BirchStream"):
            if marker in blob:
                self._layout_name = marker.decode("ascii")
                return self._layout_name
        name = self.path.name.lower()
        if "oks" in name or "oak" in name:
            self._layout_name = "OakStream"
        elif "bhs" in name or "birch" in name:
            self._layout_name = "BirchStream"
        else:
            self._layout_name = None
        return self._layout_name
    def detect_platform(self) -> str:
        if self._platform_key is not None:
            return self._platform_key
        platform = "unknown"
        try:
            cpu_platforms = {cpu_family_platform(entry.processor_signature) for entry in self.microcode_entries() if entry.processor_signature}
            cpu_platforms.discard("unknown")
            if len(cpu_platforms) == 1:
                platform = next(iter(cpu_platforms))
        except Exception:
            pass
        if platform == "unknown":
            layout = self.detect_layout_name()
            platform = normalize_platform(layout)
        if platform == "unknown" and self.has_descriptor:
            try:
                enabled = [region for region in self.regions() if region.enabled]
                order = "".join(format(region.index, "X") for region in sorted(enabled, key=lambda item: item.base))
                if order.startswith("0241"):
                    platform = "oks"
                elif order.startswith("0241") is False and "241" in order:
                    platform = "bhs"
            except Exception:
                pass
        self._platform_key = platform
        return self._platform_key
    def platform_name(self) -> str:
        platform = self.detect_platform()
        if platform == "oks":
            return "OKS / Oak Stream"
        if platform == "bhs":
            return "BHS / Birch Stream"
        return "Unknown"
    def supported_fields(self) -> list[FieldDef]:
        return all_fields(self.detect_platform())
    def raw_strap_count(self) -> int:
        return 5 if self.detect_platform() == "bhs" else 14
    def strap_offset(self, index: int) -> tuple[int, int]:
        fpsba = self.descriptor_bases()["fpsba"]
        if self.detect_platform() == "bhs" and not 0 <= index <= 4:
            raise ValueError("BHS FITm IBL strap range is 0..4")
        if 0 <= index <= 5:
            return fpsba + index * 4, 4
        if 6 <= index <= 13:
            return fpsba + 0x18 + (index - 6) * 8, 8
        raise ValueError("Supported IBL strap range is 0..13")
    def register_location(self, register: str) -> tuple[int, int]:
        if register == "FLCOMP": return self.descriptor_bases()["fcba"], 4
        if register.startswith("IBLStrap"): return self.strap_offset(int(register.removeprefix("IBLStrap")))
        btg = self.find_btg_offset()
        mapping = {"FIT4_HEADER": (0x00, 16), "BTG_CPU_DEMOTED_DEBUG_POLICY": (0x10, 4), "BTG_CONTENT_TYPE": (0x14, 4), "BTG_LENGTH": (0x18, 4), "BTG_VERSION": (0x1c, 2), "BTG_CV_TYPE": (0x1e, 1), "BTG_CRC8": (0x1f, 1), "BTG_POLICY_RESTRICTIONS": (0x20, 2), "BTG_POLICY_TYPE": (0x22, 2), "BTG_POLICY_SVN": (0x24, 2), "BTG_POLICY_KEY_TYPE": (0x26, 2)}
        if register in mapping:
            rel, size = mapping[register]; return btg + rel, size
        raise KeyError(f"Unsupported register {register}")
    def read_register(self, register: str) -> tuple[int, int, int]:
        offset, size = self.register_location(register)
        return offset, size, int.from_bytes(self.data[offset:offset + size], "little")
    def decode_field(self, name: str) -> DecodedValue:
        field = find_field(name, self.detect_platform()); offset, size, raw = self.read_register(field.register)
        value = get_bits(raw, field.bit_low, field.bit_high); decoded = field.values.get(value) if field.values else None
        warning = field.warning if (field.name.lower() == "btg.dam" and value != 0) or (field.name.lower() in ("btg.disablecpudebugging", "btg.btguardcpudebuging") and value != 1) else None
        if field.name.lower() == "strap3.mmbiwindowsize":
            if value == 0:
                decoded = "8MB"
            elif value == 1:
                decoded = "64MB"
            elif value == 2:
                decoded = "64KB"
            else:
                decoded = "Reserved"
                warning = "Reserved MMBI Window Size value"
        return DecodedValue(field.name, offset, size, raw, value, decoded, field.description, warning)
    def set_field(self, name: str, new_value: int | str) -> DecodedValue:
        field = find_field(name, self.detect_platform())
        if field.name.lower() in READ_ONLY_FIELDS:
            raise ValueError(f"{field.name} is structural/read-only; edit policy fields instead")
        offset, size, raw = self.read_register(field.register)
        self.put_int(offset, size, set_bits(raw, field.bit_low, field.bit_high, parse_int(new_value)))
        if field.group == "btg": self.update_btg_crc()
        return self.decode_field(name)
    def raw_straps(self) -> list[DecodedValue]:
        out = []
        for index in range(self.raw_strap_count()):
            offset, size = self.strap_offset(index); raw = int.from_bytes(self.data[offset:offset + size], "little")
            out.append(DecodedValue(f"IBLStrap{index}", offset, size, raw, raw, None, f"Raw IBL platform soft strap {index}"))
        return out
    def set_raw_strap(self, index: int, value: int | str) -> DecodedValue:
        if index < 0 or index >= self.raw_strap_count():
            raise ValueError(f"{self.platform_name()} supports IBLStrap0..{self.raw_strap_count() - 1}")
        value_int = parse_int(value); offset, size = self.strap_offset(index)
        if value_int < 0 or value_int >= (1 << (size * 8)):
            raise ValueError(f"IBLStrap{index} value {value_int:#x} does not fit in {size} bytes")
        self.put_int(offset, size, value_int); return self.raw_straps()[index]
    def find_fit_offset(self) -> int:
        bios = self.region("bios") if self.has_descriptor else Region(1, "bios", 0, 0, len(self.data) - 1, len(self.data), True)
        pointer_offset = bios.limit + 1 - 0x40 if self.has_descriptor else len(self.data) - 0x40
        pointer = self.u32(pointer_offset); bios_base_address = 0x100000000 - bios.size
        fit_offset = bios.base + (pointer - bios_base_address)
        if fit_offset < 0 or fit_offset + 16 > len(self.data) or bytes(self.data[fit_offset:fit_offset + 5]) != b"_FIT_":
            found = bytes(self.data).find(b"_FIT_")
            if found < 0: raise ValueError("FIT table not found")
            fit_offset = found
        return fit_offset
    def fit_entries(self) -> list[dict[str, int | str]]:
        fit_offset = self.find_fit_offset(); count = int.from_bytes(self.data[fit_offset + 8:fit_offset + 11], "little")
        bios = self.region("bios") if self.has_descriptor else Region(1, "bios", 0, 0, len(self.data) - 1, len(self.data), True)
        bios_base_address = 0x100000000 - bios.size; entries = []
        for index in range(count):
            entry_offset = fit_offset + index * 16; raw = bytes(self.data[entry_offset:entry_offset + 16])
            address = int.from_bytes(raw[0:8], "little"); size = int.from_bytes(raw[8:11], "little"); version = int.from_bytes(raw[12:14], "little"); entry_type = raw[14] & 0x7f
            absolute = bios.base + (address - bios_base_address) if address >= bios_base_address else address
            entries.append({"index": index, "fit_entry_offset": entry_offset, "type": entry_type, "address": address, "absolute_offset": absolute, "size": size, "version": version, "raw": raw.hex()})
        return entries
    def microcode_entries(self) -> list[MicrocodeEntry]:
        decoded = []
        data = bytes(self.data)
        for fit_entry in self.fit_entries():
            try:
                entry_type = int(fit_entry.get("type", -1))
            except Exception:
                continue
            if entry_type != 1:
                continue
            offset = int(fit_entry.get("absolute_offset", -1))
            entry = MicrocodeEntry(
                index=int(fit_entry.get("index", -1)),
                fit_entry_offset=int(fit_entry.get("fit_entry_offset", -1)),
                fit_address=int(fit_entry.get("address", 0)),
                offset=offset,
                size=int(fit_entry.get("size", 0)),
                version=int(fit_entry.get("version", 0)),
            )
            if offset < 0 or offset + 48 > len(data):
                entry.status = "Out of image range"
                decoded.append(entry)
                continue
            header = data[offset:offset + 48]
            (
                header_version,
                update_revision,
                date_raw,
                processor_signature,
                checksum,
                loader_revision,
                processor_flags,
                data_size,
                total_size,
            ) = struct.unpack_from("<IIIIIIIII", header, 0)
            if total_size == 0:
                total_size = 2048
            if data_size == 0 and total_size >= 48:
                data_size = total_size - 48
            checksum_valid = None
            if 48 <= total_size <= 0x2000000 and offset + total_size <= len(data):
                checksum_valid = checksum32_valid(data[offset:offset + total_size])
            cpuid = decode_cpuid_signature(processor_signature) if processor_signature else None
            status_parts = []
            if header_version != 1:
                status_parts.append(f"unexpected header version {format_hex(header_version)}")
            if loader_revision not in (0, 1):
                status_parts.append(f"loader revision {format_hex(loader_revision)}")
            if not processor_signature:
                status_parts.append("processor signature is 0")
            if checksum_valid is True:
                status_parts.append("checksum valid")
            elif checksum_valid is False:
                status_parts.append("checksum not zero")
            elif total_size:
                status_parts.append("checksum not checked")
            entry.header_version = header_version
            entry.update_revision = update_revision
            entry.date_raw = date_raw
            entry.date_text = microcode_date_text(date_raw)
            entry.processor_signature = processor_signature
            entry.processor_flags = processor_flags
            entry.checksum = checksum
            entry.loader_revision = loader_revision
            entry.data_size = data_size
            entry.total_size = total_size
            entry.checksum_valid = checksum_valid
            entry.cpuid = cpuid
            entry.status = "; ".join(status_parts) if status_parts else "decoded"
            decoded.append(entry)
        return decoded
    def common_uefi_summary(self) -> dict:
        summary = self.summary()
        microcode = [asdict(entry) for entry in self.microcode_entries()]
        summary["microcode"] = microcode
        summary["microcode_count"] = len(microcode)
        summary["microcode_signatures"] = sorted({entry["processor_signature"] for entry in microcode if entry.get("processor_signature")})
        summary["microcode_revisions"] = sorted({entry["update_revision"] for entry in microcode if entry.get("update_revision")})
        return summary
    def find_btg_offset(self) -> int:
        if self._btg_offset is not None: return self._btg_offset
        for entry in self.fit_entries():
            offset = int(entry["absolute_offset"])
            if entry["type"] == 0x4 and bytes(self.data[offset + 0x14:offset + 0x18]) == b"BTGC":
                self._btg_offset = offset; return offset
        marker = bytes(self.data).find(b"BTGC")
        if marker >= 0 and marker >= 0x14:
            self._btg_offset = marker - 0x14; return self._btg_offset
        raise ValueError("BTG FIT4 block not found")
    def update_btg_crc(self) -> int:
        fit4 = self.find_btg_offset(); length = self.u32(fit4 + 0x18); btg = fit4 + 0x10; crc_offset = fit4 + 0x1f; total_len = 4 + 8 + length
        self.data[crc_offset] = 0; crc = crc8_ccitt_init1(bytes(self.data[btg:btg + total_len])); self.data[crc_offset] = crc; return crc
    def btg_crc_status(self) -> BtgCrcStatus:
        fit4 = self.find_btg_offset(); length = self.u32(fit4 + 0x18); btg = fit4 + 0x10; crc_offset = fit4 + 0x1f; total_len = 4 + 8 + length
        saved = self.data[crc_offset]; self.data[crc_offset] = 0; calculated = crc8_ccitt_init1(bytes(self.data[btg:btg + total_len])); self.data[crc_offset] = saved
        return BtgCrcStatus(crc_offset, saved, calculated, saved == calculated)
    def summary(self) -> dict:
        btg_offset = None
        try: btg_offset = self.find_btg_offset()
        except Exception: pass
        if self.detect_platform() == "bhs":
            btg_names = ("fit4.RecordLength", "btg.Dam", "btg.Consent", "btg.S3mTrace", "btg.NpkUtilizeITHBuffer", "btg.BtGuardCpuDebuging", "btg.BtGuardBspInitialization", "btg.MeasuredBoot", "btg.VerifiedBoot", "btg.TxtSupported", "btg.AcmSvn", "btg.KmSvn", "btg.BpSvn")
        else:
            btg_names = ("fit4.RecordLength", "btg.Dam", "btg.Consent", "btg.S3mTrace", "btg.NpkUtilizeITHBuffer", "btg.DisableCpuDebugging", "btg.DisableBspInitialization", "btg.MeasuredBoot", "btg.VerifiedBoot", "btg.TxtSupported", "btg.AcmSvn", "btg.KmSvn", "btg.BpSvn")
        return {"path": str(self.path), "size": len(self.data), "platform": self.detect_platform(), "platform_name": self.platform_name(), "layout_name": self.detect_layout_name(), "has_descriptor": self.has_descriptor, "descriptor_bases": self.descriptor_bases() if self.has_descriptor else {}, "regions": [asdict(r) for r in self.regions()] if self.has_descriptor else [], "fit_offset": self.find_fit_offset(), "btg_offset": btg_offset, "btg_crc": asdict(self.btg_crc_status()) if btg_offset is not None else None, "raw_straps": [asdict(v) for v in self.raw_straps()] if self.has_descriptor else [], "btg": [asdict(self.decode_field(n)) for n in btg_names]}
    def save(self, output: str | Path, overwrite: bool = False) -> Path:
        output_path = Path(output)
        if output_path.exists() and not overwrite: raise FileExistsError(f"Output exists: {output_path}")
        output_path.write_bytes(self.data); return output_path
    def save_in_place_with_backup(self) -> Path:
        backup = self.path.with_suffix(self.path.suffix + ".bak")
        if not backup.exists(): shutil.copy2(self.path, backup)
        self.path.write_bytes(self.data); return backup

def value_to_text(value: DecodedValue) -> str:
    suffix = f" ({value.decoded})" if value.decoded else ""; warn = f" WARNING: {value.warning}" if value.warning else ""
    return f"{value.name}: value={value.value:#x}{suffix}, register={value.raw_register:#x}, offset={value.offset:#x}, size={value.size}{warn}"

def json_dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=False)

def raw_strap_index(field: str) -> int | None:
    match = re.fullmatch(r"IBLStrap(\d+)", field, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None

def format_hex(value: int | None, width: int = 0) -> str:
    if value is None:
        return "N/A"
    try:
        value = int(value)
    except Exception:
        return "N/A"
    return f"0x{value:0{width}X}" if width else f"0x{value:X}"

def microcode_date_text(raw_date: int | None) -> str:
    if raw_date is None:
        return "N/A"
    raw_date = int(raw_date)

    def bcd_byte(value: int) -> int | None:
        high = (value >> 4) & 0xF
        low = value & 0xF
        if high > 9 or low > 9:
            return None
        return high * 10 + low

    def bcd_word(value: int) -> int | None:
        digits = [(value >> shift) & 0xF for shift in (12, 8, 4, 0)]
        if any(digit > 9 for digit in digits):
            return None
        return digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]

    month = bcd_byte((raw_date >> 24) & 0xFF)
    day = bcd_byte((raw_date >> 16) & 0xFF)
    year = bcd_word(raw_date & 0xFFFF)
    if month is not None and day is not None and year is not None and 1 <= month <= 12 and 1 <= day <= 31 and 1995 <= year <= 2100:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return f"raw {format_hex(raw_date, 8)}"

def decode_cpuid_signature(signature: int) -> dict[str, int]:
    signature = int(signature)
    stepping = signature & 0xF
    base_model = (signature >> 4) & 0xF
    base_family = (signature >> 8) & 0xF
    processor_type = (signature >> 12) & 0x3
    extended_model = (signature >> 16) & 0xF
    extended_family = (signature >> 20) & 0xFF
    display_family = base_family + extended_family if base_family == 0xF else base_family
    display_model = base_model + (extended_model << 4) if base_family in (0x6, 0xF) else base_model
    return {
        "signature": signature,
        "stepping": stepping,
        "base_model": base_model,
        "base_family": base_family,
        "processor_type": processor_type,
        "extended_model": extended_model,
        "extended_family": extended_family,
        "display_family": display_family,
        "display_model": display_model,
    }

CPU_FAMILY_SIGNATURES = {
    0xA06D: "GNR-SP",
    0xA06E: "GNR-D",
    0xA06F: "SRF-SP",
    0xD06D: "CWF",
    0xB066: "GrandRidge",
    0x400F0: "DMR-OLD",
    0x400F1: "DMR",
    0x400F2: "DMRHD",
    0x400F4: "PMR",
    0x400F8: "COR",
}

BHS_CPU_FAMILIES = {"GNR-SP", "GNR-D", "SRF-SP", "CWF"}
OKS_CPU_FAMILIES = {"DMR-OLD", "DMR", "DMRHD", "PMR", "COR"}


def cpu_family_text(signature: int | None) -> str:
    if signature is None:
        return "N/A"
    try:
        signature = int(signature)
    except Exception:
        return "N/A"
    family_key = signature >> 4
    family = CPU_FAMILY_SIGNATURES.get(family_key)
    return family if family else format_hex(signature, 8)


def cpu_family_platform(signature: int | None) -> str:
    family = cpu_family_text(signature)
    if family in BHS_CPU_FAMILIES:
        return "bhs"
    if family in OKS_CPU_FAMILIES:
        return "oks"
    return "unknown"

def checksum32_valid(payload: bytes) -> bool | None:
    if not payload or len(payload) % 4:
        return None
    total = 0
    for offset in range(0, len(payload), 4):
        total = (total + struct.unpack_from("<I", payload, offset)[0]) & 0xFFFFFFFF
    return total == 0

ZERO_GUID = "00000000-0000-0000-0000-000000000000"
ALL_FFS_GUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

BIOS_KNOBS_DATA_BIN_GUID = "615e6021-603d-4124-b7ea-c48a3737bacd"
BIOS_KNOBS_CPX_DATA_BIN_GUID = "731daa2a-9259-4729-a1b5-f77209ebf54d"

SETUP_DRIVER_GUID_ORDER = [
    "dfb9bf4c-3520-4a80-904e-71d5f42e866a",
    "abbce13d-e25a-4d9f-a1f9-2f7710786892",
    "de1e3282-c8d6-40ad-957e-fbed9a491f6d",
    "6b6fd380-2c55-42c6-98bf-cbbc5a9aa666",
    "5498ab03-63ae-41a5-b490-2994e2dac68d",
    "bcea6548-e204-4486-8f2a-36e13c7838ce",
    "e6a7a1ce-5881-4b49-80be-69c91811685c",
    "21535212-83d1-4d4a-ae58-12f84d1f710d",
    "cb105c8b-3b1f-4117-993b-6d1893393716",
    "6bb0c4de-dca4-4f3e-bca8-330635da4ef3",
    "d89a7d8b-d016-4d26-93e3-eab6b4d3b0a2",
    "462caa21-7614-4503-836e-8ab6f4662331",
]

SETUP_DRIVER_GUIDS = set(SETUP_DRIVER_GUID_ORDER)

DEFAULT_DATA_GUIDS = {
    "fff12b8d-7696-4c8b-a985-2747075b4f50",
    "003e7b41-98a2-4be2-b27a-6c30c7655225",
    "1ae42876-008f-4161-b2b7-1c0d15c5ef43",
    "9971614c-8dd6-4275-852f-ae7cbcd3ad85",
    "ff7db236-f856-4924-90f8-cdf12fb875f3",
}

EFI_GLOBAL_VARIABLE_GUID = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
EFI_VARIABLE_GUID = "ddcf3616-3275-4164-98b6-fe85707ffe7d"
EFI_AUTHENTICATED_VARIABLE_GUID = "aaf32c78-947b-439a-a180-2e144ec37792"
VARIABLE_STORE_GUIDS = {EFI_GLOBAL_VARIABLE_GUID, EFI_VARIABLE_GUID, EFI_AUTHENTICATED_VARIABLE_GUID}

EFI_FIRMWARE_FILE_SYSTEM_GUIDS = {
    "7a9354d9-0468-444a-81ce-0bf617d890df",
    "8c8ce578-8a3d-4f1c-9935-896185c32dd3",
    "5473c07a-3dcb-4dca-bd6f-1e9689e7349a",
}

LZMA_CUSTOM_DECOMPRESS_GUID = "ee4e5898-3914-4259-9d6e-dc7bd79403cf"
BROTLI_CUSTOM_DECOMPRESS_GUID = "3d532050-5cda-4fd0-879e-0f7f630d5afb"

FFS_FILE_HEADER_SIZE = 0x18
FFS_FILE_HEADER2_SIZE = 0x20
FFS_ATTRIB_LARGE_FILE = 0x01
FFS_ATTRIB_CHECKSUM = 0x40
EFI_SECTION_GUID_DEFINED = 0x02
EFI_SECTION_FIRMWARE_VOLUME_IMAGE = 0x17

BITWISE_KNOB_PREFIX = 0xC0000
INVALID_KNOB_SIZE = 0xFF
BIOS_KNOBS_DATA_BIN_HDR_SIZE_OLD = 0x10
BIOS_KNOBS_DATA_BIN_HDR_SIZE = 0x40
BIOS_KNOBS_DATA_BIN_HDR_SIZE_V03 = 0x50
BIOS_KNOB_BIN_REVISION_OFFSET = 0x0F
NVAR_NAME_OFFSET = 0x0E
NVAR_SIZE_OFFSET = 0x10
BIOS_KNOB_BIN_GUID_OFFSET = 0x12

SETUP_TYPE_BY_BIN = {
    0x5: "oneof",
    0x7: "numeric",
    0x6: "checkbox",
    0x8: "string",
    0xF: "ReadOnly",
}

SETUP_TYPE_BY_IFR = {
    0x05: "oneof",
    0x07: "numeric",
    0x06: "checkbox",
    0x1C: "string",
    0x0F: "ReadOnly",
}

EFI_IFR_FORM_OP = 0x01
EFI_IFR_SUPPRESS_IF_OP = 0x0A
EFI_IFR_GRAY_OUT_IF_OP = 0x19
EFI_IFR_REF_OP = 0x0F
EFI_IFR_FORM_SET_OP = 0x0E
EFI_IFR_VARSTORE_OP = 0x24
EFI_IFR_VARSTORE_EFI_OP = 0x26
EFI_IFR_ONE_OF_OP = 0x05
EFI_IFR_CHECKBOX_OP = 0x06
EFI_IFR_NUMERIC_OP = 0x07
EFI_IFR_ONE_OF_OPTION_OP = 0x09
EFI_IFR_STRING_OP = 0x1C
EFI_IFR_END_OP = 0x29
EFI_IFR_TRUE_OP = 0x46
EFI_IFR_DEFAULT_OP = 0x5B
EFI_IFR_GUID_OP = 0x5F

EFI_HII_PACKAGE_FORMS = 0x02
EFI_HII_PACKAGE_STRINGS = 0x04
EFI_HII_SIBT_END = 0x00
EFI_HII_SIBT_STRING_SCSU = 0x10
EFI_HII_SIBT_STRING_SCSU_FONT = 0x11
EFI_HII_SIBT_STRINGS_SCSU = 0x12
EFI_HII_SIBT_STRINGS_SCSU_FONT = 0x13
EFI_HII_SIBT_STRING_UCS2 = 0x14
EFI_HII_SIBT_STRING_UCS2_FONT = 0x15
EFI_HII_SIBT_STRINGS_UCS2 = 0x16
EFI_HII_SIBT_STRINGS_UCS2_FONT = 0x17
EFI_HII_SIBT_DUPLICATE = 0x20
EFI_HII_SIBT_SKIP2 = 0x21
EFI_HII_SIBT_SKIP1 = 0x22
EFI_HII_SIBT_EXT1 = 0x30
EFI_HII_SIBT_EXT2 = 0x31
EFI_HII_SIBT_EXT4 = 0x32

EFI_IFR_TYPE_NUM_SIZE_8 = 0x00
EFI_IFR_TYPE_NUM_SIZE_16 = 0x01
EFI_IFR_TYPE_NUM_SIZE_32 = 0x02
EFI_IFR_TYPE_NUM_SIZE_64 = 0x03
EFI_IFR_TYPE_BOOLEAN = 0x04
EFI_IFR_OPTION_DEFAULT = 0x10

EFI_IFR_TIANO_GUID = "0f0b1735-87a0-4193-b266-538c38af48ce"
EDKII_IFR_BIT_VARSTORE_GUID = "82ddd68b-9163-4187-9b27-20a8fd60a71d"

OLD_NVAR_NAMES = {0: "Setup", 1: "ServerMgmt"}
OLD_NVAR_NAMES_PLY = {
    0: "Setup",
    1: "SocketIioConfig",
    2: "SocketCommonRcConfig",
    3: "SocketMpLinkConfig",
    4: "SocketMemoryConfig",
    5: "SocketMiscConfig",
    6: "SocketPowerManagementConfig",
    7: "SocketProcessorCoreConfig",
    8: "SvOtherConfiguration",
    9: "SvPchConfiguration",
}


class DecodeError(RuntimeError):
    pass


@dataclass
class WarningItem:
    message: str
    offset: int | None = None
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.offset is not None:
            data["offsetHex"] = f"0x{self.offset:X}"
        return data


@dataclass
class FirmwareFile:
    guid: str
    offset: int
    size: int
    data: bytes
    source: str


@dataclass
class VarDataLocation:
    var_id: int
    name: str
    guid: str
    data_offset: int
    data_size: int
    file_guid: str
    file_offset: int
    source: str


@dataclass
class Knob:
    var_id: int
    nvar_name: str
    nvar_guid: str
    offset: int
    offset_text: str
    size: int
    setup_type: str
    name: str
    depex: str
    raw_setup_type: int
    bitwise: bool = False
    prompt: str = ""
    description: str = ""
    default: int = 0
    current: int = 0
    default_available: bool = False
    current_available: bool = False
    min_value: int | None = None
    max_value: int | None = None
    step: int | None = None
    setup_page: str = ""
    processed: bool = False
    options: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Nvar:
    var_id: int
    name: str
    guid: str
    size: int
    knob_count_declared: int
    attr: int = 0
    readonly: bool = False
    revision: int = 0
    status: str = "ok"
    duplicate_knobs: list[dict[str, str]] = field(default_factory=list)
    knobs: list[Knob] = field(default_factory=list)


@dataclass
class DecodeResult:
    input: str
    bios_version: str
    ffs_guid: str
    ffs_offset: int
    ffs_size: int
    setup_driver_count: int
    default_data_count: int
    nvars: list[Nvar]
    warnings: list[WarningItem]


def read_uint(data: bytes, offset: int, size: int) -> int:
    if offset < 0 or size < 0 or offset + size > len(data):
        return 0
    return int.from_bytes(data[offset:offset + size], "little")


def write_uint(data: bytearray, offset: int, size: int, value: int) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise DecodeError(f"Write is outside the binary buffer at 0x{offset:X}, size {size}")
    data[offset:offset + size] = int(value).to_bytes(size, "little")


def read_c_string(data: bytes, offset: int, limit: int) -> tuple[str, int]:
    if offset >= limit:
        return "", offset
    end = offset
    while end < limit and data[end] != 0:
        end += 1
    text = data[offset:end].decode("latin-1", errors="replace")
    next_offset = end + 1 if end < limit else end
    return text, next_offset


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def guid_text_from_uefi(data: bytes, offset: int) -> str:
    if offset + 16 > len(data):
        return ZERO_GUID
    part0 = read_uint(data, offset, 4)
    part1 = read_uint(data, offset + 4, 2)
    part2 = read_uint(data, offset + 6, 2)
    tail = data[offset + 8:offset + 16]
    return f"{part0:08x}-{part1:04x}-{part2:04x}-{tail[0]:02x}{tail[1]:02x}-{tail[2:].hex()}"


def guid_to_uefi_bytes(guid_text: str) -> bytes:
    part0, part1, part2, part3, part4 = guid_text.split("-")
    return (
        int(part0, 16).to_bytes(4, "little")
        + int(part1, 16).to_bytes(2, "little")
        + int(part2, 16).to_bytes(2, "little")
        + bytes.fromhex(part3 + part4)
    )


def find_guid_offsets(data: bytes, guid_text: str) -> list[int]:
    needle = guid_to_uefi_bytes(guid_text)
    offsets: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return offsets
        offsets.append(offset)
        start = offset + 1


def looks_like_fv(data: bytes, offset: int) -> bool:
    if offset + 0x48 > len(data):
        return False
    if data[offset:offset + 16] != b"\x00" * 16:
        return False
    if guid_text_from_uefi(data, offset + 0x10) not in EFI_FIRMWARE_FILE_SYSTEM_GUIDS:
        return False
    if data[offset + 0x28:offset + 0x2C] != b"_FVH":
        return False
    size = read_uint(data, offset + 0x20, 8)
    return 0x48 <= size <= len(data) - offset


def parse_section_size(data: bytes, offset: int, end: int) -> tuple[int, int, int] | None:
    if offset + 4 > end:
        return None
    size = read_uint(data, offset, 3)
    section_type = data[offset + 3]
    header_size = 4
    if size == 0xFFFFFF:
        if offset + 8 > end:
            return None
        size = read_uint(data, offset + 4, 4)
        header_size = 8
    if size < header_size or offset + size > end:
        return None
    return size, section_type, header_size


def extract_ffs_by_guid(data: bytes, source: str, warnings: list[WarningItem], target_guids: set[str]) -> list[FirmwareFile]:
    files: list[FirmwareFile] = []
    for guid in target_guids:
        for offset in find_guid_offsets(data, guid):
            if offset + FFS_FILE_HEADER_SIZE > len(data):
                continue
            attr = data[offset + 0x13]
            size = read_uint(data, offset + 0x14, 3)
            header_size = FFS_FILE_HEADER_SIZE
            if size == 0xFFFFFF or attr & FFS_ATTRIB_LARGE_FILE:
                header_size = FFS_FILE_HEADER2_SIZE
                size = read_uint(data, offset + FFS_FILE_HEADER_SIZE, 4)
            if size < header_size or offset + size > len(data):
                warnings.append(WarningItem("Found target GUID but FFS size is invalid", offset, source))
                continue
            files.append(FirmwareFile(guid=guid, offset=offset, size=size, data=data[offset:offset + size], source=source))
    return dedupe_files(files)


def dedupe_files(files: list[FirmwareFile]) -> list[FirmwareFile]:
    unique: dict[tuple[str, int, int, str], FirmwareFile] = {}
    for file in files:
        unique[(file.guid, file.offset, file.size, file.source)] = file
    return list(unique.values())


def scan_firmware_files(
    data: bytes,
    source: str,
    warnings: list[WarningItem],
    depth: int = 0,
    target_guids: set[str] | None = None,
    stop_on_first: bool = True,
) -> list[FirmwareFile]:
    if target_guids is None:
        target_guids = {BIOS_KNOBS_DATA_BIN_GUID, BIOS_KNOBS_CPX_DATA_BIN_GUID}
    files = extract_ffs_by_guid(data, source, warnings, target_guids)
    if files and stop_on_first:
        return files
    if depth > 8:
        warnings.append(WarningItem("Maximum nested FV scan depth reached", None, source))
        return files

    for guid_offset in find_guid_offsets(data, LZMA_CUSTOM_DECOMPRESS_GUID):
        section_offset = guid_offset - 4
        if section_offset < 0:
            continue
        parsed = parse_section_size(data, section_offset, len(data))
        if parsed is None:
            continue
        section_size, section_type, _section_header_size = parsed
        if section_type != EFI_SECTION_GUID_DEFINED:
            continue
        data_offset = read_uint(data, guid_offset + 0x10, 2)
        compressed_start = section_offset + data_offset
        compressed_end = section_offset + section_size
        if compressed_start >= compressed_end:
            continue
        try:
            decompressed = lzma.decompress(data[compressed_start:compressed_end])
        except lzma.LZMAError as exc:
            warnings.append(WarningItem(f"LZMA GUID-defined section could not be decompressed: {exc}", section_offset, source))
            continue
        nested_source = f"{source}:lzma@0x{section_offset:X}"
        files.extend(scan_firmware_files(decompressed, nested_source, warnings, depth + 1, target_guids, stop_on_first))
        if files and stop_on_first:
            return dedupe_files(files)

    for guid_offset in find_guid_offsets(data, BROTLI_CUSTOM_DECOMPRESS_GUID):
        section_offset = guid_offset - 4
        warnings.append(WarningItem("Brotli compressed section found; skipped because this standalone tool uses only Python standard library", section_offset, source))

    offset = 0
    while offset + 0x48 <= len(data):
        if not looks_like_fv(data, offset):
            next_signature = data.find(b"_FVH", offset + 1)
            if next_signature < 0:
                break
            candidate_offset = max(0, next_signature - 0x28)
            offset = candidate_offset if candidate_offset > offset else next_signature + 1
            continue

        fv_size = read_uint(data, offset + 0x20, 8)
        fv_header_size = read_uint(data, offset + 0x30, 2)
        fv_end = offset + fv_size
        ffs_offset = align(offset + fv_header_size, 8)
        while ffs_offset + FFS_FILE_HEADER_SIZE <= fv_end:
            ffs_offset = align(ffs_offset, 8)
            if ffs_offset + FFS_FILE_HEADER_SIZE > fv_end:
                break
            file_guid = guid_text_from_uefi(data, ffs_offset)
            if file_guid in {ZERO_GUID, ALL_FFS_GUID}:
                break
            attr = data[ffs_offset + 0x13]
            ffs_size = read_uint(data, ffs_offset + 0x14, 3)
            header_size = FFS_FILE_HEADER_SIZE
            if ffs_size == 0xFFFFFF or attr & FFS_ATTRIB_LARGE_FILE:
                header_size = FFS_FILE_HEADER2_SIZE
                ffs_size = read_uint(data, ffs_offset + FFS_FILE_HEADER_SIZE, 4)
            if ffs_size < header_size or ffs_offset + ffs_size > fv_end:
                warnings.append(WarningItem("Invalid FFS size while walking FV", ffs_offset, source))
                break

            if file_guid in target_guids:
                files.append(FirmwareFile(file_guid, ffs_offset, ffs_size, data[ffs_offset:ffs_offset + ffs_size], source))
                if stop_on_first:
                    return dedupe_files(files)

            section_offset = ffs_offset + header_size
            ffs_end = ffs_offset + ffs_size
            while section_offset + 4 <= ffs_end:
                section_offset = align(section_offset, 4)
                parsed = parse_section_size(data, section_offset, ffs_end)
                if parsed is None:
                    break
                section_size, section_type, section_header_size = parsed
                section_payload = section_offset + section_header_size
                section_end = section_offset + section_size

                if section_type == EFI_SECTION_FIRMWARE_VOLUME_IMAGE:
                    nested = data[section_payload:section_end]
                    nested_source = f"{source}:fv@0x{section_offset:X}"
                    files.extend(scan_firmware_files(nested, nested_source, warnings, depth + 1, target_guids, stop_on_first))
                    if files and stop_on_first:
                        return dedupe_files(files)
                elif section_type == EFI_SECTION_GUID_DEFINED and section_offset + section_header_size + 0x14 <= section_end:
                    section_guid = guid_text_from_uefi(data, section_offset + section_header_size)
                    data_offset = read_uint(data, section_offset + section_header_size + 0x10, 2)
                    compressed_start = section_offset + data_offset
                    compressed = data[compressed_start:section_end]
                    if section_guid == LZMA_CUSTOM_DECOMPRESS_GUID:
                        try:
                            decompressed = lzma.decompress(compressed)
                        except lzma.LZMAError as exc:
                            warnings.append(WarningItem(f"LZMA GUID-defined section could not be decompressed: {exc}", section_offset, source))
                        else:
                            nested_source = f"{source}:lzma@0x{section_offset:X}"
                            files.extend(scan_firmware_files(decompressed, nested_source, warnings, depth + 1, target_guids, stop_on_first))
                            if files and stop_on_first:
                                return dedupe_files(files)
                    elif section_guid == BROTLI_CUSTOM_DECOMPRESS_GUID:
                        warnings.append(WarningItem("Brotli compressed section found; skipped because this standalone tool uses only Python standard library", section_offset, source))

                section_offset = align(section_end, 4)

            ffs_offset = align(ffs_offset + ffs_size, 8)

        offset = fv_end

    return dedupe_files(files)


def find_packet_start(data: bytes) -> int:
    candidates = [0x1C, 0, data.find(b"$NVAR"), data.find(b"$NVRO")]
    for candidate in candidates:
        if candidate >= 0 and data[candidate:candidate + 5] in {b"$NVAR", b"$NVRO"}:
            return candidate
    raise DecodeError("BiosKnobsDataBin payload does not contain a $NVAR/$NVRO packet")


def format_guid_from_packet(data: bytes, offset: int) -> str:
    if offset + 16 > len(data):
        return ZERO_GUID
    return guid_text_from_uefi(data, offset)


def setup_type_from_knob_info(knob_info: int, revision: int, is_readonly: bool, data: bytes, ptr: int) -> tuple[int, str, int, int, bool, int]:
    knob_type = (knob_info >> 4) & 0xF
    bit_data = 0
    if knob_type >= 0x8:
        knob_type = 0x8
        knob_size = (knob_info & 0x7F) * 2
        return knob_type, SETUP_TYPE_BY_BIN.get(knob_type, "??"), knob_size, ptr, False, bit_data

    knob_size = knob_info & 0x0F
    if revision >= 3 and knob_type < 0x4:
        knob_type += 0x4
    bitwise = False
    if knob_size >= 0xC:
        bit_data = data[ptr] if ptr < len(data) else 0
        ptr += 1
        knob_size = ((knob_size & 0x1) << 5) + ((bit_data >> 3) & 0x1F)
        bitwise = True
    setup_type = 0xF if is_readonly else knob_type
    return setup_type, SETUP_TYPE_BY_BIN.get(setup_type, "??"), knob_size, ptr, bitwise, bit_data


def parse_bios_knobs_data_bin(data: bytes, bios_id: str, warnings: list[WarningItem]) -> list[Nvar]:
    packet_start = find_packet_start(data)
    end = len(data)
    ptr = packet_start
    header_size = BIOS_KNOBS_DATA_BIN_HDR_SIZE_OLD
    nvars: list[Nvar] = []

    while ptr + header_size <= end:
        signature = data[ptr:ptr + 5]
        if signature not in {b"$NVAR", b"$NVRO"}:
            next_nvar = data.find(b"$NVAR", ptr + 1)
            next_nvro = data.find(b"$NVRO", ptr + 1)
            next_candidates = [value for value in [next_nvar, next_nvro] if value >= 0]
            if not next_candidates:
                break
            ptr = min(next_candidates)
            continue

        var_id = data[ptr + 5]
        knob_count = read_uint(data, ptr + 6, 2)
        dup_offset = read_uint(data, ptr + 8, 3)
        packet_size = read_uint(data, ptr + 0xB, 3)
        nvar_size = read_uint(data, ptr + 0xE, 2)
        if packet_size <= 0 or ptr + packet_size > end:
            warnings.append(WarningItem("Invalid $NVAR/$NVRO packet size; stopping parse", ptr, "BiosKnobsDataBin"))
            break
        if dup_offset <= 0 or dup_offset > packet_size:
            warnings.append(WarningItem("Invalid duplicate-list offset; stopping parse", ptr, "BiosKnobsDataBin"))
            break

        is_readonly = signature == b"$NVRO"
        revision = 0
        nvar_guid = ZERO_GUID
        if nvar_size == 0:
            name_table = OLD_NVAR_NAMES_PLY if bios_id[:3] == "PLY" else OLD_NVAR_NAMES
            nvar_name = name_table.get(var_id, f"Nvar{var_id}")
            entry_ptr = ptr + BIOS_KNOBS_DATA_BIN_HDR_SIZE_OLD
        else:
            revision = data[ptr + BIOS_KNOB_BIN_REVISION_OFFSET]
            if revision >= 2:
                nvar_guid = format_guid_from_packet(data, ptr + BIOS_KNOB_BIN_GUID_OFFSET)
                nvar_size = read_uint(data, ptr + NVAR_SIZE_OFFSET, 2)
            name_offset = data[ptr + NVAR_NAME_OFFSET]
            nvar_name, _ = read_c_string(data, ptr + name_offset, ptr + packet_size)
            entry_ptr = ptr + (BIOS_KNOBS_DATA_BIN_HDR_SIZE_V03 if revision >= 3 else BIOS_KNOBS_DATA_BIN_HDR_SIZE)

        nvar = Nvar(
            var_id=var_id,
            name=nvar_name,
            guid=nvar_guid,
            size=nvar_size,
            knob_count_declared=knob_count,
            readonly=is_readonly,
            revision=revision,
        )

        knob_end = ptr + dup_offset
        while entry_ptr < knob_end:
            if entry_ptr + 2 > knob_end:
                warnings.append(WarningItem("Truncated knob entry", entry_ptr, nvar_name))
                break
            knob_offset = read_uint(data, entry_ptr, 2)
            entry_ptr += 2
            bitwise = False
            if nvar_size == 0:
                knob_size = INVALID_KNOB_SIZE
                setup_type_raw = INVALID_KNOB_SIZE
                setup_type = "??"
            else:
                if entry_ptr >= knob_end:
                    warnings.append(WarningItem("Truncated knob info byte", entry_ptr, nvar_name))
                    break
                knob_info = data[entry_ptr]
                entry_ptr += 1
                setup_type_raw, setup_type, knob_size, entry_ptr, bitwise, bit_data = setup_type_from_knob_info(
                    knob_info, revision, is_readonly, data, entry_ptr
                )
                if bitwise:
                    knob_offset = BITWISE_KNOB_PREFIX + (knob_offset * 8) + (bit_data & 0x7)

            knob_name, entry_ptr = read_c_string(data, entry_ptr, knob_end)
            knob_depex, entry_ptr = read_c_string(data, entry_ptr, knob_end)
            if not knob_depex:
                knob_depex = "TRUE"
            offset_text = f"0x{knob_offset:05X}" if bitwise else f"0x{knob_offset:04X}"
            nvar.knobs.append(
                Knob(
                    var_id=var_id,
                    nvar_name=nvar_name,
                    nvar_guid=nvar_guid,
                    offset=knob_offset,
                    offset_text=offset_text,
                    size=knob_size,
                    setup_type=setup_type,
                    name=knob_name,
                    depex=knob_depex,
                    raw_setup_type=setup_type_raw,
                    bitwise=bitwise,
                )
            )

        dup_ptr = ptr + dup_offset
        while dup_ptr < ptr + packet_size:
            dup_name, dup_ptr = read_c_string(data, dup_ptr, ptr + packet_size)
            dup_depex, dup_ptr = read_c_string(data, dup_ptr, ptr + packet_size)
            if dup_name or dup_depex:
                nvar.duplicate_knobs.append({"name": dup_name, "depex": dup_depex or "TRUE"})

        if len(nvar.knobs) != knob_count:
            warnings.append(WarningItem(f"Declared knob count is {knob_count}, parsed {len(nvar.knobs)}", ptr, nvar_name))
        nvars.append(nvar)
        ptr += packet_size

    if not nvars:
        raise DecodeError("No valid $NVAR/$NVRO packets were decoded from BiosKnobsDataBin")
    return nvars


def clean_hii_string(text: str) -> str:
    return (
        text.replace("<=", " &lte; ")
        .replace(">=", " &gte; ")
        .replace('"', "&quot;")
        .replace("'", "")
        .replace("\x13", "")
        .replace("\x19", "")
        .replace("\xB5", "u")
        .replace("\xAE", "")
        .replace("<", " &lt; ")
        .replace(">", " &gt; ")
        .replace("&", "n")
        .replace("\r\n", " ")
        .replace("\n", " ")
    )


INVALID_XML_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]")


def xml_safe_text(value: object) -> str:
    return INVALID_XML_CHAR_RE.sub("", str(value))


def sanitize_xml_tree(root: ET.Element) -> None:
    for element in root.iter():
        if element.text:
            element.text = xml_safe_text(element.text)
        if element.tail:
            element.tail = xml_safe_text(element.tail)
        for key, value in list(element.attrib.items()):
            element.set(key, xml_safe_text(value))


def read_ucs2_string(data: bytes, offset: int, limit: int) -> tuple[str, int]:
    chars: list[str] = []
    ptr = offset
    while ptr + 1 < limit:
        value = read_uint(data, ptr, 2)
        ptr += 2
        if value == 0:
            break
        chars.append(chr(value & 0xFF))
    return clean_hii_string("".join(chars)), ptr


def parse_hii_strings(data: bytes, string_header: int) -> dict[int, str]:
    strings: dict[int, str] = {}
    if string_header <= 0 or string_header + 0x10 > len(data):
        return strings
    package_size = read_uint(data, string_header, 3)
    string_offset = read_uint(data, string_header + 0x8, 4)
    ptr = string_header + string_offset
    end = min(len(data), string_header + package_size)
    string_id = 1
    while ptr < end:
        block_type = data[ptr]
        ptr += 1
        if block_type == EFI_HII_SIBT_END:
            break
        if block_type == EFI_HII_SIBT_STRING_SCSU:
            text, ptr = read_c_string(data, ptr, end)
            strings[string_id] = clean_hii_string(text)
            string_id += 1
        elif block_type == EFI_HII_SIBT_STRING_UCS2:
            text, ptr = read_ucs2_string(data, ptr, end)
            strings[string_id] = text
            string_id += 1
        elif block_type == EFI_HII_SIBT_STRING_SCSU_FONT:
            ptr += 1
            _text, ptr = read_c_string(data, ptr, end)
        elif block_type == EFI_HII_SIBT_STRING_UCS2_FONT:
            ptr += 1
            _text, ptr = read_ucs2_string(data, ptr, end)
        elif block_type == EFI_HII_SIBT_SKIP1:
            string_id += read_uint(data, ptr, 1)
            ptr += 1
        elif block_type == EFI_HII_SIBT_SKIP2:
            string_id += read_uint(data, ptr, 2)
            ptr += 2
        elif block_type == EFI_HII_SIBT_DUPLICATE:
            ptr += 2
        elif block_type == EFI_HII_SIBT_EXT1:
            ptr += 2
        elif block_type == EFI_HII_SIBT_EXT2:
            ptr += 3
        elif block_type == EFI_HII_SIBT_EXT4:
            ptr += 5
        elif block_type == EFI_HII_SIBT_STRINGS_SCSU:
            count = read_uint(data, ptr, 2)
            ptr += 2
            for _ in range(count):
                _text, ptr = read_c_string(data, ptr, end)
                string_id += 1
        elif block_type == EFI_HII_SIBT_STRINGS_UCS2:
            count = read_uint(data, ptr, 2)
            ptr += 2
            for _ in range(count):
                _text, ptr = read_ucs2_string(data, ptr, end)
                string_id += 1
        elif block_type == EFI_HII_SIBT_STRINGS_SCSU_FONT:
            ptr += 1
            count = read_uint(data, ptr, 2)
            ptr += 2
            for _ in range(count):
                _text, ptr = read_c_string(data, ptr, end)
                string_id += 1
        elif block_type == EFI_HII_SIBT_STRINGS_UCS2_FONT:
            ptr += 1
            count = read_uint(data, ptr, 2)
            ptr += 2
            for _ in range(count):
                _text, ptr = read_ucs2_string(data, ptr, end)
                string_id += 1
        else:
            break
    return strings


def get_hii_package_locations(data: bytes) -> tuple[list[int], int]:
    ifr_starts: list[int] = []
    string_header = 0
    tiano_bytes = guid_to_uefi_bytes(EFI_IFR_TIANO_GUID)
    start = 0
    while True:
        guid_offset = data.find(tiano_bytes, start)
        if guid_offset < 0:
            break
        opcode_offset = guid_offset - 2
        if opcode_offset >= 0 and data[opcode_offset] == EFI_IFR_GUID_OP:
            formset_offset = guid_offset - 2 - 0x27
            if formset_offset >= 0 and read_uint(data, formset_offset, 2) == 0xA70E:
                ifr_starts.append(formset_offset)
            else:
                ifr_starts.append(opcode_offset)
        start = guid_offset + 1

    en_us = b"en-US"
    start = 0
    while True:
        lang_offset = data.find(en_us, start)
        if lang_offset < 0:
            break
        if lang_offset + 0x17 < len(data):
            string_block_type = data[lang_offset + 0x6]
            prompt_low = read_uint(data, lang_offset + 0x7, 8)
            prompt_high = read_uint(data, lang_offset + 0xF, 8)
            if string_block_type == EFI_HII_SIBT_STRING_UCS2 and prompt_low == 0x6C0067006E0045 and prompt_high == 0x6800730069:
                package_type = data[lang_offset - 0x2B] if lang_offset >= 0x2B else 0
                string_offset = read_uint(data, lang_offset - 0x26, 4) if lang_offset >= 0x26 else 0
                candidate = lang_offset + 6 - string_offset
                if package_type == EFI_HII_PACKAGE_STRINGS and 0 <= candidate < len(data):
                    string_header = candidate
                    break
        start = lang_offset + 1
    return ifr_starts, string_header


def ifr_value(data: bytes, offset: int, value_type: int) -> int:
    if value_type == EFI_IFR_TYPE_BOOLEAN:
        return int(read_uint(data, offset, 1) != 0)
    if value_type == EFI_IFR_TYPE_NUM_SIZE_8:
        return read_uint(data, offset, 1)
    if value_type == EFI_IFR_TYPE_NUM_SIZE_16:
        return read_uint(data, offset, 2)
    if value_type == EFI_IFR_TYPE_NUM_SIZE_32:
        return read_uint(data, offset, 4)
    if value_type == EFI_IFR_TYPE_NUM_SIZE_64:
        return read_uint(data, offset, 8)
    return read_uint(data, offset, 1)


def setup_page_path(
    current_form_id: int,
    form_titles: dict[int, int],
    form_refs: dict[int, dict[int, int]],
    front_page_forms: set[int],
    strings: dict[int, str],
) -> str:
    if current_form_id not in form_titles:
        return ""
    prompts: list[int] = []
    cur_form_id = current_form_id
    visited: set[int] = set()
    while cur_form_id not in visited:
        visited.add(cur_form_id)
        parent = None
        for form_id, children in form_refs.items():
            if cur_form_id in children and form_id not in visited:
                parent = form_id
                prompts.append(children[cur_form_id])
                break
        if parent is None:
            root_prompt = form_titles.get(cur_form_id, 0)
            prompts.append(root_prompt)
            if root_prompt not in front_page_forms:
                prompts.append(0x10000)
            break
        cur_form_id = parent
    page_names = [strings.get(prompt_id, "???") for prompt_id in reversed(prompts) if prompt_id]
    return "/".join(name for name in page_names if name)


def synthetic_knob_name(prompt: str, var_name: str, offset: int, used_names: set[str]) -> str:
    base = clean_hii_string(prompt or "").strip() or f"{var_name}_0x{offset:04X}"
    base = re.sub(r"[^0-9A-Za-z_]+", "_", base).strip("_") or "SetupQuestion"
    if base[0].isdigit():
        base = f"Knob_{base}"
    candidate = f"{base}__{var_name}_0x{offset:04X}"
    suffix = 2
    while candidate.lower() in used_names:
        candidate = f"{base}__{var_name}_0x{offset:04X}_{suffix}"
        suffix += 1
    used_names.add(candidate.lower())
    return candidate


def knob_dedupe_score(knob: Knob) -> int:
    score = 0
    for value in (knob.prompt, knob.description, knob.setup_page, knob.depex):
        if value:
            score += 1
    score += int(knob.default_available)
    score += int(knob.current_available)
    score += int(knob.processed)
    score += int(bool(knob.options))
    score += int(knob.min_value is not None)
    score += int(knob.max_value is not None)
    score += int(knob.step is not None)
    return score


def dedupe_knobs_by_guid_offset(nvars: list[Nvar]) -> int:
    removed = 0
    for nvar in nvars:
        unique_knobs: list[Knob] = []
        seen: dict[tuple[str, int], int] = {}
        for knob in nvar.knobs:
            key = (knob.nvar_guid.lower(), int(knob.offset))
            existing_index = seen.get(key)
            if existing_index is None:
                seen[key] = len(unique_knobs)
                unique_knobs.append(knob)
                continue
            if knob_dedupe_score(knob) > knob_dedupe_score(unique_knobs[existing_index]):
                unique_knobs[existing_index] = knob
            removed += 1
        nvar.knobs = unique_knobs
        nvar.knob_count_declared = len(unique_knobs)
    return removed


def parse_hii_only_knobs(setup_files: list[FirmwareFile], warnings: list[WarningItem]) -> list[Nvar]:
    nvars: list[Nvar] = []
    nvar_by_key: dict[tuple[str, str], Nvar] = {}
    used_names: set[str] = set()

    for setup_file in setup_files:
        ifr_starts, string_header = get_hii_package_locations(setup_file.data)
        if not ifr_starts:
            continue
        strings = parse_hii_strings(setup_file.data, string_header)
        for ifr_start in ifr_starts:
            varstore_to_nvar: dict[int, Nvar] = {}
            form_titles: dict[int, int] = {}
            form_refs: dict[int, dict[int, int]] = {}
            front_page_forms: set[int] = set()
            current_form_id = 0
            capture_front_page_form = False
            ptr = ifr_start
            end = len(setup_file.data)
            bitwise_form = False
            while ptr + 2 <= end:
                opcode = setup_file.data[ptr]
                length = setup_file.data[ptr + 1] & 0x7F
                if length <= 0 or ptr + length > end:
                    break
                if opcode in (EFI_IFR_SUPPRESS_IF_OP, EFI_IFR_GRAY_OUT_IF_OP) and (setup_file.data[ptr + 1] >> 7):
                    next_ptr = ptr + length
                    if next_ptr + 2 <= end:
                        next_opcode = setup_file.data[next_ptr]
                        next_length = setup_file.data[next_ptr + 1] & 0x7F
                        next_scope = setup_file.data[next_ptr + 1] >> 7
                        if next_opcode == EFI_IFR_TRUE_OP and next_length > 0 and next_scope == 0:
                            scan = next_ptr
                            scope_level = 1
                            while scan + 2 <= end and scope_level > 0:
                                scan_opcode = setup_file.data[scan]
                                scan_length = setup_file.data[scan + 1] & 0x7F
                                if scan_length <= 0 or scan + scan_length > end:
                                    break
                                if scan != next_ptr and (setup_file.data[scan + 1] >> 7):
                                    scope_level += 1
                                if scan_opcode == EFI_IFR_END_OP:
                                    scope_level -= 1
                                scan += scan_length
                            ptr = scan
                            continue
                if opcode == EFI_IFR_GUID_OP and guid_text_from_uefi(setup_file.data, ptr + 2) == EDKII_IFR_BIT_VARSTORE_GUID:
                    bitwise_form = True
                    ptr += length
                    continue
                if bitwise_form and opcode == EFI_IFR_END_OP:
                    bitwise_form = False
                if opcode == EFI_IFR_FORM_SET_OP:
                    capture_front_page_form = True
                elif opcode == EFI_IFR_FORM_OP:
                    current_form_id = read_uint(setup_file.data, ptr + 2, 2)
                    title_prompt = read_uint(setup_file.data, ptr + 4, 2)
                    form_titles[current_form_id] = title_prompt
                    form_refs.setdefault(current_form_id, {})
                    if capture_front_page_form:
                        front_page_forms.add(title_prompt)
                        capture_front_page_form = False
                elif opcode == EFI_IFR_REF_OP and current_form_id:
                    goto_prompt = read_uint(setup_file.data, ptr + 2, 2)
                    target_form_id = read_uint(setup_file.data, ptr + 0x0D, 2) if length >= 0x0F else 0
                    if target_form_id:
                        form_refs.setdefault(current_form_id, {})[target_form_id] = goto_prompt
                elif opcode in (EFI_IFR_VARSTORE_OP, EFI_IFR_VARSTORE_EFI_OP):
                    if opcode == EFI_IFR_VARSTORE_OP:
                        guid_offset, var_id_offset, size_offset, name_offset = 2, 0x12, 0x14, 0x16
                    else:
                        guid_offset, var_id_offset, size_offset, name_offset = 4, 2, 0x18, 0x1A
                    var_guid = guid_text_from_uefi(setup_file.data, ptr + guid_offset)
                    hii_var_id = read_uint(setup_file.data, ptr + var_id_offset, 2)
                    var_size = read_uint(setup_file.data, ptr + size_offset, 2)
                    var_name = setup_file.data[ptr + name_offset:ptr + length].split(b"\x00", 1)[0].decode("latin-1", errors="replace")
                    if not var_name:
                        var_name = f"VarStore{hii_var_id:04X}"
                    key = (var_name, var_guid)
                    nvar = nvar_by_key.get(key)
                    if nvar is None:
                        nvar = Nvar(
                            var_id=len(nvars),
                            name=var_name,
                            guid=var_guid,
                            size=var_size,
                            knob_count_declared=0,
                        )
                        nvar_by_key[key] = nvar
                        nvars.append(nvar)
                    elif var_size and not nvar.size:
                        nvar.size = var_size
                    varstore_to_nvar[hii_var_id] = nvar
                elif opcode in (EFI_IFR_ONE_OF_OP, EFI_IFR_NUMERIC_OP, EFI_IFR_CHECKBOX_OP, EFI_IFR_STRING_OP):
                    prompt_id = read_uint(setup_file.data, ptr + 2, 2)
                    help_id = read_uint(setup_file.data, ptr + 4, 2)
                    hii_var_id = read_uint(setup_file.data, ptr + 8, 2)
                    knob_offset = read_uint(setup_file.data, ptr + 0x0A, 2)
                    nvar = varstore_to_nvar.get(hii_var_id)
                    if nvar is None:
                        var_name = f"UndecodedVarStore{hii_var_id:04X}"
                        key = (var_name, ZERO_GUID)
                        nvar = nvar_by_key.get(key)
                        if nvar is None:
                            nvar = Nvar(
                                var_id=len(nvars),
                                name=var_name,
                                guid=ZERO_GUID,
                                size=0,
                                knob_count_declared=0,
                                readonly=True,
                                status="undecoded-varstore",
                            )
                            nvar_by_key[key] = nvar
                            nvars.append(nvar)
                        varstore_to_nvar[hii_var_id] = nvar
                    setup_type = SETUP_TYPE_BY_IFR.get(opcode, "??")
                    stored_offset = BITWISE_KNOB_PREFIX + knob_offset if bitwise_form else knob_offset
                    offset_text = f"0x{stored_offset:05X}" if bitwise_form else f"0x{stored_offset:04X}"
                    current_prompt = strings.get(prompt_id, f"Question_0x{prompt_id:04X}")
                    current_description = strings.get(help_id, "")
                    page_path = setup_page_path(current_form_id, form_titles, form_refs, front_page_forms, strings)
                    current_setup_page = f"{page_path}/{current_prompt}" if page_path else current_prompt
                    knob = Knob(
                        var_id=nvar.var_id,
                        nvar_name=nvar.name,
                        nvar_guid=nvar.guid,
                        offset=stored_offset,
                        offset_text=offset_text,
                        size=1,
                        setup_type=setup_type,
                        name=synthetic_knob_name(current_prompt, nvar.name, stored_offset, used_names),
                        depex="TRUE",
                        raw_setup_type=opcode,
                        bitwise=bitwise_form,
                        prompt=current_prompt,
                        description=current_description,
                        setup_page=current_setup_page,
                        processed=True,
                    )
                    if opcode == EFI_IFR_CHECKBOX_OP:
                        knob.size = 1
                        knob.default = read_uint(setup_file.data, ptr + 0x0D, 1) & 1
                        knob.default_available = True
                    elif opcode == EFI_IFR_STRING_OP:
                        knob.min_value = read_uint(setup_file.data, ptr + 0x0D, 1)
                        knob.max_value = read_uint(setup_file.data, ptr + 0x0E, 1)
                        knob.size = (knob.max_value or 0) * 2
                    elif opcode in (EFI_IFR_ONE_OF_OP, EFI_IFR_NUMERIC_OP):
                        flags = read_uint(setup_file.data, ptr + 0x0D, 1)
                        value_size = 1 << (flags & 0x03)
                        knob.size = (flags & 0x3F) if bitwise_form else value_size
                        if opcode == EFI_IFR_NUMERIC_OP:
                            if bitwise_form:
                                bit_size = max(knob.size, 1)
                                mask = (1 << bit_size) - 1
                                knob.min_value = read_uint(setup_file.data, ptr + 0x0E, value_size) & mask
                                knob.max_value = read_uint(setup_file.data, ptr + 0x0E + value_size, value_size) & mask
                                knob.step = read_uint(setup_file.data, ptr + 0x0E + value_size * 2, value_size) & mask
                            else:
                                knob.min_value = read_uint(setup_file.data, ptr + 0x0E, value_size)
                                knob.max_value = read_uint(setup_file.data, ptr + 0x0E + value_size, value_size)
                                knob.step = read_uint(setup_file.data, ptr + 0x0E + value_size * 2, value_size)
                        if setup_file.data[ptr + 1] & 0x80:
                            scope = 1
                            inner = ptr + length
                            options: list[dict[str, Any]] = []
                            while inner + 2 <= end and scope > 0:
                                inner_opcode = setup_file.data[inner]
                                inner_length = setup_file.data[inner + 1] & 0x7F
                                if inner_length <= 0 or inner + inner_length > end:
                                    break
                                if inner_opcode == EFI_IFR_ONE_OF_OPTION_OP:
                                    option_text = read_uint(setup_file.data, inner + 2, 2)
                                    option_flag = read_uint(setup_file.data, inner + 4, 1)
                                    option_type = option_flag & 0x0F
                                    option_value = ifr_value(setup_file.data, inner + 6, option_type)
                                    options.append({"text": strings.get(option_text, f"NotFound(0x{option_text:04X})"), "value": option_value})
                                    if option_flag & EFI_IFR_OPTION_DEFAULT:
                                        knob.default = option_value
                                        knob.default_available = True
                                elif inner_opcode == EFI_IFR_DEFAULT_OP:
                                    default_type = read_uint(setup_file.data, inner + 4, 1) & 0x0F
                                    knob.default = ifr_value(setup_file.data, inner + 5, default_type)
                                    knob.default_available = True
                                if setup_file.data[inner + 1] & 0x80:
                                    scope += 1
                                if inner_opcode == EFI_IFR_END_OP:
                                    scope -= 1
                                inner += inner_length
                            if options:
                                knob.options = options
                    nvar.knobs.append(knob)
                ptr += length

    for nvar in nvars:
        nvar.knob_count_declared = len(nvar.knobs)
    dedupe_knobs_by_guid_offset(nvars)
    undecoded_varstore_questions = sum(
        len(nvar.knobs) for nvar in nvars if nvar.status == "undecoded-varstore"
    )
    if undecoded_varstore_questions:
        warnings.append(WarningItem(f"Preserved {undecoded_varstore_questions} HII questions with undecoded VarStore metadata", None, "HII"))
    return [nvar for nvar in nvars if nvar.knobs]


def enrich_knobs_from_hii(nvars: list[Nvar], setup_files: list[FirmwareFile]) -> int:
    enriched = 0
    knob_by_var_offset: dict[tuple[int, int], list[Knob]] = {}
    nvars_by_name: dict[tuple[str, str], list[Nvar]] = {}
    for nvar in nvars:
        nvars_by_name.setdefault((nvar.name, nvar.guid), []).append(nvar)
        nvars_by_name.setdefault((nvar.name, ZERO_GUID), []).append(nvar)
        for knob in nvar.knobs:
            knob_by_var_offset.setdefault((nvar.var_id, knob.offset), []).append(knob)

    for setup_file in setup_files:
        ifr_starts, string_header = get_hii_package_locations(setup_file.data)
        if not ifr_starts:
            continue
        strings = parse_hii_strings(setup_file.data, string_header)
        for ifr_start in ifr_starts:
            varstore_to_nvar: dict[int, Nvar] = {}
            form_titles: dict[int, int] = {}
            form_refs: dict[int, dict[int, int]] = {}
            front_page_forms: set[int] = set()
            current_form_id = 0
            capture_front_page_form = False
            ptr = ifr_start
            end = len(setup_file.data)
            bitwise_form = False
            while ptr + 2 <= end:
                opcode = setup_file.data[ptr]
                length = setup_file.data[ptr + 1] & 0x7F
                if length <= 0 or ptr + length > end:
                    break
                if opcode in (EFI_IFR_SUPPRESS_IF_OP, EFI_IFR_GRAY_OUT_IF_OP) and (setup_file.data[ptr + 1] >> 7):
                    next_ptr = ptr + length
                    if next_ptr + 2 <= end:
                        next_opcode = setup_file.data[next_ptr]
                        next_length = setup_file.data[next_ptr + 1] & 0x7F
                        next_scope = setup_file.data[next_ptr + 1] >> 7
                        if next_opcode == EFI_IFR_TRUE_OP and next_length > 0 and next_scope == 0:
                            scan = next_ptr
                            scope_level = 1
                            while scan + 2 <= end and scope_level > 0:
                                scan_opcode = setup_file.data[scan]
                                scan_length = setup_file.data[scan + 1] & 0x7F
                                if scan_length <= 0 or scan + scan_length > end:
                                    break
                                if scan != next_ptr and (setup_file.data[scan + 1] >> 7):
                                    scope_level += 1
                                if scan_opcode == EFI_IFR_END_OP:
                                    scope_level -= 1
                                scan += scan_length
                            ptr = scan
                            continue
                if opcode == EFI_IFR_GUID_OP and guid_text_from_uefi(setup_file.data, ptr + 2) == EDKII_IFR_BIT_VARSTORE_GUID:
                    bitwise_form = True
                    ptr += length
                    continue
                if bitwise_form and opcode == EFI_IFR_END_OP:
                    bitwise_form = False
                if opcode == EFI_IFR_FORM_SET_OP:
                    capture_front_page_form = True
                elif opcode == EFI_IFR_FORM_OP:
                    current_form_id = read_uint(setup_file.data, ptr + 2, 2)
                    title_prompt = read_uint(setup_file.data, ptr + 4, 2)
                    form_titles[current_form_id] = title_prompt
                    form_refs.setdefault(current_form_id, {})
                    if capture_front_page_form:
                        front_page_forms.add(title_prompt)
                        capture_front_page_form = False
                elif opcode == EFI_IFR_REF_OP and current_form_id:
                    goto_prompt = read_uint(setup_file.data, ptr + 2, 2)
                    target_form_id = read_uint(setup_file.data, ptr + 0x0D, 2) if length >= 0x0F else 0
                    if target_form_id:
                        form_refs.setdefault(current_form_id, {})[target_form_id] = goto_prompt
                elif opcode in (EFI_IFR_VARSTORE_OP, EFI_IFR_VARSTORE_EFI_OP):
                    if opcode == EFI_IFR_VARSTORE_OP:
                        guid_offset, var_id_offset, size_offset, name_offset = 2, 0x12, 0x14, 0x16
                    else:
                        guid_offset, var_id_offset, size_offset, name_offset = 4, 2, 0x18, 0x1A
                    var_guid = guid_text_from_uefi(setup_file.data, ptr + guid_offset)
                    hii_var_id = read_uint(setup_file.data, ptr + var_id_offset, 2)
                    var_name = setup_file.data[ptr + name_offset:ptr + length].split(b"\x00", 1)[0].decode("latin-1", errors="replace")
                    matches = nvars_by_name.get((var_name, var_guid)) or nvars_by_name.get((var_name, ZERO_GUID)) or []
                    if matches:
                        chosen = next((item for item in matches if not item.readonly), matches[0])
                        varstore_to_nvar[hii_var_id] = chosen
                elif opcode in (EFI_IFR_ONE_OF_OP, EFI_IFR_NUMERIC_OP, EFI_IFR_CHECKBOX_OP, EFI_IFR_STRING_OP):
                    prompt_id = read_uint(setup_file.data, ptr + 2, 2)
                    help_id = read_uint(setup_file.data, ptr + 4, 2)
                    hii_var_id = read_uint(setup_file.data, ptr + 8, 2)
                    knob_offset = read_uint(setup_file.data, ptr + 0x0A, 2)
                    nvar = varstore_to_nvar.get(hii_var_id)
                    if nvar is None:
                        ptr += length
                        continue
                    lookup_offset = BITWISE_KNOB_PREFIX + knob_offset if bitwise_form else knob_offset
                    candidates = knob_by_var_offset.get((nvar.var_id, lookup_offset), [])
                    if not candidates:
                        ptr += length
                        continue
                    expected_setup_type = SETUP_TYPE_BY_IFR.get(opcode)
                    candidates = [item for item in candidates if item.setup_type == expected_setup_type]
                    if not candidates:
                        ptr += length
                        continue
                    if opcode in (EFI_IFR_ONE_OF_OP, EFI_IFR_NUMERIC_OP):
                        flags = read_uint(setup_file.data, ptr + 0x0D, 1)
                        value_size = 1 << (flags & 0x03)
                        bit_size = flags & 0x3F
                        expected_size = bit_size if bitwise_form else value_size
                        candidates = [item for item in candidates if item.size in (INVALID_KNOB_SIZE, expected_size)]
                        if not candidates:
                            ptr += length
                            continue
                    knob = candidates[0]
                    current_prompt = strings.get(prompt_id, "")
                    current_description = strings.get(help_id, "")
                    page_path = setup_page_path(current_form_id, form_titles, form_refs, front_page_forms, strings)
                    if page_path:
                        current_setup_page = f"{page_path}/{current_prompt}"
                    else:
                        current_setup_page = current_prompt
                    if knob.processed:
                        if not (knob.setup_page.startswith("NONE/") and current_setup_page and not current_setup_page.startswith("NONE/")):
                            ptr += length
                            continue
                    knob.prompt = current_prompt
                    knob.description = current_description
                    knob.setup_page = current_setup_page
                    knob.setup_type = SETUP_TYPE_BY_IFR.get(opcode, knob.setup_type)
                    if opcode == EFI_IFR_CHECKBOX_OP:
                        knob.size = 1
                        knob.default = read_uint(setup_file.data, ptr + 0x0D, 1) & 1
                        knob.default_available = True
                    elif opcode == EFI_IFR_STRING_OP:
                        knob.min_value = read_uint(setup_file.data, ptr + 0x0D, 1)
                        knob.max_value = read_uint(setup_file.data, ptr + 0x0E, 1)
                        knob.size = (knob.max_value or 0) * 2
                    elif opcode in (EFI_IFR_ONE_OF_OP, EFI_IFR_NUMERIC_OP):
                        flags = read_uint(setup_file.data, ptr + 0x0D, 1)
                        value_size = 1 << (flags & 0x03)
                        knob.size = (flags & 0x3F) if bitwise_form else value_size
                        if opcode == EFI_IFR_NUMERIC_OP:
                            if bitwise_form:
                                bit_size = max(knob.size, 1)
                                mask = (1 << bit_size) - 1
                                knob.min_value = read_uint(setup_file.data, ptr + 0x0E, value_size) & mask
                                knob.max_value = read_uint(setup_file.data, ptr + 0x0E + value_size, value_size) & mask
                                knob.step = read_uint(setup_file.data, ptr + 0x0E + value_size * 2, value_size) & mask
                            else:
                                knob.min_value = read_uint(setup_file.data, ptr + 0x0E, value_size)
                                knob.max_value = read_uint(setup_file.data, ptr + 0x0E + value_size, value_size)
                                knob.step = read_uint(setup_file.data, ptr + 0x0E + value_size * 2, value_size)
                        if setup_file.data[ptr + 1] & 0x80:
                            scope = 1
                            inner = ptr + length
                            options: list[dict[str, Any]] = []
                            while inner + 2 <= end and scope > 0:
                                inner_opcode = setup_file.data[inner]
                                inner_length = setup_file.data[inner + 1] & 0x7F
                                if inner_length <= 0 or inner + inner_length > end:
                                    break
                                if inner_opcode == EFI_IFR_ONE_OF_OPTION_OP:
                                    option_text = read_uint(setup_file.data, inner + 2, 2)
                                    option_flag = read_uint(setup_file.data, inner + 4, 1)
                                    option_type = option_flag & 0x0F
                                    option_value = ifr_value(setup_file.data, inner + 6, option_type)
                                    options.append({"text": strings.get(option_text, f"NotFound(0x{option_text:04X})"), "value": option_value})
                                    if option_flag & EFI_IFR_OPTION_DEFAULT:
                                        knob.default = option_value
                                        knob.default_available = True
                                elif inner_opcode == EFI_IFR_DEFAULT_OP:
                                    default_type = read_uint(setup_file.data, inner + 4, 1) & 0x0F
                                    knob.default = ifr_value(setup_file.data, inner + 5, default_type)
                                    knob.default_available = True
                                if setup_file.data[inner + 1] & 0x80:
                                    scope += 1
                                if inner_opcode == EFI_IFR_END_OP:
                                    scope -= 1
                                inner += inner_length
                            if options:
                                knob.options = options
                    knob.processed = True
                    enriched += 1
                ptr += length
    return enriched


def parse_variable_store_locations(
    data: bytes,
    nvars: list[Nvar],
    file_guid: str = "",
    file_offset: int = 0,
    source: str = "",
) -> dict[int, VarDataLocation]:
    nvars_by_name: dict[tuple[str, str], list[Nvar]] = {}
    for nvar in nvars:
        nvars_by_name.setdefault((nvar.name, nvar.guid), []).append(nvar)
        nvars_by_name.setdefault((nvar.name, ZERO_GUID), []).append(nvar)

    locations: dict[int, VarDataLocation] = {}
    candidate_offsets = sorted({offset for guid in VARIABLE_STORE_GUIDS for offset in find_guid_offsets(data, guid)})
    for ptr in candidate_offsets:
        if ptr + 0x1C > len(data):
            continue
        store_guid = guid_text_from_uefi(data, ptr)
        store_size = read_uint(data, ptr + 0x10, 4)
        if store_size <= 0x1C or store_size == 0xFFFFFFFF:
            continue
        store_end = min(len(data), ptr + store_size)
        store_format = read_uint(data, ptr + 0x14, 1)
        store_state = read_uint(data, ptr + 0x15, 1)
        if store_format != 0x5A or store_state != 0xFE:
            continue
        if store_guid in {EFI_GLOBAL_VARIABLE_GUID, EFI_AUTHENTICATED_VARIABLE_GUID}:
            header_size = 0x3C
            name_size_offset = 0x24
            data_size_offset = 0x28
            vendor_guid_offset = 0x2C
        else:
            header_size = 0x20
            name_size_offset = 0x08
            data_size_offset = 0x0C
            vendor_guid_offset = 0x10
        var_ptr = align(ptr + 0x1C, 4)
        while var_ptr + header_size <= store_end:
            if read_uint(data, var_ptr, 2) != 0x55AA:
                break
            name_size = read_uint(data, var_ptr + name_size_offset, 4)
            value_size = read_uint(data, var_ptr + data_size_offset, 4)
            vendor_guid = guid_text_from_uefi(data, var_ptr + vendor_guid_offset)
            name_start = var_ptr + header_size
            name_end = min(store_end, name_start + name_size)
            chars: list[str] = []
            for idx in range(name_start, name_end - 1, 2):
                code = read_uint(data, idx, 2)
                if code == 0:
                    break
                chars.append(chr(code & 0xFF))
            name = "".join(chars)
            value_start = var_ptr + header_size + name_size
            value_end = min(store_end, value_start + value_size)
            matches = nvars_by_name.get((name, vendor_guid)) or nvars_by_name.get((name, ZERO_GUID)) or []
            for nvar in matches:
                locations.setdefault(
                    nvar.var_id,
                    VarDataLocation(
                        var_id=nvar.var_id,
                        name=name,
                        guid=vendor_guid,
                        data_offset=file_offset + value_start,
                        data_size=max(0, value_end - value_start),
                        file_guid=file_guid,
                        file_offset=file_offset,
                        source=source,
                    ),
                )
            var_ptr = align(value_start + value_size, 4)
    return locations


def parse_variable_stores(data: bytes, nvars: list[Nvar]) -> dict[int, bytes]:
    locations = parse_variable_store_locations(data, nvars)
    var_data: dict[int, bytes] = {}
    for var_id, location in locations.items():
        start = location.data_offset
        end = start + location.data_size
        var_data[var_id] = data[start:end]
    return var_data


def apply_default_data(nvars: list[Nvar], default_files: list[FirmwareFile]) -> int:
    applied = 0
    var_data: dict[int, bytes] = {}
    for default_file in default_files:
        parsed = parse_variable_stores(default_file.data, nvars)
        var_data.update(parsed)
    for nvar in nvars:
        data = var_data.get(nvar.var_id)
        if not data:
            continue
        for knob in nvar.knobs:
            if knob.offset >= BITWISE_KNOB_PREFIX:
                bit_position = knob.offset & 0x3FFFF
                byte_offset = bit_position // 8
                bit_offset = bit_position % 8
                value_size = (bit_offset + knob.size + 7) // 8
                if byte_offset + value_size > len(data):
                    continue
                raw = read_uint(data, byte_offset, value_size)
                mask = (1 << knob.size) - 1
                value = (raw >> bit_offset) & mask
            else:
                if knob.offset + knob.size > len(data):
                    continue
                value = read_uint(data, knob.offset, knob.size)
            knob.default = value
            knob.current = value
            knob.default_available = True
            knob.current_available = True
            applied += 1
    return applied


def parse_scalar_value(knob: Knob, text: str) -> int:
    value_text = text.strip()
    for option in knob.options:
        if str(option.get("text", "")).lower() == value_text.lower():
            return int(option["value"])
    try:
        return int(value_text, 0)
    except ValueError as exc:
        option_names = ", ".join(str(option.get("text", "")) for option in knob.options)
        hint = f"; valid options: {option_names}" if option_names else ""
        raise DecodeError(f"Invalid value '{text}' for knob {knob.name}{hint}") from exc


def find_knobs_by_name(result: DecodeResult, name: str) -> list[Knob]:
    target = name.strip()
    nvar_filter = ""
    if "." in target:
        nvar_filter, target = target.split(".", 1)
    matches: list[Knob] = []
    for nvar in result.nvars:
        if nvar_filter and nvar.name.lower() != nvar_filter.lower():
            continue
        for knob in nvar.knobs:
            if knob.name.lower() == target.lower():
                matches.append(knob)
    return matches


def ffs_header_size(data: bytes | bytearray, ffs_offset: int) -> int:
    attr = read_uint(data, ffs_offset + 0x13, 1)
    size = read_uint(data, ffs_offset + 0x14, 3)
    if size == 0xFFFFFF or attr & FFS_ATTRIB_LARGE_FILE:
        return FFS_FILE_HEADER2_SIZE
    return FFS_FILE_HEADER_SIZE


def update_ffs_file_checksum(image: bytearray, ffs_offset: int, ffs_size: int) -> None:
    attr = read_uint(image, ffs_offset + 0x13, 1)
    if not (attr & FFS_ATTRIB_CHECKSUM):
        return
    checksum_offset = ffs_offset + 0x11
    old_checksum = image[checksum_offset]
    image[checksum_offset] = 0
    total = sum(image[ffs_offset:ffs_offset + ffs_size]) & 0xFF
    image[checksum_offset] = (-total) & 0xFF
    if old_checksum != image[checksum_offset]:
        return


def write_knob_value(image: bytearray, location: VarDataLocation, knob: Knob, value: int) -> tuple[int, int, int]:
    if knob.setup_type == "string":
        raise DecodeError(f"String knob patching is not supported yet: {knob.name}")
    if knob.offset >= BITWISE_KNOB_PREFIX:
        bit_position = knob.offset & 0x3FFFF
        byte_offset = bit_position // 8
        bit_offset = bit_position % 8
        value_size = (bit_offset + knob.size + 7) // 8
        if value < 0 or value >= (1 << knob.size):
            raise DecodeError(f"Value 0x{value:X} does not fit {knob.size} bits for {knob.name}")
        if byte_offset + value_size > location.data_size:
            raise DecodeError(f"Knob {knob.name} offset is outside variable {location.name}")
        absolute_offset = location.data_offset + byte_offset
        old_raw = read_uint(image, absolute_offset, value_size)
        mask = ((1 << knob.size) - 1) << bit_offset
        new_raw = (old_raw & ~mask) | ((value << bit_offset) & mask)
        write_uint(image, absolute_offset, value_size, new_raw)
        old_value = (old_raw & mask) >> bit_offset
        return absolute_offset, old_value, value
    if value < 0 or value >= (1 << (knob.size * 8)):
        raise DecodeError(f"Value 0x{value:X} does not fit {knob.size} bytes for {knob.name}")
    if knob.offset + knob.size > location.data_size:
        raise DecodeError(f"Knob {knob.name} offset is outside variable {location.name}")
    absolute_offset = location.data_offset + knob.offset
    old_value = read_uint(image, absolute_offset, knob.size)
    write_uint(image, absolute_offset, knob.size, value)
    return absolute_offset, old_value, value


def patch_bios_file(input_path: Path, output_path: Path, assignments: list[str], bios_id: str = "") -> list[str]:
    if not assignments:
        raise DecodeError("No knob assignments were provided")
    if input_path.resolve() == output_path.resolve():
        raise DecodeError("Refusing to overwrite the input binary. Choose a different --output path.")
    result = decode_file(input_path, bios_id=bios_id)
    image = bytearray(input_path.read_bytes())
    warnings: list[WarningItem] = []
    default_files = scan_firmware_files(bytes(image), str(input_path), warnings, target_guids=DEFAULT_DATA_GUIDS, stop_on_first=False)
    locations: dict[int, VarDataLocation] = {}
    ffs_sizes_by_offset: dict[int, int] = {}
    for default_file in default_files:
        if default_file.source != str(input_path):
            continue
        parsed = parse_variable_store_locations(
            default_file.data,
            result.nvars,
            file_guid=default_file.guid,
            file_offset=default_file.offset,
            source=default_file.source,
        )
        locations.update(parsed)
        ffs_sizes_by_offset[default_file.offset] = default_file.size
    if not locations:
        raise DecodeError("No writable raw default-data/NVRAM variable store was found in this BIOS image")

    reports: list[str] = []
    touched_ffs_offsets: set[int] = set()
    for assignment in assignments:
        if "=" not in assignment:
            raise DecodeError(f"Invalid assignment '{assignment}'. Expected KNOB=VALUE")
        name, value_text = assignment.split("=", 1)
        matches = find_knobs_by_name(result, name)
        if not matches:
            raise DecodeError(f"Knob not found: {name}")
        writable_matches = [knob for knob in matches if knob.var_id in locations]
        if not writable_matches:
            raise DecodeError(f"Knob '{name}' was found, but its NVAR is not present in writable default-data/NVRAM")
        if len(writable_matches) > 1:
            choices = ", ".join(f"{knob.nvar_name}.{knob.name}@{knob.offset_text}" for knob in writable_matches)
            raise DecodeError(f"Ambiguous knob name '{name}'. Use NVAR.KnobName. Matches: {choices}")
        knob = writable_matches[0]
        value = parse_scalar_value(knob, value_text)
        location = locations[knob.var_id]
        absolute_offset, old_value, new_value = write_knob_value(image, location, knob, value)
        touched_ffs_offsets.add(location.file_offset)
        width = max(2, knob.size * 2)
        reports.append(
            f"{knob.nvar_name}.{knob.name}: 0x{old_value:0{width}X} -> 0x{new_value:0{width}X} "
            f"at BIOS offset 0x{absolute_offset:X} (NVAR offset {knob.offset_text})"
        )

    for ffs_offset in touched_ffs_offsets:
        ffs_size = ffs_sizes_by_offset.get(ffs_offset)
        if ffs_size:
            update_ffs_file_checksum(image, ffs_offset, ffs_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)
    return reports


def decode_file(path: Path, bios_id: str = "") -> DecodeResult:
    if not path.is_file():
        raise DecodeError(f"Input file not found: {path}")
    data = path.read_bytes()
    warnings: list[WarningItem] = []
    candidates = scan_firmware_files(data, str(path), warnings)
    setup_files = scan_firmware_files(data, str(path), warnings, target_guids=SETUP_DRIVER_GUIDS, stop_on_first=False)
    setup_order = {guid: index for index, guid in enumerate(SETUP_DRIVER_GUID_ORDER)}
    setup_files.sort(key=lambda item: (setup_order.get(item.guid, len(setup_order)), item.source, item.offset))

    if candidates:
        best = sorted(candidates, key=lambda item: (0 if item.guid == BIOS_KNOBS_DATA_BIN_GUID else 1, item.offset))[0]
        nvars = parse_bios_knobs_data_bin(best.data, bios_id, warnings)
        enriched = enrich_knobs_from_hii(nvars, setup_files)
        if setup_files and enriched == 0:
            warnings.append(WarningItem("Setup driver FFS files were found, but no HII questions matched BiosKnobsDataBin knobs", None, "HII"))
        ffs_guid = best.guid
        ffs_offset = best.offset
        ffs_size = best.size
    else:
        warnings.append(WarningItem("No BiosKnobsDataBin FFS file was found; falling back to HII/IFR-only decode", None, "HII"))
        nvars = parse_hii_only_knobs(setup_files, warnings)
        if not nvars:
            raise DecodeError("No BiosKnobsDataBin FFS file was found, and no HII/IFR setup questions could be decoded.")
        ffs_guid = "HII_IFR_ONLY"
        ffs_offset = 0
        ffs_size = 0

    default_files = scan_firmware_files(data, str(path), warnings, target_guids=DEFAULT_DATA_GUIDS, stop_on_first=False)
    applied_defaults = apply_default_data(nvars, default_files)
    dedupe_knobs_by_guid_offset(nvars)
    if default_files and applied_defaults == 0:
        warnings.append(WarningItem("Default-data/NVRAM files were found, but no variable data matched decoded NVARs", None, "NVRAM"))
    return DecodeResult(
        input=str(path),
        bios_version=path.stem,
        ffs_guid=ffs_guid,
        ffs_offset=ffs_offset,
        ffs_size=ffs_size,
        setup_driver_count=len(setup_files),
        default_data_count=len(default_files),
        nvars=nvars,
        warnings=warnings,
    )


def knob_rows(result: DecodeResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for nvar in result.nvars:
        for knob in nvar.knobs:
            if not knob.processed:
                continue
            value_width = max(2, knob.size * 2)
            default_text = f"0x{knob.default:0{value_width}X}" if knob.default_available else ""
            current_text = f"0x{knob.current:0{value_width}X}" if knob.current_available else ""
            rows.append(
                {
                    "type": "scalar",
                    "name": knob.name,
                    "Nvar": knob.nvar_name,
                    "NvarGuid": knob.nvar_guid,
                    "varstoreIndex": f"{knob.var_id:02d}",
                    "setupType": knob.setup_type,
                    "size": knob.size,
                    "offset": knob.offset_text,
                    "prompt": knob.prompt,
                    "description": knob.description,
                    "depex": clean_hii_string(knob.depex),
                    "default": default_text,
                    "CurrentVal": current_text,
                    "defaultAvailable": str(knob.default_available).lower(),
                    "currentAvailable": str(knob.current_available).lower(),
                    "min": "" if knob.min_value is None else f"0x{knob.min_value:X}",
                    "max": "" if knob.max_value is None else f"0x{knob.max_value:X}",
                    "step": "" if knob.step is None else str(knob.step),
                    "SetupPgPtr": knob.setup_page,
                }
            )
    return rows


def result_to_json(result: DecodeResult) -> dict[str, Any]:
    decode_type = "HII_IFR_ONLY" if result.ffs_guid == "HII_IFR_ONLY" else "BiosKnobsDataBin"
    return {
        "input": result.input,
        "biosVersion": result.bios_version,
        "decodeType": decode_type,
        "biosKnobsDataBin": {
            "guid": result.ffs_guid,
            "offset": result.ffs_offset,
            "offsetHex": f"0x{result.ffs_offset:X}",
            "size": result.ffs_size,
            "sizeHex": f"0x{result.ffs_size:X}",
            "decodeType": decode_type,
        },
        "summary": {
            "nvarCount": len(result.nvars),
            "knobCount": sum(len(nvar.knobs) for nvar in result.nvars),
            "setupDriverCount": result.setup_driver_count,
            "defaultDataCount": result.default_data_count,
            "warningCount": len(result.warnings),
        },
        "nvars": [
            {
                "varId": nvar.var_id,
                "name": nvar.name,
                "guid": nvar.guid,
                "size": nvar.size,
                "knobCountDeclared": nvar.knob_count_declared,
                "knobCountParsed": len(nvar.knobs),
                "readonly": nvar.readonly,
                "revision": nvar.revision,
                "duplicateKnobs": nvar.duplicate_knobs,
                "knobs": [asdict(knob) for knob in nvar.knobs],
            }
            for nvar in result.nvars
        ],
        "warnings": [warning.to_dict() for warning in result.warnings],
    }


def write_xml(result: DecodeResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("SYSTEM")
    ET.SubElement(root, "PLATFORM", {"NAME": "UNKNOWN", "CPU": "UNKNOWN", "CHIPSET": "UNKNOWN"})
    ET.SubElement(root, "BIOS", {"VERSION": result.bios_version, "TSTAMP": "UNKNOWN"})
    decode_type = "HII_IFR_ONLY" if result.ffs_guid == "HII_IFR_ONLY" else "BiosKnobsDataBin"
    ET.SubElement(root, "GBT", {"Version": "UNKNOWN", "TSTAMP": "UNKNOWN", "Type": decode_type, "XmlCliVer": "N/A", "XmlCliType": "Standalone"})
    ET.SubElement(root, "FrontPage", {"FirmwareVersion": result.bios_version, "ProductName": "UNKNOWN", "CpuVersion": "UNKNOWN", "CpuSpeed": "UNKNOWN", "MemorySize": "UNKNOWN"})
    meta = ET.SubElement(root, "BIOS_KNOBS_DATA_BIN")
    meta.set("guid", result.ffs_guid)
    meta.set("offset", f"0x{result.ffs_offset:X}")
    meta.set("size", f"0x{result.ffs_size:X}")
    meta.set("decodeType", decode_type)
    meta.set("setupDriverCount", str(result.setup_driver_count))
    meta.set("defaultDataCount", str(result.default_data_count))

    nvars_element = ET.SubElement(root, "Nvars")
    for nvar in result.nvars:
        element = ET.SubElement(nvars_element, "Nvar")
        element.set("varstoreIndex", f"{nvar.var_id:02d}")
        element.set("name", nvar.name)
        element.set("size", f"0x{nvar.size:04X}")
        element.set("attribute", f"0x{nvar.attr:08X}")
        element.set("KnobCount", str(len(nvar.knobs)))
        element.set("guid", nvar.guid)
        element.set("readonly", str(nvar.readonly).lower())
        element.set("revision", f"0x{nvar.revision:X}")
        if nvar.status != "ok":
            element.set("status", nvar.status)

    knobs_element = ET.SubElement(root, "biosknobs")
    for nvar in result.nvars:
        for knob in nvar.knobs:
            if not knob.processed:
                continue
            element = ET.SubElement(knobs_element, "knob")
            element.set("type", "scalar")
            element.set("setupType", knob.setup_type)
            element.set("name", knob.name)
            element.set("varstoreIndex", f"{knob.var_id:02d}")
            element.set("Nvar", knob.nvar_name)
            element.set("NvarGuid", knob.nvar_guid)
            element.set("prompt", knob.prompt)
            element.set("description", knob.description)
            element.set("size", str(knob.size))
            element.set("offset", knob.offset_text)
            element.set("depex", clean_hii_string(knob.depex))
            if knob.setup_page:
                element.set("SetupPgPtr", knob.setup_page)
            value_width = max(2, knob.size * 2)
            element.set("default", f"0x{knob.default:0{value_width}X}" if knob.default_available else "")
            element.set("CurrentVal", f"0x{knob.current:0{value_width}X}" if knob.current_available else "")
            element.set("defaultAvailable", str(knob.default_available).lower())
            element.set("currentAvailable", str(knob.current_available).lower())
            if knob.current_available:
                element.set("valueSource", "default-data/NVRAM" if result.default_data_count else "IFR default")
            elif knob.default_available:
                element.set("valueSource", "IFR default")
            else:
                element.set("valueSource", "not available")
            if knob.setup_type == "numeric" and knob.min_value is not None and knob.max_value is not None:
                element.set("min", f"0x{knob.min_value:X}")
                element.set("max", f"0x{knob.max_value:X}")
                element.set("step", str(knob.step or 0))
            if knob.setup_type == "string" and knob.min_value is not None and knob.max_value is not None:
                element.set("minsize", f"0x{knob.min_value:X}")
                element.set("maxsize", f"0x{knob.max_value:X}")
            if knob.options:
                options_element = ET.SubElement(element, "options")
                for option in knob.options:
                    option_element = ET.SubElement(options_element, "option")
                    option_element.set("text", str(option["text"]))
                    option_element.set("value", f"0x{int(option['value']):X}")

    if result.warnings:
        warnings_element = ET.SubElement(root, "warnings")
        for warning in result.warnings:
            element = ET.SubElement(warnings_element, "warning")
            element.set("message", warning.message)
            if warning.offset is not None:
                element.set("offset", f"0x{warning.offset:X}")
            if warning.context:
                element.set("context", warning.context)

    sanitize_xml_tree(root)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def write_csv(result: DecodeResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = knob_rows(result)
    fields = ["type", "name", "Nvar", "NvarGuid", "varstoreIndex", "setupType", "size", "offset", "prompt", "description", "depex", "SetupPgPtr", "default", "CurrentVal", "defaultAvailable", "currentAvailable", "min", "max", "step"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(result: DecodeResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result_to_json(result), indent=2, ensure_ascii=False), encoding="utf-8")

def fitm_core():
    build_field_db()
    return sys.modules[__name__]


def knob_core():
    return sys.modules[__name__]

def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False))


def cmd_fit_summary(args: argparse.Namespace) -> int:
    core = fitm_core()
    image = core.OksBiosImage(args.image)
    summary = image.summary()
    if args.json:
        _print_json(summary)
        return 0
    print(f"Image: {summary['path']}")
    print(f"Platform: {summary.get('platform_name', 'Unknown')}")
    print(f"Layout: {summary.get('layout_name') or 'N/A'}")
    print(f"Size: 0x{summary['size']:x}")
    print(f"Descriptor: {'yes' if summary['has_descriptor'] else 'no'}")
    print(f"FIT offset: 0x{summary['fit_offset']:x}")
    print(f"BTG offset: {summary['btg_offset']:#x}" if summary['btg_offset'] is not None else "BTG offset: not found")
    if summary.get("btg_crc"):
        crc = summary["btg_crc"]
        state = "valid" if crc["valid"] else "INVALID"
        print(f"BTG CRC8: stored=0x{crc['stored']:02x} calculated=0x{crc['calculated']:02x} {state}")
    print("\nBTG:")
    for item in summary.get("btg", []):
        print("  " + core.value_to_text(core.DecodedValue(**item)))
    return 0


def cmd_fit_list_fields(args: argparse.Namespace) -> int:
    core = fitm_core()
    rows = []
    for field in core.all_fields(args.platform):
        if args.group and field.group != args.group:
            continue
        if args.json:
            rows.append(asdict(field))
            continue
        values = " values=" + ", ".join(f"{key:#x}:{text}" for key, text in field.values.items()) if field.values else ""
        ro = " [read-only]" if field.name.lower() in core.READ_ONLY_FIELDS else ""
        print(f"{field.name:46s} {field.register:30s} bits={field.bit_high}:{field.bit_low}{ro} - {field.description}{values}")
    if args.json:
        _print_json(rows)
    else:
        if args.platform == "bhs":
            print("IBLStrap0..IBLStrap4 raw registers are also supported for fit-get/fit-set on BHS.")
        elif args.platform == "oks":
            print("IBLStrap0..IBLStrap13 raw registers are also supported for fit-get/fit-set on OKS.")
        else:
            print("Raw IBLStrapN register support depends on the decoded platform.")
    return 0


def cmd_fit_get(args: argparse.Namespace) -> int:
    core = fitm_core()
    image = core.OksBiosImage(args.image)
    index = core.raw_strap_index(args.field)
    if index is not None:
        straps = image.raw_straps()
        if index >= len(straps):
            raise SystemExit(f"{image.platform_name()} supports IBLStrap0..{len(straps) - 1}")
        value = straps[index]
    else:
        value = image.decode_field(args.field)
    if args.json:
        _print_json(asdict(value))
    else:
        print(core.value_to_text(value))
    return 0


def cmd_fit_dump_straps(args: argparse.Namespace) -> int:
    core = fitm_core()
    image = core.OksBiosImage(args.image)
    straps = image.raw_straps()
    if args.json:
        _print_json([asdict(item) for item in straps])
    else:
        for item in straps:
            print(core.value_to_text(item))
    return 0


def cmd_uefi_summary(args: argparse.Namespace) -> int:
    core = fitm_core()
    image = core.OksBiosImage(args.image)
    summary = image.common_uefi_summary()
    if args.json:
        _print_json(summary)
        return 0
    print(f"Image: {summary['path']}")
    print(f"Platform: {summary.get('platform_name', 'Unknown')}")
    print(f"Layout: {summary.get('layout_name') or 'N/A'}")
    print(f"Size: 0x{summary['size']:x}")
    print(f"Descriptor: {'yes' if summary['has_descriptor'] else 'no'}")
    print(f"FIT offset: 0x{summary['fit_offset']:x}")
    print(f"BTG offset: {summary['btg_offset']:#x}" if summary['btg_offset'] is not None else "BTG offset: not found")
    signatures = summary.get("microcode_signatures", [])
    revisions = summary.get("microcode_revisions", [])
    print("\nMicrocode:")
    print(f"  Entries: {summary.get('microcode_count', 0)}")
    if signatures:
        print("  CPUIDs: " + ", ".join(format_hex(value, 8) for value in signatures))
    if revisions:
        print("  Microcode revisions: " + ", ".join(format_hex(value, 8) for value in revisions))
    for entry in summary.get("microcode", []):
        fit_index = entry.get("index", "N/A")
        microcode_revision = format_hex(entry.get("update_revision"), 8)
        signature = format_hex(entry.get("processor_signature"), 8) if entry.get("processor_signature") else "N/A"
        family_text = cpu_family_text(entry.get("processor_signature"))
        print(
            f"  FIT index {fit_index} @ {format_hex(entry.get('offset'))}: "
            f"CPU Family={family_text}, microcode revision={microcode_revision}, CPUID={signature}, "
            f"date={entry.get('date_text') or 'N/A'}, platform_id={format_hex(entry.get('processor_flags'), 8)}, "
            f"size={format_hex(entry.get('total_size'))}, "
            f"status={entry.get('status', 'decoded')}"
        )
        if args.details and entry.get("cpuid"):
            cpuid = entry["cpuid"]
            print(
                "    CPUID decode: "
                f"family={format_hex(cpuid['display_family'])}, model={format_hex(cpuid['display_model'])}, "
                f"stepping={format_hex(cpuid['stepping'])}, type={format_hex(cpuid['processor_type'])}, "
                f"base_family={format_hex(cpuid['base_family'])}, base_model={format_hex(cpuid['base_model'])}, "
                f"ext_family={format_hex(cpuid['extended_family'])}, ext_model={format_hex(cpuid['extended_model'])}, "
                f"cpu_family={cpu_family_text(entry.get('processor_signature'))}"
            )
    return 0


def _save_image_result(image: OksBiosImage, output: str | None, in_place: bool, overwrite: bool) -> tuple[Path, Path | None]:
    if in_place:
        backup = image.save_in_place_with_backup()
        return image.path, backup
    if not output:
        output = image.path.with_name("outimage.bin")
    return image.save(output, overwrite=overwrite), None


def _region_selector(value: str | int) -> str | int:
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def _microcode_entry_by_index(image: OksBiosImage, fit_index: int) -> MicrocodeEntry:
    for entry in image.microcode_entries():
        if entry.index == fit_index:
            return entry
    raise ValueError(f"Microcode FIT index {fit_index} was not found")


def microcode_slot_size(image: OksBiosImage, entry: MicrocodeEntry) -> int:
    fit_entries = []
    for fit_entry in image.fit_entries():
        try:
            fit_index = int(fit_entry.get("index", -1))
            fit_offset = int(fit_entry.get("absolute_offset", -1))
        except Exception:
            continue
        if fit_index < 0 or fit_offset < 0:
            continue
        fit_entries.append({"index": fit_index, "offset": fit_offset})

    fit_entries.sort(key=lambda item: item["index"])
    position = next((idx for idx, item in enumerate(fit_entries) if item["index"] == entry.index), None)
    if position is None:
        raise ValueError(f"FIT index {entry.index} was not found in the FIT table")

    neighbor_position = position + 1 if entry.index <= 1 else position - 1
    if neighbor_position < 0 or neighbor_position >= len(fit_entries):
        raise ValueError(f"Unable to determine the replacement slot size for FIT index {entry.index}")

    slot_size = abs(int(entry.offset) - int(fit_entries[neighbor_position]["offset"]))
    if slot_size <= 0:
        raise ValueError(f"Invalid replacement slot size {slot_size} for FIT index {entry.index}")
    return slot_size


def cmd_bios_region_export(args: argparse.Namespace) -> int:
    image = OksBiosImage(args.image)
    region_id = _region_selector(args.region)
    region = image.region(region_id)
    if not region.enabled or region.size <= 0:
        raise ValueError(f"Region not available: {args.region}")
    export_data = bytes(image.data[region.base:region.base + region.size])
    if len(export_data) != region.size:
        raise ValueError(f"BIOS region slice length {len(export_data)} does not match region size {region.size}")
    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(export_data)
    result = {"output": str(output), "region": asdict(region), "bytes": len(export_data)}
    if args.json:
        _print_json(result)
    else:
        print(f"Exported region {region.index}-{region.name}: {output}")
        print(f"  Base=0x{region.base:08X} Limit=0x{region.limit:08X} Size=0x{region.size:X} Bytes={len(export_data)}")
    return 0


def cmd_bios_region_replace(args: argparse.Namespace) -> int:
    image = OksBiosImage(args.image)
    region_id = _region_selector(args.region)
    region = image.region(region_id)
    replacement = Path(args.replacement).read_bytes()
    image.replace_region_bytes(region_id, replacement)
    saved, backup = _save_image_result(image, args.output, args.in_place, args.overwrite)
    result = {"saved": str(saved), "backup": str(backup) if backup else None, "region": asdict(region), "replacement_bytes": len(replacement)}
    if args.json:
        _print_json(result)
    else:
        print(f"Replaced region {region.index}-{region.name}: {saved}")
        print(f"  Replacement bytes={len(replacement)} Region size=0x{region.size:X} Padding=0xFF")
        if backup:
            print(f"  Backup: {backup}")
    return 0


def cmd_microcode_export(args: argparse.Namespace) -> int:
    image = OksBiosImage(args.image)
    entry = _microcode_entry_by_index(image, args.fit_index)
    total_size = int(entry.total_size or 0)
    offset = int(entry.offset)
    if offset < 0 or total_size <= 0 or offset + total_size > len(image.data):
        raise ValueError(f"Microcode FIT index {args.fit_index} range is invalid")
    export_data = bytes(image.data[offset:offset + total_size])
    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(export_data)
    result = {"output": str(output), "fit_index": entry.index, "offset": entry.offset, "total_size": total_size, "bytes": len(export_data)}
    if args.json:
        _print_json(result)
    else:
        print(f"Exported microcode FIT index {entry.index}: {output}")
        print(f"  Offset=0x{entry.offset:X} TotalSize=0x{total_size:X} Bytes={len(export_data)}")
    return 0


def cmd_microcode_replace(args: argparse.Namespace) -> int:
    image = OksBiosImage(args.image)
    entry = _microcode_entry_by_index(image, args.fit_index)
    replacement_path = Path(args.replacement)
    if replacement_path.suffix.lower() == ".inc":
        replacement, conversion_stats = convert_mcu_inc_to_bin(replacement_path)
    else:
        replacement = replacement_path.read_bytes()
        conversion_stats = None
    slot_size = microcode_slot_size(image, entry)
    if len(replacement) > slot_size:
        raise ValueError(f"Replacement size {len(replacement)} exceeds microcode slot size {slot_size}")
    offset = int(entry.offset)
    if offset < 0 or offset + slot_size > len(image.data):
        raise ValueError(f"Microcode FIT index {args.fit_index} range is invalid")
    image.data[offset:offset + slot_size] = replacement.ljust(slot_size, b"\xff")
    saved, backup = _save_image_result(image, args.output, args.in_place, args.overwrite)
    result = {"saved": str(saved), "backup": str(backup) if backup else None, "fit_index": entry.index, "offset": offset, "slot_size": slot_size, "replacement_bytes": len(replacement), "converted_from_inc": conversion_stats is not None}
    if conversion_stats:
        result["conversion"] = conversion_stats
    if args.json:
        _print_json(result)
    else:
        print(f"Replaced microcode FIT index {entry.index}: {saved}")
        print(f"  Offset=0x{offset:X} SlotSize=0x{slot_size:X} Replacement bytes={len(replacement)} Padding=0xFF")
        if conversion_stats:
            print(f"  Converted INC replacement: literals={conversion_stats.get('literals_found', 0)} bytes={conversion_stats.get('bytes_emitted', 0)}")
        if backup:
            print(f"  Backup: {backup}")
    return 0


def cmd_mcu_inc_to_bin(args: argparse.Namespace) -> int:
    input_path = Path(args.input_inc)
    output = Path(args.output) if args.output else input_path.with_suffix(".bin")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    binary, stats = convert_mcu_inc_to_bin(input_path)
    output.write_bytes(binary)
    result = {"output": str(output), "input": str(input_path), **stats}
    if args.json:
        _print_json(result)
    else:
        print(f"Converted MCU INC to BIN: {output}")
        print(f"  Input: {input_path}")
        print(f"  Literals={stats['literals_found']} Bytes={stats['bytes_emitted']}")
    return 0


def cmd_mcu_bin_to_inc(args: argparse.Namespace) -> int:
    input_path = Path(args.input_bin)
    output = Path(args.output) if args.output else input_path.with_suffix(".inc")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    inc_text, stats = convert_mcu_bin_to_inc(input_path)
    output.write_text(inc_text, encoding="utf-8")
    result = {"output": str(output), "input": str(input_path), **stats}
    if args.json:
        _print_json(result)
    else:
        print(f"Converted MCU BIN to INC: {output}")
        print(f"  Input: {input_path}")
        print(f"  DWORDs={stats['dwords_emitted']} Bytes={stats['bytes_read']}")
    return 0


def cmd_fit_set(args: argparse.Namespace) -> int:
    if not args.in_place and not args.output:
        raise SystemExit("fit-set requires --output unless --in-place is specified")
    core = fitm_core()
    image = core.OksBiosImage(args.image)
    index = core.raw_strap_index(args.field)
    value = image.set_raw_strap(index, core.parse_int(args.value)) if index is not None else image.set_field(args.field, args.value)
    if args.in_place:
        backup = image.save_in_place_with_backup()
        saved = image.path
    else:
        saved = image.save(args.output, overwrite=args.overwrite)
        backup = None
    result = {"saved": str(saved), "backup": str(backup) if backup else None, "field": asdict(value)}
    if args.json:
        _print_json(result)
    else:
        print(core.value_to_text(value))
        print(f"Saved: {saved}")
        if backup:
            print(f"Backup: {backup}")
    return 0


def cmd_knob_decode(args: argparse.Namespace) -> int:
    core = knob_core()
    image = Path(args.image)
    xml_path = Path(args.xml) if args.xml else image.with_suffix(image.suffix + ".bios_knobs.xml")
    result = core.decode_file(image, bios_id=args.bios_id)
    core.write_xml(result, xml_path)
    if args.csv:
        core.write_csv(result, Path(args.csv))
    if args.json:
        core.write_json(result, Path(args.json))
    processed = sum(1 for nvar in result.nvars for knob in nvar.knobs if knob.processed)
    decode_type = "HII/IFR-only fallback" if result.ffs_guid == "HII_IFR_ONLY" else "BiosKnobsDataBin"
    print("Decode complete")
    print(f"  Input: {image}")
    print(f"  Decode type: {decode_type}")
    print(f"  XML: {xml_path}")
    if args.csv:
        print(f"  CSV: {args.csv}")
    if args.json:
        print(f"  JSON: {args.json}")
    print(f"  NVARs: {len(result.nvars)}")
    print(f"  Knobs: {processed}")
    if result.warnings:
        print(f"  Warnings: {len(result.warnings)}")
    return 0


def cmd_knob_patch(args: argparse.Namespace) -> int:
    if not args.sets:
        raise SystemExit("knob-patch requires at least one --set KNOB=VALUE assignment")
    if not args.output:
        raise SystemExit("knob-patch requires --output")
    core = knob_core()
    reports = core.patch_bios_file(Path(args.image), Path(args.output), args.sets, bios_id=args.bios_id)
    print("Patch complete")
    print(f"  Input: {args.image}")
    print(f"  Output: {args.output}")
    for report in reports:
        print(f"  {report}")
    return 0


def cmd_patch_all(args: argparse.Namespace) -> int:
    current = Path(args.image)
    intermediate = Path(args.fit_output) if args.fit_output else None
    if args.fit_set:
        if not intermediate:
            raise SystemExit("patch-all with --fit-set requires --fit-output")
        for index, assignment in enumerate(args.fit_set):
            if "=" not in assignment:
                raise SystemExit(f"Invalid --fit-set assignment: {assignment}")
            field, value = assignment.split("=", 1)
            output = intermediate if index == len(args.fit_set) - 1 else intermediate.with_name(f"{intermediate.stem}.{index}{intermediate.suffix}")
            fit_args = argparse.Namespace(image=str(current), field=field, value=value, output=str(output), in_place=False, overwrite=True, json=False)
            cmd_fit_set(fit_args)
            current = output
    if args.knob_set:
        if not args.output:
            raise SystemExit("patch-all with --knob-set requires --output")
        knob_args = argparse.Namespace(image=str(current), output=args.output, sets=args.knob_set, bios_id=args.bios_id)
        cmd_knob_patch(knob_args)
        current = Path(args.output)
    print(f"Final binary: {current}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified BIOS modify CUI for AI automation")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fit-summary", help="Decode descriptor, straps, FIT and BTG summary")
    p.add_argument("image")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit_summary)

    p = sub.add_parser("fit-list-fields", help="List supported FITm/softstrap/BTG fields")
    p.add_argument("--group", choices=["flcomp", "softstrap", "btg"])
    p.add_argument("--platform", choices=["oks", "bhs", "unknown"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit_list_fields)

    p = sub.add_parser("fit-get", help="Read a named FITm/softstrap/BTG field or raw IBLStrapN")
    p.add_argument("image")
    p.add_argument("field")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit_get)

    p = sub.add_parser("fit-set", help="Set a named FITm/softstrap/BTG field or raw IBLStrapN")
    p.add_argument("image")
    p.add_argument("field")
    p.add_argument("value")
    p.add_argument("-o", "--output")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit_set)

    p = sub.add_parser("fit-dump-straps", help="Print raw platform IBLStrap values")
    p.add_argument("image")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit_dump_straps)

    p = sub.add_parser("uefi-summary", aliases=["common-uefi-summary"], help="Decode Common UEFI image-level content and microcode/CPUID FIT entries")
    p.add_argument("image")
    p.add_argument("--details", action="store_true", help="Print decoded CPUID family/model/stepping details for each microcode entry")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_uefi_summary)

    p = sub.add_parser("bios-region-export", aliases=["region-export"], help="Export a flash region such as 1-bios by base/limit/size")
    p.add_argument("image")
    p.add_argument("--region", default="bios", help="Region name or index, default: bios")
    p.add_argument("--output", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_bios_region_export)

    p = sub.add_parser("bios-region-replace", aliases=["region-replace"], help="Replace a flash region; smaller replacements are padded with 0xFF")
    p.add_argument("image")
    p.add_argument("replacement")
    p.add_argument("--region", default="bios", help="Region name or index, default: bios")
    p.add_argument("-o", "--output")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_bios_region_replace)

    p = sub.add_parser("microcode-export", aliases=["mcu-export"], help="Export a FIT type-1 microcode entry by FIT index")
    p.add_argument("image")
    p.add_argument("fit_index", type=int)
    p.add_argument("--output", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_microcode_export)

    p = sub.add_parser("microcode-replace", aliases=["mcu-replace"], help="Replace a FIT type-1 microcode entry by FIT index")
    p.add_argument("image")
    p.add_argument("fit_index", type=int)
    p.add_argument("replacement")
    p.add_argument("-o", "--output")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_microcode_replace)

    p = sub.add_parser("mcu-inc-to-bin", aliases=["microcode-inc-to-bin"], help="Convert an MCU INC file into a raw binary payload")
    p.add_argument("input_inc")
    p.add_argument("--output", "-o")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mcu_inc_to_bin)

    p = sub.add_parser("mcu-bin-to-inc", aliases=["microcode-bin-to-inc"], help="Convert a raw MCU binary payload into dd-style INC text")
    p.add_argument("input_bin")
    p.add_argument("--output", "-o")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mcu_bin_to_inc)

    p = sub.add_parser("knob-decode", help="Decode BIOS binary knobs to XML/CSV/JSON")
    p.add_argument("image")
    p.add_argument("--xml")
    p.add_argument("--csv")
    p.add_argument("--json")
    p.add_argument("--bios-id", default="")
    p.set_defaults(func=cmd_knob_decode)

    p = sub.add_parser("knob-patch", help="Patch offline BIOS knob values")
    p.add_argument("image")
    p.add_argument("--set", dest="sets", action="append", default=[])
    p.add_argument("--output", required=True)
    p.add_argument("--bios-id", default="")
    p.set_defaults(func=cmd_knob_patch)

    p = sub.add_parser("patch-all", help="Apply FITm assignments then BIOS knob assignments")
    p.add_argument("image")
    p.add_argument("--fit-set", action="append", default=[], metavar="FIELD=VALUE")
    p.add_argument("--fit-output")
    p.add_argument("--knob-set", action="append", default=[], metavar="KNOB=VALUE")
    p.add_argument("--output")
    p.add_argument("--bios-id", default="")
    p.set_defaults(func=cmd_patch_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

