#!/usr/bin/env python3
"""
Parse ReferenceCodeFatalErrors.h to extract RC fatal error codes.

This script parses Intel firmware error definitions from the header file and
generates a JSON database with major/minor error code mappings.

CRITICAL: Minor codes are NAMESPACED by major codes. The same minor code value
(e.g., 0x2C) can have different meanings under different major codes.

@copyright
INTEL CONFIDENTIAL
Copyright (C) 2026 Intel Corporation.
"""

import re
import json
import sys
from pathlib import Path
from collections import defaultdict


class RCFatalErrorParser:
    """Parser for ReferenceCodeFatalErrors.h"""
    
    def __init__(self, header_path):
        """Initialize parser with path to header file."""
        self.header_path = Path(header_path)
        self.major_codes = {}  # {hex_value: {name, line, description}}
        self.minor_codes = {}  # {major_hex: {minor_hex: {name, line, description}}}
        self.current_major = None  # Track which major code we're processing enums for
        
    def parse(self):
        """Parse the header file and extract all error codes."""
        if not self.header_path.exists():
            raise FileNotFoundError(f"Header file not found: {self.header_path}")
        
        with open(self.header_path, 'r') as f:
            lines = f.readlines()
        
        print(f"Parsing {len(lines)} lines from {self.header_path.name}", file=sys.stderr)
        
        # First pass: Extract all major codes
        self._extract_major_codes(lines)
        print(f"✓ Found {len(self.major_codes)} major error codes", file=sys.stderr)
        
        # Second pass: Extract enums and associate with major codes
        self._extract_minor_codes(lines)
        total_minors = sum(len(minors) for minors in self.minor_codes.values())
        print(f"✓ Found {total_minors} minor error codes across {len(self.minor_codes)} major codes", file=sys.stderr)
        
        return self._build_database()
    
    def _extract_major_codes(self, lines):
        """Extract #define ERR_* major code definitions."""
        # Pattern for major codes like: #define ERR_RC_INTERNAL3   0xCD
        # Handle both with and without leading spaces
        major_pattern = re.compile(r'^\s*#define\s+(ERR_\w+)\s+(0x[0-9A-Fa-f]+)')
        
        for line_num, line in enumerate(lines, 1):
            match = major_pattern.match(line)
            if match:
                name = match.group(1)
                hex_value = match.group(2).upper()
                
                # Skip if it looks like a minor code (more than 2 spaces before #define)
                if re.match(r'^  [  ]+#define', line):
                    continue
                
                # Skip specific non-error defines
                if name in ['ERR_GENERAL_ASSERT_MINOR_CODE', 'ERR_INVALID_SIGNAL']:
                    continue
                
                # Store major code
                self.major_codes[hex_value] = {
                    'name': name,
                    'line': line_num,
                    'description': self._extract_description_from_name(name)
                }
    
    def _extract_minor_codes(self, lines):
        """Extract typedef enum blocks and associate with major codes."""
        in_enum = False
        enum_lines = []
        enum_start_line = 0
        
        for line_num, line in enumerate(lines, 1):
            # Detect enum start
            if re.match(r'^\s*typedef\s+enum\s*\{', line):
                in_enum = True
                enum_start_line = line_num
                enum_lines = []
                # Try to find associated major code from preceding comments
                self.current_major = self._find_associated_major(lines, line_num)
                continue
            
            # Collect enum content
            if in_enum:
                enum_lines.append((line_num, line))
                
                # Detect enum end
                if re.match(r'^\s*\}\s*\w+;', line):
                    in_enum = False
                    # Parse the collected enum
                    self._parse_enum_block(enum_lines, enum_start_line)
                    enum_lines = []
                    self.current_major = None
    
    def _find_associated_major(self, lines, enum_line_num):
        """Find which major code this enum belongs to by looking at preceding comments."""
        # Look backwards up to 10 lines for a comment indicating the major code
        for i in range(max(0, enum_line_num - 10), enum_line_num):
            line = lines[i]
            
            # Look for patterns like "// ERR_RC_INTERNAL3 Minor codes"
            # or "// Minor codes for ERR_RC_INTERNAL3"
            # or "// ERR_MRC_POINTER Minor codes"
            match = re.search(r'//.*\b(ERR_\w+)\b.*[Mm]inor', line)
            if match:
                major_name = match.group(1)
                # Find the hex value for this major name
                for hex_val, info in self.major_codes.items():
                    if info['name'] == major_name:
                        print(f"  → Associated enum at line {enum_line_num} with {major_name} ({hex_val})", file=sys.stderr)
                        return hex_val
            
            # Also look for patterns like "ERR_MRC_POINTER Minor codes" (no //)
            match = re.search(r'^\s*(ERR_\w+)\s+[Mm]inor', line)
            if match:
                major_name = match.group(1)
                for hex_val, info in self.major_codes.items():
                    if info['name'] == major_name:
                        print(f"  → Associated enum at line {enum_line_num} with {major_name} ({hex_val})", file=sys.stderr)
                        return hex_val
            
            # Look for patterns like "// Minor errors related to ERR_PIPE_SYNC"
            match = re.search(r'//.*related to\s+(ERR_\w+)', line)
            if match:
                major_name = match.group(1)
                for hex_val, info in self.major_codes.items():
                    if info['name'] == major_name:
                        print(f"  → Associated enum at line {enum_line_num} with {major_name} ({hex_val})", file=sys.stderr)
                        return hex_val
        
        return None
    
    def _parse_enum_block(self, enum_lines, enum_start_line):
        """Parse an enum block and extract minor codes."""
        # Pattern for enum entries like:
        # RC_FATAL_ERROR_INTERNAL3_MINOR_CODE_048 = 48,   // Invalid Group transferred to...
        entry_pattern = re.compile(
            r'^\s*(\w+)\s*=\s*(\d+)\s*,?\s*(?://\s*(.*))?'
        )
        
        minor_entries = {}
        
        for line_num, line in enum_lines:
            match = entry_pattern.match(line)
            if match:
                name = match.group(1)
                value = int(match.group(2))
                comment = match.group(3).strip() if match.group(3) else ""
                
                # Skip _MAX entries
                if '_MAX' in name or '_LAST' in name:
                    continue
                
                hex_value = f"0x{value:02X}"
                
                # Try to infer major code from enum entry name if not found
                if self.current_major is None:
                    self.current_major = self._infer_major_from_enum_name(name)
                
                minor_entries[hex_value] = {
                    'name': name,
                    'line': line_num,
                    'description': comment if comment else self._extract_description_from_name(name),
                    'value': value
                }
        
        # Store minor codes under their major code
        if self.current_major and minor_entries:
            if self.current_major not in self.minor_codes:
                self.minor_codes[self.current_major] = {}
            self.minor_codes[self.current_major].update(minor_entries)
        elif minor_entries:
            # Generic minor codes (no specific major association)
            # These might be used with multiple major codes
            if 'GENERIC' not in self.minor_codes:
                self.minor_codes['GENERIC'] = {}
            self.minor_codes['GENERIC'].update(minor_entries)
    
    def _infer_major_from_enum_name(self, enum_name):
        """Try to infer major code from enum entry name pattern."""
        # Patterns like RC_FATAL_ERROR_INTERNAL3_MINOR_CODE_048
        # or SPD_FATAL_ERROR_READ_MINOR_CODE_048
        
        # Extract the middle part (between FATAL_ERROR and MINOR_CODE)
        match = re.match(r'(\w+_)?FATAL_ERROR_(\w+?)_MINOR_CODE_\d+', enum_name)
        if match:
            middle_part = match.group(2)
            
            # Try to match with major code names
            for hex_val, info in self.major_codes.items():
                major_name = info['name']
                # Check if middle part appears in major name
                if middle_part in major_name:
                    return hex_val
        
        return None
    
    def _extract_description_from_name(self, name):
        """Generate human-readable description from macro name."""
        # Remove common prefixes
        desc = name.replace('ERR_', '').replace('RC_FATAL_ERROR_', '')
        desc = desc.replace('_MINOR_CODE', '').replace('MINOR_CODE_', '')
        
        # Convert underscores to spaces and title case
        desc = desc.replace('_', ' ').title()
        
        return desc
    
    def _build_database(self):
        """Build the final JSON database structure."""
        database = {}
        
        for major_hex, major_info in self.major_codes.items():
            database[major_hex.lower()] = {
                'type': 'major',
                'name': major_info['name'],
                'description': major_info['description'],
                'source': f"CpRcPkg/Include/ReferenceCodeFatalErrors.h:{major_info['line']}",
                'minors': {}
            }
            
            # Add associated minor codes
            if major_hex in self.minor_codes:
                for minor_hex, minor_info in self.minor_codes[major_hex].items():
                    database[major_hex.lower()]['minors'][minor_hex.lower()] = {
                        'name': minor_info['name'],
                        'description': minor_info['description'],
                        'source': f"CpRcPkg/Include/ReferenceCodeFatalErrors.h:{minor_info['line']}"
                    }
        
        return database


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Parse ReferenceCodeFatalErrors.h to generate error code database'
    )
    parser.add_argument(
        'header_file',
        help='Path to ReferenceCodeFatalErrors.h'
    )
    parser.add_argument(
        '-o', '--output',
        default='rc_fatal_errors_database.json',
        help='Output JSON file (default: rc_fatal_errors_database.json)'
    )
    parser.add_argument(
        '--pretty',
        action='store_true',
        help='Pretty print JSON with indentation'
    )
    
    args = parser.parse_args()
    
    # Parse the header file
    rc_parser = RCFatalErrorParser(args.header_file)
    database = rc_parser.parse()
    
    # Write to JSON
    output_path = Path(args.output)
    with open(output_path, 'w') as f:
        if args.pretty:
            json.dump(database, f, indent=2, sort_keys=True)
        else:
            json.dump(database, f, sort_keys=True)
    
    print(f"\n✓ Database written to {output_path}", file=sys.stderr)
    print(f"  Total major codes: {len(database)}", file=sys.stderr)
    total_minors = sum(len(info['minors']) for info in database.values())
    print(f"  Total minor codes: {total_minors}", file=sys.stderr)


if __name__ == '__main__':
    main()
