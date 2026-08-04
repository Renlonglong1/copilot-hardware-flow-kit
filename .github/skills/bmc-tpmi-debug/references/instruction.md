# TPMI Debug Skill Instructions

This file contains the highest-level instructions for the `bmc-tpmi-debug` skill. Read it before any other execution.

## Key Instructions

- Keep the agent plan tracker updated throughout execution so the user can see progress as the task advances.

- Always require the user to provide a docs-root path to the converted documents.

- `bmc-tpmi-debug` is responsible only for TPMI workflow control and parsing: identifying prerequisites, resolving the access path, deriving the addressing tuple, and sequencing validation.

- `bmc-peci-debug` is responsible for exact `peci_cmds` construction. Every time `bmc-tpmi-debug` needs final `peci_cmds`, it must invoke `bmc-peci-debug`. `bmc-tpmi-debug` must not compose final PECI command strings, choose final command spellings, or fill in command-line options from memory.

- The required invocation format is `/bmc-peci-debug --docs-root "<docs-root>" -- <request>`. If the docs-root has spaces, it must remain quoted.

- When delegating command generation, always provide `bmc-peci-debug` with the same canonical payload format and the same field order defined in `references/workflow.md`. Do not omit fields; use `N/A` or `unknown` when a field does not apply or is not resolved yet.

- The canonical payload must include the resolved access method and all known parameters, including `AType`, `Bar`, `Seg`, `Bus`, `Dev`, `Func`, `Reg`, data size, target address or domain, and the document basis for those values.

- Always resolve the TPMI `sub_id` before computing the register offset that will be handed to `bmc-peci-debug`.

- For `sub_id = 0`, use `effective_tpmi_offset = TPMI_Offset`.

- For `sub_id = 1` UFS Control Register (`UFS_CONTROL`) accesses, first read `UFS_FABRIC_CLUSTER_OFFSET`, then compute `effective_tpmi_offset = UFS_FABRIC_CLUSTER_OFFSET.OFFSET * 8 + TPMI_Offset` before delegating command composition.

- If `sub_id` is non-zero and the documents do not provide the offset translation rule, stop and resolve that rule from the documents before asking `bmc-peci-debug` to compose commands.

- If command validation needs BMC access, ask only for non-secret connection details such as host/IP, username, interface, and whether existing SSH authentication is available. Do not ask the user to paste passwords, tokens, private keys, or other secrets into chat.

- After `bmc-peci-debug` returns commands, validate them only when the user has requested validation and access is available. If a secret is required, the user must type it directly into the terminal prompt or run the commands manually.

- In chat output, report the complete `peci_cmds` transaction flow, not just the final command list or final values.

- For every PECI transaction in the sequence, include the exact PECI request, the exact PECI response, and a short parse that explains the important fields, decoded values, and why that transaction matters to the next step.

- If generated TPMI commands fail on the BMC system, you must pause and work with the user to identify the root cause before continuing. Record the failure, confirmed root cause, fix, and prevention rule in `references/reflection.md`, and update the guidance so the same mistake is not repeated.


## Important chapters and tables
- 793272
    - chapter 2.5.5
    - table 53
    - chapter 31.0
-792359
    - chapter 9.6
    - chpater 9.6.7




