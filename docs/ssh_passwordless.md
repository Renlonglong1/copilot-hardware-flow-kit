# Approved SSH identity setup

For step-by-step new-PC setup, see sections 6.4 and 6.5 of
`SYSTEM_HANDOVER.zh-CN.md` (also included in its Word copy). They distinguish
non-SSH features from hardware access and cover client installation, personal
keys, agent setup, server-side public-key authorization, independently verified
host fingerprints, local configuration and the `SSH_OK` acceptance check.

Have the receiving user obtain their own approved SSH authorization. Do not copy
the departing user's private key or credentials. Populate `ssh.identityFile`
with a local path reference only and use an independently verified host-key alias
when required.

The hardware wrappers construct SSH arguments from the resolved local profile,
including batch mode, timeout and optional explicit identity. A bare `ssh`
command does not load that profile.

Use `scripts\Test-SshAccess.ps1 -ConfigPath <approved-profile>` and require
`SSH_OK` before hardware work. When host identity changes, stop and verify the
new fingerprint through the approved channel. Never use
`StrictHostKeyChecking=no` to bypass trust.
