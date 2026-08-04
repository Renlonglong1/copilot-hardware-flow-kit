# BMC MCTP Info Dump Reference

This bundle ships with its own Python entrypoint at `scripts/mctp_info_dump.py` so it can be shared without depending on a repo-root script.

## Running From This Repo

Run the packaged Python workflow directly from the `plat-eng-ai-tools` repo root:

```bash
python copilot/skills/bmc-mctp-info-dump/scripts/mctp_info_dump.py
```

Or use the bundled helper wrapper:

```bash
copilot/skills/bmc-mctp-info-dump/scripts/run-mctp-debug.sh
```

Run against a specific destination EID or interface:

```bash
python copilot/skills/bmc-mctp-info-dump/scripts/mctp_info_dump.py -d 8 -i i3c -s 0 -m 0x81 --endpoint-uuids --debug
```

The helper script accepts the same trailing arguments:

```bash
copilot/skills/bmc-mctp-info-dump/scripts/run-mctp-debug.sh -d 8 -i i3c
```

## Remote Execution

Set remote connection values through environment variables:

```bash
MCTP_SSH_HOST=bmc.example.com \
MCTP_SSH_USER=root \
MCTP_SSH_PASSWORD='your-password' \
MCTP_DEST_EID=8 \
python copilot/skills/bmc-mctp-info-dump/scripts/mctp_info_dump.py
```

## Raw Payload Decoding

Decode one or more Get Routing Table payloads without remote routing-table fetches:

```bash
python copilot/skills/bmc-mctp-info-dump/scripts/mctp_info_dump.py "01 0a 00 ff 01 01 08 06 06 30 01 22"
```

Pass multiple payloads as separate arguments or newline-separated input strings.

## Current Output Structure

The script prints, for each destination report:

1. The destination label, for example `Destination EID 8 Output:`.
2. Executed Get Routing Table commands.
3. Raw routing-table response data.
4. The decoded routing-table table.
5. Get Endpoint UUID commands.
6. Get MCTP Version Support commands.
7. Raw endpoint UUID and version-support response data.
8. The endpoint table, including supported MCTP versions and supported message types with raw codes.

## Useful Symptoms

- `uuid response is too short`: the UUID command returned no usable 16-byte UUID payload.
- `MCTP Version Support response is truncated`: the version-support command returned an incomplete version-entry payload.
- `No MCTP Response line found in command output`: the remote command ran, but the script could not find a parseable `MCTP Response` line.
- `Detected repeated routing table handle`: the remote routing-table walk looped unexpectedly.

## Interpretation Tips

- Supported message types are shown as display name plus raw code, such as `MCTP Control (0x00)`.
- Interface selection for endpoint queries is derived from the transport binding: I3C entries use `i3c`, other bindings currently fall back to `pcie`.
- Routing-table entries are expanded to endpoint query targets across the full EID range.
- If the same EID is reachable on multiple interfaces, the script queries each EID/interface path separately and reports each result as its own row.
