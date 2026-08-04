"""
Regression tests for bios-analyze-log decoder.

Each test fixture is a minimal synthetic log that mirrors patterns seen in
real HSDES investigations. Tests verify parse_log() extracts the right
type/code fields, and that generate_summary() produces non-empty output
without crashing.

Run with:  pytest tests/test_decoder.py -v
"""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from decode_ewl import EWLDecoder


@pytest.fixture(scope="module")
def decoder():
    return EWLDecoder()


@pytest.fixture(scope="module")
def decoder_bhs():
    return EWLDecoder(platform='bhs')


# ---------------------------------------------------------------------------
# EWL parsing
# ---------------------------------------------------------------------------

EWL_BLOCK_LOG = """\
Enhanced warning of type 1 logged:
Major Warning Code = 0x0A, Minor Warning Code = 0x05,
Major Checkpoint: 0x7B, Minor Checkpoint: 0x01
Socket 0
Channel 4
Dimm 0
Rank 1

Enhanced warning of type 1 logged:
Major Warning Code = 0x0A, Minor Warning Code = 0x05,
Major Checkpoint: 0x7B, Minor Checkpoint: 0x01
Socket 0
Channel 5
Dimm 0
Rank 0
"""

EWL_INLINE_LOG = "S00, Major Warning Code = 0x29, Minor Warning Code = 0x15, some context"

EWL_LEGACY_LOG = "Error Logged: Class Code = 0011, Error Code = 0005, Minor Code = 0026"


def test_ewl_block_parsed(decoder):
    codes = decoder.parse_log(EWL_BLOCK_LOG)
    ewl = [c for c in codes if c['type'] == 'EWL']
    assert len(ewl) == 2, f"Expected 2 EWL blocks, got {len(ewl)}"
    assert ewl[0]['major'] == '0x0A'
    assert ewl[0]['minor'] == '0x05'
    assert ewl[0]['channel'] == '4'
    assert ewl[0]['dimm'] == '0'
    assert ewl[0]['rank'] == '1'


def test_ewl_block_grouping_in_summary(decoder):
    codes = decoder.parse_log(EWL_BLOCK_LOG)
    summary = decoder.generate_summary(codes)
    assert 'Occurrences:** 2' in summary
    assert '0x0A' in summary


def test_ewl_inline_parsed(decoder):
    codes = decoder.parse_log(EWL_INLINE_LOG)
    ewl = [c for c in codes if c['type'] == 'EWL']
    assert len(ewl) == 1
    assert ewl[0]['major'] == '0x29'
    assert ewl[0]['minor'] == '0x15'
    assert ewl[0]['socket'] == '00'


def test_ewl_legacy_parsed(decoder):
    codes = decoder.parse_log(EWL_LEGACY_LOG)
    ewl = [c for c in codes if c['type'] == 'EWL']
    assert len(ewl) == 1
    assert ewl[0]['major'] == '0x11'    # Class Code 0011 hex → 0x11
    assert ewl[0]['minor'] == '0x26'    # Minor Code 0026 hex → 0x26


# ---------------------------------------------------------------------------
# IPSD parsing
# ---------------------------------------------------------------------------

IPSD_LOG = "ERROR: C80000002:V00021002 I0 DE1F3623-038D-42FE-A096-8EAA80C8171D"


def test_ipsd_parsed(decoder):
    codes = decoder.parse_log(IPSD_LOG)
    ipsd = [c for c in codes if c['type'] == 'IPSD']
    assert len(ipsd) == 1
    assert ipsd[0]['ipsd_code'] == 'C80000002'


def test_ipsd_decoded_description(decoder):
    result = decoder.decode_ipsd_error('C80000002')
    assert 'Device Error' in result['description']


def test_ipsd_in_summary(decoder):
    codes = decoder.parse_log(IPSD_LOG)
    summary = decoder.generate_summary(codes)
    assert 'IPSD' in summary
    assert 'Device Error' in summary


def test_ipsd_not_parsed_on_bhs(decoder_bhs):
    codes = decoder_bhs.parse_log(IPSD_LOG)
    ipsd = [c for c in codes if c['type'] == 'IPSD']
    assert len(ipsd) == 0


def test_summary_does_not_mention_ipsd_on_bhs(decoder_bhs):
    codes = decoder_bhs.parse_log(EWL_BLOCK_LOG)
    summary = decoder_bhs.generate_summary(codes)
    assert 'IPSD errors' not in summary
    assert 'IPSD (Intel Platform Service Provider) Errors' not in summary


# ---------------------------------------------------------------------------
# RC Fatal parsing
# ---------------------------------------------------------------------------

RC_FATAL_BLOCK_LOG = """\
**FATAL ERROR**
Major Error Code = 0xCD
Minor Error Code = 0x2C
Socket = 0
"""

RC_FATAL_COMBINED_LOG = "RC Fatal Error Code = 0x3000CD2C"

RC_FATAL_FILE_REF_LOG = "RC_FATAL_ERROR! ServerSiliconPkg/Mem/MemDecodeGenDdr.c: 741"


def test_rc_fatal_block_parsed(decoder):
    codes = decoder.parse_log(RC_FATAL_BLOCK_LOG)
    rc = [c for c in codes if c['type'] == 'RC_FATAL']
    assert len(rc) == 1, f"Expected 1 RC Fatal, got {len(rc)}"
    assert rc[0]['major'] == '0xCD'
    assert rc[0]['minor'] == '0x2C'
    assert rc[0]['socket'] == '0'


def test_rc_fatal_combined_code_parsed(decoder):
    codes = decoder.parse_log(RC_FATAL_COMBINED_LOG)
    rc = [c for c in codes if c['type'] == 'RC_FATAL']
    assert len(rc) == 1
    assert rc[0]['major'] == '0xCD'
    assert rc[0]['minor'] == '0x2C'


def test_rc_fatal_file_ref_parsed(decoder):
    codes = decoder.parse_log(RC_FATAL_FILE_REF_LOG)
    rc = [c for c in codes if c['type'] == 'RC_FATAL']
    assert len(rc) == 1
    assert 'MemDecodeGenDdr.c: 741' in rc[0].get('file_ref', '')


def test_rc_fatal_in_summary(decoder):
    codes = decoder.parse_log(RC_FATAL_BLOCK_LOG)
    summary = decoder.generate_summary(codes)
    assert 'RC Fatal' in summary
    assert '0xCD' in summary


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_log_no_crash(decoder):
    codes = decoder.parse_log("")
    assert codes == []
    summary = decoder.generate_summary(codes)
    assert 'No error codes found' in summary


def test_informational_lines_not_flagged(decoder):
    """Debug success prints must not be treated as errors."""
    log = "InstallHobData() Guid: 12345678-0000-0000-0000-000000000000 HobAddress: 0xFFF00000"
    codes = decoder.parse_log(log)
    assert codes == []


def test_mixed_log_all_types(decoder):
    mixed = EWL_BLOCK_LOG + "\n" + IPSD_LOG + "\n" + RC_FATAL_BLOCK_LOG
    codes = decoder.parse_log(mixed)
    types = {c['type'] for c in codes}
    assert 'EWL' in types
    assert 'IPSD' in types
    assert 'RC_FATAL' in types


def test_timestamp_stripped_from_block(decoder):
    log = """\
[2026-02-05-18:24:53] Enhanced warning of type 1 logged:
[2026-02-05-18:24:53] Major Warning Code = 0x0A, Minor Warning Code = 0x05,
[2026-02-05-18:24:53] Major Checkpoint: 0x7B, Minor Checkpoint: 0x01
[2026-02-05-18:24:53] Socket 0
[2026-02-05-18:24:53] Channel 2
[2026-02-05-18:24:53] Dimm 0
[2026-02-05-18:24:53] Rank 0
"""
    codes = decoder.parse_log(log)
    ewl = [c for c in codes if c['type'] == 'EWL']
    assert len(ewl) == 1
    assert ewl[0]['channel'] == '2'


def test_single_code_decode(decoder):
    result = decoder.decode_code('0x0A', '0x05')
    assert result['major_name'] is not None
    assert result['minor_name'] is not None


def test_degraded_socket1_spd_not_flagged(decoder):
    """SPD read failures on absent Socket 1 must not appear as EWL entries."""
    log = "Failed to read SPD data at Socket:1 Channel:0 Dimm:0"
    codes = decoder.parse_log(log)
    assert codes == []


# ---------------------------------------------------------------------------
# Bug regression: Critical #1 — adjacent FATAL ERROR blocks, no blank line
# ---------------------------------------------------------------------------

def test_adjacent_rc_fatal_blocks_both_captured(decoder):
    """Two consecutive FATAL ERROR blocks without a blank-line separator must each
    be captured as a separate RC_FATAL entry (first must not be overwritten)."""
    log = (
        "**FATAL ERROR**\n"
        "Major Error Code = 0xCD\n"
        "Minor Error Code = 0x2C\n"
        "Socket = 0\n"
        "**FATAL ERROR**\n"
        "Major Error Code = 0xBB\n"
        "Minor Error Code = 0x11\n"
        "Socket = 1\n"
    )
    codes = decoder.parse_log(log)
    rc = [c for c in codes if c['type'] == 'RC_FATAL']
    assert len(rc) == 2, f"Expected 2 RC Fatal entries, got {len(rc)}: {[(c['major'],c['minor']) for c in rc]}"
    majors = {c['major'] for c in rc}
    assert '0xCD' in majors, "First block (0xCD) was lost"
    assert '0xBB' in majors, "Second block (0xBB) was lost"


# ---------------------------------------------------------------------------
# Bug regression: Critical #2 — single-line trigger + combined code
# ---------------------------------------------------------------------------

def test_rc_fatal_single_line_trigger_with_combined_code(decoder):
    """RC_FATAL_ERROR! with combined code on the same line must be parsed."""
    log = "RC_FATAL_ERROR! RC Fatal Error Code = 0x3000CD2C"
    codes = decoder.parse_log(log)
    rc = [c for c in codes if c['type'] == 'RC_FATAL']
    assert len(rc) == 1, f"Expected 1 RC Fatal, got {len(rc)}"
    assert rc[0]['major'] == '0xCD'
    assert rc[0]['minor'] == '0x2C'


# ---------------------------------------------------------------------------
# Bug regression: Important #3 — 6-digit code must NOT create a false positive
# ---------------------------------------------------------------------------

def test_six_digit_combined_code_not_flagged(decoder):
    """A 6-digit hex value must not be misidentified as a combined RC Fatal code."""
    log = "Error Code = 0xABCDEF"
    codes = decoder.parse_log(log)
    rc = [c for c in codes if c['type'] == 'RC_FATAL']
    assert rc == [], f"Expected no RC Fatal entries, got {rc}"
