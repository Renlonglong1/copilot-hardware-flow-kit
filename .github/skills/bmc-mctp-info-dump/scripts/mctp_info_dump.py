from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, replace


ROUTING_ENTRY_TYPE_NAMES = {
    0x00: "Single EP",
    0x01: "Single EP Br",
    0x02: "Bridge",
    0x03: "Additional EPs",
}

ASSIGNMENT_TYPE_NAMES = {
    0: "dynamically configured",
    1: "statically configured",
}

TRANSPORT_BINDING_NAMES = {
    0x00: "Reserved",
    0x01: "MCTP over SMBus/I2C (DSP0237)",
    0x02: "MCTP over PCIe VDM (DSP0238)",
    0x03: "MCTP over USB",
    0x04: "MCTP over KCS",
    0x05: "MCTP over Serial",
    0x06: "MCTP over I3C (DSP0233)",
    0x07: "MCTP over MMBI",
    0x08: "MCTP over PCC",
    0x09: "MCTP over UCIe",
    0xFF: "Vendor defined (requirements in DSP0236)",
}

MESSAGE_TYPE_NAMES = {
    0x00: "MCTP Control",
    0x01: "PLDM",
    0x02: "NC-SI over MCTP",
    0x03: "Ethernet over MCTP",
    0x04: "NVMe Management Messages",
    0x05: "SPDM",
    0x06: "Secured Messages",
    0x7E: "Vendor Defined PCI",
    0x7F: "Vendor Defined IANA",
}

MEDIA_TYPE_NAMES = {
    0x00: {0x00: "Unspecified"},
    0x02: {
        0x00: "Unspecified",
        0x01: "PCIe revision 5.x compatible or CXL 1.x / 2.x compatible",
    },
    0x06: {
        0x00: "Unspecified",
        0x03: "I3C Basic compatible",
        0x30: "I3C Basic",
    },
    0xFF: {
        0x00: "Unspecified",
    },
}

DEFAULT_SSH_HOST = ""
DEFAULT_SSH_USER = ""
DEFAULT_SSH_PASSWORD = ""
DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_SSH_COMMAND_TIMEOUT_SECONDS = 30
DEFAULT_SOCKET0_PRIMARY_IMH_DEST_EID = 8
DEFAULT_SECONDARY_DEST_EID = 11
DEFAULT_MCTP_INTERFACE = "i3c"
DEFAULT_MCTP_SOURCE_EID = 0
DEFAULT_MCTP_MESSAGE_TYPE = "0x81"
DEFAULT_GET_ROUTING_TABLE_COMMAND_CODE = "0xa"
DEFAULT_UUID_COMMAND_CODE = "0x3"
DEFAULT_GET_MCTP_VERSION_SUPPORT_COMMAND_CODE = "0x4"
DEFAULT_SUPPORTED_MESSAGE_TYPES_COMMAND_CODE = "0x5"
DEFAULT_CONTROL_MESSAGE_TYPE_ID = 0x00
LAST_ENTRY_HANDLE = 0xFF
I3C_TRANSPORT_BINDING_ID = 0x06
UUID_RESPONSE_TOO_SHORT_ERROR = "uuid response is too short"
MCTP_VERSION_ENTRY_SIZE = 4

RESPONSE_LINE_PATTERN = re.compile(r"MCTP Response\s*:\s*(.+)")


@dataclass(frozen=True)
class RemoteOptions:
    host: str
    user: str
    password: str
    ssh_connect_timeout_seconds: int
    ssh_command_timeout_seconds: int
    dest_eid: int
    interface: str
    source_eid: int
    message_type: str
    command_code: str
    start_entry_handle: int
    debug: bool
    show_endpoint_uuids: bool


@dataclass(frozen=True)
class EndpointQueryTarget:
    eid: int
    interface: str
    transport_binding: str


@dataclass(frozen=True)
class CommandResult:
    command: str
    output: str


class RemoteConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EndpointUuidResult:
    eid: int
    interface: str
    transport_binding: str
    command: str
    version_support_command: str
    uuid_value: str | None
    raw_response: str | None
    error: str | None
    version_support_response: str | None
    supported_versions: list[str] | None
    version_support_error: str | None
    supported_message_types: list[str] | None
    supported_message_types_error: str | None


def parse_hex_bytes(hex_string: str) -> bytes:
    return bytes.fromhex(hex_string)


def parse_numeric_value(raw_value: str) -> int:
    value = raw_value.strip().lower()
    if value.startswith("0x"):
        return int(value, 16)
    return int(value, 10)


def get_env_value(name: str, default: str) -> str:
    return os.environ.get(name, default)


def get_env_numeric_value(name: str, default: int) -> int:
    return parse_numeric_value(os.environ.get(name, str(default)))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Decode MCTP Get Routing Table responses from raw payloads or fetch them "
            "from a remote target over SSH."
        )
    )
    parser.add_argument(
        "responses",
        nargs="*",
        help="Raw Get Routing Table response payloads. If omitted, the script fetches responses remotely.",
    )
    parser.add_argument(
        "-H",
        "--host",
        default=get_env_value("MCTP_SSH_HOST", DEFAULT_SSH_HOST),
        help="SSH host for remote fetches.",
    )
    parser.add_argument(
        "-u",
        "--user",
        default=get_env_value("MCTP_SSH_USER", DEFAULT_SSH_USER),
        help="SSH username for remote fetches.",
    )
    parser.add_argument(
        "-p",
        "--password",
        default=get_env_value("MCTP_SSH_PASSWORD", DEFAULT_SSH_PASSWORD),
        help="SSH password for remote fetches.",
    )
    parser.add_argument(
        "-d",
        "--dest-eid",
        type=parse_numeric_value,
        default=get_env_numeric_value("MCTP_DEST_EID", DEFAULT_SOCKET0_PRIMARY_IMH_DEST_EID),
        help="Destination EID passed to mctp_cmds.",
    )
    parser.add_argument(
        "--ssh-connect-timeout",
        type=parse_numeric_value,
        default=get_env_numeric_value(
            "MCTP_SSH_CONNECT_TIMEOUT",
            DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS,
        ),
        help="SSH connect timeout in seconds for remote fetches.",
    )
    parser.add_argument(
        "--ssh-command-timeout",
        type=parse_numeric_value,
        default=get_env_numeric_value(
            "MCTP_SSH_COMMAND_TIMEOUT",
            DEFAULT_SSH_COMMAND_TIMEOUT_SECONDS,
        ),
        help="Overall timeout in seconds for remote command execution.",
    )
    parser.add_argument(
        "-i",
        "--interface",
        default=get_env_value("MCTP_INTERFACE", DEFAULT_MCTP_INTERFACE),
        help="Transport interface passed to mctp_cmds.",
    )
    parser.add_argument(
        "-s",
        "--source-eid",
        type=parse_numeric_value,
        default=get_env_numeric_value("MCTP_SOURCE_EID", DEFAULT_MCTP_SOURCE_EID),
        help="Source EID passed to mctp_cmds.",
    )
    parser.add_argument(
        "-m",
        "--message-type",
        default=get_env_value("MCTP_MESSAGE_TYPE", DEFAULT_MCTP_MESSAGE_TYPE),
        help="MCTP message type argument passed to mctp_cmds.",
    )
    parser.add_argument(
        "-c",
        "--command-code",
        default=get_env_value("MCTP_COMMAND_CODE", DEFAULT_GET_ROUTING_TABLE_COMMAND_CODE),
        help="MCTP command code argument passed to mctp_cmds.",
    )
    parser.add_argument(
        "-e",
        "--start-entry-handle",
        type=parse_numeric_value,
        default=0,
        help="Initial routing table handle to request during remote fetches.",
    )
    parser.add_argument(
        "-g",
        "--debug",
        action="store_true",
        help="Show executed commands and raw MCTP responses.",
    )
    parser.add_argument(
        "-U",
        "--endpoint-uuids",
        action="store_true",
        help="Include the Endpoint UUIDs table and fetch endpoint UUID details.",
    )
    return parser


def parse_arguments(argv: list[str]) -> tuple[list[str], RemoteOptions]:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    responses = normalize_response_inputs(args.responses)
    if not responses:
        missing_remote_arguments = [
            option_name
            for option_name, value in (
                ("--host", args.host),
                ("--user", args.user),
                ("--password", args.password),
            )
            if not value.strip()
        ]
        if missing_remote_arguments:
            parser.error(
                "remote fetches require "
                + ", ".join(missing_remote_arguments)
                + " (or the corresponding MCTP_SSH_* environment variables)"
            )
    options = RemoteOptions(
        host=args.host,
        user=args.user,
        password=args.password,
        ssh_connect_timeout_seconds=args.ssh_connect_timeout,
        ssh_command_timeout_seconds=args.ssh_command_timeout,
        dest_eid=args.dest_eid,
        interface=args.interface,
        source_eid=args.source_eid,
        message_type=args.message_type,
        command_code=args.command_code,
        start_entry_handle=args.start_entry_handle,
        debug=args.debug,
        show_endpoint_uuids=args.endpoint_uuids,
    )
    return responses, options


def decode_entry_type(entry_type: int) -> str:
    route_type = (entry_type >> 6) & 0x03
    assignment_type = (entry_type >> 5) & 0x01
    port_number = entry_type & 0x1F

    route_name = ROUTING_ENTRY_TYPE_NAMES.get(route_type, f"Unknown type 0x{route_type:02x}")
    assignment_name = ASSIGNMENT_TYPE_NAMES.get(
        assignment_type,
        f"unknown assignment 0x{assignment_type:02x}",
    )
    return f"{route_name}, {port_number}, {assignment_name}"


def get_route_type(entry_type: int) -> int:
    return (entry_type >> 6) & 0x03


def decode_transport_binding(binding_id: int) -> str:
    return TRANSPORT_BINDING_NAMES.get(binding_id, f"Unknown binding 0x{binding_id:02x}")


def decode_media_type(binding_id: int, media_id: int) -> str:
    return MEDIA_TYPE_NAMES.get(binding_id, {}).get(media_id, f"Unknown media 0x{media_id:02x}")


def decode_message_type(message_type_id: int) -> str:
    return MESSAGE_TYPE_NAMES.get(message_type_id, f"Unknown message type 0x{message_type_id:02x}")


def format_supported_message_type(message_type_id: int) -> str:
    return f"{decode_message_type(message_type_id)} (0x{message_type_id:02x})"


def format_eid(eid: int) -> str:
    return f"{eid} 0x{eid:02x}"


def format_physical_address(address: bytes) -> list[str]:
    return [f"0x{byte:x}" for byte in address]


def choose_interface_for_binding(binding_id: int) -> str:
    return "i3c" if binding_id == I3C_TRANSPORT_BINDING_ID else "pcie"


def build_mctp_command(
    dest_eid: int,
    interface: str,
    source_eid: int,
    message_type: str,
    command_code: str,
    *command_args: int,
) -> str:
    command_parts = [
        "mctp_cmds",
        "-d",
        str(dest_eid),
        "-i",
        interface,
        "-s",
        str(source_eid),
        message_type,
        command_code,
        *(str(arg) for arg in command_args),
    ]
    return " ".join(command_parts)


def decode_get_routing_table_response(hex_string: str) -> dict:
    data = parse_hex_bytes(hex_string)

    if len(data) < 5:
        raise ValueError("Response is too short")

    result = {
        "control_header": f"0x{data[0]:02x}",
        "command_code": f"0x{data[1]:02x}",
        "completion_code": f"0x{data[2]:02x}",
        "next_entry_handle": data[3],
        "entry_count": data[4],
        "entries": [],
    }

    offset = 5

    for index in range(result["entry_count"]):
        if offset + 6 > len(data):
            raise ValueError(f"Not enough data for routing table entry {index}")

        eid_range_size = data[offset]
        starting_eid = data[offset + 1]
        entry_type = data[offset + 2]
        physical_transport_binding_id = data[offset + 3]
        physical_media_type_id = data[offset + 4]
        physical_address_size = data[offset + 5]

        end = offset + 6 + physical_address_size
        if end > len(data):
            raise ValueError(f"Physical address overruns payload in entry {index}")

        physical_address = data[offset + 6:end]

        result["entries"].append(
            {
                "Range": eid_range_size,
                "Starting EID": format_eid(starting_eid),
                "Entry Type/Port Number": decode_entry_type(entry_type),
                "Physical Transport Binding Identifier": decode_transport_binding(
                    physical_transport_binding_id
                ),
                "Physical Media Type Identifier": decode_media_type(
                    physical_transport_binding_id,
                    physical_media_type_id,
                ),
                "Addr Size": physical_address_size,
                "Physical Address": str(format_physical_address(physical_address)),
                "_range": eid_range_size,
                "_starting_eid": starting_eid,
                "_route_type": get_route_type(entry_type),
                "_transport_binding_id": physical_transport_binding_id,
            }
        )

        offset = end

    result["remaining_bytes"] = " ".join(f"{byte:02x}" for byte in data[offset:])
    return result


def decode_get_endpoint_uuid_response(hex_string: str) -> dict:
    data = parse_hex_bytes(hex_string)

    if len(data) < 19:
        raise ValueError(UUID_RESPONSE_TOO_SHORT_ERROR)

    uuid_bytes = data[3:19]
    if len(uuid_bytes) != 16:
        raise ValueError("UUID response does not contain a 16-byte UUID")

    return {
        "control_header": f"0x{data[0]:02x}",
        "command_code": f"0x{data[1]:02x}",
        "completion_code": f"0x{data[2]:02x}",
        "uuid": str(uuid.UUID(bytes=bytes(uuid_bytes))),
        "remaining_bytes": " ".join(f"{byte:02x}" for byte in data[19:]),
    }


def decode_get_supported_message_types_response(hex_string: str) -> dict:
    data = parse_hex_bytes(hex_string)

    if len(data) < 4:
        raise ValueError("Supported Message Types response is too short")

    message_type_count = data[3]
    end = 4 + message_type_count
    if end > len(data):
        raise ValueError("Supported Message Types response is truncated")

    return {
        "control_header": f"0x{data[0]:02x}",
        "command_code": f"0x{data[1]:02x}",
        "completion_code": f"0x{data[2]:02x}",
        "message_type_count": message_type_count,
        "supported_message_types": [
            format_supported_message_type(message_type_id) for message_type_id in data[4:end]
        ],
        "remaining_bytes": " ".join(f"{byte:02x}" for byte in data[end:]),
    }


def decode_mctp_version_component(encoded_byte: int, component_name: str) -> int:
    if (encoded_byte >> 4) != 0x0F:
        raise ValueError(
            f"MCTP version {component_name} byte has unsupported encoding 0x{encoded_byte:02x}"
        )
    return encoded_byte & 0x0F


def format_mctp_version_entry(version_entry: bytes) -> str:
    if len(version_entry) != MCTP_VERSION_ENTRY_SIZE:
        raise ValueError("MCTP version entry must contain four bytes")

    major_version = decode_mctp_version_component(version_entry[0], "major")
    minor_version = decode_mctp_version_component(version_entry[1], "minor")
    version_parts = [str(major_version), str(minor_version)]

    update_version_byte = version_entry[2]
    if update_version_byte != 0xFF:
        update_version = decode_mctp_version_component(update_version_byte, "update")
        version_parts.append(str(update_version))

    version = ".".join(version_parts)
    alpha_byte = version_entry[3]
    if alpha_byte != 0x00:
        version = f"{version} alpha 0x{alpha_byte:02x}"

    return version


def decode_get_mctp_version_support_response(hex_string: str) -> dict:
    data = parse_hex_bytes(hex_string)

    if len(data) < 4:
        raise ValueError("MCTP Version Support response is too short")

    version_count = data[3]
    end = 4 + version_count * MCTP_VERSION_ENTRY_SIZE
    if end > len(data):
        raise ValueError("MCTP Version Support response is truncated")

    return {
        "control_header": f"0x{data[0]:02x}",
        "command_code": f"0x{data[1]:02x}",
        "completion_code": f"0x{data[2]:02x}",
        "version_count": version_count,
        "supported_versions": [
            format_mctp_version_entry(data[offset : offset + MCTP_VERSION_ENTRY_SIZE])
            for offset in range(4, end, MCTP_VERSION_ENTRY_SIZE)
        ],
        "remaining_bytes": " ".join(f"{byte:02x}" for byte in data[end:]),
    }


def extract_mctp_responses(command_output: str) -> list[str]:
    responses: list[str] = []
    for line in command_output.splitlines():
        match = RESPONSE_LINE_PATTERN.search(line)
        if match:
            responses.append(match.group(1).strip())

    if not responses:
        raise ValueError("No MCTP Response line found in command output")

    return responses


def normalize_response_inputs(raw_inputs: list[str]) -> list[str]:
    responses: list[str] = []
    for raw_input in raw_inputs:
        responses.extend(line.strip() for line in raw_input.splitlines() if line.strip())
    return responses


def decode_get_routing_table_responses(hex_strings: list[str]) -> dict:
    if not hex_strings:
        raise ValueError("At least one response is required")

    decoded_responses = [decode_get_routing_table_response(hex_string) for hex_string in hex_strings]
    first_response = decoded_responses[0]

    return {
        "control_header": first_response["control_header"],
        "command_code": first_response["command_code"],
        "completion_code": first_response["completion_code"],
        "response_count": len(decoded_responses),
        "next_entry_handle": decoded_responses[-1]["next_entry_handle"],
        "entry_count": sum(response["entry_count"] for response in decoded_responses),
        "entries": [entry for response in decoded_responses for entry in response["entries"]],
        "remaining_bytes": [
            response["remaining_bytes"]
            for response in decoded_responses
            if response["remaining_bytes"]
        ],
        "responses": decoded_responses,
    }


def run_remote_shell_command(options: RemoteOptions, remote_command: str) -> str:
    command = [
        "sshpass",
        "-p",
        options.password,
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        f"ConnectTimeout={options.ssh_connect_timeout_seconds}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        f"{options.user}@{options.host}",
        remote_command,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=options.ssh_command_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RemoteConnectionError(
            f"Remote command timed out after {options.ssh_command_timeout_seconds} seconds"
        ) from error

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        details = stderr or stdout or f"exit code {completed.returncode}"
        if any(
            marker in details.lower()
            for marker in (
                "connection timed out",
                "no route to host",
                "connection refused",
                "network is unreachable",
                "could not resolve hostname",
            )
        ):
            raise RemoteConnectionError(f"Remote command failed: {details}")
        raise RuntimeError(f"Remote command failed: {details}")

    return completed.stdout


def run_remote_mctp_command(options: RemoteOptions, entry_handle: int) -> CommandResult:
    remote_command = build_mctp_command(
        options.dest_eid,
        options.interface,
        options.source_eid,
        options.message_type,
        options.command_code,
        entry_handle,
    )
    return CommandResult(command=remote_command, output=run_remote_shell_command(options, remote_command))


def fetch_endpoint_control_response(
    target: EndpointQueryTarget,
    options: RemoteOptions,
    command_code: str,
    *command_args: int,
) -> tuple[str | None, str | None, str]:
    remote_command = build_mctp_command(
        target.eid,
        target.interface,
        options.source_eid,
        options.message_type,
        command_code,
        *command_args,
    )

    try:
        command_output = run_remote_shell_command(options, remote_command)
        return extract_mctp_responses(command_output)[-1], None, remote_command
    except (RuntimeError, ValueError) as error:
        return None, str(error), remote_command


def fetch_mctp_version_support(
    target: EndpointQueryTarget,
    options: RemoteOptions,
) -> tuple[str | None, list[str] | None, str | None, str]:
    response, error, remote_command = fetch_endpoint_control_response(
        target,
        options,
        DEFAULT_GET_MCTP_VERSION_SUPPORT_COMMAND_CODE,
        DEFAULT_CONTROL_MESSAGE_TYPE_ID,
    )
    if response is None:
        return None, None, error or "no response captured", remote_command

    try:
        decoded = decode_get_mctp_version_support_response(response)
        return response, decoded["supported_versions"], None, remote_command
    except ValueError as decode_error:
        return response, None, str(decode_error), remote_command


def fetch_supported_message_types(
    target: EndpointQueryTarget,
    options: RemoteOptions,
) -> tuple[list[str] | None, str | None]:
    try:
        response, error, _ = fetch_endpoint_control_response(
            target,
            options,
            DEFAULT_SUPPORTED_MESSAGE_TYPES_COMMAND_CODE,
        )
        if response is None:
            return None, error or "no response captured"
        decoded = decode_get_supported_message_types_response(response)
        return decoded["supported_message_types"], None
    except ValueError as error:
        return None, str(error)


def fetch_remote_routing_table_responses(options: RemoteOptions) -> tuple[list[str], list[str]]:
    responses: list[str] = []
    commands: list[str] = []
    entry_handle = options.start_entry_handle
    seen_handles: set[int] = set()

    while True:
        if entry_handle in seen_handles:
            raise RuntimeError(f"Detected repeated routing table handle {entry_handle}")
        seen_handles.add(entry_handle)

        command_result = run_remote_mctp_command(options, entry_handle)
        commands.append(command_result.command)
        batch_responses = extract_mctp_responses(command_result.output)
        responses.extend(batch_responses)

        decoded_batch = decode_get_routing_table_response(batch_responses[-1])
        entry_handle = decoded_batch["next_entry_handle"]
        if entry_handle in {0, LAST_ENTRY_HANDLE}:
            return responses, commands


def build_endpoint_query_targets(entries: list[dict]) -> list[EndpointQueryTarget]:
    targets: list[EndpointQueryTarget] = []
    seen_targets: set[tuple[int, str]] = set()

    for entry in entries:
        range_size = max(int(entry["_range"]), 1)
        starting_eid = int(entry["_starting_eid"])
        binding_id = int(entry["_transport_binding_id"])
        interface = choose_interface_for_binding(binding_id)
        transport_binding = decode_transport_binding(binding_id)

        for eid in range(starting_eid, starting_eid + range_size):
            target_key = (eid, interface)
            if target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            targets.append(
                EndpointQueryTarget(
                    eid=eid,
                    interface=interface,
                    transport_binding=transport_binding,
                )
            )

    return targets


def fetch_remote_endpoint_uuids(
    entries: list[dict],
    options: RemoteOptions,
) -> tuple[list[EndpointUuidResult], list[str]]:
    results: list[EndpointUuidResult] = []
    commands: list[str] = []

    for target in build_endpoint_query_targets(entries):
        remote_command = build_mctp_command(
            target.eid,
            target.interface,
            options.source_eid,
            options.message_type,
            DEFAULT_UUID_COMMAND_CODE,
        )
        commands.append(remote_command)
        version_support_response, supported_versions, version_support_error, version_support_command = (
            fetch_mctp_version_support(target, options)
        )
        supported_message_types, supported_message_types_error = fetch_supported_message_types(
            target,
            options,
        )

        try:
            command_output = run_remote_shell_command(options, remote_command)
        except RuntimeError:
            results.append(
                EndpointUuidResult(
                    eid=target.eid,
                    interface=target.interface,
                    transport_binding=target.transport_binding,
                    command=remote_command,
                    version_support_command=version_support_command,
                    uuid_value=None,
                    raw_response=None,
                    error=UUID_RESPONSE_TOO_SHORT_ERROR,
                    version_support_response=version_support_response,
                    supported_versions=supported_versions,
                    version_support_error=version_support_error,
                    supported_message_types=supported_message_types,
                    supported_message_types_error=supported_message_types_error,
                )
            )
            continue

        try:
            response = extract_mctp_responses(command_output)[-1]
            decoded = decode_get_endpoint_uuid_response(response)
            results.append(
                EndpointUuidResult(
                    eid=target.eid,
                    interface=target.interface,
                    transport_binding=target.transport_binding,
                    command=remote_command,
                    version_support_command=version_support_command,
                    uuid_value=decoded["uuid"],
                    raw_response=response,
                    error=None,
                    version_support_response=version_support_response,
                    supported_versions=supported_versions,
                    version_support_error=version_support_error,
                    supported_message_types=supported_message_types,
                    supported_message_types_error=supported_message_types_error,
                )
            )
        except ValueError as error:
            results.append(
                EndpointUuidResult(
                    eid=target.eid,
                    interface=target.interface,
                    transport_binding=target.transport_binding,
                    command=remote_command,
                    version_support_command=version_support_command,
                    uuid_value=None,
                    raw_response=None,
                    error=str(error),
                    version_support_response=version_support_response,
                    supported_versions=supported_versions,
                    version_support_error=version_support_error,
                    supported_message_types=supported_message_types,
                    supported_message_types_error=supported_message_types_error,
                )
            )

    return results, commands


def render_grid_table(rows: list[dict]) -> str:
    headers = [
        "Range",
        "Starting EID",
        "Entry Type/Port Number",
        "Physical Transport Binding Identifier",
        "Physical Media Type Identifier",
        "Addr Size",
        "Physical Address",
    ]
    numeric_headers = {"Range", "Addr Size"}

    widths: dict[str, int] = {}
    for header in headers:
        widths[header] = len(header)
        for row in rows:
            widths[header] = max(widths[header], len(str(row[header])))

    def make_border(fill: str, junction: str = "+") -> str:
        return junction + junction.join(fill * (widths[header] + 2) for header in headers) + junction

    def make_row(values: dict[str, object] | None = None, header: bool = False) -> str:
        cells = []
        for column in headers:
            text = column if header else str(values[column])
            if not header and column in numeric_headers:
                cells.append(f" {text:>{widths[column]}} ")
            else:
                cells.append(f" {text:<{widths[column]}} ")
        return "|" + "|".join(cells) + "|"

    if not rows:
        return "No routing table entries"

    lines = [
        make_border("-"),
        make_row(header=True),
        make_border("=", junction="+"),
    ]

    for row in rows:
        lines.append(make_row(values=row))
        lines.append(make_border("-"))

    return "\n".join(lines)


def render_raw_responses(responses: list[str]) -> str:
    lines = ["Raw Response Data:"]
    for index, response in enumerate(responses, start=1):
        lines.append(f"[{index}] {response}")
    return "\n".join(lines)


def render_executed_commands(
    routing_table_commands: list[str],
) -> str:
    lines = ["Executed mctp_cmds:"]

    if routing_table_commands:
        lines.append("Get Routing Table:")
        for command in routing_table_commands:
            lines.append(command)

    return "\n".join(lines)


def render_uuid_results(
    results: list[EndpointUuidResult],
    uuid_commands: list[str],
    debug: bool,
) -> str:
    if not results:
        return "Endpoint UUIDs: no endpoint UUID queries were issued"

    headers = [
        "EID",
        "Interface",
        "Transport Binding",
        "UUID",
        "Supported MCTP Versions",
        "Supported Message Types",
    ]
    widths = {header: len(header) for header in headers}
    rows: list[dict[str, str]] = []

    for result in results:
        if result.supported_message_types is not None:
            supported_text = ", ".join(result.supported_message_types) or "none"
        else:
            supported_text = (
                f"unavailable ({result.supported_message_types_error or 'no response captured'})"
            )

        row = {
            "EID": str(result.eid),
            "Interface": result.interface,
            "Transport Binding": result.transport_binding,
            "UUID": result.uuid_value or "-",
            "Supported MCTP Versions": (
                ", ".join(result.supported_versions)
                if result.supported_versions is not None
                else f"unavailable ({result.version_support_error or 'no response captured'})"
            ),
            "Supported Message Types": supported_text,
        }
        rows.append(row)
        for header in headers:
            widths[header] = max(widths[header], len(row[header]))

    def make_border(fill: str) -> str:
        return "+" + "+".join(fill * (widths[header] + 2) for header in headers) + "+"

    def make_row(values: dict[str, str] | None = None, header: bool = False) -> str:
        cells = []
        for column in headers:
            text = column if header else values[column]
            if column == "EID" and not header:
                cells.append(f" {text:>{widths[column]}} ")
            else:
                cells.append(f" {text:<{widths[column]}} ")
        return "|" + "|".join(cells) + "|"

    lines: list[str] = []
    if debug and uuid_commands:
        lines.append("Get Endpoint UUID:")
        lines.extend(uuid_commands)
        lines.append("Get MCTP Version Support:")
        lines.extend(result.version_support_command for result in results)
        lines.append("Raw Endpoint Query Response Data:")
        for result in results:
            lines.append(f"[EID {result.eid}] {result.command}")
            if result.raw_response:
                lines.append(f"[EID {result.eid}] response: {result.raw_response}")
            else:
                lines.append(
                    f"[EID {result.eid}] response: {result.error or 'no response captured'}"
                )
            lines.append(f"[EID {result.eid}] {result.version_support_command}")
            if result.version_support_response:
                lines.append(
                    f"[EID {result.eid}] version support response: {result.version_support_response}"
                )
            else:
                lines.append(
                    "[EID {eid}] version support response: {error}".format(
                        eid=result.eid,
                        error=result.version_support_error or "no response captured",
                    )
                )
    lines.extend(["Endpoint UUIDs:", make_border("-"), make_row(header=True), make_border("=")])
    for row in rows:
        lines.append(make_row(values=row))
        lines.append(make_border("-"))
    return "\n".join(lines)


def render_target_report(
    dest_eid: int,
    responses: list[str],
    routing_table_commands: list[str],
    uuid_results: list[EndpointUuidResult],
    uuid_commands: list[str],
    decoded_entries: list[dict],
    debug: bool,
    show_endpoint_uuids: bool,
) -> str:
    lines = [f"Destination EID {dest_eid} Output:"]

    if debug and routing_table_commands:
        lines.append(render_executed_commands(routing_table_commands))
        lines.append("")

    if debug:
        lines.append(render_raw_responses(responses))
        lines.append("")

    lines.append(render_grid_table(decoded_entries))
    if show_endpoint_uuids:
        lines.append("")
        lines.append(render_uuid_results(uuid_results, uuid_commands, debug))
    return "\n".join(lines)


def render_target_error_report(dest_eid: int, error: Exception) -> str:
    return "\n".join(
        [
            f"Destination EID {dest_eid} Output:",
            f"Unable to collect routing table data: {error}",
        ]
    )


def collect_target_report(
    options: RemoteOptions,
    responses: list[str] | None = None,
) -> str:
    routing_table_commands: list[str] = []
    if responses is None:
        responses, routing_table_commands = fetch_remote_routing_table_responses(options)

    decoded = decode_get_routing_table_responses(responses)
    uuid_results: list[EndpointUuidResult] = []
    uuid_commands: list[str] = []
    if options.show_endpoint_uuids:
        uuid_results, uuid_commands = fetch_remote_endpoint_uuids(decoded["entries"], options)
    return render_target_report(
        options.dest_eid,
        responses,
        routing_table_commands,
        uuid_results,
        uuid_commands,
        decoded["entries"],
        options.debug,
        options.show_endpoint_uuids,
    )


def collect_optional_target_report(options: RemoteOptions) -> str:
    try:
        return collect_target_report(options)
    except (RuntimeError, ValueError) as error:
        return render_target_error_report(options.dest_eid, error)


if __name__ == "__main__":
    responses, remote_options = parse_arguments(sys.argv[1:])
    reports: list[str] = []

    if responses:
        reports.append(collect_target_report(remote_options, responses=responses))
    else:
        try:
            reports.append(collect_target_report(remote_options))
        except RemoteConnectionError as error:
            reports.append(render_target_error_report(remote_options.dest_eid, error))
        else:
            if remote_options.dest_eid != DEFAULT_SECONDARY_DEST_EID:
                reports.append(
                    collect_optional_target_report(
                        replace(remote_options, dest_eid=DEFAULT_SECONDARY_DEST_EID)
                    )
                )

    print("\n\n".join(reports))