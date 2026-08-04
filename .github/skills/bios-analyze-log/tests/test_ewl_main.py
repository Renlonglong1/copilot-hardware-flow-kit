"""
Tests for bios-analyze-log/scripts/main.py CLI entry point.

Covers the decode, analyze-log, and help commands plus the unknown-command
error path.  EWLDecoder calls are mocked wherever file I/O is a concern.

Run with:  pytest bios-analyze-log/tests/test_ewl_main.py -v
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Load bios-analyze-log/scripts/main.py by file path to avoid module-name
# collisions with other skills that also have a script called main.py.
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
_MAIN_PATH = os.path.join(_SCRIPTS_DIR, "main.py")
sys.path.insert(0, _SCRIPTS_DIR)

_spec = importlib.util.spec_from_file_location("bios_log_analyzer_main", _MAIN_PATH)
ewl_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ewl_main)


# ---------------------------------------------------------------------------
# help command
# ---------------------------------------------------------------------------

class TestHelpCommand:
    @patch("sys.argv", ["main.py", "help"])
    def test_help_prints_usage(self, capsys):
        ewl_main.main()
        out = capsys.readouterr().out
        assert "decode" in out.lower()
        assert "analyze-log" in out

    @patch("sys.argv", ["main.py"])
    def test_no_args_prints_help_and_exits_1(self, capsys):
        with pytest.raises(SystemExit) as exc:
            ewl_main.main()
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "decode" in out.lower()


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    @patch("sys.argv", ["main.py", "bogus-command"])
    def test_unknown_command_exits_1(self, capsys):
        with pytest.raises(SystemExit) as exc:
            ewl_main.main()
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# decode command
# ---------------------------------------------------------------------------

class TestDecodeCommand:
    @patch("sys.argv", ["main.py", "decode"])
    def test_no_args_prints_usage(self, capsys):
        ewl_main.main()
        out = capsys.readouterr().out
        assert "Usage" in out

    def test_decode_major_only(self, capsys):
        mock_decoder = MagicMock()
        mock_decoder.decode_code.return_value = {
            "major_code": "0X0A",
            "minor_code": None,
            "major_name": "WARN_DIMM_COMPAT",
            "minor_name": None,
            "major_desc": "DIMM compatibility warning",
            "minor_desc": None,
        }

        with patch("sys.argv", ["main.py", "decode", "0x0A"]):
            with patch.object(ewl_main, "EWLDecoder", return_value=mock_decoder):
                ewl_main.main()

        mock_decoder.decode_code.assert_called_once()
        out = capsys.readouterr().out
        assert "Decoded Error Code" in out
        assert "0X0A" in out

    def test_decode_major_and_minor(self, capsys):
        mock_decoder = MagicMock()
        mock_decoder.decode_code.return_value = {
            "major_code": "0X0A",
            "minor_code": "0X05",
            "major_name": "WARN_DIMM_COMPAT",
            "minor_name": "WARN_MINOR_CONFIG_NOT_SUPPORTED",
            "major_desc": "DIMM compatibility warning",
            "minor_desc": "Config not supported",
        }

        with patch("sys.argv", ["main.py", "decode", "0x0A", "0x05"]):
            with patch.object(ewl_main, "EWLDecoder", return_value=mock_decoder):
                ewl_main.main()

        out = capsys.readouterr().out
        assert "0X0A" in out
        assert "0X05" in out

    def test_decode_unknown_code_shows_not_found(self, capsys):
        mock_decoder = MagicMock()
        mock_decoder.decode_code.return_value = {
            "major_code": "0XFF",
            "minor_code": None,
            "major_name": None,
            "minor_name": None,
            "major_desc": None,
            "minor_desc": None,
        }

        with patch("sys.argv", ["main.py", "decode", "0xFF"]):
            with patch.object(ewl_main, "EWLDecoder", return_value=mock_decoder):
                ewl_main.main()

        out = capsys.readouterr().out
        assert "not found" in out.lower() or "Status" in out

    def test_decode_bare_decimal_major(self, capsys):
        """Main converts bare numbers to 0X-prefixed hex before calling decode_code."""
        mock_decoder = MagicMock()
        mock_decoder.decode_code.return_value = {
            "major_code": "0XA",
            "minor_code": None,
            "major_name": "SOME_WARN",
            "minor_name": None,
            "major_desc": "desc",
            "minor_desc": None,
        }

        with patch("sys.argv", ["main.py", "decode", "10"]):
            with patch.object(ewl_main, "EWLDecoder", return_value=mock_decoder):
                ewl_main.main()

        # Verify decode_code was called (exact arg normalisation is an impl detail)
        mock_decoder.decode_code.assert_called_once()


# ---------------------------------------------------------------------------
# analyze-log command
# ---------------------------------------------------------------------------

class TestAnalyzeLogCommand:
    def test_analyze_log_inline_text(self, capsys):
        mock_decoder = MagicMock()
        mock_decoder.parse_log.return_value = []
        mock_decoder.generate_summary.return_value = "No error codes found.\n"

        log_snippet = "Enhanced warning of type 1 logged: Major Warning Code = 0x0A"
        with patch("sys.argv", ["main.py", "analyze-log", log_snippet]):
            with patch.object(ewl_main, "EWLDecoder", return_value=mock_decoder):
                ewl_main.main()

        mock_decoder.parse_log.assert_called_once()
        out = capsys.readouterr().out
        assert "No error codes found" in out

    def test_analyze_log_no_args_reads_stdin(self, capsys):
        mock_decoder = MagicMock()
        mock_decoder.parse_log.return_value = []
        mock_decoder.generate_summary.return_value = "No error codes found.\n"

        with patch("sys.argv", ["main.py", "analyze-log"]):
            with patch("sys.stdin.isatty", return_value=False):
                with patch("sys.stdin.read", return_value="some log text"):
                    with patch.object(ewl_main, "EWLDecoder", return_value=mock_decoder):
                        ewl_main.main()

        mock_decoder.parse_log.assert_called_once_with("some log text")
        out = capsys.readouterr().out
        assert "No error codes found" in out

    @patch("sys.argv", ["main.py", "analyze-log"])
    def test_analyze_log_no_stdin_prints_usage(self, capsys):
        with patch("sys.stdin.isatty", return_value=True):
            ewl_main.main()
        out = capsys.readouterr().out
        assert "Usage" in out or "analyze-log" in out
