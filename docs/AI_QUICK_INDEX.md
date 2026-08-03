# AI Quick Index

Read this first to choose the smallest needed context. Do not read every document by default.

## Task Router

| User task | Read/use |
| --- | --- |
| UI stage 1 planning | `.github\skills\ips-ui-plan-stage\SKILL.md` |
| IPS/HSD consult / extract only | `.github\skills\ips-consult-flow\SKILL.md` |
| IPS/HSD debug reproduction | `.github\skills\ips-hsd-repro-flow\SKILL.md` |
| BHS flash / boot / MLC flow | `.github\skills\bhs-hardware-flow\SKILL.md` |
| Need PS/PY command syntax | `.github\skills\common-ps-py-commands\SKILL.md` |
| Oak Stream CScripts discovery or usage | `docs\cscripts_oak_stream_usage.md` |
| Select a lab machine for IPS/HSD reproduction | `docs\lab_machine_inventory.md`, then `config\lab-machine-inventory.json` |
| UI operation/config | `docs\ips_copilot_ui.md` |
| HSD API details only when needed | `docs\hsd_python_api_notes.md` |
| BHS RAS, hang/MCE, performance/power, or Oak Stream collateral reference | `docs\bhs_platform_reference_knowledge.md`, then its linked PDF section |
| Personal testing preferences and reusable troubleshooting lessons | `docs\personal_preferences_and_lessons.md` |

Machine-readable router:

```text
config\ai-task-router.json
```

## Golden Shortcuts

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
```

Start UI:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1
```

Fetch HSD:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <ID> -ForceCurlDirect
```

Validate local scripts:

```powershell
py -m py_compile .\scripts\ips_copilot_ui.py .\scripts\extract_hsd_article.py
```

Validated BHS flow:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

## Safety Rules

- Consult/extract tasks: no SSH, no flashing, no power cycle, no serial, no MLC.
- Debug/repro tasks: flash success is required before boot capture.
- EM100 success must include `Download Complete`, `Verify Pass`, `Emulator is in Emulation mode`, `Authentication Pass`.
- If `No device is connected!`, check/close `EM100.exe` or `Emulator.exe`.
- Use `copilot --allow-all`, not stdin `/allow-all`, for UI subprocess permissions.
