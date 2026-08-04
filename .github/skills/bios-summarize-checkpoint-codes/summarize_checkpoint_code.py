import os
import re
import sys

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    SAVE_TO_EXCEL = True
except ImportError:
    SAVE_TO_EXCEL = False

CODE_LOCATION = r'C:\code'
os.chdir(CODE_LOCATION)

# Project configuration
PROJECTS = {
    'BirchStreamRp': [
        r'Intel\CpRcPkg\Include\Memory\MemoryCheckpointCodes.h',
        r'Intel\ServerSiliconPkg\Mem\Library\MemCallTableLib\GnrSrf\MemCallTableSoc.c',
        r'Intel\ServerSiliconPkg\Mem\Library\MemTrainingLib\Gnr\MemTrainingCallTable.c'
    ],
    'EGS': [
        r'Intel\CpRcPkg\Include\Memory\MemoryCheckpointCodes.h',
        r'Intel\ServerSiliconPkg\Mem\Library\MemCallTableLib\Spr\MemCallTableSoc.c',
        r'Intel\ServerSiliconPkg\Mem\Library\MemTrainingLib\Spr\MemTrainingCallTable.c'
    ],
    'OakStreamRp': [
        r'Intel\CpRcPkg\Include\Memory\MemoryCheckpointCodes.h',
        r'Intel\ServerSiliconPkg\Mem\Library\MemCallTableLib\Gen4\MemCallTableSoc.c',
        r'MemoryTraining\SubsysMemoryTraining\host_src_pkgs\MemoryFirmware\ServerMemoryPkg\IncludePrivate\TrainingSteps\HtcDmr.h'
    ]
}

# Regex patterns (compiled once for efficiency)
DEFINE_PATTERN = re.compile(r'#define\s+(CHECK\w+)\s+(0x[0-9A-Fa-f]+)')
ENUM_PATTERN = re.compile(r'typedef enum \{(.*?)\}', re.DOTALL)
DEBUG_STRING_PATTERN = re.compile(r'CALL_TABLE_STRING\s*\(\s*"([^"]+)"\s*\)')
TRAINING_STEP_PATTERN = re.compile(r'TRAINING_STEP\s*\((.*?)\)', re.DOTALL)

def select_project():
    """Get project from command-line argument or print usage."""
    if len(sys.argv) < 2:
        print('Usage: python summarize_checkpoint_code.py <project>')
        print('\nAvailable projects:')
        for idx, name in enumerate(PROJECTS.keys()):
            print(f'  {idx} . {name}')
        sys.exit(1)
    
    project_arg = sys.argv[1]
    
    # Try to match by name
    if project_arg in PROJECTS:
        return project_arg
    
    # Try to match by index
    try:
        idx = int(project_arg)
        project_list = list(PROJECTS.keys())
        if 0 <= idx < len(project_list):
            return project_list[idx]
    except ValueError:
        pass
    
    # Invalid project
    print(f'Error: Invalid project "{project_arg}"')
    print('\nAvailable projects:')
    for idx, name in enumerate(PROJECTS.keys()):
        print(f'  {idx} . {name}')
    sys.exit(1)

def validate_file_exists(file_path):
    """Validate that a file exists; raise FileNotFoundError if not."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f'File not found: {file_path}')
    return file_path

def build_checkpoint_codes_dict(checkpoint_code_path):
    """Parse checkpoint code definitions from header file."""
    check_codes_dict = {'zero_value': 0}
    
    with open(checkpoint_code_path, 'r') as fp:
        content = fp.read()
    
    # Extract #define CHECK_* macros
    for match in DEFINE_PATTERN.finditer(content):
        code_name, code_value = match.groups()
        check_codes_dict[code_name] = int(code_value, 16)
    
    # Extract enum blocks
    for enum_block in ENUM_PATTERN.findall(content):
        for idx, line in enumerate([l.strip() for l in enum_block.split('\n') if l.strip()]):
            code = line.split('=')[0].strip().rstrip(',')
            if code:
                check_codes_dict[code] = idx
    
    return check_codes_dict

def validate_and_lookup_codes(major, minor, check_codes_dict):
    """Validate that major and minor codes exist; return tuple (major_byte, minor_byte) or None."""
    if major not in check_codes_dict:
        print(f'warning: major code {major} missing')
        return None
    if minor not in check_codes_dict:
        print(f'warning: minor code {minor} missing')
        return None
    return (check_codes_dict[major], check_codes_dict[minor])

def format_checkpoint_code(major_byte, minor_byte):
    """Format major and minor bytes into checkpoint code."""
    return f'0x{major_byte:02x}{minor_byte:02x}0000'

def get_dmr_training_steps(table_path, check_codes_dict, target_project):
    """Extract DMR training steps (OakStream specific)."""
    csv_lines = []
    
    with open(table_path, 'r') as fp:
        content = fp.read()
    
    for match in TRAINING_STEP_PATTERN.finditer(content):
        items = [i.strip() for i in match.group(1).split(',') if i.strip()]
        func_name = f"ExecuteDdrTraining - {items[0]}"
        debug = items[-1].replace('"', '')
        major = items[2]
        minor = items[3]
        
        codes = validate_and_lookup_codes(major, minor, check_codes_dict)
        if codes is None:
            continue
        
        checkpoint_code = format_checkpoint_code(*codes)
        csv_lines.append(f'{func_name},{debug},{checkpoint_code}')
    
    return csv_lines
def get_checkpoint_codes(table_path, check_codes_dict, target_project, ddr_training_path=None, header=''):
    """Extract function-to-code mappings from call table."""
    csv_lines = []
    is_main_table = not header  # Add header only for main table
    
    with open(table_path, 'r') as fp:
        content = fp.read()
    
    # Parse call table structure: [] = { ... };
    try:
        table_content = content.split('[] = {')[1].split('};')[0]
    except IndexError:
        print(f'Error: Could not parse table structure in {table_path}')
        return csv_lines
    
    lines = [line.strip() for line in table_content.split('\n') if line.strip() and line.strip()[0] == '{']
    
    for line in lines:
        items = [i.strip() for i in line.split(',') if i.strip()]
        if not items:
            continue
        
        # Clean up function name (remove leading brace and spaces)
        function = items[0].lstrip('{').strip()
        if function == 'PipeSync':  # Skip PipeSync
            continue
        
        # Handle OakStream's different field offset (add 1 to indices)
        offset = 1 if target_project == 'OakStreamRp' else 0
        
        major = items[1 + offset]
        minor = items[2 + offset] if items[2 + offset] != '0' else 'zero_value'
        
        # Extract debug string
        debug_raw = items[5 + offset]
        match = DEBUG_STRING_PATTERN.search(debug_raw)
        debug = match.group(1) if match else debug_raw.replace('"', '')
        
        codes = validate_and_lookup_codes(major, minor, check_codes_dict)
        if codes is None:
            continue
        
        checkpoint_code = format_checkpoint_code(*codes)
        full_function_name = header + function
        csv_lines.append(f'{full_function_name},{debug},{checkpoint_code}')
        
        # Handle nested DDR training functions
        if ddr_training_path:
            if target_project != 'OakStreamRp' and function == 'DdrTraining':
                csv_lines.extend(get_checkpoint_codes(
                    ddr_training_path, check_codes_dict, target_project, header='DdrTraining - '
                ))
            elif target_project == 'OakStreamRp' and function == 'ExecuteDdrTraining':
                csv_lines.extend(get_dmr_training_steps(ddr_training_path, check_codes_dict, target_project))
    
    return csv_lines

def get_file_paths(target_project):
    """Get and validate all required file paths for the target project."""
    if target_project not in PROJECTS:
        raise ValueError(f'Unknown project: {target_project}')
    
    if not os.path.isdir(target_project):
        raise FileNotFoundError(f'Project directory not found: {target_project}')
    
    paths = PROJECTS[target_project]
    
    # Checkpoint code path (special handling for OakStream)
    if target_project == 'OakStreamRp' and os.path.isfile(os.path.join('ZCodeFW', paths[0])):
        checkpoint_code_path = os.path.join('ZCodeFW', paths[0])
    else:
        checkpoint_code_path = os.path.join(target_project, paths[0])
    
    call_table_path = os.path.join(target_project, paths[1])
    ddr_training_path = os.path.join(target_project, paths[2])
    
    # Validate all paths
    validate_file_exists(checkpoint_code_path)
    validate_file_exists(call_table_path)
    validate_file_exists(ddr_training_path)
    
    return checkpoint_code_path, call_table_path, ddr_training_path

def save_table_to_excel(table_data, file_name, sheet_name='codes'):
    """Save table data to Excel file with formatted header."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    
    # Define header style
    header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    center_align = Alignment(horizontal='center', vertical='center')
    
    # Write headers and data
    for row_idx, row_data in enumerate(table_data, start=1):
        for col_idx, cell_value in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
            
            # Apply header formatting to first row
            if row_idx == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = center_align
    
    # Auto-adjust column widths
    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 40
    ws.column_dimensions['C'].width = 18
    
    wb.save(file_name)

def save_report(csv_lines, target_project):
    """Save checkpoint codes report to CSV or Excel file."""
    file_name = f'{target_project}_CheckpointCodes'
    
    if SAVE_TO_EXCEL:
        file_name_full = f'{file_name}.xlsx'
        header = ['Function', 'Debug String', 'Checkpoint Code']
        table = [header] + [line.split(',') for line in csv_lines]
        save_table_to_excel(table, file_name_full, 'codes')
    else:
        file_name_full = f'{file_name}.csv'
        with open(file_name_full, 'w') as fp:
            fp.write('Function,Debug String,Checkpoint Code\n')
            fp.write('\n'.join(csv_lines))
    
    print(f'Saved to {file_name_full}')
    return file_name_full

def main():
    """Main execution flow."""
    try:
        target_project = select_project()
        checkpoint_code_path, call_table_path, ddr_training_path = get_file_paths(target_project)
        
        print(f'\nProcessing {target_project}...')
        print(f'Parsing checkpoint codes from {checkpoint_code_path}')
        check_codes_dict = build_checkpoint_codes_dict(checkpoint_code_path)
        
        print(f'Extracting functions from {call_table_path}')
        csv_lines = get_checkpoint_codes(
            call_table_path, check_codes_dict, target_project, ddr_training_path
        )
        
        print(f'\nGenerated {len(csv_lines)} checkpoint code entries')
        save_report(csv_lines, target_project)
        
    except FileNotFoundError as e:
        print(f'Error: {e}')
        sys.exit(1)
    except Exception as e:
        print(f'Unexpected error: {e}')
        sys.exit(2)

if __name__ == '__main__':
    main()

