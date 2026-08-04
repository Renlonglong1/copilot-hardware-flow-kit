# BMC MCTP Info Dump Design

## Overview

This document describes the design of the `bmc-mctp-info-dump` skill packaged under `copilot/skills/bmc-mctp-info-dump/` in `plat-eng-ai-tools`.

The bundle exists to make BMC MCTP triage repeatable. It provides a fixed workflow for collecting routing-table information, deriving endpoint targets, and enriching those targets with endpoint-level control queries.

The bundle is intentionally self-contained. Its primary runtime entrypoint is `scripts/mctp_info_dump.py`.

## Goals

- Provide a repeatable workflow for BMC MCTP information dumps.
- Support two operator entry modes: raw payload decoding and remote collection over SSH.
- Preserve both raw bytes and decoded summaries in the output so parsing assumptions can be verified.
- Compare the requested destination EID with destination EID `11` during remote runs.
- Keep the workflow self-contained within the skill directory.

## Non-Goals

- General-purpose MCTP protocol coverage.
- A stable importable Python library.
- Structured output formats such as JSON.
- Concurrent endpoint querying.
- Secure credential management beyond the current SSH-based operational workflow.

## Package Layout

The bundle is packaged as a self-contained unit:

- `SKILL.md`
  - Declares when the skill should be used and defines the operator workflow.
- `scripts/mctp_info_dump.py`
  - Implements the packaged Python workflow.
- `scripts/run-mctp-debug.sh`
  - Thin shell wrapper that injects defaults and forwards CLI arguments to the packaged Python entrypoint.
- `references/usage.md`
  - Documents invocation patterns, expected output sections, and common failure symptoms.
- `references/design.md`
  - Describes the architecture, data flow, and maintenance considerations for the skill.

## User Interaction Contract

The skill defines a strict operator flow:

1. Decide whether the task is raw routing-table decoding or live remote collection.
2. If remote collection is needed, gather SSH host, user, and password first.
3. Confirm transport parameters such as destination EID, interface, source EID, and message type.
4. Run the packaged Python tool directly or via the helper shell wrapper.
5. Review output in a fixed order: routing commands, raw routing responses, decoded routing table, endpoint UUID data, endpoint version-support data, and supported message types.
6. For remote runs, compare the requested destination EID with destination EID `11`.

This contract matters because the skill is designed for diagnostic consistency rather than for flexible ad hoc exploration.

## Runtime Modes

### Raw Decode Mode

In raw mode, the user passes one or more `Get Routing Table` response payloads on the command line.

Behavior:

1. Parse CLI arguments and normalize payload input.
2. Decode the provided routing-table payloads.
3. Expand decoded routes into endpoint query targets.
4. Use the configured remote SSH target for follow-up endpoint queries.
5. Render a report for the requested destination EID only.

Important implication: raw mode avoids remote routing-table collection, but it does not become fully offline because endpoint enrichment still depends on live queries.

### Remote Collection Mode

In remote mode, the script collects routing-table pages directly from the BMC host over SSH.

Behavior:

1. Build `mctp_cmds` requests with the selected destination EID, interface, source EID, and message type.
2. Walk the routing table by repeatedly querying the current entry handle.
3. Stop when the next-entry handle is `0` or `0xff`.
4. Decode all collected pages into a single routing-table view.
5. Expand the routing table into endpoint query targets.
6. Query each endpoint for UUID, MCTP version support, and supported message types.
7. Render a report for the requested destination EID.
8. If the requested destination EID is not `11`, repeat the remote collection flow for destination EID `11`.

The automatic secondary-EID comparison is part of the skill's operational contract.

## Architecture

The Python implementation follows a linear script pipeline with small helper functions:

- constants and lookup tables
- immutable dataclasses for options, command results, targets, and endpoint rows
- CLI parsing and environment-default handling
- response decoders for MCTP control commands
- SSH transport helpers
- routing-table and endpoint query orchestration
- text report rendering
- a small `__main__` block that selects raw mode or remote mode

This keeps the tool easy to run and modify as a script, but decoding, transport, orchestration, and presentation are tightly coupled.

## Core Data Model

### `RemoteOptions`

Holds all parameters required to execute remote `mctp_cmds` calls:

- SSH host, user, password
- destination EID
- interface
- source EID
- message type
- routing-table command code
- starting entry handle

### `EndpointQueryTarget`

Represents a derived endpoint query target:

- `eid`
- `interface`
- `transport_binding`

Targets are deduplicated by `(eid, interface)`, which is required because the same EID can be reachable on more than one transport path.

### `EndpointUuidResult`

Despite its name, the endpoint result row stores more than UUID information:

- UUID command and response state
- UUID value or UUID error
- MCTP version-support command and raw response
- decoded supported versions or version-support error
- supported message types or message-type query error

The type name is somewhat misleading because the row represents a combined endpoint enrichment result.

## Decoding Pipeline

### Routing Table

`decode_get_routing_table_response()` parses one response page into:

- control header
- command code
- completion code
- next entry handle
- entry count
- decoded entries
- trailing undecoded bytes

`decode_get_routing_table_responses()` merges multiple pages into one aggregate result used for target expansion and rendering.

Each routing entry carries both display fields and hidden helper fields such as `_range`, `_starting_eid`, and `_transport_binding_id` so the decoding stage can feed later orchestration steps without reparsing formatted strings.

### Endpoint UUID

`decode_get_endpoint_uuid_response()` expects at least 19 bytes and extracts a 16-byte UUID starting at offset 3. Short responses are surfaced as `uuid response is too short`.

### MCTP Version Support

`decode_get_mctp_version_support_response()` interprets the response as:

- 3-byte control header
- 1-byte version count
- `N` four-byte version entries

Version bytes are decoded into values such as `1.0`, `1.1`, and `1.3.3`.

### Supported Message Types

`decode_get_supported_message_types_response()` interprets the response as:

- 3-byte control header
- 1-byte message-type count
- `N` message-type bytes

Known message types are mapped to readable names while preserving the raw code in the rendered string, for example `SPDM (0x05)`.

## Remote Transport Model

All live collection uses `sshpass` plus `ssh` to run `mctp_cmds` on the remote BMC.

Command construction is centralized in `build_mctp_command()` and follows this shape:

```text
mctp_cmds -d <dest_eid> -i <interface> -s <source_eid> <message_type> <command_code> [args...]
```

`run_remote_shell_command()` is the transport boundary. It captures stdout and stderr and raises a hard failure when the remote command exits non-zero.

The design intentionally treats the text line matching `MCTP Response:` as the parse boundary between remote command output and decoder input.

## Endpoint Expansion Rules

Routing-table entries are expanded into endpoint targets using the following rules:

- `range_size` is treated as at least `1`
- each EID in `[starting_eid, starting_eid + range_size)` becomes a target candidate
- transport binding `0x06` maps to interface `i3c`
- all other bindings currently map to `pcie`
- duplicate `(eid, interface)` targets are suppressed

This design is intentionally simple and operationally useful, but the interface mapping is a heuristic rather than a full transport-resolution model.

## Reporting Contract

For each destination report, the output is arranged in a stable diagnostic order:

1. `Destination EID <n> Output:`
2. Executed `Get Routing Table` commands when routing data was fetched remotely
3. Raw routing-table response payloads
4. A decoded routing-table grid
5. Executed `Get Endpoint UUID` commands
6. Executed `Get MCTP Version Support` commands
7. Raw endpoint UUID and version-support response lines
8. An endpoint table containing EID, interface, transport binding, UUID, supported MCTP versions, and supported message types

The reporting model favors operator traceability over compactness.

## Error Handling Model

The design splits failures into hard failures and soft failures.

### Hard Failures

These abort the current destination report:

- remote routing-table command failure
- malformed routing-table payloads
- repeated routing-table handle detection
- missing `MCTP Response` lines in routing-table command output

### Soft Failures

These are recorded per endpoint row so the rest of the report can still be generated:

- short or invalid UUID responses
- version-support query or decode failures
- supported-message-type query failures

This split is intentional: routing-table collection is foundational, while endpoint enrichment is best-effort.

## Defaults and Assumptions

The current implementation keeps remote SSH access explicit:

- SSH host: must be provided through CLI arguments or `MCTP_SSH_HOST`
- SSH user: must be provided through CLI arguments or `MCTP_SSH_USER`
- SSH password: must be provided through CLI arguments or `MCTP_SSH_PASSWORD`
- primary destination EID: `8`
- comparison destination EID: `11`
- default interface: `i3c`
- default source EID: `0`
- default message type: `0x81`

This keeps the bundle environment-neutral while preserving the bundled routing-table defaults.
