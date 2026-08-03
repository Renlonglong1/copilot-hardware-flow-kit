# Copilot Hardware Flow Kit - Compact Instructions

Minimize token usage: read `docs\AI_QUICK_INDEX.md` first, then only the matching skill/doc.

## Skill Router

- Stage 1 UI planning: `.github\skills\ips-ui-plan-stage\SKILL.md`
- IPS/HSD consult or extract only: `.github\skills\ips-consult-flow\SKILL.md`
- IPS/HSD debug/reproduction: `.github\skills\ips-hsd-repro-flow\SKILL.md`
- BHS hardware flash/boot/MLC: `.github\skills\bhs-hardware-flow\SKILL.md`
- Common PS/PY commands: `.github\skills\common-ps-py-commands\SKILL.md`

## Non-negotiable Rules

1. Never ask for or store passwords, cookies, SSO tokens, service tokens, Kerberos ticket contents, or SSH private keys.
2. Consult/extract mode must not SSH, flash, power cycle, control serial, or run MLC.
3. Debug/repro mode must fail fast if flash fails; do not capture boot logs after failed flash.
4. EM100 flash success requires: `Download Complete`, `Verify Pass`, `Emulator is in Emulation mode`, `Authentication Pass`.
5. If EM100 says `No device is connected!`, check DediProg USB and close `EM100.exe` / `Emulator.exe` by PID if needed.
6. Prefer existing scripts and templates over re-deriving commands.

## Key Entry Points

```text
docs\AI_QUICK_INDEX.md
docs\common_ps_py_commands.md
config\ips-copilot-ui.template.json
```

