---
name: bios-export-knobs
description: Export BIOS setup knobs to Excel with platform-aware scoping (EGS/BHS/OKS). Trigger this skill for requests such as exporting BIOS knob tables, generating setup knob Excel, extracting HFR/VFR options, collecting defaults/options/dependencies, or platform-specific knob exports. If BIOS path is omitted, default to the selected platform's Intel directory. Intel-subtree scope, unrelated-directory exclusion, and always-hidden/disabled filtering are enforced consistently across EGS/BHS/OKS.
---

# BIOS Export Knobs

Automatically export BIOS setup knobs to Excel using the selected platform and BIOS path.

## Supported Platforms

- `EGS` -> `<EGS_ROOT>`
- `BHS` -> `<BHS_ROOT>`
- `OKS` -> `<OKS_ROOT>`

## Output Columns (Fixed Order)

1. `knob name`
2. `knob variable`
3. `description`
4. `knob options`
5. `default value`
6. `menu path`
7. `hfr file location`
8. `dependency`

## Usage Rules

- Platform confirmation is mandatory first (`EGS`/`BHS`/`OKS`).
- Users may provide a BIOS path. If omitted, default to the selected platform's `Intel` directory.
- Scan path must stay inside the selected platform `Intel` subtree (out-of-scope paths must fail) to avoid cross-platform contamination.
- Keep duplicate knob names if definition context differs (different file/variable/condition). Do not merge.
- Sort output by directory, file, and line number so nearby knobs stay adjacent.
- Exclude these unrelated directories on all platforms: `FishhawkFallsRpPkg`, `LoganvilleRpPkg`, `GnrwsRpPkg`, `KaseyvilleRpPkg`, `DunlowPlatSamplePkg`, `NovaLakePlatSamplePkg`, `Features`, `NovaLakeRestrictedPkg`, `SummitvilleRpPkg`.
- Filter always-hidden items on all platforms: `suppressif/grayoutif/disableif` with always-true conditions (for example: `TRUE`, `1`, `EFI_TRUE`, `TRUE==TRUE`, `1==1`).

## Interaction Flow

1. If platform is missing, use the question tool to ask user to choose `EGS/BHS/OKS`.
2. If BIOS path is missing, use the platform `Intel` directory directly (no extra prompt).
3. Prefer GUI entry (platform selection + path input):

```powershell
python ./scripts/run_export_interactive.py
```

4. Or use the CLI exporter:

```powershell
python ./scripts/export_bios_knobs.py --platform OKS --bios-path ./Intel --output ./reports/oks_knobs.xlsx
```

If `--bios-path` is not provided, exporter auto-uses the platform `Intel` directory:

```powershell
python ./scripts/export_bios_knobs.py --platform OKS --output ./reports/oks_knobs.xlsx
```

## Required Report Items

After completion, always report:

- Excel output path
- JSON intermediate file path
- Total exported rows
- Count of unresolved default values (if any)

## Field Semantics

- `knob name`: UI display name (prefer prompt text)
- `knob variable`: variable name (prefer last token of `varid`, for example `PagePolicy`)
- `description`: help text (fallback to prompt text if help is missing)
- `knob options`: available values/ranges for oneof/checkbox/numeric
- `default value`: raw default value (for example `0x2`), do not append option label
- `menu path`: `EDKII Menu\\<Form Title>\\<Knob Name>`
- `hfr file location`: path relative to BIOS root with line number
- `dependency`: display condition context (for example `suppressif`, `grayoutif`)

## Example (Page Policy)

- knob name: `Page Policy`
- knob variable: `PagePolicy`
- description: `Select DRAM Page Policy`
- knob options: `Closed(0x1), Adaptive(0x2)`
- default value: `0x2`
- menu path: `EDKII Menu\\Socket Configuration\\Memory Configuration\\Page Policy`
- hfr file location: `Intel/ServerPlatformPkg/Platform/Dxe/SocketSetup/MemorySetup.hfr:2985`
- dependency: `ideqval SOCKET_MEMORY_CONFIGURATION.Is3dsDimmPresent == 1 (suppressed)`

## Dependency Output Mode

- Use concise mode by default: output only the nearest 1 to 2 key display conditions.
- Example: `ideqval SOCKET_MEMORY_CONFIGURATION.Is3dsDimmPresent == 1 (suppressif)`

## Cross-Platform Consistency

- The same constraints (Intel subtree scope, unrelated-directory exclusion, always-hidden/disabled filtering) apply uniformly to `EGS`, `BHS`, and `OKS`.
