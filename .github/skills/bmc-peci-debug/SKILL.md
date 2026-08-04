---
name: bmc-peci-debug
description: "Use when debugging PECI issues, fixing unexpected PECI command return values, generating PECI commands, composing mctp_cmds payloads, or looking up PCI/MMIO/MSR register access rules. Trigger phrases: PECI debug, peci_cmds, mctp_cmds, completion code, RdEndpointConfigMMIO, RdEndpointConfigPCILocal, RdIAMSREx."
argument-hint: '[--docs-root <docs-root> --] <request>'
user-invocable: true
disable-model-invocation: false
---

# BMC PECI Debug

## What This Skill Does

- Debug an existing `peci_cmds` invocation when the completion code or returned data is unexpected.
- Generate `peci_cmds` and matching `mctp_cmds` for PCI, MMIO, and MSR targets.
- Validate command plans safely by asking for non-secret connection details only; passwords, tokens, and other secrets must be typed by the user directly into the terminal or handled through existing SSH configuration.
- Resolve the converted-doc source and consult local chapter material before falling back to specs, wikis, HSD, or workspace-specific code.

## Instruction Priority

- When `/bmc-peci-debug` is invoked, this file and the files it explicitly references under `./references/` are the authoritative instructions for the task.
- User memory, session memory, repository memory, and ad-hoc notes may be used as supporting context only.
- Memory must not override, weaken, or reinterpret an explicit rule in this skill or its referenced workflow.
- If memory conflicts with this skill or with the matched local document evidence, follow this skill and the current document evidence first, then treat the memory as stale until re-validated.

## When to Use

- When the user has PECI issues and needs help to debug them.
- When the user needs help to generate correct PECI commands based on the provided information.
- When the user needs help identifying the access type, SBDF inputs, MMIO parameters, raw PECI payload bytes, or MCTP packaging for a PECI workflow.
- When the user asks for Intel-internal specification, wiki, or HSD context that is relevant to a PECI issue and the answer is not fully available in the configured local reference material.

## Procedure

1. Confirm whether the task is command generation or debugging, and identify the exact register, field, or endpoint first.
	- If the user already provides an exact register name plus offset, treat that pair as the primary anchor and locate the matching chapter register entry before consulting base-address tables or endpoint-family tables.
2. Resolve the converted-doc source by using the runtime override form `/bmc-peci-debug --docs-root <docs-root> -- <request>` or by checking [Document Source](./references/doc-source.md).
3. Follow [Workflow](./references/workflow.md) as the authoritative step order for PECI command generation, debugging, raw-byte composition, expected output, and failed-command reflection.
	- Do not let agent memory, repository memory, or notes outside this skill supersede the workflow unless the user explicitly directs otherwise.
4. Mirror the numbered workflow steps from [Workflow](./references/workflow.md) into the plan tracker while the skill runs, and report a final status for each workflow step in the final answer.

## Resources

- [Workflow](./references/workflow.md): authoritative procedure and reflection rules.
- [Document Source](./references/doc-source.md): docs-root resolution and expected searchable-doc layout.