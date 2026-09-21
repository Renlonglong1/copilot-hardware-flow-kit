# Local Runtime Profiles

Keep portable code, documentation, and templates in Git. Keep the configuration that
binds the kit to one Windows machine in `config\local\`, which is ignored by Git.

## Resolution Order

Hardware scripts resolve their configuration in this order:

1. Explicit `-ConfigPath`.
2. `COPILOT_HARDWARE_FLOW_CONFIG` environment variable.
3. `config\local\hardware-flow.json`.
4. `$HOME\copilot-hardware-flow-local\hardware-flow.json`.

The scripts fail before any hardware action if no usable profile is available.

The UI launcher uses `config\local\ips-copilot-ui.json` when present; otherwise it
uses the portable loopback-only template.

## This Machine

This deployed machine has local profiles for the validated lab-control-05 flow and LAN UI.
They are intentionally untracked. The hardware profile pins the target SSH identity
file and the already verified host-key alias, so the scripts do not rely on whichever
default key happens to exist on a developer PC.

Do not test this profile with a bare `ssh debug@<host>` command and treat an
authentication failure as a hardware-flow connectivity failure: direct OpenSSH does
not read `hardware-flow.json`. Use `.\scripts\Test-SshAccess.ps1`, which resolves the
local profile and passes its `identityFile` and `hostKeyAlias` to SSH. Continue only
when it reports `SSH_OK`.

MLC can run without a credential only when COM3 is already at a root shell. A cold
boot that reaches a login prompt requires an approved runtime secret mechanism; do
not add that credential to any profile.

## New Machine Setup

1. Copy `config\hardware-flow.template.json` to `config\local\hardware-flow.json`.
2. Populate only the target server, remote tool paths, serial ports, and optional
   local SSH key path. Do not put private-key content, passwords, tokens, or cookies
   in the profile.
3. Run `.\scripts\Test-SshAccess.ps1` and require `SSH_OK` before a hardware flow.
4. Copy `config\ips-copilot-ui.template.json` to
   `config\local\ips-copilot-ui.json` only when the UI must be reachable on the LAN;
   explicitly set its LAN host and report URL.

Existing `local\hardware-flow.json` and lab-inventory entries are validated lab
snapshots, not defaults for a newly deployed machine.
