# Development and Deployment Contract

This document is for Copilot sessions running on the developer's personal computer.
Its purpose is to keep the repository portable: development changes are committed
once, while each deployment machine supplies only its own local runtime profile.

## Non-Negotiable Boundary

| Store in Git | Store only on the deployment machine |
| --- | --- |
| Scripts, reusable skills, tests, templates, schema validation, and generic documentation | SSH private keys, passwords, tokens, Kerberos material, `known_hosts`, machine-specific paths, lab IPs used only by that deployment, and raw customer logs |
| Portable templates under `config\` | Runtime profiles under `config\local\` or `$HOME\copilot-hardware-flow-local\` |
| Validated lab snapshots, clearly labeled as snapshots | The active target selection and SSH identity used to operate hardware |

Never add sensitive material to a script, Markdown file, tracked JSON file, test
fixture, command history, or commit.

## Runtime Configuration Contract

Core scripts resolve the hardware profile in this order:

1. Explicit `-ConfigPath`.
2. `COPILOT_HARDWARE_FLOW_CONFIG`.
3. `config\local\hardware-flow.json`.
4. `$HOME\copilot-hardware-flow-local\hardware-flow.json`.

No profile must result in a clear failure before SSH, power, flash, serial, or MLC
actions. A script must not silently fall back to a historical lab machine.

The local hardware profile owns:

- SSH target, optional local identity-file path, and verified host-key alias.
- Remote tool, image, log, serial-port, and platform paths.
- Hardware-flow timing and device-specific validation signals.

The local UI profile, `config\local\ips-copilot-ui.json`, owns only deployment UI
settings such as LAN binding and report URL. The tracked UI template remains
loopback-only.

## Rules for New Code

1. **Inject configuration.** Add a field to `config\hardware-flow.template.json`
   when code needs a new machine-dependent value. Read it from the resolved profile;
   do not hardcode a path, IP, user name, or port.
2. **Keep templates safe.** Templates use placeholders or portable defaults. They
   must not contain a private key path that only works on one developer PC, a
   password, token, cookie, or unverified lab endpoint.
3. **Validate early.** Validate required configuration and local prerequisites before
   an irreversible action. Report the missing field or file precisely.
4. **Preserve explicit overrides.** A caller-provided `-ConfigPath` always takes
   priority over defaults.
5. **Do not bypass SSH trust.** Use a configured identity file and verified
   host-key alias. Do not add `StrictHostKeyChecking=no`.
6. **Separate snapshots from defaults.** Historical `dbgsh*` configurations and
   documentation are evidence of prior validation, not implicit deployment defaults.
7. **Keep secrets external.** A command requiring a credential must use an approved
   runtime secret mechanism or fail clearly; it must never introduce a default
   credential in source.

## Private-PC Development Workflow

1. Start from a clean branch and modify only portable code, templates, and docs.
2. Add or update a template field and its validation when introducing a
   machine-dependent behavior.
3. Test syntax and non-hardware behavior locally.
4. Review the diff for machine-specific values and secrets before committing.
5. Push the reviewed code; do not copy private runtime profiles into Git.

Useful review commands:

```powershell
git status --short
git diff --check
git diff
```

## Deployment-Machine Workflow

After pulling the new code, adjust only the ignored local profiles:

```powershell
New-Item -ItemType Directory -Path .\config\local -Force
Copy-Item .\config\hardware-flow.template.json .\config\local\hardware-flow.json
Copy-Item .\config\ips-copilot-ui.template.json .\config\local\ips-copilot-ui.json
```

Set the deployment-specific values, then perform the non-destructive connection
check before a hardware flow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1
```

Require `SSH_OK`. Do not proceed to power control, flashing, serial capture, or MLC
if it fails. Do not substitute a bare `ssh debug@<host>` result for this check:
direct OpenSSH does not load the runtime profile's target-specific identity or
host-key alias.

## Change Review Checklist

Before merging development changes, verify:

- [ ] No new hardcoded developer-home path, deployment IP, password, token, or SSH
      key appears in tracked files.
- [ ] New machine-dependent values are represented in a tracked template and read
      from the resolved local profile.
- [ ] Scripts fail before hardware actions when configuration is absent or invalid.
- [ ] Local profiles remain ignored by Git.
- [ ] Documentation states whether an example is a portable template or a validated
      lab snapshot.
- [ ] SSH examples retain host-key verification.

## Related Documents

- `docs\local_runtime_profiles.md`: profile locations and resolution behavior.
- `docs\ssh_passwordless.md`: SSH identity and host-key troubleshooting.
- `docs\migration_to_new_copilot.md`: new-machine setup.
- `docs\git_usage_guide.md`: personal-development and deployment-server Git flow.
