---
name: bios-firmware-decoder
description: "Use when automating offline BIOS/IFWI firmware inspection or modification: decode BIOS binary knobs, patch BIOS knob values, inspect or edit FIT/FITm softstrap fields, BootGuard or DAM policy bits, export/replace BIOS regions or MCU payloads, convert MCU INC/BIN files, and use the unified BIOS GUI for offline decode/edit or live runtime BIOS knob programming. Trigger phrases: bios firmware decoder, BIOS binary decode, BIOS knob patch, softstrap edit, BootGuard DAM, FITm summary, offline BIOS binary modification, MCU replace, MCU INC conversion, runtime BIOS knob change."
argument-hint: "Provide the BIOS binary path, desired FIT/softstrap/BootGuard/DAM changes, BIOS knob assignments, BIOS region or MCU export/replace/convert target, and output directory if known."
---

# BIOS Firmware Decoder

Use this workflow for BIOS/IFWI inspection, offline binary modification, MCU payload handling, and the runtime BIOS knob GUI workspace.

## Tools

The `tools/` folder lives beside this `SKILL.md`, so all examples below use relative paths.

| Friendly name | Canonical file | Primary use |
|---|---|---|
| BIOS Firmware Decoder CUI | `tools/bios_firmware_decoder.py` | v0.1.0; self-contained command-line entry for FITm/softstrap/BootGuard/DAM and offline BIOS knob automation |
| BIOS Firmware Decoder GUI | `tools/bios_firmware_decoder.pyw` | v0.1.0; user-facing GUI for offline BIOS knob flows plus integrated FITm/softstrap/BootGuard editor and runtime BIOS knob programming |

Both tools support the Common UEFI image operations needed for this workflow:

- BIOS region export and replacement for flash descriptor region `1-bios` / `bios`.
- MCU / microcode export and replacement for FIT type-1 entries by FIT index.
- MCU include/binary conversion between `.inc` text and raw binary payloads.

Current boundary: the Common UEFI GUI shows UEFI driver / FFS module inventory as a planned parser area. Do not promise UEFI driver or FFS module decode/export unless the tool implementation is extended first.

## When To Use This Skill

Use this skill when the user wants one or more of these actions as one BIOS firmware workflow:

- Inspect or modify FITm/softstrap/BootGuard/DAM fields, including raw `IBLStrapN` registers.
- Decode or patch offline BIOS knobs from a BIOS/IFWI/SPI binary.
- Export or replace the descriptor `1-bios` / `bios` flash region.
- Export, replace, or convert FIT type-1 MCU/microcode payloads.
- Apply FITm assignments and BIOS knob assignments together with `patch-all`.
- Launch the GUI for offline decode/edit flows or live runtime BIOS knob programming.

## Required Inputs

Collect only the missing inputs needed for the requested phases:

- `bios_binary`: input BIOS/IFWI/SPI image path.
- `output_dir`: directory for generated XML, JSON, CSV, and patched binaries.
- `fit_assignments`: named FIT/softstrap/BootGuard assignments.
- `knob_assignments`: BIOS knob assignments.
- `region_target`: BIOS flash region name or index, usually `bios` or `1`.
- `fit_index`: FIT index for MCU/microcode export or replacement.
- `replacement_binary`: BIOS-region or MCU replacement binary path.
- `mcu_conversion_input`: MCU `.inc` or raw binary path when only converting payload formats.
- `interactive`: whether to launch GUI tools instead of running CUI automation.

## Workflow

### Intent Resolution Before Modification

When the user asks to view or modify a BIOS setting, first decode the user-provided binary, then locate the requested target in the decoded output before making any change.

- Determine whether the target is exposed as a BIOS knob, a FITm/softstrap/BootGuard field, a flash descriptor region, or a Common UEFI microcode/CPUID entry.
- Confirm the requested field exists in the decoded binary before patching anything.
- If the requested target cannot be found, report that explicitly instead of guessing or writing a nearby field.
- Use the user's short description to infer the likely BIOS intent when they do not name an exact field.
- When Common UEFI exposes CPUID family information, use it as a platform hint: GNR-SP/GNR-D/SRF-SP/CWF map to BHS, and DMR/DMR-OLD/DMRHD/PMR/COR map to OKS.

Common intent mappings:

- "ensure BIOS can be halted" means `btg.DisableCpuDebugging = 0x0` (CPU debugging allowed) and `btg.Consent = 0x1` (Enabled).
- "ensure BIOS can unlock" means `btg.Dam = 0x1` (Enabled).
- "enable S3M Log" or "enable S3M Uart" means `btg.S3mTrace = 0x1` (Enabled).

### Offline BIOS Binary Decode

Use the CUI for automation:

```powershell
python tools\bios_firmware_decoder.py knob-decode <input_binary> --xml <output_xml>
python tools\bios_firmware_decoder.py knob-decode <input_binary> --xml <output_xml> --csv <output_csv> --json <output_json>
```

If the image does not contain `BiosKnobsDataBin`, `knob-decode` falls back to HII/IFR parsing and enriches results from default-data/NVRAM stores when available. In fallback mode, internal Intel knob names, databin depex records, duplicate knob metadata, and hidden/non-HII knobs are not guaranteed.

### FIT / Softstrap / BootGuard Decode And Patch

List supported fields before writing if the requested field name is not exact:

```powershell
python tools\bios_firmware_decoder.py fit-list-fields --platform oks
python tools\bios_firmware_decoder.py fit-list-fields --platform bhs --group btg --json
```

Inspect summary, individual fields, or raw straps:

```powershell
python tools\bios_firmware_decoder.py fit-summary <input_binary>
python tools\bios_firmware_decoder.py fit-summary <input_binary> --json
python tools\bios_firmware_decoder.py fit-get <input_binary> btg.Dam
python tools\bios_firmware_decoder.py fit-get <input_binary> IBLStrap2 --json
python tools\bios_firmware_decoder.py fit-dump-straps <input_binary>
```

Patch a named field or raw strap:

```powershell
python tools\bios_firmware_decoder.py fit-set <input_binary> btg.Dam 0x1 --output <patched_binary> --overwrite
python tools\bios_firmware_decoder.py fit-set <input_binary> IBLStrap2 0x12345678 --in-place
```

For combined FITm and BIOS knob edits, keep FITm edits first and BIOS knob edits second:

```powershell
python tools\bios_firmware_decoder.py patch-all <input_binary> --fit-set btg.Dam=0x1 --fit-output <fit_patched.bin> --knob-set KnobName=0x1 --output <final_binary>
```

### GUI Entry

```powershell
pythonw tools\bios_firmware_decoder.pyw
```

In the GUI, decode a BIOS binary, open the Common UEFI view, then select one of these rows:

- `Flash Regions -> 1 - bios`: use `Export` to save only the BIOS region slice. The exported bytes are exactly the decoded region `size`, where `size = limit - base + 1`. Use `Replace` to update the `1-bios` region; the selected replacement may be smaller than the region size and is padded with `0xFF`, but it must not be larger.
- `Microcode / CPUID -> FIT index ...`: use `Export` to save the MCU/microcode bytes from that FIT entry. Use `Replace` to write a new MCU into the slot derived from the selected FIT entry file offset and an adjacent FIT entry file offset; the selected replacement may be smaller than the slot and is padded with `0xFF`, but it must not be larger.

GUI BIOS region and MCU replacement actions write a new BIOS image to `outimage.bin` beside the loaded image and do not modify the original input image. Other staged offline BIOS knob and FITm edits use the top `Rebuild Binary` or `Replace` action to persist changes.

### BIOS Region Export And Replace

Use the CUI when automation is preferred:

```powershell
python tools\bios_firmware_decoder.py bios-region-export <input_binary> --region bios --output <bios_region.bin> --overwrite
python tools\bios_firmware_decoder.py bios-region-export <input_binary> --region 1 --output <bios_region.bin> --overwrite
```

The export is strictly based on the decoded descriptor region metadata:

- `base` is the byte offset of the region start.
- `limit` is the inclusive byte offset of the region end.
- `size` is `limit - base + 1`.
- The output length must equal `size`; it is not the full IFWI/SPI image unless the descriptor itself says the BIOS region spans the full image.

Replace the BIOS region with:

```powershell
python tools\bios_firmware_decoder.py bios-region-replace <input_binary> <replacement_bios_region.bin> --region bios --output <patched_binary> --overwrite
python tools\bios_firmware_decoder.py bios-region-replace <input_binary> <replacement_bios_region.bin> --region 1 --in-place
```

Replacement rule:

- The replacement file size must be less than or equal to the decoded `1-bios` region size.
- If the replacement is smaller than the region size, the remaining bytes are padded with `0xFF`.
- If it is larger, the tool rejects it.

### MCU / Microcode Export And Replace

First list MCU/FIT entries:

```powershell
python tools\bios_firmware_decoder.py uefi-summary <input_binary> --details
```

Export a microcode entry by FIT index:

```powershell
python tools\bios_firmware_decoder.py microcode-export <input_binary> <fit_index> --output <mcu.bin> --overwrite
python tools\bios_firmware_decoder.py mcu-export <input_binary> <fit_index> --output <mcu.bin> --overwrite
```

Replace a microcode entry by FIT index:

```powershell
python tools\bios_firmware_decoder.py microcode-replace <input_binary> <fit_index> <replacement_mcu.bin> --output <patched_binary> --overwrite
python tools\bios_firmware_decoder.py mcu-replace <input_binary> <fit_index> <replacement_mcu.bin> --in-place
```

MCU replacement rule:

- The target entry must be a FIT type-1 microcode entry.
- The slot size is derived from the absolute difference between the selected FIT entry file offset and the adjacent FIT entry file offset. FIT entry order is based on FIT index; file offsets are not assumed to be monotonic.
- Replacement input may be either a raw binary payload or an `.inc` file; `.inc` replacements are converted to binary before the slot-size check.
- The replacement file size must be less than or equal to that slot size.
- If the replacement is smaller than the slot, the remaining bytes are padded with `0xFF`.
- If it is larger, the tool rejects it.

Convert MCU payload formats without replacing an image:

```powershell
python tools\bios_firmware_decoder.py mcu-inc-to-bin <mcu.inc> --output <mcu.bin> --overwrite
python tools\bios_firmware_decoder.py mcu-bin-to-inc <mcu.bin> --output <mcu.inc> --overwrite
```

## Verification

Always verify after writing a binary:

- Confirm the output file exists and is not the same path as the input unless in-place was explicitly requested.
- For FIT/softstrap/BootGuard changes, run `fit-get` or `fit-summary` against the final binary.
- For BIOS knob changes, decode the final binary and confirm the requested value.
- For BIOS region export, compare the output file size with the decoded `1-bios` region `size` from `fit-summary` or `bios-region-export` output.
- For BIOS region replacement, confirm the replacement input was not larger than `1-bios` and verify the saved binary can still decode.
- For MCU replacement, run `uefi-summary --details` against the final binary and confirm the target FIT index reports the expected CPUID/revision/status.

## Final Response Format

For completed automation, report:

- Original binary path.
- Final binary path.
- Intermediate binary paths, if any.
- FIT/softstrap/BootGuard before/after values.
- BIOS knob before/after values.
- BIOS region base/limit/size and exported/replacement byte count, when region operations were performed.
- MCU FIT index, offset, total size or slot size, and exported/replacement byte count, when MCU operations were performed.
- Verification commands or verification summary.
