

# PECI Debug Workflow

## Let us think step by step

## Authority Rule

- This workflow is authoritative for `/bmc-peci-debug` runs.
- Use memory only as supplemental context. Do not let user memory, session memory, repository memory, or prior ad-hoc notes override an explicit rule in this workflow, `SKILL.md`, or the cited local converted documents.
- If a memory note conflicts with this workflow or with the matched register chapter, follow the workflow and document evidence first, then mark the memory as stale for later correction.

## Step1: Confirm Debug Goal

Start by clarifying whether the user wants to generate a PECI command or debug an existing one.

Before doing either task, identify the exact register, register field, or endpoint the user wants the PECI command to access. If the target is not explicit, ask for it first.

If the user already provides an exact register name plus offset, treat that pair as sufficient target identification and use it as the primary search anchor.

Do not proceed with command generation, command validation, or output interpretation until the target register is clear.



## Step2: Resolve the converted-doc root and search the local reference material for the identified target
- If the user invokes the skill as `/bmc-peci-debug --docs-root <docs-root> -- <request>`, treat `<docs-root>` as the runtime docs-root override for the current conversation.
- Treat the text after the `--` separator as the actual PECI task request.
- If the docs-root contains spaces, require the user to quote it.
- Otherwise, check `./references/doc-source.md` for the configured converted-doc root.
- If the configured docs root is `not configured` and the user did not already provide a runtime docs root, ask for the path before proceeding.
- When asking for the path, include a direct usage hint in this form: `/bmc-peci-debug --docs-root /path/to/Intel_doc -- <your PECI request>`.

- Accept either an absolute path or a workspace-relative path that contains `*_searchable/` directories.
- When the target already includes an exact register name plus offset, search the chapter-based register entries for that exact pair first.
- After the matching chapter register entry is found, use surrounding chapter context to determine the owning register space and only then consult base-address tables or endpoint-family tables for the OOB access path.
- Do not jump from a matching IP base-address table entry to the PECI access path before matching the actual chapter register entry.
- Use the chapter-based Markdown files in `<docs-root>/*_searchable/chapters/`
    -rank:
        - 793272
        - 792359
        - 648590
- Use `<docs-root>/*_searchable/chunks/` only when the chapter files are too coarse for the target.

## Step3: Get access type of the target register
- MMIO
  - You need use `RdEndpointConfigMMIO` or `WrEndpointConfigMMIO` command type in `peci_cmds`
- PCI
  - You need use `RdEndpointConfigPCILocal` or `WrEndpointConfigPCILocal` command type in `peci_cmds`
- MSR
  - You need use `RdIAMSREx` or `WrIAMSREx` command type in `peci_cmds`

## Step4: Check the target register's content to obtain parameters
- MMIO: AType Bar Seg Bus Dev Func Reg
    -Atype/seg/bus/dev/func: refer "Rd/WrEndPointConfig() MMIO Command Parameters" table
    -reg: target register offset in hex
  -if the table shows a bus number in parentheses such as `(1, 9)` or `(0, 4-7, 8)`, do not copy that literal value into `Bus`
  -for DMR, a parenthesized bus number is a pre-enumerated RootBus index; resolve it to the BIOS-programmed post-enumerated bus number through the matching `CPUBUSNOx.ROOTBUSSx` field before composing `RdEndpointConfigMMIO` or `RdEndpointConfigPCI`
  -to discover those `ROOTBUSSx` values over PECI on DMR, read the `CPUBUSNOx` registers through `RdEndpointConfigPCILocal` on OOBMSM instead of treating `CPUBUSNOx` as a target MMIO register
  -when the final MMIO or PCI command depends on a runtime `ROOTBUSSx` value, first give the user the helper `peci_cmds` needed to read that `CPUBUSNOx` register, then wait for or use the returned bus value before generating the final target-register command
  -unless the MMIO command table or its notes explicitly say to add an endpoint-specific base address, do not fold BAR base or in-band MMIO base into `Reg`
  -for PCIe-compliant accelerator endpoints such as DSA, IAA, and QAT, use the documented register offset as `Reg`; BAR selection is already carried separately by `Bar`
- PCI: Seg Bus Dev Func Reg
    -seg: default is 0
    -bus/dev/func: refer the register's chapter
    -reg: target register offset in hex
- MSR: Thread Address
    -Thread: you can use 0
    -Address: target MSR offset in hex

When all the parameters are obtained, generate the peci_cmds based on the format and the command type.

## Step5: Review the Notes section before finalizing peci_cmds syntax

- Before providing the final `peci_cmds` syntax, review the `Notes` section at the end of this document.
- If the target is a DMR integrated IP MMIO register, verify that the `Reg` parameter follows the OOB PECI mapping guidance in `Notes` rather than directly reusing an in-band MMIO formula.
- If the `Notes` section adds a target-specific exception or verified example, prefer that guidance over a generic syntax pattern.
- If the `Notes` section adds a verified target-specific exception for `AType`, `Bar`, address width packing, binding, or transport bytes, prefer that verified exception over the generic MMIO table for the same fully qualified target instance and context.

## Step6: Compose PECI raw data bytes
- Do not skip this step when using this skill. Unless the user explicitly asks to omit `mctp_cmds`, always compose the raw data bytes and corresponding `mctp_cmds` output.
- The generated `mctp_cmds` must be copy-paste ready for direct execution in the BMC shell.
- According to 648590, compose the raw data bytes from related command type.
- Derive the PECI payload bytes by walking the 648590 request table strictly left to right for the selected command form. Do not infer byte order or field count from a similar command.
- Before finalizing any raw command, account for every byte position after `CMD` with a field name from 648590.
  - Do not collapse, skip, or mentally merge fields just because their values are `0x00`.
  - If the table shows a reserved field, emit it explicitly in the payload.
  - For packed fields, state the packing rule before emitting the byte, for example `Device[4:0]<<3 | Function[2:0]`.
- For multi-byte address or data fields, encode bytes in the order shown by the 648590 command table and cross-check against a verified example when one exists.
- add peci over mctp payload header
    - from table System Management API over MCTP Request (over I3C) of 648590
    - example:
        - byte 0: IC + Message Type = 0x7E
        - byte 1 and 2: MCTP PCI Vendor Defined Vendor ID = 0x8086, encoded on the command line as `0x80 0x86`
        - byte 3: Rq + Instance ID = 0x80
        - byte 4: Intel MCTP OpCode = 0x2
- When generating `mctp_cmds`, specify the binding network with `-n`.
  - In the currently verified environment, use `-n 2` for i3c binding.
  - In the currently verified environment, use `-n 1` for pcie binding.
- When generating user-facing `mctp_cmds`, prefer decimal destination EIDs in `-d`, not hex forms.
  - Use `-d 9` for Primary IMH (`imh0`), which corresponds to `Domain ID = 8`.
  - Use `-d 10` for Secondary IMH (`imh1`), which corresponds to `Domain ID = 9`.
  - If an older verified example elsewhere in this document shows `-d 0x9`, treat that as the same destination as `-d 9`, but normalize the final command you output to the user into `-d 9` or `-d 10`.
  - This `-d 9` and `-d 10` mapping is a final output-normalization rule for user-facing commands, not by itself a verified claim that every example below was executed with those exact decimal forms.
- For `RdEndPointConfig() - MMIO`, choose the Write Length from the address width in 648590, not from whether the register offset numerically fits in 32 bits.
  - `AType = 0x05` means 32-bit address packing: `WL = 0x0E` and 4 address bytes.
  - `AType = 0x06` means 64-bit address packing: `WL = 0x12` and 8 address bytes.
  - If `AType = 0x06`, do not shorten the request to `WL = 0x0E` just because the offset is `0x0` or otherwise small.
- For `RdEndPointConfig() - Local PCI Cfg`, use 648590 section 4.2.12.1, not `RdPCIConfigLocal()` section 4.2.10.
  - `WL = 0x0C` and `RL = 0x02/0x03/0x05` for byte/word/dword reads.
  - After `CMD = 0xC1`, emit `DomainID/Retry`, `MessageType = 0x03`, `EndPointID = 0x00`, `Rsvd = 0x00`, `Rsvd = 0x00`, `AddressType = 0x04`, `Segment`, `Register[7:0]`, `Device[0]<<7 | Function[2:0]<<4 | Register[11:8]`, `Bus[3:0]<<4 | Device[4:1]`, and `Reserved[3:0]<<4 | Bus[7:4]`.
  - The converted Markdown line wrap for 648590 section 4.2.12.1 is easy to misread. Before finalizing the last three request bytes, cross-check against a verified raw command instead of trusting the visual wrap alone.
  - If a verified target-specific raw command disagrees with the visually wrapped Markdown extraction on those packed bytes, treat that as a target-specific exception and record the exact validated tuple in `Notes` instead of silently generalizing it.
  - There must be 11 bytes after `CMD` in the request. If a generated local-PCI raw command is shorter, or if it uses `CMD = 0xE1`, treat it as malformed and recompute it.
- For `RdEndPointConfig() - MMIO`, follow the full 648590 request field order after `CMD = 0xC1`: `DomainID/Retry`, `MessageType`, `EndPointID`, `Rsvd`, `Bar ID`, `AddressType`, `Segment`, `Device[4:0]<<3 | Function[2:0]`, `Bus`, then the address bytes.
  - Do not omit the `Rsvd = 0x00` byte between `EndPointID` and `Bar ID`.
  - For the currently used endpoint reads, `EndPointID = 0x00`.
  - For the 64-bit form, there must be 17 bytes after `CMD`: `DomainID/Retry`, `MessageType`, `EndPointID`, `Rsvd`, `Bar ID`, `AddressType`, `Segment`, `Device/Function`, `Bus`, and `Address[0:7]`.
  - For the 32-bit form, there must be 13 bytes after `CMD`: the same leading fields followed by `Address[0:3]`.
  - If a generated `RdEndPointConfig() - MMIO` raw command does not satisfy that field count, treat it as malformed and recompute it before replying.
- Prefer verified byte order from working examples over a verbal interpretation of the table when the table lists a multi-byte field as a single hex value.


## Step7: expected output
you must need provide the following output: you do not need validate them in the current enviroment, just give them to the user to validate them.
- When this skill is used, the default expectation is to provide both `peci_cmds` and `mctp_cmds`, even if the user only asks how to access the register with `peci_cmds`.
- If the target belongs to a numbered endpoint family with multiple instances and the user did not narrow it to one instance, provide a concrete multi-instance command set instead of only one template.
  - For families such as `MSE_n`, list at least the first 6 instances when they are available, for example `MSE_0` through `MSE_5`.
  - For each listed instance, provide both the matching `peci_cmds` and `mctp_cmds`.
  - Keep invariant fields implicit in a short preface, then vary only the instance-specific fields such as `Domain ID`, `Bus`, `Dev`, `Func`, packed `Device/Function` byte, and destination EID when needed.
- peci_cmds.
    - peci_cmds usage refer peci_cmds format on this page
- mctp_cmds with the raw data bytes as payload
    - mctp_cmds usage refer mctp_cmds format on this page
  - the command must be directly copy-paste runnable in the BMC shell
  - include the correct binding network with `-n`
  - for IMH-targeted output, prefer `-d 9` for Primary IMH (`Domain ID = 8`) and `-d 10` for Secondary IMH (`Domain ID = 9`)
  - treat that `-d 9` and `-d 10` choice as the required final output format even when older verified examples in `Notes` still show `-d 0x9`
  - example for i3c on Primary IMH: `mctp_cmds -i i3c -n 2 -d 9 -s ....`

Finally, ask the user whether they want this skill to validate the generated commands in their environment. If validation is requested, collect only non-secret connection details such as BMC host/IP, username, interface, and whether existing SSH authentication is already configured. Do not ask the user to paste passwords, tokens, private keys, or other secrets into chat. If a secret is required, tell the user to type it directly into the terminal prompt or run the validation commands manually. Report the executed `peci_cmds`, returned output, and any parsed result back to the user.

## Step 8. Reflection loop after a failed command

If the suggested command does not work, and the user validates or adjusts it manually, do not stop at replacing the command.

You must explicitly compare the failed command with the working command and identify the root cause before giving the corrected result.

Required reflection steps:

- State which field or assumption was wrong.
  - Typical categories: wrong access type selection, wrong SBDF source, wrong MMIO versus OOB mapping, wrong register offset interpretation, wrong size, wrong domain ID, wrong interface, wrong write length or address width packing, or incomplete reading of the reference chapter.
- If the returned completion code is `0x82`, do not immediately conclude that the generated command syntax or target parameters are wrong.
  - For DMR, treat `0x82` as a low-power or resource-unavailable condition first.
  - Before changing domain, processor ID, SBDF, or register offset, retry with the same target command after applying the platform wake/access preparation step.
  - In the currently verified environment, first run `tpmitool access 0xE 0x8 0x2 --domain 8`, then rerun the original `peci_cmds`.
  - If the platform and interface support it, `peci_cmds -w` is also a documented wake-assisted retry path, but do not skip the verified `tpmitool access 0xE 0x8 0x2 --domain 8` sequence when the user has already identified it as required in their environment.
- If the failure involves SBDF, bus numbering, or choosing between `RdEndpointConfigPCILocal`, `RdEndpointConfigPCI`, and `RdEndpointConfigMMIO`, explicitly consult the generic access chapter for the platform family before trusting a target-specific table literally.
  - For DMR, use 792359 section 7.1.3 as the tie-breaker: `Local PCI Cfg` uses pre-enumerated bus numbering, while `PCI Cfg` and local-device `MMIO` paths can require BIOS-programmed post-enumerated `ROOTBUSSx` values.
- If the failure involves raw-byte composition for `RdEndpointConfigPCILocal`, explicitly distinguish `RdPCIConfigLocal()` from `RdEndPointConfig() - Local PCI Cfg` before changing BDF or offset values.
  - `peci_cmds RdEndpointConfigPCILocal` maps to 648590 section 4.2.12.1 with `CMD = 0xC1`, `MessageType = 0x03`, and `AddressType = 0x04`.
  - Do not reuse the 4.2.10 `RdPCIConfigLocal()` `CMD = 0xE1` payload just because both paths ultimately read local PCI configuration space.
  - If the generated raw bytes differ only in the packed local-PCI address bytes, compare them against the 648590 4.2.12.1 field order before changing `Seg/Bus/Dev/Func/Reg`. A swapped `0x01 0x11` versus `0x11 0x01` pair can be a byte-order defect rather than an SBDF defect.
- Explicitly state whether the failed command used the wrong bus-numbering model.
  - For DMR local devices with CSRs such as DSA, IAA, and QAT, call out that MMIO uses the post-enumerated bus value programmed at the matching `ROOTBUSSx`, not the literal parenthesized bus index shown in the register table.
- Point to the exact document statement, table, or verified example that supports the correction.
- Explain why the original command looked plausible but was still wrong.
- Give the corrected command and summarize only the parameters that changed.
- Treat the corrected command as the new local ground truth only for the same fully qualified target instance and transport context unless a stronger source contradicts it.
- Generalize a corrected command to a wider target family only when the note explicitly states which fields are invariant and which fields must still be recomputed.
- When `RdEndpointConfigPCILocal` works on an endpoint but `RdEndpointConfigMMIO` fails, run `RdEndpointConfigPCI` on the same SBDF before changing offset math. This distinguishes a generic endpoint path or command-format issue from a bad SBDF guess.

When the failure exposed a workflow gap, update the guidance source instead of keeping the fix only in the reply.

- If the correction is target-specific, add it to `Notes` as a verified example or exception.
- If the correction changes the general decision process, update the numbered workflow steps.

Do not repeat the same unsupported assumption after a user has already disproved it with a working command.


## peci_cmds format

peci_cmds [-h] [-v] [-t] [-a <addr>] [-i <domain id>] [-s <size>] [-l <count>] <command> [parameters]
Options:
        -h          Display this help information
        -v          Display additional information about the command
        -t          Measure request-to-response time
        -w          Enable wake on PECI before cmd and disable after use
        -l <count>  Loop the command the given number of times. <count> is in the range 1 to 18446744073709551615
        -a <addr>   Address of the target. Accepted values are 48-55 (0x30-0x37). Default is 48 (0x30)
        -i <domain id>Domain ID of the target. Accepted values are 0-127. Default is 0
        -s <size>   Size of data to read or write in bytes. Accepted values are 1, 2, 4, 8, and 16. Default is 4
        -d          Set PECI interface. Supported interfaces:
                        -d i3c for PECI over MCTP over I3C (default).
                        -d pcie for PECI over MCTP over PCIe.

Commands:
        RdIAMSREx                   MSR Ex Read <Thread Address>
        WrIAMSREx                   MSR Ex Write <Thread Address Data>
        RdEndpointConfigPCILocal    Endpoint Local PCI Config Read <Seg Bus Dev Func Reg>
        WrEndpointConfigPCILocal    Endpoint Local PCI Config Write <Seg Bus Dev Func Reg Data>
        RdEndpointConfigPCI         Endpoint PCI Config Read <Seg Bus Dev Func Reg>
        WrEndpointConfigPCI         Endpoint PCI Config Write <Seg Bus Dev Func Reg Data>
        RdEndpointConfigMMIO        Endpoint MMIO Read <AType Bar Seg Bus Dev Func Reg>
        WrEndpointConfigMMIO        Endpoint MMIO Write <AType Bar Seg Bus Dev Func Reg Data>
        Crashdump                   Crashdump <opcode [parameters]>
        raw                         Raw PECI command in bytes

      The command list above means the BMC-side `peci_cmds` tool supports the following PECI commands:

      | Command | Category | Parameters | Supported by BMC `peci_cmds` | Description |
      | --- | --- | --- | --- | --- |
      | `RdIAMSREx` | MSR read | `<Thread Address>` | Yes | Read an MSR Ex register from the target thread. |
      | `WrIAMSREx` | MSR write | `<Thread Address Data>` | Yes | Write an MSR Ex register on the target thread. |
      | `RdEndpointConfigPCILocal` | PCI config read | `<Seg Bus Dev Func Reg>` | Yes | Read local endpoint PCI configuration space. |
      | `WrEndpointConfigPCILocal` | PCI config write | `<Seg Bus Dev Func Reg Data>` | Yes | Write local endpoint PCI configuration space. |
      | `RdEndpointConfigPCI` | PCI config read | `<Seg Bus Dev Func Reg>` | Yes | Read endpoint PCI configuration space through the PCI path. |
      | `WrEndpointConfigPCI` | PCI config write | `<Seg Bus Dev Func Reg Data>` | Yes | Write endpoint PCI configuration space through the PCI path. |
      | `RdEndpointConfigMMIO` | MMIO read | `<AType Bar Seg Bus Dev Func Reg>` | Yes | Read endpoint MMIO space. |
      | `WrEndpointConfigMMIO` | MMIO write | `<AType Bar Seg Bus Dev Func Reg Data>` | Yes | Write endpoint MMIO space. |
      | `Crashdump` | Telemetry / dump | `<opcode [parameters]>` | Yes | Execute a crashdump subcommand with the given opcode and parameters. |
      | `raw` | Raw PECI transport | bytes | Yes | Send a raw PECI command as byte data. |



## mctp_cmds format

Command line tool for interacting with MCTP layer
Usage: mctp_cmds [OPTIONS]

Options:
  -h,--help                   Print this help message and exit
  -w,--timeout UINT           Timeout
  -n,--net UINT               Network ID
  -d,--dest UINT              Destination EID
  -i,--intf TEXT              Interface to be used. Available interfaces include i3c,smbus,pcie
  -e,--ext                    List out complete EID info
  -l,--list                   List all the available MCTP interface info
  -s,--sendRcv UINT ...       Send MCTP request payload and receive response payload
  -t,--telemetry TEXT ...     Send Telemetry request payload and receive response payload
  -v,--version                Version Info



### Notes(reflection from failed attempts and verified examples):

1. DMR integrated IP OOB MMIO access

- Do not directly reuse the in-band formula `MMIO_BASE + IP Base Address + register_offset` as the `Reg` parameter of `peci_cmds RdEndpointConfigMMIO`.
- The in-band formula is for CPU-side MMIO address calculation. For OOB PECI access to integrated IPs, `RdEndpointConfigMMIO` should use the OOB PECI mapping from the dummy SBDF table plus the OOB-visible register offset.
- If a chapter explicitly says it documents in-band MMIO address calculation, treat that as a separate path from OOB PECI unless the OOB spec says to reuse the same full address.
- For DMR endpoints that use the generic MMIO parameter table, only add an extra endpoint-specific base when the table notes explicitly require `Address: Register offset + <IP base>`. Table 50 note 3 shows such exceptions for endpoints like NCU and Punit CBB. Accelerators such as DSA, IAA, and QAT are not in that exception list, so their `Reg` remains the documented register offset.

Verified DMR SCA example:

- Target register: `SCA IP signature (IP_ID_1_MEM)`
- Target instance and context: `SCA_0` on primary IMH, `i = 8`
- Register offset: `0x4308`
- Verified OOB PECI parameters:
  - `Domain ID = 8`
  - `AType = 0x5`
  - `Bar = 0`
  - `Seg = 255`
  - `Bus = 62`
  - `Dev = 0`
  - `Func = 0`
  - `Reg = 0x4308`

- Verified command:
  ```bash
  peci_cmds -s 4 -i 8 RdEndpointConfigMMIO 0x5 0 255 62 0 0 0x4308
  ```

2. Verified MCTP over I3C packing for DMR SCA MMIO read

- Root cause from failed attempt:
  - The Vendor ID field `0x8086` was expanded with the wrong on-wire byte order.
  - The i3c binding network flag `-n 2` was omitted.
- Verified rule:
  - For the working `mctp_cmds` form used here, Vendor ID `0x8086` is sent as `0x80 0x86`.
  - In the currently verified environment, use `-n 2` with `-i i3c`.
  - In the currently verified environment, use `-n 1` with `-i pcie`.

Verified FRP_AGE_MEM example:

- Target register: `FRP s (FRP_AGE_MEM)`
- Target instance and context: `SCA_0` on primary IMH, `-i i3c -n 2 -d 0x9`
- Register offset: `0x2020`
- Verified command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 0x9 -s 0x7E 0x80 0x86 0x80 0x02 0x0E 0x09 0xC1 0x10 0x05 0x00 0x00 0x00 0x05 0xFF 0x00 0x3E 0x20 0x20 0x00 0x00
  ```

3. Verified MCTP over I3C packing for DMR I3C HCI_VERSION read

- Root cause from failed attempt:
  - The request used the 32-bit MMIO write length `0x0E` even though the command used `AType = 0x06`, which 648590 defines as 64-bit address packing.
  - The request omitted the upper 4 address bytes required by the 64-bit MMIO request format.
- Verified rule:
  - For `RdEndPointConfig() - MMIO`, `AType = 0x06` requires `WL = 0x12` and 8 address bytes.
  - This remains true even when the effective register offset is `0x0` and the high address bytes are all zero.

Verified HCI_VERSION example:

- Target register: `HCI_VERSION`
- Target instance and context: `SPD_0` on primary IMH, `-i i3c -n 2 -d 0x9`
- Register offset: `0x0`
- Verified command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 0x9 -s 0x7E 0x80 0x86 0x80 0x02 0x12 0x05 0xC1 0x10 0x05 0x00 0x00 0x00 0x06 0xFF 0x84 0x3F 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00
  ```

4. Verified RdEndpointConfig MMIO field order for DMR Punit IMH PACKAGE_POWER_SKU_CFG

- Root cause from failed attempt:
  - The request omitted the `Rsvd = 0x00` byte between `EndPointID` and `Bar ID` in the 648590 `RdEndPointConfig() - MMIO` request layout.
  - That omission shifted `Bar ID`, `AddressType`, `Segment`, `Device/Function`, `Bus`, and all address bytes left by one position, producing a malformed packet even though most visible values still looked plausible.
- Verified rule:
  - For `RdEndPointConfig() - MMIO`, preserve the full field order from 648590: `DomainID/Retry`, `MessageType`, `EndPointID`, `Rsvd`, `Bar ID`, `AddressType`, `Segment`, `Device[4:0]<<3 | Function[2:0]`, `Bus`, then address bytes.
  - Do not omit reserved fields when composing the raw payload, even when their value is `0x00`.

Verified PACKAGE_POWER_SKU_CFG example:

- Target register: `PACKAGE POWER SKU (PACKAGE_POWER_SKU_CFG)`
- Target instance and context: `Punit IMH`, primary IMH, `-i i3c -n 2 -d 0x9`
- Register offset: `0x110`
- Verified command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 0x9 -s 0x7E 0x80 0x86 0x80 0x02 0x12 0x09 0xC1 0x10 0x05 0x00 0x00 0x00 0x06 0xFF 0xDE 0x3E 0x10 0x01 0x00 0x00 0x00 0x00 0x00 0x00
  ```

5. Corrected MMIO `Device/Function` packed byte for Intel TH `SWDEST[0]`

- Root cause from failed Intel TH attempt:
  - The generated request used the correct MMIO path, BAR, segment, bus, and register offset, but encoded the `Device/Function` packed byte as if the device number were written unshifted.
  - For `Bus = 0`, `Dev = 3`, `Func = 0`, the incorrect byte was emitted as `0x03` instead of `0x18`.
  - That made the raw payload look locally plausible while still targeting the wrong encoded endpoint tuple on the wire.
- Correct rule from 648590 section 4.2.12.3:
  - After `Segment[7:0]`, emit the MMIO `Device/Function` packed byte as `Device[4:0]<<3 | Function[2:0]`, then emit the `Bus` byte.
  - Therefore, for `Dev = 3`, `Func = 0`, the packed byte is `(0x3 << 3) | 0x0 = 0x18`.
- Corrected Intel TH example:
  - Target register: `Switching Destination [0] (SWDEST[0])`
  - Target instance and context: Intel TH AC0 on primary IMH, `Domain ID = 8`, `AType = 0x6`, `Bar = 0`, `Seg = 0`, `Bus = 0`, `Dev = 3`, `Func = 0`, `Reg = 0x8`
  - Corrected command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 9 -s 0x7E 0x80 0x86 0x80 0x02 0x12 0x05 0xC1 0x10 0x05 0x00 0x00 0x00 0x06 0x00 0x18 0x00 0x08 0x00 0x00 0x00 0x00 0x00 0x00 0x00
  ```
- Generalization:
  - When a DMR MMIO raw command differs only by a `0x03` versus `0x18` style `Device/Function` byte for the same `Dev` and `Func`, treat that first as a packed-byte composition issue, not as evidence that `Bus`, `Dev`, or `Func` itself must change.

6. Verified `RdEndpointConfigPCILocal` raw-byte packing

- Root cause from failed attempt:
  - The request used the `RdPCIConfigLocal()` packet format from 648590 section 4.2.10 with `CMD = 0xE1`.
  - The user-facing command was `peci_cmds RdEndpointConfigPCILocal`, which must instead use `RdEndPointConfig() - Local PCI Cfg` from section 4.2.12.1 with `CMD = 0xC1`.
  - That mistake omitted the endpoint wrapper fields `MessageType`, `EndPointID`, both reserved bytes, `AddressType`, and `Segment`, so the raw request was not the wire equivalent of the suggested `peci_cmds` command.
- Verified rule:
  - For `peci_cmds RdEndpointConfigPCILocal`, compose the raw MCTP payload from 648590 section 4.2.12.1.
  - Use `WL = 0x0C`, `CMD = 0xC1`, `MessageType = 0x03`, `EndPointID = 0x00`, `Rsvd = 0x00`, `Rsvd = 0x00`, `AddressType = 0x04`, then `Segment`, `Register[7:0]`, `Device[0]<<7 | Function[2:0]<<4 | Register[11:8]`, `Bus[3:0]<<4 | Device[4:1]`, and `Reserved[3:0]<<4 | Bus[7:4]`.
  - Do not substitute the simpler `RdPCIConfigLocal()` `0xE1` format when the target command is `RdEndpointConfigPCILocal`.

Corrected example aligned with 648590 section 4.2.12.1:

- Context: `RdEndpointConfigPCILocal` dword read over i3c on primary IMH, `Domain ID = 8`, destination EID 9, register offset `0x170`
- Corrected command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 9 -s 0x7E 0x80 0x86 0x80 0x02 0x0C 0x05 0xC1 0x10 0x03 0x00 0x00 0x00 0x04 0x00 0x70 0x11 0x01 0x00
  ```

7. DMR parenthesized bus numbers in Table 50 and similar MMIO tables

- Root cause from failed DSA attempt:
  - The command used the literal pre-enumerated bus index shown in parentheses in the MMIO parameter table.
  - For DMR MMIO and PCI paths, those parenthesized values are not fixed runtime bus numbers after BIOS enumeration.
- Verified rule:
  - In the DMR register overview, note 1 under the endpoint command tables states that bus numbers shown in parentheses are BIOS-programmed values and must be obtained from the respective `CPUBUSNOx.ROOTBUSSx` field.
  - In the DMR OOBMSM description, MMIO for devices with CSRs uses the post-enumerated bus number programmed at the same `ROOTBUSSx`.
  - `CPUBUSNO0.ROOTBUSS1` maps RootBus 1, `CPUBUSNO2.ROOTBUSS9` maps RootBus 9, and so on.
  - On DMR, `CPUBUSNOx` are OOBMSM PCI configuration registers, so read them with `RdEndpointConfigPCILocal` using OOBMSM local SBDF `0/0/2/0` and the appropriate domain ID.
  - Do not over-interpret a register chapter's per-register `OOB Access` row as forbidding all PECI access paths. For this case, `CPUBUSNOx` was still readable through the generic `RdEndpointConfigPCILocal` path documented in the OOBMSM access flow.
  - For this skill, when the runtime bus value is not already known, the required response sequence is: give the helper `CPUBUSNOx` read command first, decode the needed `ROOTBUSSx` byte from the returned dword, then generate the final endpoint command with that decoded bus.

Verified helper commands to discover DSA root buses:

- Primary IMH OOBMSM `CPUBUSNO0` (`ROOTBUSS1` is bits `15:8`):

8. `cc:0x82` on DMR command validation

- Root cause from failed attempt:
  - `cc:0x82` can indicate the target resources are in a low-power or otherwise temporarily unavailable state, not that the generated PECI command is malformed.
  - For the currently verified environment, retrying the same command without the required access preparation can repeat the same false-negative result.
- Verified rule:
  - When validating a generated command on this environment and the response is `cc:0x82`, first run `tpmitool access 0xE 0x8 0x2 --domain 8`, then rerun the original `peci_cmds` before changing command parameters.
  - Keep the original command unchanged for this retry so the follow-up result discriminates low-power/access gating from a real parameter mistake.
  ```bash
  peci_cmds -s 4 -i 8 RdEndpointConfigPCILocal 0 0 2 0 0x190
  ```
- Primary IMH OOBMSM `CPUBUSNO2` (`ROOTBUSS9` is bits `15:8`):
  ```bash
  peci_cmds -s 4 -i 8 RdEndpointConfigPCILocal 0 0 2 0 0x198
  ```
- Secondary IMH OOBMSM `CPUBUSNO0` (`ROOTBUSS1` is bits `15:8`):
  ```bash
  peci_cmds -s 4 -i 9 RdEndpointConfigPCILocal 0 0 2 0 0x190
  ```
- Secondary IMH OOBMSM `CPUBUSNO2` (`ROOTBUSS9` is bits `15:8`):
  ```bash
  peci_cmds -s 4 -i 9 RdEndpointConfigPCILocal 0 0 2 0 0x198
  ```

Verified decode example:

- User-validated command:
  ```bash
  peci_cmds -s 4 -i 8 RdEndpointConfigPCILocal 0 0 2 0 0x190
  ```
- User-validated response:
  ```text
  cc:0x40 0x0f0e0d00
  ```
- Decoding:
  - `ROOTBUSS0 = 0x00`
  - `ROOTBUSS1 = 0x0d`
  - `ROOTBUSS2 = 0x0e`
  - `ROOTBUSS3 = 0x0f`
- Therefore, for primary IMH `DSA_0`, use `Bus = 0x0d` in the final command generated for that same runtime context.

DSA VERSION correction summary:

- Target register: `DSA Version (VERSION)`
- Target instance and context: `DSA_0` or `DSA_1` on DMR IMH
- Register offset: `0x0`
- Corrected OOB PECI parameter rule:
  - `Domain ID = 8` for primary IMH, `9` for secondary IMH
  - `AType = 0x6`
  - `Bar = 0`
  - `Seg = 0`
  - `Bus = value of ROOTBUSS1 for DSA_0, value of ROOTBUSS9 for DSA_1`
  - `Dev = 0`
  - `Func = 0`
  - `Reg = 0x0`

Verified end-to-end DSA_0 example:

- Helper command to discover the runtime bus:
  ```bash
  peci_cmds -s 4 -i 8 RdEndpointConfigPCILocal 0 0 2 0 0x190
  ```
- User-validated response:
  ```text
  cc:0x40 0x0f0e0d00
  ```
- Decoded bus:
  - `ROOTBUSS1 = 0x0d`
- Final user-validated command:
  ```bash
  peci_cmds -s 4 -i 8 RdEndpointConfigMMIO 0x6 0 0 0x0d 0 0 0x0
  ```

9. Verified MCTP over I3C packing for DMR RdEndPointConfig() - Local PCI Cfg

- Root cause from failed EXPPTMBAR attempt:
  - The request used the right PECI command family and SBDF, but the final PCI address packing bytes were wrong.
  - The generated request omitted the `Device[0]<<7 | Function[2:0]<<4 | Register[11:8]` byte after `Register[7:0]`.
  - That omission shifted the remaining bytes left, so the request ended with only two PCI address bytes instead of three.
  - This happened because the Local PCI Cfg layout in 648590 was not followed literally for the last three address bytes.
- Verified rule from 648590 section 4.2.12.1:
  - After `Segment[7:0]` and `Register[7:0]`, the next bytes are packed as:
    - `Device[0]<<7 | Function[2:0]<<4 | Register[11:8]`
    - `Bus[3:0]<<4 | Device[4:1]`
    - `Reserved[3:0]<<4 | Bus[7:4]`
  - For `Seg = 0`, `Bus = 0`, `Dev = 4`, `Func = 0`, `Reg = 0x10`, those bytes are `0x00 0x02 0x00`.
- Verified EXPPTMBAR example:
  - Target register: `PCIe Root Port 0 EXPPTMBAR low dword`
  - Target instance and context: primary IMH Port A, `-i i3c -n 2 -d 0x9`
  - PECI parameters: `Domain ID = 8`, `Seg = 0`, `Bus = 0`, `Dev = 4`, `Func = 0`, `Reg = 0x10`
  - User-validated command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 0x9 -s 0x7E 0x80 0x86 0x80 0x02 0x0C 0x05 0xC1 0x10 0x03 0x00 0x00 0x00 0x04 0x00 0x10 0x00 0x02 0x00
  ```
  - In this verified request, the final three PCI address bytes are `0x00 0x02 0x00`, which decode to `Bus = 0`, `Dev = 4`, `Func = 0`, and `Reg[11:8] = 0`.
- Related user-validated `CPUBUSNO0` access that exposed the same byte-order issue:
  - Context: `peci_cmds -d i3c -i 8 -s 4 RdEndpointConfigPCILocal 0 0 2 1 0x190`
  - A previous generated payload used `... 0x90 0x01 0x11 0x00`, which looked plausible because it followed the visually wrapped Markdown table from 648590 section 4.2.12.1 too literally.
  - The user-validated working payload is `0x7E 0x80 0x86 0x80 0x02 0x0C 0x05 0xC1 0x10 0x03 0x00 0x00 0x00 0x04 0x00 0x90 0x11 0x01 0x00`.
  - Root cause: the two packed local-PCI address bytes were emitted in the wrong order during raw-byte composition. This is a transport-byte composition error, not an access-type or SBDF-selection error.
  - For this exact tuple, after the invariant bytes `0x10 0x03 0x00 0x00 0x00 0x04 0x00 0x90`, the final local-PCI address bytes must be `0x11 0x01 0x00`.
  - Treat this as local ground truth for `CPUBUSNO0` on OOBMSM function 1 over i3c unless a stronger verified source contradicts it.
- Final user-validated response:
  ```text
  cc:0x40 0x00000300
  ```

10. 792359 section 7.1.3 summary and why it matters

- Section 7.1.3 is the controlling generic-access model for DMR `Rd/WrEndPointConfig()` usage. Treat it as the tie-breaker when a target-specific register table is easy to misread.
- It separates the three access families by semantics, not just by opcode syntax:
  - `Local PCI Cfg` targets processor-resident PCI configuration space and uses pre-enumerated bus numbering from the register specification.
  - `PCI Cfg` uses BIOS-programmed post-enumerated bus numbering and may require resolving the bus through `CPUBUSNO`.
  - `MMIO` generally uses the BDF of the PCI device associated with the MMIO register, and for devices with CSRs this also means the post-enumerated bus value programmed at the matching `ROOTBUSSx`.
- For DMR local devices with CSRs, Table 78 in section 7.1.3 is directly relevant to this case: it says local MMIO uses post-enumerated bus numbering programmed at the same `ROOTBUSSx`.
- The chapter also explains why two commands in the same debug flow can legitimately use different bus semantics:
  - use `RdEndpointConfigPCILocal` to read OOBMSM `CPUBUSNOx` because that target is processor-local PCI config space
  - use `RdEndpointConfigMMIO` with the decoded `ROOTBUSSx` value to access DSA MMIO because DSA is a local device with CSRs and its MMIO path follows post-enumerated bus numbering
- Therefore, this case is not an exception to section 7.1.3; it is a direct application of it. The initial failure happened because the command ignored the chapter's pre-enumerated versus post-enumerated split.

11. Corrected `RdEndpointConfigPCILocal` packed-byte order for OOBMSM Telemetry DVSEC read

- Root cause from failed `DVSEC_HDR_FEAT3_CAP1` attempt:
  - The generated raw payload used the correct access type and SBDF, but emitted the second and third local-PCI packed address bytes in the wrong order.
  - The incorrect payload tail for `Seg = 0`, `Bus = 0`, `Dev = 2`, `Func = 1`, `Reg = 0x194` was `0x94 0x01 0x11 0x00`.
  - That looked plausible because the converted Markdown rendering of 648590 section 4.2.12.1 is visually wrapped around the packed address bytes.
- Correct rule from 648590 section 4.2.12.1:
  - After `Segment[7:0]` and `Register[7:0]`, emit `Device[0]<<7 | Function[2:0]<<4 | Register[11:8]`, then `Bus[3:0]<<4 | Device[4:1]`, then `Reserved[3:0]<<4 | Bus[7:4]`.
  - For `Bus = 0`, `Dev = 2`, `Func = 1`, `Reg = 0x194`, the packed local-PCI address bytes are:
    - `Register[7:0] = 0x94`
    - `Device[0]<<7 | Function[2:0]<<4 | Register[11:8] = 0x00 | 0x10 | 0x01 = 0x11`
    - `Bus[3:0]<<4 | Device[4:1] = 0x00 | 0x01 = 0x01`
    - `Reserved[3:0]<<4 | Bus[7:4] = 0x00`
  - Therefore the corrected payload tail is `0x94 0x11 0x01 0x00`.
- Corrected DVSEC example:
  - Target register: `devsec hdr cap 1 (DVSEC_HDR_FEAT3_CAP1)`
  - Target instance and context: OOBMSM Telemetry PCI configuration space, function 1, primary IMH over i3c
  - PECI parameters: `Domain ID = 8`, `Seg = 0`, `Bus = 0`, `Dev = 2`, `Func = 1`, `Reg = 0x194`
  - Corrected command:
  ```bash
  mctp_cmds -i i3c -n 2 -d 9 -s 0x7E 0x80 0x86 0x80 0x02 0x0C 0x05 0xC1 0x10 0x03 0x00 0x00 0x00 0x04 0x00 0x94 0x11 0x01 0x00
  ```
- Generalization:
  - This is not a target-specific SBDF exception. Apply the corrected packed-byte order to all `RdEndpointConfigPCILocal` and `WrEndpointConfigPCILocal` raw payload composition unless a stronger verified source contradicts it.
  - When only `0x01 0x11` versus `0x11 0x01` changes for a local PCI config raw request, treat it first as a packed-byte composition issue, not as evidence that `Bus`, `Dev`, `Func`, or `Reg` should change.
