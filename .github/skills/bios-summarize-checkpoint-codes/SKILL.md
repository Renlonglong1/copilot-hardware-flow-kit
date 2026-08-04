# bios-summarize-checkpoint-codes

## Summary
Automatically parse Intel server project memory training source code and generate a comprehensive checkpoint code report (CSV or Excel) mapping functions to debug strings and their corresponding checkpoint codes across BirchStream, EagleStream, and OakStream projects.

## Trigger Phrases
- generate checkpoint code report
- summarize checkpoint codes
- extract memory checkpoint codes
- create checkpoint code mapping

## When to Use This Skill
Use this skill when you need to:
- Extract checkpoint codes from memory training libraries for a specific Intel project
- Build a mapping of training functions to their debug strings and checkpoint codes
- Generate a searchable report of all checkpoint codes in a project
- Analyze which functions have which checkpoint code pairs (major, minor)
- Run the script via command-line with project name or index

## Scope
- **Personal skill** — applies across all workspaces
- Works with Intel server projects: BirchStream (BHS), EagleStream (EGS), OakStream (OKS)
- Processes source from standardized paths in C:\code directory
- Command-line driven (non-interactive)

## Command-Line Usage
```powershell
python summarize_checkpoint_code.py <project>
```

**Project argument options:**
- By name: `BirchStreamRp`, `EagleStreamRp`, or `OakStreamRp`
- By index: `0` (BirchStream), `1` (EagleStream), `2` (OakStream)

**Examples:**
```powershell
python summarize_checkpoint_code.py BirchStreamRp
python summarize_checkpoint_code.py 0
```

If no argument is provided, script displays usage and available projects.

## Workflow Steps

### 1. Validate Command-Line Argument
Receive project argument from command-line:
- If no argument: display usage message and list available projects, then exit
- If invalid argument: display error message and list available projects, then exit
- If valid project name or index: proceed to step 2

### 2. Locate Source Files
For the validated project, verify these three source files exist in C:\code directory:
- `{PROJECT}/Intel/CpRcPkg/Include/Memory/MemoryCheckpointCodes.h` — Contains checkpoint code definitions
- `{PROJECT}/Intel/ServerSiliconPkg/Mem/Library/MemCallTableLib/{SOC}/MemCallTableSoc.c` — Contains main call table
- `{PROJECT}/Intel/ServerSiliconPkg/Mem/Library/MemTrainingLib/{SOC}/MemTrainingCallTable.c` (or OKS DMR path) — Contains training steps

Where `{SOC}` is: `Gnr` (BHS/EGS) or `Gen4` (OKS)

If any file is missing, stop and report the error with the missing path.

### 3. Parse Checkpoint Code Definitions
Read the header file and extract:
- All `#define CHECK_*` macros and their hex values
- All `typedef enum { ... }` blocks and their sequential indices
- Special case: Map `'0'` to `'zero_value'` for minor codes

Store in `check_codes_dict` dictionary (e.g., `check_codes_dict['CHECK_ADDR_MAJOR'] = 0x12`)

### 4. Extract Function-to-Code Mappings
Parse the call table file and extract training functions with their:
- **Function name** (base name, e.g., `AddrLvl`, `DdrTraining`)
- **Major code** (checkpoint code major byte)
- **Minor code** (checkpoint code minor byte)
- **Debug string** (extracted from `CALL_TABLE_STRING(...)` or function documentation)

Special handling:
- Skip `PipeSync` function (no checkpoint code)
- For `DdrTraining` (BHS/EGS) or `ExecuteDdrTraining` (OKS): recursively parse the DDR training sub-table
- Prepend function hierarchy: e.g., `DdrTraining - NameOfSubfunction`
- OKS has different field offsets (add 1 to item indices for function/major/minor)

### 5. Build CSV Report
Generate table with columns: `Function, Debug String, Checkpoint Code`

For each function:
1. Look up major code in `check_codes_dict` → get major byte
2. Look up minor code in `check_codes_dict` → get minor byte
3. Assemble checkpoint code: `0x{major:02x}{minor:02x}0000`
4. Append row: `{Function}, {Debug String}, {Checkpoint Code}`

Example:
```
AddrLvl, Address Level Training, 0x10010000
DdrTraining - Vref, Vref Sweep Training, 0x10020000
```

### 6. Output Report
**Auto-detect output format:**
- If `openpyxl` package is installed → Save as formatted Excel (`.xlsx`) with styled headers
- Otherwise → Save as plain CSV (`.csv`)

**Excel formatting (when openpyxl available):**
- Blue header row with white bold text, centered
- Auto-adjusted column widths (30, 40, 18 characters)

**Output file naming:** `{PROJECT_NAME}_CheckpointCodes.{xlsx|csv}`

**Location:** Save to current working directory (C:\code or user's cwd)

Display confirmation message with full file path.

## Quality Criteria
✓ All source files found and validated  
✓ Main call table functions parsed correctly (with leading brace cleanup)  
✓ DdrTraining function properly detected and recursively parsed  
✓ Training steps from nested call tables extracted (e.g., 46 training steps for EGS)  
✓ No missing checkpoint code definitions (warnings logged for any missing codes)  
✓ Correct major/minor byte ordering in hex checkpoint codes  
✓ Output file created and saved successfully  
✓ CSV/Excel formatting is correct and readable  

## Error Handling
| Error | Action |
|-------|--------|
| No command-line argument | Display usage message with available projects and exit code 1 |
| Invalid project argument | Display error with available projects and exit code 1 |
| Project directory not found | Display error with full path and exit code 1 |
| Source file missing | Display error with missing file path and exit code 1 |
| Missing checkpoint code definition | Log warning and skip that function entry |
| openpyxl unavailable | Fall back to CSV format automatically |
| File write permission denied | Report error and exit code 2 |

## Implementation Notes
- Command-line argument validation with helpful usage messages
- Pre-compiled regex patterns (4 patterns) for efficient parsing
- Uses openpyxl for native Excel generation (no external dependencies like SaveTableToExcel)
- Handles platform-specific differences (BHS/EGS vs OKS field offsets)
- Recursive parsing for nested training function tables (e.g., DdrTraining sub-steps)
- Graceful fallback to CSV if openpyxl is unavailable
- Exit codes: 0 (success), 1 (user error), 2 (runtime error)
- **Fixed:** Properly cleans up function names from call table parsing to enable DdrTraining detection

## Related Skills
- **bios-locate-knob** — Find related BIOS setup options for memory training
- **bios-analyze-log** — Decode checkpoint codes from BIOS logs
- **bios-ras-test** — Run memory training tests and validate output

## Related Customizations
Consider pairing with `.instructions.md` to:
- Set workspace-specific CODE_LOCATION path
- Configure default output directory
- Add shell integration for batch processing multiple projects
- Create wrapper scripts for automated checkpoint code generation pipelines
