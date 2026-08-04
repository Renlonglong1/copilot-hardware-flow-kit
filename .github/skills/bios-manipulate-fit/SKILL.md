---
name: bios-manipulate-fit
description: Modify or query Intel FITm (Modular Flash Image Tool) settings in an IFWI binary image. Use this skill whenever the user wants to change FIT settings, read/show/check current FIT setting values, modify flash descriptor parameters, update SPI configuration, change boot guard settings, modify soft straps, or rebuild an IFWI image with different FITm configuration. Trigger phrases include "change FIT setting", "show FIT setting", "what is the current value of", "read IFWI setting", "check descriptor setting", "modify IFWI", "update flash descriptor", "FITm", "fit_cmd", "change SPI setting", "rebuild IFWI with different settings", "modify descriptor setting", "change boot profile", "update flash component size", "show me the boot guard profile", "what's the flash size". Also use when the user mentions container names like descriptor, btg, dbg, pfm, fvm, isclk, or wants to decompose/recompose an IFWI binary, or simply wants to inspect what settings an IFWI currently has.
---

# FITm — Query and Modify FIT Settings in IFWI Binary

This skill provides workflows to either **query** (read/display) or **modify** (change and rebuild) Intel Modular Flash Image Tool (FITm) settings in an IFWI binary. Determine which workflow the user needs based on their request:

- **Query workflow** — User wants to see current setting values ("what is...", "show me...", "check...")
- **Modify workflow** — User wants to change settings and rebuild the image ("change...", "set...", "modify...")

## Prerequisites

- Python environment with FITm dependencies installed
- Access to the FITm tool directory containing `fit_cmd.py`
- An IFWI binary file to modify

## Query Workflow — Show Setting Values

Use this workflow when the user wants to read or display the current value of one or more settings in an IFWI binary without modifying anything.

### Step 0: Locate FITm tool and IFWI binary

Same as the modify workflow (see below) — load or prompt for the FITm directory and IFWI path.

### Step 1: Export current configuration

Decompose the IFWI binary to get its full settings XML:

```
python fit_cmd.py -i <ifwi_binary> -s current_config.xml
```

### Step 2: Find and display the requested settings

Parse `current_config.xml` to find the setting(s) the user asked about. Settings are organized by container:

```xml
<container name="descriptor">
    <setting name="FlashComponent1Size" value="0x4000000"/>
</container>
```

Present the results clearly to the user:

| Container | Setting | Current Value |
|-----------|---------|---------------|
| descriptor | FlashComponent1Size | 0x4000000 |

**If the user's request is vague** (e.g., "show me boot guard settings"), show all settings in the relevant container. Use `python fit_cmd.py -h <container_name>` to get descriptions of what each setting means.

**If the user asks about a specific setting by description** (e.g., "what's the flash size?"), search the XML for likely matches and also check `-h` output for setting descriptions to identify the right one.

### Step 3 (optional): Show setting details

If the user wants more context about a setting (valid values, description, constraints), run:

```
python fit_cmd.py -h <container:setting_name>
```

This displays a table with the setting's type, value limitations, default value, and description.

---

## Modify Workflow — Change Settings and Rebuild

Use this workflow when the user wants to change settings and produce a new IFWI binary.

### Step 0: Locate FITm tool and IFWI binary

Check if a saved FITm path exists in the workspace at `.fitm_config.json`. If it does, display it and ask the user to confirm or provide a new path. If it doesn't exist, prompt the user for:

1. The folder path containing `fit_cmd.py` (the FITm tool directory)
2. The IFWI binary file path to modify

Validate that `fit_cmd.py` exists in the specified folder. Save the confirmed path to `.fitm_config.json` in the workspace root so it persists for future invocations:

```json
{
  "fitm_dir": "C:\\path\\to\\FITm",
  "last_ifwi": "C:\\path\\to\\ifwi.bin"
}
```

Always ask the user to confirm even when loading from saved config — paths may become stale.

### Step 1: Export current settings to before.xml

Decompose the IFWI binary and save its full configuration XML. This captures all current settings as the baseline:

```
python fit_cmd.py -i <ifwi_binary> -s before.xml
```

Run this command from the FITm tool directory. The output `before.xml` contains every container and setting in the image.

### Step 2: Create tomodify.xml and apply user's changes

1. Copy `before.xml` to `tomodify.xml`
2. Parse the user's requested changes. Changes are expressed as `container:setting=value` pairs (e.g., `descriptor:FlashComponent1Size=0x4000000`)
3. Modify the corresponding `<setting name="..." value="..."/>` entries in `tomodify.xml`
4. Show the user a summary of what will change (old value → new value) and ask for confirmation before proceeding

**Finding the right setting:** If the user describes a change in natural language (e.g., "change flash size to 64MB"), use `python fit_cmd.py -h <container_name>` to look up available settings and valid values. Common containers:
- `descriptor` — Flash descriptor settings (SPI components, sizes, frequencies, access permissions)
- `btg` — Boot Guard configuration (profiles, keys, hashes)
- `dbg` — Debug settings (ESE config, ROM_B)
- `pfm` — Platform Firmware Manifest (PFR SPI region definitions)
- `fvm` — Firmware Volume Manifest (seamless update regions)
- `isclk` — Clock configuration
- `layout` — Platform layout, region order, region sizes

**XML setting format:**
```xml
<container name="descriptor">
    <setting name="FlashComponent1Size" value="0x4000000"/>
    <setting name="NumberOfSpiComponents" value="1"/>
</container>
```

### Step 3: Build new IFWI with modified settings

Build a new image using `tomodify.xml` as input configuration:

```
python fit_cmd.py -b -i tomodify.xml
```

This produces a new `outimage.bin` in the FITm tool directory. If the build fails, report the error to the user — common issues include:
- Missing firmware collateral files (BIOS binary, PDR, etc.) — may need `--params bios:input_file=<path>`
- Invalid setting values — check valid ranges with `-h container:setting`
- Schema validation errors — consider `--skip_schema_validation` if appropriate

### Step 4: Export settings from new image to after.xml

Decompose the newly built image to capture its configuration:

```
python fit_cmd.py -i outimage.bin -s after.xml
```

### Step 5: Compare before.xml and after.xml in VS Code

Open a diff view in VS Code so the user can visually verify exactly what changed:

```powershell
code --diff before.xml after.xml
```

This gives the user full confidence that only their intended changes were applied.

## Important Notes

- Always work from the FITm tool directory as the working directory — FITm resolves relative paths from there
- The `--report_config` flag can be added to any command to show non-default settings in a table format
- Use `--verbose` during build for detailed logging if troubleshooting is needed
- If the user wants to override settings at build time without modifying the XML, use `--params container:setting=value` directly on the build command
- Full paths can be used for all file references to avoid relative path issues

## FITm CLI Quick Reference

| Action | Command |
|--------|---------|
| Export full config from binary | `python fit_cmd.py -i <image.bin> -s <output.xml>` |
| Export non-default settings only | `python fit_cmd.py -i <image.bin> --save_simple_xml <output.xml>` |
| Build image from config XML | `python fit_cmd.py -b -i <config.xml>` |
| Build with param overrides | `python fit_cmd.py -b -i <config.xml> --params container:setting=value` |
| Show all settings in container | `python fit_cmd.py -h <container_name>` |
| Show single setting details | `python fit_cmd.py -h <container:setting_name>` |
| Report non-default config | `python fit_cmd.py -i <image.bin> --report_config` |
| Build with verbose logging | `python fit_cmd.py -b -i <config.xml> --verbose` |
