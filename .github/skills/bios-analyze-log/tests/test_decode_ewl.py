"""Tests for bios-analyze-log EWL decoder."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from decode_ewl import EWLDecoder


@pytest.fixture
def decoder():
    """Create decoder instance with default databases."""
    return EWLDecoder()


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

class TestDatabaseLoading:
    def test_ewl_database_loads(self, decoder):
        assert decoder.db is not None
        assert len(decoder.db) > 100, "Expected 124+ EWL codes"

    def test_rc_fatal_database_loads(self, decoder):
        assert decoder.rc_db is not None
        assert len(decoder.rc_db) > 40, "Expected 49+ RC fatal major codes"

    def test_ipsd_errors_loaded(self, decoder):
        assert len(decoder.IPSD_ERRORS) == 28, "Expected 28 IPSD error codes"
        assert 0x80000010 in decoder.IPSD_ERRORS  # Timeout


# ---------------------------------------------------------------------------
# EWL code decoding
# ---------------------------------------------------------------------------

class TestDecodeCode:
    def test_known_ewl_code(self, decoder):
        result = decoder.decode_code("0x29", "0x15")
        assert result["major_name"] is not None
        assert "WARN" in result["major_name"] or "warn" in result["major_name"].lower()

    def test_major_only(self, decoder):
        result = decoder.decode_code("0x29")
        assert result["major_name"] is not None
        assert result["minor_name"] is None

    def test_unknown_code(self, decoder):
        # Use a code very unlikely to exist in the database
        result = decoder.decode_code("0x01")
        # Should return structure with the code preserved
        assert result["major_code"] == "0x01"

    def test_case_insensitive(self, decoder):
        upper = decoder.decode_code("0X29", "0X15")
        lower = decoder.decode_code("0x29", "0x15")
        assert upper["major_name"] == lower["major_name"]


# ---------------------------------------------------------------------------
# RC Fatal error decoding
# ---------------------------------------------------------------------------

class TestDecodeRcFatal:
    def test_known_rc_fatal(self, decoder):
        result = decoder.decode_rc_fatal_error("0xcd")
        assert result["major_name"] is not None

    def test_rc_fatal_with_minor(self, decoder):
        # Find a major code that has minors
        for code, info in decoder.rc_db.items():
            if info.get("minors"):
                first_minor = list(info["minors"].keys())[0]
                result = decoder.decode_rc_fatal_error(code, first_minor)
                assert result["minor_name"] is not None
                break

    def test_unknown_rc_fatal(self, decoder):
        result = decoder.decode_rc_fatal_error("0x01")
        assert result["major_code"] == "0x01"


# ---------------------------------------------------------------------------
# Combined error code decoding
# ---------------------------------------------------------------------------

class TestDecodeErrorCode:
    def test_combined_format(self, decoder):
        # 0x3000CD2C: context=0x3000, major=0xCD, minor=0x2C
        result = decoder.decode_error_code("0x3000CD2C")
        assert result["context"] == "0x3000"
        assert "0xCD" in result["major_code"]
        assert "0x2C" in result["minor_code"]

    def test_integer_input(self, decoder):
        result = decoder.decode_error_code(0x3000CD2C)
        assert result["context"] == "0x3000"


# ---------------------------------------------------------------------------
# IPSD error decoding
# ---------------------------------------------------------------------------

class TestDecodeIpsd:
    def test_known_ipsd_code(self, decoder):
        result = decoder.decode_ipsd_error(0x80000010)
        assert "Timeout" in result["description"]

    def test_unknown_ipsd_code(self, decoder):
        result = decoder.decode_ipsd_error(0x99999999)
        assert result["description"] == "Unknown IPSD Error"


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

class TestParseLog:
    def test_ewl_multiline_block(self, decoder):
        """Test the Enhanced warning multi-line block format."""
        log_block = """Enhanced warning of type 2 logged:
 Major Warning Code = 0x29
 Minor Warning Code = 0x15
 Data  = 0x00, 0x00, 0x00, 0x00"""
        codes = decoder.parse_log(log_block)
        assert len(codes) > 0

    def test_error_logged_pattern(self, decoder):
        """Test the Error Logged single-line format."""
        log_line = "Error Logged: Class Code = 0029, Error Code = 0015, Minor Code = 0026"
        codes = decoder.parse_log(log_line)
        assert len(codes) > 0

    def test_empty_log(self, decoder):
        codes = decoder.parse_log("")
        assert codes is not None
        assert len(codes) == 0

    def test_no_codes_in_text(self, decoder):
        codes = decoder.parse_log("This is just normal text with no error codes")
        assert len(codes) == 0
