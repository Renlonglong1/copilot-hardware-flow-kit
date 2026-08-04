# TPMI Debug Reflections

Append new entries at the end of this file after an error, clarification loop, or corrected workflow.

Use this format for BMC command failures so the root cause and prevention rule are explicit:

## [YYYY-MM-DD] Short title
- failing command:
- observed error:
- target context:
- source document section:
- confirmed root cause:
- correction made:
- prevention rule:
- workflow or instruction updated:

## reflection notes

## [2026-05-26] UFS_CONTROL sub ID 1 offset handling
- failing command: N/A
- observed error: UFS Control Register access would incorrectly use the raw TPMI_Offset when the register sub_id is 1h.
- target context: UFS Control Register (UFS_CONTROL), non-zero sub_id handling
- source document section: UFS_CONTROL register description, UFS_FABRIC_CLUSTER_OFFSET definition
- confirmed root cause: The workflow only treated the register offset like a Sub ID 0 access and did not require a separate translation rule for sub_id 1.
- correction made: Added a workflow rule to parse sub_id before offset calculation and, for UFS_CONTROL with sub_id 1, read UFS_FABRIC_CLUSTER_OFFSET first and compute effective_tpmi_offset = UFS_FABRIC_CLUSTER_OFFSET.OFFSET * 8 + TPMI_Offset.
- prevention rule: Always resolve sub_id before delegating command composition. For non-zero sub_id registers, apply the documented offset translation rule and pass both raw_tpmi_offset and effective_tpmi_offset in the canonical payload.
- sub ID rule reminder: Sub ID 0 registers use effective_tpmi_offset = TPMI_Offset.
- sub ID rule reminder: Sub ID 1 UFS_CONTROL uses effective_tpmi_offset = UFS_FABRIC_CLUSTER_OFFSET.OFFSET * 8 + TPMI_Offset.
- workflow or instruction updated: references/workflow.md, references/instruction.md

## [2026-05-26] UFS_CONTROL cluster selection after sub_id 1 translation
- failing command: tpmitool access 0x2 0x8 --domain 8 --sub-id 1
- observed error: Invalid instance
- target context: UFS Control Register (UFS_CONTROL) on primary IMH UFS, local-cluster-scoped sub_id 1 access
- source document section: UFS_HEADER.LOCAL_FABRIC_CLUSTER_ID_MASK, UFS_FABRIC_CLUSTER_OFFSET, UFS_CONTROL register description, co-design DMR Fabric DVFS TPMI register map
- confirmed root cause: The access used the raw sub_id 1 TPMI offset without first selecting a valid local fabric cluster. UFS status/control registers are cluster-scoped, so the translated offset depends on the chosen cluster ID.
- correction made: Read UFS_HEADER first to discover valid local clusters, then read UFS_FABRIC_CLUSTER_OFFSET and use the matching 8-bit cluster offset byte for the chosen cluster. Co-design confirms that on DMR IMH, cluster 0 is the IO fabric and cluster 1 is the memory fabric. For the validated primary IMH case, LOCAL_FABRIC_CLUSTER_ID_MASK = 0x03, cluster 0 offset byte = 0x02, cluster 1 offset byte = 0x06, effective_tpmi_offset values are 0x18 and 0x38, and the validated MMIO addresses are 0x200a0b8 and 0x200a0d8.
- prevention rule: When UFS exposes multiple local clusters, do not guess cluster 0 or cluster 1. Use LOCAL_FABRIC_CLUSTER_ID_MASK to enumerate valid cluster IDs, choose the cluster that matches the target fabric domain, then compute effective_tpmi_offset from the corresponding UFS_FABRIC_CLUSTER_OFFSET byte before composing final access commands.
- DMR cluster meaning reminder: On DMR IMH, cluster 0 maps to the IO fabric and cluster 1 maps to the memory fabric.
- DMR register naming reminder: On DMR IMH, cluster 0 uses UFS_STATUS/UFS_CONTROL and cluster 1 uses UFS_STATUS_FABRIC_1/UFS_CONTROL_FABRIC_1.
- DMR die-scope reminder: DMR CBB exposes only one local fabric cluster, cluster 0.
- DMR topology reminder: IMH exposes two local fabric clusters, while CBB exposes one local fabric cluster.
- workflow or instruction updated: references/reflection.md
