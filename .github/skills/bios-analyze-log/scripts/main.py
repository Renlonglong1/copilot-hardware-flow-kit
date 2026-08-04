#!/usr/bin/env python3
"""
EWL Decoder SKILL - GitHub Copilot SKILL for decoding BIOS error codes

Commands:
  decode <major> [minor] - Decode a single error code
  analyze-log <text>     - Analyze full BIOS log
  help                   - Show usage information
"""

import sys
import os
from pathlib import Path

# Import decoder from same directory
from decode_ewl import EWLDecoder, SUPPORTED_PLATFORMS

# Default platform (can be overridden via --platform flag)
_DEFAULT_PLATFORM = "oks"


def _pop_platform(args):
    """Extract --platform VALUE from args list, return (platform, remaining_args)."""
    remaining = []
    platform = _DEFAULT_PLATFORM
    i = 0
    while i < len(args):
        if args[i] == "--platform" and i + 1 < len(args):
            platform = args[i + 1].lower()
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    return platform, remaining


def cmd_decode(args):
    """Handle /decode command."""
    platform, args = _pop_platform(args)
    if not args:
        print("Usage: decode [--platform egs|bhs|oks] <major_code> [minor_code]")
        print("Example: decode --platform bhs 0x29 0x15")
        return
    
    major = args[0].upper()
    if not major.startswith('0X'):
        major = f"0X{int(major, 0):X}"
    
    minor = None
    if len(args) > 1:
        minor = args[1].upper()
        if not minor.startswith('0X'):
            minor = f"0X{int(minor, 0):X}"
    
    # Initialize decoder with selected platform
    decoder = EWLDecoder(platform=platform)
    
    # Decode
    result = decoder.decode_code(major, minor)
    
    # Format for Copilot display
    output = ["## Decoded Error Code\n\n"]
    output.append(f"**Code:** `{result['major_code']}`")
    if result['minor_code']:
        output.append(f" / `{result['minor_code']}`")
    output.append("\n\n")
    
    if result['major_name']:
        output.append(f"**Name:** {result['major_name']}")
        if result['minor_name']:
            output.append(f" / {result['minor_name']}")
        output.append("\n\n")
    
    if result['major_desc']:
        output.append(f"**Description:** {result['major_desc']}")
        if result['minor_desc']:
            output.append(f" / {result['minor_desc']}")
        output.append("\n\n")
    
    if not result['major_name']:
        output.append("\n**Status:** Code not found in database\n")
    
    print(''.join(output))


def cmd_analyze_log(args):
    """Handle /analyze-log command."""
    platform, args = _pop_platform(args)
    if not args:
        # Read from stdin
        if not sys.stdin.isatty():
            log_text = sys.stdin.read()
        else:
            print("Usage: analyze-log [--platform egs|bhs|oks] <log_text>")
            print("Or pipe log content via stdin")
            return
    else:
        log_text = ' '.join(args)
    
    # Initialize decoder with selected platform
    decoder = EWLDecoder(platform=platform)
    
    # Parse and decode
    codes = decoder.parse_log(log_text)
    summary = decoder.generate_summary(codes)
    
    print(summary)


def cmd_help():
    """Show help information."""
    help_text = """
# EWL Decoder SKILL

Decode BIOS Enhanced Warning Log (EWL), RC Fatal, and IPSD error codes.
Supports multiple platforms: EGS (EagleStream), BHS (BirchStream), OKS (OakStream).

## Commands

### decode [--platform egs|bhs|oks] <major> [minor]
Decode a single error code.

Examples:
  decode 0x29 0x15
  decode --platform bhs 0x29 0x15

### analyze-log [--platform egs|bhs|oks] <text>
Analyze a full BIOS log and decode all error codes.

Examples:
  analyze-log --platform egs "Enhanced warning of type 2 logged:..."
  cat bios.log | analyze-log --platform bhs

### help
Show this help message.

## Platforms
- egs: EagleStream / ServerGen2
- bhs: BirchStream / ServerGen3
- oks: OakStream / ServerGen4 (default, includes IPSD support)
"""
    print(help_text)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        cmd_help()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    
    if command == 'decode':
        cmd_decode(args)
    elif command == 'analyze-log':
        cmd_analyze_log(args)
    elif command == 'help':
        cmd_help()
    else:
        print(f"Unknown command: {command}")
        print("Use 'help' for usage information")
        sys.exit(1)


if __name__ == '__main__':
    main()
