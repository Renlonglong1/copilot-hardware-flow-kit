---
name: bmc-mctp-info-dump
description: "Dump a BMC MCTP routing table and related endpoint data over I3C or PCIe using the packaged mctp_info_dump.py workflow. Use when collecting EIDs, transport bindings, remote mctp_cmds output, routing table decode results, UUID failures, MCTP version support, or comparing destination EID 8 and 11."
argument-hint: "destination EID, interface, whether to decode raw payloads or run remote fetches, and any known SSH host, user, and password"
user-invocable: true
---

# BMC MCTP Info Dump

Use this skill for repeatable BMC MCTP information dumps driven by the packaged script `scripts/mctp_info_dump.py`.

## When to Use

- Decode raw Get Routing Table responses.
- Run remote MCTP debugging over SSH with `mctp_cmds`.
- Compare routing and UUID behavior for the configured destination EID and destination EID `11`.
- Inspect endpoint UUID failures such as `uuid response is too short`.
- Review supported message types, including raw codes like `MCTP Control (0x00)`, `PLDM (0x01)`, and `SPDM (0x05)`.
- Review MCTP version support for each discovered endpoint.

## Workflow

1. Decide whether the task is raw-payload decoding or remote execution.
2. If raw routing-table payloads are provided, decode them directly and do not ask for SSH details.
3. For remote execution, first check whether the SSH host, user, and password are already available from the user's request, earlier conversation context, or the relevant `MCTP_SSH_*` environment variables. Prompt only for values that are still missing. Offer `root` as the suggested user if the user wants a default, but require the password to be provided explicitly when it is missing.
4. After the connection details are complete, confirm the destination EID, interface, source EID, and MCTP message type.
5. Run `scripts/mctp_info_dump.py` directly, or use the helper script [run-mctp-debug.sh](./scripts/run-mctp-debug.sh). Use `--debug` to include executed commands and raw responses, and `--endpoint-uuids` to fetch and display endpoint UUID, version support, and supported message types.
6. Review the output in this order:
   - Decoded routing table entries (always shown)
   - Get Routing Table commands and raw responses (shown with `--debug`)
   - Get Endpoint UUID commands and raw UUID responses (shown with `--endpoint-uuids` and `--debug`)
   - Get MCTP Version Support commands and raw version-support responses (shown with `--endpoint-uuids` and `--debug`)
   - Endpoint UUID table with supported message types (shown with `--endpoint-uuids`)
7. If the remote run is used without raw payload inputs, compare the primary destination EID output with the extra destination EID `11` output.

## Completion Checks

- Raw-decode mode finishes only after the routing-table payload has been decoded or the decode failure is reported clearly.
- Remote mode finishes only after all missing SSH fields have been collected, the command has run, and the output review covers routing data. If `--endpoint-uuids` was used, also review UUID data, version-support data, and supported message types.
- If the script reports failures such as truncated UUID or version-support responses, include those symptoms explicitly instead of treating the run as a silent success.
- When remote routing-table fetches are used, confirm whether the comparison against destination EID `11` was produced or explain why it was skipped.

## Notes

- The packaged script at `scripts/mctp_info_dump.py` decodes routing-table payloads, queries endpoint UUIDs, queries MCTP version support, and queries supported message types.
- For remote runs, reuse SSH host, user, and password when they are already present in the request or environment, and ask only for the missing fields.
- The packaged workflow can read remote connection values from `MCTP_SSH_HOST`, `MCTP_SSH_USER`, and `MCTP_SSH_PASSWORD`.
- In remote mode, the current script runs once for the requested destination EID and once more for destination EID `11`.
- If raw routing-table responses are passed on the command line, the script decodes those responses directly and does not perform the extra remote routing-table fetch for EID `11`.

## Packaged Assets

- [Packaged Python script](./scripts/mctp_info_dump.py)
- [Helper script](./scripts/run-mctp-debug.sh)
- [Design](./references/design.md)
- [Usage and examples](./references/usage.md)