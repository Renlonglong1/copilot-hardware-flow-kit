# bmc-tpmi-debug skill

This directory is the `bmc-tpmi-debug` skill package for TPMI register access and TPMI workflow orchestration under `plat-eng-ai-tools/copilot/skills`. It parses TPMI-specific inputs and leaves final `peci_cmds` composition to `bmc-peci-debug`.

## Layout

- `SKILL.md`: skill metadata and instructions
- `references/`: longer-form reference material
- `scripts/`: helper scripts or command wrappers
- `install-skill.sh`: installs this skill into a workspace or user scope

## Runtime Rules

- The user must provide a docs-root path to the converted documents before the skill does substantive work.
- Command validation is optional. If validation requires BMC access, collect only non-secret details in chat and have the user type any required secret directly into the terminal prompt.
- `references/instruction.md` is the highest-priority guidance for the skill.
- Concrete execution steps live in `references/workflow.md`.
- Error follow-up summaries should be appended to `references/reflection.md`.

## Install

Install into a workspace:

```bash
./install-skill.sh /path/to/workspace
```

The workspace path must already exist.

Install for the current user:

```bash
./install-skill.sh --global
```

Overwrite an existing install:

```bash
./install-skill.sh --force --global
```

On Windows, run the script from Git Bash, MSYS2, Cygwin, or WSL.

## Installed Structure

The installer validates that these required files exist before copying:

- `SKILL.md`
- `README.md`
- `references/instruction.md`
- `references/workflow.md`
- `references/reflection.md`
- `scripts/README.md`