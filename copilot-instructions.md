# Copilot Hardware Flow Kit - Compact Instructions

Read `docs\AI_QUICK_INDEX.md` first and then only the matching skill/doc. Do not load the whole repo context by default.

## Skill Router

- UI planning: `.github\skills\ips-ui-plan-stage\SKILL.md`
- IPS/HSD consult/extract: `.github\skills\ips-consult-flow\SKILL.md`
- IPS/HSD debug/repro: `.github\skills\ips-hsd-repro-flow\SKILL.md`
- BHS hardware flow: `.github\skills\bhs-hardware-flow\SKILL.md`
- PS/PY command templates: `.github\skills\common-ps-py-commands\SKILL.md`
- BHS RAS, hang/MCE, performance/power, or Oak Stream collateral reference:
  `docs\bhs_platform_reference_knowledge.md`

## Core Safety

- No secrets.
- Consult/extract means no hardware actions.
- Debug/repro means flash must pass before boot capture.
- Prefer scripts/templates in `scripts\` and `common-ps-py-commands`.
