# TPMI Debug Workflow

## Standard Flow

1. Obtain RootbusS0 value
    - read CPU Bus Number Register 0 (CPUBUSNO0) — Offset 190h
    - get ROOTBUSS0 value




2. Obtain dVSEC structure and parse important data
    - read below registers
        - devsec hdr cap 1 (DVSEC_HDR_FEAT1_CAP1) — Offset 174h
            - obtain
                - DVSEC_LEN
        - Dev Cap 2 (DVSEC_HDR_FEAT1_CAP2) — Offset 178h
            - obtain
                - NUMENTRIES
                - ENTRYSIZE
        - devsec hdr cap 3 (DVSEC_HDR_FEAT1_CAP3) — Offset 17Ch
            - obtain
                - TBIR
                - ADDRESS: address offset in bar
            - On DMR platform, OOBMSM only support PCIe BAR1 as TPMI MMIO space entry, tBIR in VSEC structure only for PCIe configuration space, actually MMIO access need to transfer to BAR1. Which means, we need use TBIR = 1 for further calculation.

3. Collect important parameters of Rd/WrEndpointConfig() from document 793272 Chapter 2.5.5
    - Address type = 0x6
    - Bar ID = 0x1
    - S/B/D/F = 0/(0)/2/1
        - (0) means ROOTBUSS0
    - TPMI address caculation formula

4. According to the TPMI register description, decide its TPMI feature on the Table 53 of 793272. Now you have "PFS.Cap_Offset[feature] + instance_idx × PFS.EntrySize × 4".

5. According to the TPMI register description, decide TPMI register offset and `sub_id`.
    - record the raw `TPMI_Offset`
    - record `sub_id`
    - if `sub_id = 0`, use `effective_tpmi_offset = TPMI_Offset`
    - if `sub_id = 1` for UFS Control Register (`UFS_CONTROL`), first read `UFS_FABRIC_CLUSTER_OFFSET`, then compute `effective_tpmi_offset = UFS_FABRIC_CLUSTER_OFFSET.OFFSET * 8 + TPMI_Offset`
    - if `sub_id` is non-zero and no documented translation rule is available yet, stop and resolve the formula from the documents before continuing

6. Now you have all the parameters to calculate final Address with the formula: BMC_TPMI_FEATURES_FIXED_OFFSET = 0x2000000

    ADDRESS = VSEC.Table_Offset + PFS.Cap_Offset[feature] + instance_idx × PFS.EntrySize×4 + effective_tpmi_offset + BMC_TPMI_FEATURES_FIXED_OFFSET

7. Delegate exact `peci_cmds` composition to `bmc-peci-debug`
    - always invoke `bmc-peci-debug`; never compose final commands inside `bmc-tpmi-debug`
    - use the exact invocation form `/bmc-peci-debug --docs-root "<docs-root>" -- <request>`
    - build `<request>` from the canonical delegation payload below, preserving field names and field order
    - require `bmc-peci-debug` to return the final `peci_cmds` and the assumptions that must hold on the target BMC system
    - if required fields are still missing, stop and resolve the missing TPMI inputs before asking for final command composition

8. Validate the generated commands on the BMC system in sequence only when the user requests validation and non-secret connection details are available. If authentication requires a secret, have the user type it directly into the terminal prompt or run the commands manually.

9. Use tpmitool in BMC to validate your final result. Refer tpmitool usage below.

10. If any command fails on the BMC system, classify whether the failure came from TPMI flow derivation or PECI command construction, then run the failure handling flow below with the user.


## domain ID mapping

IMH0 --- Domain ID 8
IMH1 --- Domain ID 9
CBB0 --- Domain ID 0
CBB1 --- Domain ID 1
CBB2 --- Domain ID 2
CBB3 --- Domain ID 3

## default domain ID selection
IMH0
CBB0

## BMC Failure Handling

When a generated TPMI command fails on the BMC system:

1. Capture the exact failing command, error output, target context, and the document section used to derive the command.

2. Work with the user to narrow the root cause. Do not guess. Confirm whether the issue comes from wrong addressing, wrong access method, missing prerequisite state, unsupported platform behavior, bad assumptions from the documents, or incorrect PECI command composition.

3. After the root cause is confirmed, record a reflection entry in `references/reflection.md` with:
        - date
        - failing command
        - observed error
        - target context
        - source document section
        - confirmed root cause
        - correction made
        - prevention rule
        - guidance or workflow update required

4. Update the relevant skill instruction or workflow immediately when the prevention rule changes future behavior. If the confirmed issue is in PECI command composition rather than TPMI flow derivation, update `bmc-peci-debug` guidance instead of duplicating the rule here.

5. Only resume generating or validating additional TPMI commands after the user agrees the root cause is understood and the prevention step is recorded.


## Delegation Payload

Before asking `bmc-peci-debug` to compose commands, `bmc-tpmi-debug` must hand over the payload in the exact format below.

Invocation template:

```text
/bmc-peci-debug --docs-root "<docs-root>" -- compose peci_cmds from this TPMI payload:
objective: <target register or TPMI objective>
access_method: <MMIO|PCI|unknown>
sub_id: <value|0|unknown>
raw_tpmi_offset: <value|unknown>
effective_tpmi_offset: <value|unknown>
atype: <value|N/A|unknown>
bar: <value|N/A|unknown>
seg: <value|unknown>
bus: <value|unknown>
dev: <value|unknown>
func: <value|unknown>
reg: <value|unknown>
data_size: <value|unknown>
target_addr: <value|N/A|unknown>
target_domain: <value|N/A|unknown>
prerequisites: <comma-separated list or none>
document_basis: <comma-separated chapter/table/section references>
expected_operation: <read|write|other>
```

Payload rules:

- preserve the exact field order from the template
- keep every field present on every invocation
- use `N/A` when a field does not apply
- use `unknown` when a field should exist but is not resolved yet
- do not rename fields or collapse multiple fields into prose
- keep `prerequisites` and `document_basis` as single-line comma-separated values
- when `sub_id` affects offset translation, set `effective_tpmi_offset` to the translated value, not the raw `TPMI_Offset`

Required payload fields:

- docs-root
- objective
- access_method
- sub_id
- raw_tpmi_offset
- effective_tpmi_offset
- atype
- bar
- seg
- bus
- dev
- func
- reg
- data_size
- target_addr
- target_domain
- prerequisites
- document_basis
- expected_operation


## Expected Output
Report the full `peci_cmds` transaction flow in chat when commands are generated or validated.

Output requirements:

- include every PECI transaction in execution order
- for each transaction, show the exact PECI request
- for each transaction, show the exact PECI response
- for each request and response pair, include a short parse of the important fields and decoded values
- explain what each transaction proves, derives, or unlocks for the next step
- do not skip intermediate transactions even when the final address or final register value is already known
- end with the final derived TPMI access conclusion and the final command sequence; label it as validated only when it was actually run successfully





## tpmitool usage
Usage:
tpmitool [-h] [-v] [--cpu <cpu num>] [--domain <domain id>] [--sub-id <sub-ID>] <command> [parameters]
Options:
        -h          Display this help information
        -v          Display additional information about the command
        --cpu       CPU to target. Default is 0
        --domain    Domain to target. Default is 0
        --sub-id    Sub ID to target, if applicable. Default is 0
Commands:
        access                      Access a TPMI register <ID Offset [Data]>
