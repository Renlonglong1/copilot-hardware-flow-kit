# Copilot Hardware Flow Kit — Portable Handover

This is the 2026-09-21 **sanitized handover distribution**, published on an independent
branch without the original Git history. It is not the raw lab workspace or a
replacement for the existing `main` branch.

## Handover documents

- [中文系统交接文档 — Markdown](docs/SYSTEM_HANDOVER.zh-CN.md)
- [中文系统交接文档 — Word](docs/SYSTEM_HANDOVER.zh-CN.docx)
- [Distribution scope and exclusions](docs/DELIVERY_SCOPE.md)

The kit provides a local Python web workbench, IPS/HSD extraction and consultation,
Copilot planning/execution, persistent Query tasks, report management, and
PowerShell wrappers for approved hardware workflows.

## First deployment

Use a dedicated directory for this branch. Do not merge its unrelated history
into an existing deployment, and do not overwrite existing local configuration.

```powershell
git clone --branch handover/2026-09-21-portable --single-branch https://github.com/Renlonglong1/copilot-hardware-flow-kit.git
Set-Location .\copilot-hardware-flow-kit
New-Item -ItemType Directory -Path .\config\local -Force
Copy-Item .\config\hardware-flow.template.json .\config\local\hardware-flow.json
Copy-Item .\config\ips-copilot-ui.template.json .\config\local\ips-copilot-ui.json
Copy-Item .\config\lab-machine-inventory.template.json .\config\lab-machine-inventory.json
```

All three destination configurations are ignored by Git. Replace placeholders
only with approved machine settings; never add credentials or private-key content.
In the local UI profile, change `machineMatching.inventoryPath` to
`config\\lab-machine-inventory.json`. This is also the inventory path used by
the core workflow prompts.

Before configuration, the distribution UI template displays only a non-routable
`configure-before-use.invalid` placeholder, not a usable hardware target.
The template keeps loopback binding. Configure the real inventory and hardware
profile before requesting any SSH, flash, power, serial, or MLC action.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -NoBrowser
```

Default URL: `http://127.0.0.1:8765/`. The UI has no built-in authentication; do not
expose it to the public internet. Approved shared deployments require an
authenticated access boundary.

## Dependencies

The UI uses the Python standard library. Windows PowerShell, Python/`py.exe`,
Copilot CLI and approved Copilot access are needed for the full UI workflow.
HSD uses an authorized enterprise identity and network; SSH/SCP, EM100,
PowerSplitter, serial devices, Host OS MLC and Outlook are optional integrations
required only for their respective operations. No vendor binaries, firmware
images or licenses are included.

## Safety

Stage 1 only generates a plan. Extraction/consultation never performs hardware
actions. Debug requires approved hardware access, matching platform and image,
and successful flash evidence before boot capture or MLC.

The four required flash messages are `Download Complete`, `Verify Pass`,
`Emulator is in Emulation mode`, and `Authentication Pass`.

Read `docs\AI_QUICK_INDEX.md`, the Chinese handover, and the matching core skill.
Historical lab references are not deployment defaults.

## Offline regression

```powershell
python -m unittest discover -s .\scripts -p test_ips_copilot_ui.py -q
py -m py_compile .\scripts\ips_copilot_ui.py .\scripts\extract_hsd_article.py
```

These tests do not prove that real enterprise accounts or lab hardware are ready.
