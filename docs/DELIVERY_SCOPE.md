# Handover distribution scope

Date: 2026-09-21. Source: the maintained working tree based on commit `48ceb39`,
including local changes present at handover preparation time.

This branch is a new root snapshot. It contains no parents from the original Git
history and does not remove anything from the original workspace or `main`.
The existing repository's old branches/history are not sanitized by this delivery.
Any cleanup of those branches requires a separate administrator-approved process.

## Included

- All top-level core Python and PowerShell scripts and existing UI tests.
- The six core planning, consult, reproduction, automatic Query, hardware and
  common-command skills.
- Portable document-generation, design, web-testing and skill-authoring helpers,
  with their bundled license files retained.
- Portable configuration templates, an explicitly non-operational machine
  inventory example, and fresh deployment guidance.
- The Chinese Markdown and Word handover documents, copied identically from
  the local delivery.

Generic utilities may have optional dependencies not needed by the core UI.
Their inclusion is not a claim that every optional helper has been deployed.

## Excluded

- `learningfile`, internal platform collateral and register/reference datasets.
- Actual lab inventories, machine profiles, BKC mappings, customer records and
  historical audit/measurement material.
- Local runtime profiles, `out`, `inbox`, logs, databases, user authentication
  state, private keys and vendor binaries/images.
- Domain-specific extended skills and custom agents that depend on internal
  collateral or were not approved as part of the portable core distribution.
- The original commit history.

The excluded source files remain intact in the original local project. Authorized
successors must obtain them separately through company-controlled channels.
This is the complete **portable core** delivery, not an unfiltered copy of every
file on the development machine.

## Distribution-specific changes

Private lab IP examples were replaced with documentation-only `192.0.2.x`
addresses; lab names were replaced with generic labels. Actual device identifiers,
customer aliases and image names are not supplied as operational defaults.
Service API URLs in integration source are retained as interface definitions,
not as credentials or customer records.

The example inventory points to `configure-before-use.invalid` and cannot be
used for real hardware access. Populate ignored deployment files first.
The original worktree's operational settings were not changed.

The main handover describes the source system. Deployment instructions specific
to this sanitized branch are in `README.md` and take precedence for file inclusion
and initial inventory setup. References to excluded internal material are access
requests for an approved internal handover, not downloadable attachments.
