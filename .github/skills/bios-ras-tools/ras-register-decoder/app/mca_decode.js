/**
 * MCA (Machine Check Architecture) Error Code Decoder
 * 
 * Decodes MSCOD and MCACOD fields from IA32_MCi_STATUS registers
 * based on GNR EDS Section 19.2 encoding tables.
 */

// =============================================================================
// Bank-to-IP Mapping
// =============================================================================

const MCA_BANK_IP = {
    0: "IFU", 1: "DCU", 2: "DTLB", 3: "MLC", 4: "Ubox",
    5: "UPI", 6: "PCU", 7: "CHA", 8: "Reserved", 9: "LLC",
    10: "Reserved", 11: "MSE", 12: "B2CMI",
    13: "MCCHAN", 14: "MCCHAN", 15: "MCCHAN", 16: "MCCHAN",
    17: "MCCHAN", 18: "MCCHAN", 19: "MCCHAN", 20: "MCCHAN",
    21: "MCCHAN", 22: "MCCHAN", 23: "MCCHAN", 24: "MCCHAN",
    25: "Unused", 26: "Unused", 27: "Unused", 28: "Unused",
    29: "Unused", 30: "Unused", 31: "Unused",
};

// =============================================================================
// MSCOD Encoding Tables (from GNR EDS 19.2)
// =============================================================================

// Table 126: IFU MCA Encoding (MSCOD + MCACOD combined)
const IFU_ENCODING = [
    { mscod: 0x0000, mcacod: 0x0005, desc: "PRF parity error" },
    { mscod: 0x0001, mcacod: 0x0005, desc: "DSB Data parity error" },
    { mscod: 0x0005, mcacod: 0x0005, desc: "DSB offset / NATA (BPU-TA) parity error - correctable" },
    { mscod: 0x0004, mcacod: 0x0005, desc: "DSB Tag parity error - correctable" },
    { mscod: 0x0002, mcacod: 0x0005, desc: "ms patch ram parity error - uncorrectable" },
    { mscod: 0x000B, mcacod: 0x0005, desc: "msrom parity (infant mortality) - uncorrectable" },
    { mscod: 0x0016, mcacod: 0x0005, desc: "ms uniq rom parity (infant mortality) - uncorrectable" },
    { mscod: 0x0009, mcacod: 0x0005, desc: "mspatch CAM parity error - uncorrectable" },
    { mscod: 0x000A, mcacod: 0x0005, desc: "mspatch data parity error - uncorrectable" },
    { mscod: 0x0003, mcacod: 0x0005, desc: "IQ LIP, iqarrest Parity Error - uncorrectable" },
    { mscod: 0x0007, mcacod: 0x0005, desc: "idq uop parity - uncorrectable" },
    { mscod: 0x0008, mcacod: 0x0005, desc: "BIQ Parity - uncorrectable" },
    { mscod: 0x000D, mcacod: 0x0005, desc: "SDB parity error" },
    { mscod: 0x000E, mcacod: 0x0005, desc: "RS/IDQ imm parity error" },
    { mscod: 0x000F, mcacod: 0x040A, desc: "Execution Residue Checking - uncorrectable" },
    { mscod: 0x0006, mcacod: 0x0005, desc: "TMUL array parity error - uncorrectable" },
    { mscod: 0x0010, mcacod: 0x0005, desc: "RS parity errors (rsbpc) - uncorrectable" },
    { mscod: 0x000C, mcacod: 0x0005, desc: "RAT parity error (freelist) - uncorrectable" },
    { mscod: 0x0011, mcacod: 0x0005, desc: "RAT parity error (rahtc) - uncorrectable" },
    { mscod: 0x0012, mcacod: 0x0005, desc: "RAT parity error (roalc) - uncorrectable" },
    { mscod: 0x0013, mcacod: 0x0005, desc: "Immd Folding EU, uop error at RAT - uncorrectable" },
    { mscod: 0x0014, mcacod: 0x0005, desc: "Immd Folding Data, uop error at RAT - uncorrectable" },
    { mscod: 0x0015, mcacod: 0x0005, desc: "Immd Folding MEM, uop error at RAT - uncorrectable" },
    { mscod: 0x0018, mcacod: 0x0005, desc: "ROBTTD Array Parity Error - uncorrectable" },
    { mscod: 0x0003, mcacod: 0x0010, desc: "IFU iTLB parity error with DSB hit" },
    { mscod: 0x0006, mcacod: 0x0010, desc: "IFU iTLB parity error (on FERestart)" },
    { mscod: 0x0004, mcacod: 0x0150, desc: "IFU IC data parity error (on FERestart)" },
    { mscod: 0x0005, mcacod: 0x0150, desc: "IFU IC tag parity error (on FERestart)" },
    { mscod: 0x000C, mcacod: 0x0150, desc: "IFU poison (poisoned data received on icache miss) - uncorrectable" },
    { mscod: 0x0002, mcacod: 0x0150, desc: "DSB hit with parity error + IFU tag miss - uncorrectable" },
    { mscod: 0x0000, mcacod: 0x0406, desc: "Rob MC Trusted Path - uncorrectable" },
    { mscod: 0x0002, mcacod: 0x0406, desc: "Patch Ram Trust MCA - uncorrectable" },
];

// Table 127: DCU MCA Encoding (MSCOD uses wildcard ??, match lower byte)
const DCU_ENCODING = [
    { mscod_mask: 0x00FF, mscod_val: 0x0020, mcacod: 0x0401, desc: "APIC stores/loads Unsupported data size - uncorrectable" },
    { mscod_mask: 0x00FF, mscod_val: 0x0020, mcacod: 0x0404, desc: "APIC loads/stores hitting data/tag parity errors - uncorrectable" },
    { mscod_mask: 0x00FF, mscod_val: 0x0010, mcacod: 0x0174, desc: "WBINVD hitting tag/data parity error" },
    { mscod_mask: 0x00FF, mscod_val: 0x0010, mcacod: 0x0134, desc: "DCU Data - Load Poison (coming from MLC)" },
    { mscod_mask: 0x00FF, mscod_val: 0x0000, mcacod: 0x0124, desc: "Tag parity error on store" },
    { mscod_mask: 0x00FF, mscod_val: 0x0000, mcacod: 0x0114, desc: "Load read error" },
    { mscod_mask: 0x00FF, mscod_val: 0x0000, mcacod: 0x0184, desc: "Snoop confirms hitting tag/data parity error" },
    { mscod_mask: 0x00FF, mscod_val: 0x0000, mcacod: 0x0164, desc: "Prefetcher tag error - correctable" },
    { mscod_mask: 0x00FF, mscod_val: 0x0000, mcacod: 0x0174, desc: "DCU evict parity error" },
    { mscod_mask: 0x00FF, mscod_val: 0x0011, mcacod: 0x0134, desc: "Stuffed load - load poison from MLC - uncorrectable" },
];

// Table 128: DTLB MCA Encoding
const DTLB_ENCODING = [
    { mscod: 0x0000, mcacod: 0x0014, desc: "DTLB Tag - uncorrectable" },
    { mscod: 0x0001, mcacod: 0x0014, desc: "DTLB Data - uncorrectable" },
    { mscod: 0x0000, mcacod: 0x0019, desc: "STLB Tag - correctable" },
    { mscod: 0x0001, mcacod: 0x0019, desc: "STLB Data" },
    { mscod: 0x0003, mcacod: 0x0019, desc: "PDE/EPDE data parity - uncorrectable" },
    { mscod: 0x0002, mcacod: 0x0019, desc: "PDE/EPDE tag parity - correctable" },
    { mscod: 0x0002, mcacod: 0x0005, desc: "Fast Scratchpad - uncorrectable" },
    { mscod: 0x000D, mcacod: 0x0005, desc: "ICLB Attributes Parity Error - uncorrectable" },
    { mscod: 0x0004, mcacod: 0x0005, desc: "Seg register file - uncorrectable" },
    { mscod: 0x0003, mcacod: 0x0406, desc: "Trust IEU - uncorrectable" },
    { mscod: 0x0004, mcacod: 0x0406, desc: "Trust AGU - uncorrectable" },
];

// Table 129: MLC MCA Encoding (MSCOD uses MLC MSCOD Decoder - Table 130)
const MLC_ENCODING = [
    { mscod: null, mcacod: 0x0400, desc: "WDTimeout (3 strike) - uncorrectable" },
    { mscod: 0x0000, mcacod: 0x040E, desc: "Power Management Agent Hardware Error - uncorrectable" },
    { mscod: 0x00C0, mcacod: 0x0406, desc: "Trust - uncorrectable" },
    { mscod: 0xC010, mcacod: 0x0135, desc: "Data read column detect - correctable" },
    { mscod: null, mcacod: 0x0405, desc: "SQDB or IDI (addr/data) parity - uncorrectable" },
    { mscod: null, mcacod: 0x0135, desc: "Data read - DCU RD, RFO, ITOM" },
    { mscod: null, mcacod: 0x0151, desc: "Instr fetch - IFU CRD (code read)" },
    { mscod: null, mcacod: 0x0165, desc: "Prefetch - MPL RD, RFO, CRD" },
    { mscod: null, mcacod: 0x0179, desc: "Fill/Evict - eviction" },
    { mscod: null, mcacod: 0x0145, desc: "Data write - DCU WB" },
    { mscod: null, mcacod: 0x0185, desc: "Snoop - probe/confirm" },
    { mscod: null, mcacod: 0x0189, desc: "Snoop" },
    { mscod: null, mcacod: 0x0129, desc: "MLC Flush (ECC error on tag or data)" },
    { mscod: null, mcacod: 0x0409, desc: "Error during C6 restore - uncorrectable" },
    { mscod: null, mcacod: 0x04AC, desc: "Internal error code - uncorrectable" },
    { mscod: null, mcacod: 0x0115, desc: "Generic read - SETMON (zlen) - uncorrectable" },
];

// Table 130: MLC MSCOD Decoder (field-based)
// Fields: C6SRAM[9:8], Misc[7:6], Data[5:4], MESI[3:2], Tag[1:0]
// 00=no err, 01=C err, 10=UC err, 11=special
const MLC_MSCOD_FIELDS = {
    "C6SRAM": { shift: 8, mask: 0x3, values: { 0: "No Err", 1: "Correctable", 2: "Uncorrectable" } },
    "Misc":   { shift: 6, mask: 0x3, values: { 0: "No Err", 1: "SQ/IDI Err", 2: "SQ/IDI Err", 3: "Trust" } },
    "Data":   { shift: 4, mask: 0x3, values: { 0: "No Err", 1: "Correctable", 2: "Uncorrectable", 3: "Poison+no Fwd" } },
    "MESI":   { shift: 2, mask: 0x3, values: { 0: "No Err", 1: "Correctable", 2: "Uncorrectable" } },
    "Tag":    { shift: 0, mask: 0x3, values: { 0: "No Err", 1: "Correctable", 2: "Uncorrectable" } },
};

// Table 131-138: UBOX MSCOD Encoding (Bank 4)
const UBOX_MSCOD = {
    // Table 131: HW Errors (MCACOD 407h)
    0x8001: "Unsupported Opcode",
    0x8002: "Misaligned, Rd, SMM",
    0x8003: "Misaligned, Wr, SMM",
    0x8004: "Misaligned, Rd, !SMM",
    0x8005: "Misaligned, Wr, !SMM",
    0x8006: "Misaligned, Rd, SMM",
    0x8007: "Misaligned, Wr, SMM",
    0x8008: "Misaligned, Rd, !SMM",
    0x8009: "Misaligned, Wr, !SMM",
    0x800A: "SMI Timeout",
    0x800B: "Lock Master Timeout",
    0x800C: "GPSB Parity Error",
    0x800D: "SAI Error",
    0x800E: "Semaphore Error",
    // Table 132: B2UBOX (MCACOD 407h)
    0x8000: "Poison",
    0x800F: "VN1 NCB Ingress Overflow",
    0x8010: "VN1 NCS Ingress Overflow",
    0x8011: "VN0 NCB Ingress Overflow",
    0x8012: "VN0 NCS Ingress Overflow",
    0x8015: "VN1 NCB Crd Overflow",
    0x8016: "VN1 NCS Crd Overflow",
    0x8017: "VN0 NCB Crd Overflow",
    0x8018: "VN0 NCS Crd Overflow",
    0x801C: "SGX_Doorbell_Error",
    0x801E: "Incorrect Bank Index",
    0x801D: "FullBank Invalid Error",
    0x801F: "Bad Fuse Pull",
};

const UBOX_MCACOD = {
    0x0407: "UBOX HW/Internal Error",
    0x040B: "Scan-at-Field Error",
    0x040C: "Shutdown Suppression Error",
    0x0412: "SCF Bridge Error (B2HOT/B2CXL/B2UPI)",
    0x0413: "SCF Sub IP Internal Parity Error",
};

// Table 133: Scan-at-Field (MCACOD 40Bh)
const UBOX_SAF_MSCOD = {
    0x0006: "Scan failure",
};

// Table 134: Shutdown Suppression (MCACOD 40Ch)
const UBOX_SHUTDOWN_MSCOD = {
    0x0001: "CR4_MCE_CLEAR: MCE when CR4.MCE is clear",
    0x0002: "MCE_MCIP_SET: MCE when MCIP bit is set",
    0x0003: "MCE_UNDER_WFS: MCE under Wait-for-SIPI",
    0x0004: "MCE_LT_HANDSHAKE: Unrecoverable error during security flow",
    0x0005: "TRIPLE_FAULT: SW triple fault shutdown",
    0x0006: "VMX_ABORT: VMX exit consistency check failures",
    0x0007: "RSM_CONSISTENCY_FAIL: RSM consistency check failures",
    0x0008: "SMM_PROTECTED_ENTRY_FAIL: Invalid conditions on protected mode SMM entry",
    0x0009: "UCODE_PATCH_LOAD_FAIL: Unrecoverable error during security flow",
};

// Table 139-140: UPI MSCOD Encoding (Bank 5)
const UPI_MSCOD = {
    // UC errors
    0x0000: "UC Phy Initialization Failure (NumInit)",
    0x0001: "UC Phy Detected Drift Buffer Alarm",
    0x0002: "UC Phy Detected Latency Buffer Rollover",
    0x0010: "UC LL Rx detected CRC error: unsuccessful LLR (entered Abort state)",
    0x0011: "UC LL Rx Unsupported/Undefined packet",
    0x0012: "UC LL or Phy Control Error",
    0x0013: "UC LL Rx Parameter Exception",
    0x0014: "UC LL TDX Failure",
    0x0015: "UC LL SGX Failure",
    0x0016: "UC LL Tx SDC Parity Error",
    0x0017: "UC LL Rx SDC Parity Error",
    0x0018: "UC LL FLE Failure",
    0x001F: "UC LL Detected Control Error from UFI2UPI",
    // Correctable errors
    0x0020: "COR Phy Initialization Abort",
    0x0021: "COR Phy Inband Reset",
    0x0022: "COR Phy Lane failure, recovery in x8 width",
    0x0023: "COR Phy L0c error corrected without Phy reset",
    0x0024: "COR Phy L0c error triggering Phy reset",
    0x0025: "COR Phy L0p exit error corrected with reset",
    0x0030: "COR LL Rx detected CRC error: successful LLR without Phy Reinit",
    0x0031: "COR LL Rx detected CRC error: successful LLR with Phy Reinit",
};

// Table 141-142: PCU/PUNIT MSCOD Encoding (Bank 6)
const PCU_MSCOD = {
    // HW Errors
    0x0002: "PMU microcontroller uncorrectable error",
    0x0003: "PMU microcontroller uncorrectable error",
    0x0008: "PMU microcontroller error",
    0x0009: "PMU microcontroller error",
    0x000A: "PMU microcontroller patch load error",
    0x000B: "PMU microcontroller POReqValid error",
    0x0010: "PMU TeleSRAM double-bit ECC error",
    0x0020: "Power Management Agent signaled error (UCNA, may be informational)",
    0x0080: "S3M signaled error",
    0x00A0: "PMU HPMSRAM double-bit ECC error",
    0x00B0: "PMU TPMISRAM double-bit ECC error",
    // FW Errors
    0x0900: "MCA_TSC_DOWNLOAD_TIMEOUT",
    0x0B00: "MCA_GPSB_TIMEOUT",
    0x0C00: "MCA_PMSB_TIMEOUT",
    0x1000: "MCA_PMAX_CALIB_ERROR",
    0x1100: "MCA_INSTANCES_EXCEED: IP Configuration Error",
    0x1A00: "MCA_DISP_RUN_BUSY_TIMEOUT",
    0x1D00: "MCA_MORE_THAN_ONE_LT_AGENT",
    0x2300: "MCA_PCU_SVID_ERROR",
    0x3500: "MCA_SVID_LOADLINE_INVALID",
    0x3600: "MCA_SVID_ICCMAX_INVALID",
    0x4000: "MCA_SVID_VIDMAX_INVALID",
    0x4100: "MCA_SVID_VDDRAMP_INVALID",
    0x4800: "MCA_ITD_FUSE_INVALID",
    0x4900: "MCA_SVID_DC_LL_INVALID",
    0x4A00: "MCA_FIVR_PD_HARDERR",
    0x4C00: "MCA_HPM_DOUBLE_BIT_ERROR_DETECTED",
    0x5600: "SVID_ACTIVE_VID_FUSE_ERROR",
    0x6300: "MCA_SVID_VCCIN_PROTOCOL_ERROR",
    0x6400: "MCA_SPPR_TIMEOUT",
    0x6500: "MCA_HWRS_RESET_COMPLETE_TIMEOUT",
    0x6600: "MCA_MEM_DEVICETYPE_MISMATCH",
    0x6700: "MCA_THERMAL_SENSOR_INVALID",
    0x9900: "MCA_THERMAL_SENSOR_INVALID (UCNA, informational)",
    0x9C00: "MCA_RECOVERABLE_DIE_THERMAL_TOO_HOT (>135°C, UCNA)",
    0xA100: "MCA_PKGS_RECOVERABLE_RESET_PREP_ACK_TIMEOUT (UCNA)",
};

// Table 143-144: CHA MSCOD/MCACOD Encoding (Bank 7)
const CHA_MSCOD = {
    0x03: "SAD_ERR_WB_TO_MMIO",
    0x04: "SAD_ERR_IA_ACCESS_TO_GSM",
    0x05: "SAD_ERR_CORRUPTING_OTHER",
    0x06: "SAD_ERR_NON_CORRUPTING_OTHER",
    0x09: "SAD_ERR_SAD_MISS",
    0x0A: "PARITY_DATA_ERROR",
    0x0B: "CORE_WB_MISS_LLC",
    0x0C: "TOR_TIMEOUT",
    0x0D: "ISMQ_REQ_2_INVLD_TOR_ENTRY",
    0x0E: "HA_STATE_PARITY_ERROR",
    0x0F: "COH_TT_ERR",
    0x16: "MULT_TOR_ENTRY_MATCH",
    0x17: "MULT_LLC_WAY_TAG_MATCH",
    0x18: "BL_REQ_RTID_TABLE_MISS",
    0x19: "AK_REQ_RTID_TABLE_MISS",
    0x1F: "ADDR_PARITY_ERROR",
    0x2A: "ISMQ_UNEXP_RSP",
    0x2B: "TWOLM_MULT_HIT",
    0x2C: "HA_UNEXP_RSP",
    0x2D: "SAD_ERR_RRQWBQ_TO_NONHOM",
    0x2E: "SAD_ERR_IIOTONONHOM",
    0x33: "AK_BL_UQID_PTY_ERROR",
    0x34: "WXSNP_WITH_SNPCOUNT_ZERO",
    0x35: "MEM_PUSH_WR_NS_BACKSNOOP_REQD",
    0x36: "SAD_ERR_UNSECURE_UPI_ACCESS",
    0x37: "CLFLUSH_MMIO_HIT_M",
    0x38: "SAD_ERR_IAL_ABORT",
    0x3D: "SAD_ERR_TDX_ABORT",
    0x3E: "IPQ_AUX_DATA_PARITY_ERR",
    0x3F: "IRQ_AUX_DATA_PARITY_ERR",
    0x40: "TOR_AUX_DATA_PARITY_ERR",
    0x41: "SAD_ERR_ITOM_CFG",
    0x42: "AK_RSP_TDX_ERR",
    0x43: "BL_RSP_TDX_ERR",
    0x44: "AK_RSP_SGX_ERR",
    0x45: "BL_RSP_SGX_ERR",
    0x46: "AK_CXL_RSP_ERR",
    0x47: "BUFFER_OVERFLOW_IRQ",
    0x48: "BUFFER_OVERFLOW_PRQ",
    0x49: "BUFFER_OVERFLOW_IPQ",
    0x4A: "BUFFER_OVERFLOW_RRQ",
    0x4B: "BUFFER_OVERFLOW_WBQ",
};

const CHA_MCACOD = {
    0x010A: "Cache Errors: ERR.G.L2",
    0x0136: "Cache Errors: DRD.D.L2",
    0x0146: "Cache Errors: DWR.D.L2",
    0x0152: "Cache Errors: IRD.I.L2",
    0x0166: "Cache Errors: PREFETCH.D.L2",
    0x017A: "Cache Errors: EVICT.G.L2",
    0x0182: "Cache Errors: SNOOP.I.L2",
    0x0186: "Cache Errors: SNOOP.D.L2",
    0x0405: "Internal/E2E Parity/ECC",
    0x0408: "SAD errors",
};

// Table 145: LLC MSCOD Encoding (Bank 9)
const LLC_MSCOD = {
    0x0001: "UNCORRECTABLE_DATA_ERROR",
    0x0002: "UNCORRECTABLE_TAG_ERR",
    0x0007: "CORRECTABLE_DATA_ERROR",
    0x0008: "MEM_POISON_DATA_ERROR",
    0x000A: "PARITY_DATA_ERROR",
    0x0011: "LLC_TAG_CORR_ERROR",
    0x0012: "LLC_STCV_CRR_ERROR",
    0x0013: "LLC_STCV_UNCORR_ERROR",
    0x0021: "SF_TAG_UNCORR_ERROR",
    0x0022: "SF_TAG_CORR_ERROR",
    0x0023: "SF_STCV_CORR_ERROR",
    0x0024: "SF_STCV_UNCORR_ERROR",
    0x0028: "LLC_TWOLM_CORR_ERROR",
    0x0029: "LLC_TWOLM_UNCORR_ERROR",
    0x0031: "SF_TWOLM_CORR_ERROR",
    0x0032: "SF_TWOLM_UNCORR_ERROR",
    0x0039: "RSF_ST_CORR_ERROR",
    0x003A: "RSF_TAG_UNCORR_ERROR",
    0x003B: "RSF_ST_UNCORR_ERROR",
    0x003C: "RSF_TAG_CORR_ERROR",
};

// Table 146: MSE MSCOD Encoding (Bank 11)
const MSE_MSCOD = {
    0x0001: "Internal Error - structure parity",
    0x0002: "Internal Error - fifo under/overflow",
    0x0003: "Internal Error - internal misc",
    0x0005: "Security Error - SGX NS",
    0x0006: "Security Error - SGX NS 2LM",
    0x0007: "Security Error - integrity",
    0x0008: "Security Error - TD mismatch",
    0x0009: "Internal Error - key ID poison",
    0x000A: "Internal Error - key ID correctable",
    0x000B: "Internal Error - key ID uncorrectable",
    0x000C: "Internal Error - AES parity",
    0x0010: "Internal Error - CMI addr parity",
    0x0011: "Internal Error - CMI TID parity",
    0x0012: "Internal Error - CMI WBE parity",
    0x0013: "Internal Error - CMI data parity",
    0x0014: "Internal Error - CMI malformed packet",
    0x0015: "Internal Error - CMI meta data parity",
};

// Table 147: B2CMI MSCOD Encoding (Bank 12)
const B2CMI_MSCOD = {
    0x0001: "Read ECC error",
    0x0002: "Bucket 1 error",
    0x0003: "Tracker parity error",
    0x0004: "Security mismatch",
    0x0007: "Read completion parity error",
    0x0008: "Response parity error",
    0x0009: "Timeout error",
    0x000A: "Address parity error",
    0x000C: "CMI credit over subscription error",
    0x000D: "SAI mismatch error",
};

// Table 148: MCCHAN MSCOD Encoding (Banks 13-24)
const MCCHAN_MSCOD = {
    0x0001: "Address parity error (APPP)",
    0x0002: "CMI Wr data parity error on sCH0",
    0x2002: "CMI Wr data parity error on sCH1",
    0x0003: "CMI Uncorr/Corr ECC error on sCH0",
    0x2003: "CMI Uncorr/Corr ECC error on sCH1",
    0x0004: "CMI Wr BE parity error on sCH0",
    0x2004: "CMI Wr BE parity error on sCH1",
    0x0005: "CMI Wr MAC parity error on sCH0",
    0x2005: "CMI Wr MAC parity error on sCH1",
    0x0008: "Correctable patrol scrub error",
    0x0010: "Uncorrectable patrol scrub error",
    0x0020: "Correctable spare error",
    0x0040: "Uncorrectable spare error",
    0x0080: "Correctable error for demand or underfill reads",
    0x00A0: "Uncorrectable error for demand or underfill reads",
    0x00B0: "Poison read from memory (poison disabled in MC)",
    0x00C0: "Read 2LM metadata error",
    0x0100: "WDB read Parity error on sCH0",
    0x2100: "WDB read Parity error on sCH1",
    0x0102: "WDB read Uncorr/Corr ECC error on sCH0",
    0x2102: "WDB read Uncorr/Corr ECC error on sCH1",
    0x0104: "WDB BE read parity error on sCH0",
    0x2104: "WDB BE read parity error on sCH1",
    0x0106: "WDB read persistent Corr ECC error on sCH0",
    0x2106: "WDB read persistent Corr ECC error on sCH1",
    0x0108: "DDR link fail",
    0x0109: "Illegal incoming opcode",
    0x0200: "DDR CAP parity or WrCRC error",
    0x0400: "Scheduler address parity error",
    0x0832: "MC internal errors",
    0x0833: "MCTracker Address RF parity error",
};

// =============================================================================
// MCACOD Compound Error Code Decoding (Intel Architecture-Defined)
// Format depends on bit patterns - see Intel SDM Vol 3B, Section 16.9.2
// =============================================================================

const MCACOD_SIMPLE = {
    0x0000: "No Error",
    0x0001: "Unclassified",
    0x0002: "Microcode ROM Parity Error",
    0x0003: "External Error",
    0x0004: "FRC Error",
    0x0005: "Internal Parity Error",
    0x0006: "SMM Handler Code Access Violation",
};

// Transaction Type (TT)
const MCACOD_TT = { 0: "Instruction", 1: "Data", 2: "Generic", 3: "Reserved" };
// Level (LL)
const MCACOD_LL = { 0: "L0", 1: "L1", 2: "L2", 3: "Generic/L3" };
// Request (RRRR) for cache hierarchy
const MCACOD_RRRR = {
    0: "ERR", 1: "RD", 2: "WR", 3: "DRD",
    4: "DWR", 5: "IRD", 6: "PREFETCH", 7: "EVICT", 8: "SNOOP"
};
// Participation (PP) for bus errors
const MCACOD_PP = { 0: "SRC (Local)", 1: "RES (Responded)", 2: "OBS (Observed)", 3: "Generic" };
// Memory/IO (II) for bus errors
const MCACOD_II = { 0: "Memory", 1: "Reserved", 2: "I/O", 3: "Other" };

/**
 * Decode MCACOD using Intel Architecture compound format.
 * Returns a description string or null if not decodable.
 */
function decodeMCAcod(mcacod) {
    // Simple error codes
    if (MCACOD_SIMPLE[mcacod] !== undefined) {
        return MCACOD_SIMPLE[mcacod];
    }

    // TLB Error: 0000 0000 0001 TTLL (bit 4 set, bits 15:5 = 0)
    if ((mcacod & 0xFFF0) === 0x0010) {
        const tt = (mcacod >> 2) & 0x3;
        const ll = mcacod & 0x3;
        return `TLB Error [${MCACOD_TT[tt]}, ${MCACOD_LL[ll]}]`;
    }

    // Memory Hierarchy Error: 0000 0001 RRRR TTLL (bit 8 set, bits 15:9 = 0)
    if ((mcacod & 0xFE00) === 0x0000 && (mcacod & 0x0100) !== 0) {
        const rrrr = (mcacod >> 4) & 0xF;
        const tt = (mcacod >> 2) & 0x3;
        const ll = mcacod & 0x3;
        const reqStr = MCACOD_RRRR[rrrr] || `REQ_${rrrr}`;
        return `Cache Hierarchy Error [${reqStr}.${MCACOD_TT[tt]}.${MCACOD_LL[ll]}]`;
    }

    // Bus/Interconnect Error: 0000 1PPT RRRR IILL (bit 11 set, bits 15:12 = 0)
    if ((mcacod & 0xF000) === 0x0000 && (mcacod & 0x0800) !== 0) {
        const pp = (mcacod >> 9) & 0x3;
        const t = (mcacod >> 8) & 0x1;
        const rrrr = (mcacod >> 4) & 0xF;
        const ii = (mcacod >> 2) & 0x3;
        const ll = mcacod & 0x3;
        const timeout = t ? ", Timeout" : "";
        const reqStr = MCACOD_RRRR[rrrr] || `REQ_${rrrr}`;
        return `Bus/Interconnect Error [${MCACOD_PP[pp]}, ${reqStr}, ${MCACOD_II[ii]}, ${MCACOD_LL[ll]}${timeout}]`;
    }

    // Extended compound: bit 12 set (Filter indication in newer architectures)
    if ((mcacod & 0x1000) !== 0) {
        const base = mcacod & 0x0FFF;
        // Try decoding base as memory hierarchy or bus error
        if ((base & 0x0100) !== 0) {
            const rrrr = (base >> 4) & 0xF;
            const tt = (base >> 2) & 0x3;
            const ll = base & 0x3;
            const reqStr = MCACOD_RRRR[rrrr] || `REQ_${rrrr}`;
            return `Filtered Cache Hierarchy Error [${reqStr}.${MCACOD_TT[tt]}.${MCACOD_LL[ll]}]`;
        }
        if ((base & 0x0800) !== 0) {
            const pp = (base >> 9) & 0x3;
            const t = (base >> 8) & 0x1;
            const rrrr = (base >> 4) & 0xF;
            const ii = (base >> 2) & 0x3;
            const ll = base & 0x3;
            const timeout = t ? ", Timeout" : "";
            const reqStr = MCACOD_RRRR[rrrr] || `REQ_${rrrr}`;
            return `Filtered Bus Error [${MCACOD_PP[pp]}, ${reqStr}, ${MCACOD_II[ii]}, ${MCACOD_LL[ll]}${timeout}]`;
        }
    }

    // Internal Timer Error
    if (mcacod === 0x0400) {
        return "Internal Timer Error";
    }

    // Common uncore MCACOD values (used across CHA, LLC, MSE, B2CMI, UPI, PCU)
    const UNCORE_MCACOD = {
        0x0405: "Internal Parity/ECC Error",
        0x0407: "Internal HW Error",
        0x0408: "SAD Error",
        0x040A: "Execution Residue Checking Error",
        0x040B: "Scan-at-Field Error",
        0x040C: "Shutdown Suppression Error",
        0x040E: "Power Management HW Error",
        0x0412: "SCF Bridge Error",
        0x0413: "SCF Sub IP Internal Parity Error",
    };
    if (UNCORE_MCACOD[mcacod]) {
        return UNCORE_MCACOD[mcacod];
    }
    
    // Internal unclassified
    if ((mcacod & 0xFC00) === 0x0400) {
        return `Internal Error (0x${mcacod.toString(16).toUpperCase()})`;
    }

    return null;
}


// =============================================================================
// Main Decode Function
// =============================================================================

/**
 * Get the bank number from a register name like "IA32_MC13_STATUS"
 * Returns bank number or -1 if not an MC register.
 */
function getMCBankNumber(regName) {
    const match = regName.match(/^IA32_MC(\d+)_/);
    return match ? parseInt(match[1]) : -1;
}

/**
 * Get the IP name for a given bank number.
 */
function getMCBankIP(bank) {
    return MCA_BANK_IP[bank] || "Unknown";
}

/**
 * Decode MSCOD for a given bank.
 * Returns { description, table } or null.
 */
function decodeMSCOD(bank, mscod, mcacod) {
    const ip = getMCBankIP(bank);

    switch (ip) {
        case "IFU": {
            // IFU uses combined MSCOD+MCACOD lookup
            const entry = IFU_ENCODING.find(e => e.mscod === mscod && e.mcacod === mcacod);
            if (entry) return { description: entry.desc, table: "Table 126: IFU MCA Encoding" };
            // Try MSCOD-only match with wildcard MCACOD
            const partial = IFU_ENCODING.find(e => e.mscod === mscod);
            if (partial) return { description: partial.desc + " (MCACOD mismatch)", table: "Table 126: IFU MCA Encoding" };
            return null;
        }
        case "DCU": {
            // DCU uses masked MSCOD (lower byte) + MCACOD
            const entry = DCU_ENCODING.find(e =>
                (mscod & e.mscod_mask) === e.mscod_val && e.mcacod === mcacod
            );
            if (entry) return { description: entry.desc, table: "Table 127: DCU MCA Encoding" };
            // Try MCACOD-only match
            const byMcacod = DCU_ENCODING.find(e => e.mcacod === mcacod);
            if (byMcacod) return { description: byMcacod.desc, table: "Table 127: DCU MCA Encoding" };
            return null;
        }
        case "DTLB": {
            const entry = DTLB_ENCODING.find(e => e.mscod === mscod && e.mcacod === mcacod);
            if (entry) return { description: entry.desc, table: "Table 128: DTLB MCA Encoding" };
            const partial = DTLB_ENCODING.find(e => e.mscod === mscod);
            if (partial) return { description: partial.desc, table: "Table 128: DTLB MCA Encoding" };
            return null;
        }
        case "MLC": {
            // Check exact MSCOD+MCACOD first
            const entry = MLC_ENCODING.find(e =>
                (e.mscod === null || e.mscod === mscod) && e.mcacod === mcacod
            );
            if (entry) {
                let desc = entry.desc;
                // Add MLC MSCOD decoder breakdown if applicable
                if (entry.mscod === null && mscod !== 0) {
                    const breakdown = decodeMLC_MSCOD(mscod);
                    if (breakdown) desc += " | MSCOD: " + breakdown;
                }
                return { description: desc, table: "Table 129/130: MLC MCA Encoding" };
            }
            return null;
        }
        case "Ubox": {
            // Check MCACOD-specific tables
            if (mcacod === 0x040C && UBOX_SHUTDOWN_MSCOD[mscod]) {
                return { description: UBOX_SHUTDOWN_MSCOD[mscod], table: "Table 134: Shutdown Suppression" };
            }
            if (mcacod === 0x040B && UBOX_SAF_MSCOD[mscod]) {
                return { description: UBOX_SAF_MSCOD[mscod], table: "Table 133: Scan-at-Field" };
            }
            if (UBOX_MSCOD[mscod]) {
                return { description: UBOX_MSCOD[mscod], table: "Table 131/132: UBOX MSCOD" };
            }
            return null;
        }
        case "UPI": {
            if (UPI_MSCOD[mscod]) {
                return { description: UPI_MSCOD[mscod], table: "Table 139/140: UPI MSCOD" };
            }
            return null;
        }
        case "PCU": {
            if (PCU_MSCOD[mscod]) {
                return { description: PCU_MSCOD[mscod], table: "Table 141/142: PUNIT MSCOD" };
            }
            return null;
        }
        case "CHA": {
            if (CHA_MSCOD[mscod]) {
                return { description: CHA_MSCOD[mscod], table: "Table 143: CHA MSCOD" };
            }
            return null;
        }
        case "LLC": {
            if (LLC_MSCOD[mscod]) {
                return { description: LLC_MSCOD[mscod], table: "Table 145: LLC MSCOD" };
            }
            return null;
        }
        case "MSE": {
            if (MSE_MSCOD[mscod]) {
                return { description: MSE_MSCOD[mscod], table: "Table 146: MSE MSCOD" };
            }
            return null;
        }
        case "B2CMI": {
            if (B2CMI_MSCOD[mscod]) {
                return { description: B2CMI_MSCOD[mscod], table: "Table 147: B2CMI MSCOD" };
            }
            return null;
        }
        case "MCCHAN": {
            if (MCCHAN_MSCOD[mscod]) {
                return { description: MCCHAN_MSCOD[mscod], table: "Table 148: MCCHAN MSCOD" };
            }
            // Check proprietary range 0x0800-0x082F
            if (mscod >= 0x0800 && mscod <= 0x082F) {
                return { description: "Proprietary error (MISC bits 9:63 contain proprietary info)", table: "Table 148: MCCHAN MSCOD" };
            }
            return null;
        }
        default:
            return null;
    }
}

/**
 * Decode MLC MSCOD using field-based decoder (Table 130).
 */
function decodeMLC_MSCOD(mscod) {
    const parts = [];
    for (const [name, field] of Object.entries(MLC_MSCOD_FIELDS)) {
        const val = (mscod >> field.shift) & field.mask;
        if (val !== 0) {
            const meaning = field.values[val] || `Unknown(${val})`;
            parts.push(`${name}=${meaning}`);
        }
    }
    return parts.length > 0 ? parts.join(", ") : null;
}

/**
 * Decode MCACOD for a given bank.
 * Uses bank-specific table first, then architecture-defined compound encoding.
 */
function decodeMCACOD(bank, mcacod) {
    const ip = getMCBankIP(bank);

    // Check bank-specific MCACOD tables
    if (ip === "CHA" && CHA_MCACOD[mcacod]) {
        return { description: CHA_MCACOD[mcacod], table: "Table 144: CHA MCACOD" };
    }
    if (ip === "Ubox" && UBOX_MCACOD[mcacod]) {
        return { description: UBOX_MCACOD[mcacod], table: "UBOX MCACOD" };
    }

    // Try architecture-defined compound format
    const archDecode = decodeMCAcod(mcacod);
    if (archDecode) {
        return { description: archDecode, table: "Intel MCA Architecture" };
    }

    return null;
}

/**
 * Full decode of an MCi_STATUS register value.
 * Returns an object with decoded MSCOD and MCACOD info.
 */
function decodeMCiStatus(regName, statusValue) {
    const bank = getMCBankNumber(regName);
    if (bank < 0) return null;

    // Check VAL bit (bit 63) - if not set, status is invalid
    if ((statusValue >> 63n) === 0n) return null;

    const ip = getMCBankIP(bank);
    const mscod = Number((statusValue >> 16n) & 0xFFFFn);
    const mcacod = Number(statusValue & 0xFFFFn);

    const mscodResult = decodeMSCOD(bank, mscod, mcacod);
    const mcacodResult = decodeMCACOD(bank, mcacod);

    return {
        bank,
        ip,
        mscod,
        mcacod,
        mscodDecode: mscodResult,
        mcacodDecode: mcacodResult,
    };
}
