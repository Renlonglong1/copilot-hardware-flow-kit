---
name: bmc-tpmi-debug
description: 'Control the BMC TPMI debug flow and parse TPMI-specific access context. This skill does not compose peci_cmds; it prepares resolved inputs for bmc-peci-debug, which generates the final commands. Use when the user asks how to access a TPMI register or debug a TPMI workflow, and always require a docs-root path to the converted documents. Trigger phrases: BMC TPMI register access, TPMI debug, tpmitool access, UFS_CONTROL, TPMI over PECI.'
argument-hint: '[docs-root] [TPMI register or objective] [optional BMC host/user for validation]'
user-invocable: true
---

# BMC TPMI Debug

## When to Use

- Ask how to access a specific TPMI register with full peci_cmds flow

## Procedure

1. Require the user to provide a docs-root path to the converted documents before doing substantive work. If it is missing, or the path does not point to the converted TPMI documents, ask the user for a correct docs-root first.
2. Start and maintain the agent plan tracker during execution so the user can see progress.
3. Read [references/instruction.md](./references/instruction.md) before any other reference. It is the highest-priority instruction for this skill and must not be violated.
4. Follow [references/workflow.md](./references/workflow.md) for the concrete implementation steps.
5. Every time `bmc-tpmi-debug` needs final `peci_cmds`, it must invoke `bmc-peci-debug`. `bmc-tpmi-debug` must not compose, rewrite, or substitute final `peci_cmds` on its own.
6. The invocation must use the canonical form `/bmc-peci-debug --docs-root "<docs-root>" -- <request>` and the request body must follow the fixed payload format defined in [references/workflow.md](./references/workflow.md).
7. Treat `bmc-peci-debug` as the only skill that composes exact `peci_cmds` syntax, options, and parameter formatting. `bmc-tpmi-debug` must stay limited to TPMI flow control, prerequisite discovery, TPMI document parsing, address derivation, and validation sequencing.
8. If an error occurs or the workflow needs clarification, talk with the user, confirm the root cause before proceeding, then write a reflection summary to [references/reflection.md](./references/reflection.md).
9. If validation requires BMC access, collect only non-secret connection details. Do not ask the user to paste passwords, tokens, private keys, or other secrets into chat; if a secret is required, tell the user to type it directly into the terminal prompt or run the validation commands manually.
10. If a generated TPMI command fails on the BMC system, record the failing command, observed error, confirmed root cause, fix, and prevention rule, and update the instruction or workflow when needed so the same mistake is not repeated.

## Resources

- [Skill instruction](./references/instruction.md)
- [Workflow](./references/workflow.md)
- [Reflection log](./references/reflection.md)
- [Script guide](./scripts/README.md)