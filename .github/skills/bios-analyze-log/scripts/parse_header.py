#!/usr/bin/env python3
"""
Parse Intel Enhanced Warning Log header file and generate JSON database.

Extracts all WARN_* macro definitions from EnhancedWarningLogLib.h
and generates a structured JSON database with major and minor codes.
"""

import re
import json
from collections import OrderedDict
from pathlib import Path


def convert_name_to_description(name):
    """
    Convert WARN_CODE_NAME to description format.
    
    Examples:
        WARN_MEMORY_TRAINING -> MEMORY TRAINING
        WARN_RX_DQS_SMALL_EYE -> RX DQS SMALL EYE
        WARN_CXL_MAILBOX_COMMAND_INVALID -> CXL MAILBOX COMMAND INVALID
    """
    # Remove WARN_ prefix
    if name.startswith('WARN_'):
        name = name[5:]
    
    # Convert to title case with spaces
    # Handle special cases like MINOR, DQ, RX, WR, etc.
    words = name.split('_')
    
    # Join with spaces
    description = ' '.join(words)
    
    return description


def parse_header_file(header_path):
    """
    Parse Intel EWL header file and extract WARN_* definitions.
    
    Returns dict with major codes containing nested minor codes.
    Structure:
    {
        "0x29": {
            "name": "WARN_MEMORY_TRAINING",
            "description": "MEMORY TRAINING",
            "type": "major",
            "source_line": 231,
            "minors": {
                "0x15": {
                    "name": "WARN_RX_DQS_SMALL_EYE",
                    "description": "RX DQS SMALL EYE"
                }
            }
        }
    }
    """
    
    with open(header_path, 'r') as f:
        lines = f.readlines()
    
    codes = OrderedDict()
    current_major = None
    
    # Regex patterns
    major_pattern = r'^#define\s+(\w+)\s+(0x[0-9A-Fa-f]+)'
    minor_pattern = r'^\s*#define\s+(\w+)\s+(0x[0-9A-Fa-f]+)'
    
    for line_num, line in enumerate(lines, 1):
        # Skip lines with parentheses (aliases) or empty lines
        if '(' in line or line.strip().startswith('//'):
            continue
        
        # Check for major code (no leading whitespace)
        major_match = re.match(major_pattern, line)
        if major_match:
            name = major_match.group(1)
            # Only process WARN_* definitions
            if name.startswith('WARN_'):
                hex_val = major_match.group(2).upper()
                # Normalize to lowercase key
                hex_key = hex_val.lower()
                
                # Check for deprecated marker
                is_deprecated = 'DEPRECATED' in line
                
                current_major = {
                    'name': name,
                    'description': convert_name_to_description(name),
                    'type': 'major',
                    'source_line': line_num,
                    'minors': OrderedDict(),
                    'deprecated': is_deprecated
                }
                codes[hex_key] = current_major
            continue
        
        # Check for minor code (with leading whitespace, but not in major definition line)
        if current_major and line.startswith((' ', '\t')):
            minor_match = re.match(minor_pattern, line)
            if minor_match:
                name = minor_match.group(1)
                if name.startswith('WARN_') or name == 'WARN_MINOR_WILDCARD':
                    hex_val = minor_match.group(2).upper()
                    hex_key = hex_val.lower()
                    
                    # Check for deprecated marker
                    is_deprecated = 'DEPRECATED' in line
                    
                    current_major['minors'][hex_key] = {
                        'name': name,
                        'description': convert_name_to_description(name),
                        'deprecated': is_deprecated
                    }
    
    return codes


def remove_deprecated_if_requested(codes, remove_deprecated=False):
    """
    Optionally remove deprecated codes.
    
    Args:
        codes: Dictionary of codes
        remove_deprecated: If True, removes codes marked as deprecated
    
    Returns:
        Filtered codes dictionary
    """
    if not remove_deprecated:
        return codes
    
    filtered = OrderedDict()
    for hex_key, major_info in codes.items():
        if not major_info.get('deprecated', False):
            # Also filter deprecated minors
            major_info['minors'] = OrderedDict(
                (k, v) for k, v in major_info['minors'].items()
                if not v.get('deprecated', False)
            )
            filtered[hex_key] = major_info
    
    return filtered


def cleanup_json_structure(codes):
    """
    Clean up JSON structure by removing deprecated field and empty minors.
    
    Keeps the structure clean for the decoder while removing metadata.
    """
    cleaned = OrderedDict()
    
    for hex_key, major_info in codes.items():
        cleaned_major = OrderedDict()
        cleaned_major['name'] = major_info['name']
        cleaned_major['description'] = major_info['description']
        cleaned_major['type'] = 'major'
        
        # Only include source_line if needed
        cleaned_major['source_line'] = major_info.get('source_line')
        
        # Clean minors
        cleaned_minors = OrderedDict()
        for minor_hex, minor_info in major_info['minors'].items():
            cleaned_minors[minor_hex] = {
                'name': minor_info['name'],
                'description': minor_info['description']
            }
        
        cleaned_major['minors'] = cleaned_minors
        cleaned[hex_key] = cleaned_major
    
    return cleaned


def generate_database(header_path, output_path, include_source_lines=True, include_deprecated=False):
    """
    Parse header file and generate JSON database.
    
    Args:
        header_path: Path to EnhancedWarningLogLib.h
        output_path: Path to output JSON file
        include_source_lines: Include source line numbers in output
        include_deprecated: Include deprecated codes in output
    """
    
    print(f"Parsing header file: {header_path}")
    codes = parse_header_file(header_path)
    
    # Filter deprecated if requested
    if not include_deprecated:
        codes = remove_deprecated_if_requested(codes, remove_deprecated=True)
    
    print(f"Found {len(codes)} major codes")
    
    # Count minors
    total_minors = sum(len(major['minors']) for major in codes.values())
    print(f"Found {total_minors} minor codes")
    
    # Clean up structure
    cleaned_codes = cleanup_json_structure(codes)
    
    # Remove source_line if not requested
    if not include_source_lines:
        for major_info in cleaned_codes.values():
            major_info.pop('source_line', None)
    
    # Write to JSON
    with open(output_path, 'w') as f:
        json.dump(cleaned_codes, f, indent=2)
    
    print(f"Database written to: {output_path}")
    print(f"File size: {Path(output_path).stat().st_size} bytes")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Parse EWL header file and generate database')
    parser.add_argument('header_file', help='Path to EnhancedWarningLogLib.h')
    parser.add_argument('-o', '--output', default='ewl_codes_database.json', help='Output JSON file')
    parser.add_argument('--no-source-lines', action='store_true', help='Exclude source line numbers')
    parser.add_argument('--include-deprecated', action='store_true', help='Include deprecated codes')
    
    args = parser.parse_args()
    
    header_path = Path(args.header_file)
    if not header_path.exists():
        print(f"Error: Header file not found: {header_path}")
        return 1
    
    output_path = Path(args.output)
    
    generate_database(
        header_path,
        output_path,
        include_source_lines=not args.no_source_lines,
        include_deprecated=args.include_deprecated
    )
    
    return 0


if __name__ == '__main__':
    exit(main())
