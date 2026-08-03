# Remote BKC Inventory on dbgsh05

Host: `10.239.84.44`  
SSH user: `debug`  
Remote root: `C:\Users\debug\Desktop\BKC`  
Captured: `2026-07-13 15:47:07`

Machine-readable inventory: `config\bkc-remote-inventory.dbgsh05.json`.

## Flash Image Selection Notes

- Prefer `128MB full IFWI` files for normal emulator flashing unless the flow explicitly needs split 64 MB images.
- `1P0` / `IBL1P0` in the filename indicates a 1S/1P candidate.
- `_2s` in the filename indicates a 2S/2P candidate.
- In the `35D23` folder, the files without `_2s` are paired with `_2s` variants and are treated as the 1S/1P candidates.
- Small `capsule`, `mmc`, `swap`, `base_*`, `GoldScripts`, and `setup_ubios` binaries are support/component files, not the primary full IFWI selection target.

## Main BKC Candidates

| Version | Socket | Type | Relative path |
| --- | --- | --- | --- |
| 35.D23 | 1S/1P | 128MB full IFWI | `35D23\OKSDCRB1.IPC.0035.D23.2605132239_D1A800009a1_D2A5200020c_D1B5100030e_NA_DMR_IBL_X64.bin` |
| 35.D23 | 2S/2P | 128MB full IFWI | `35D23\OKSDCRB1.IPC.0035.D23.2605132239_D1A800009a1_D2A5200020c_D1B5100030e_NA_DMR_IBL_X64_2s.bin` |
| 35.D23 | 1S/1P | 64MB split/half IFWI | `35D23\OKSDCRB1.IPC.0035.D23.2605132239_D1A800009a1_D2A5200020c_D1B5100030e_NA_DMR_IBL_X64_64MB.bin` |
| 35.D23 | 2S/2P | 64MB split/half IFWI | `35D23\OKSDCRB1.IPC.0035.D23.2605132239_D1A800009a1_D2A5200020c_D1B5100030e_NA_DMR_IBL_X64_64MB_2s.bin` |
| 30.D61 | 1S/1P | 128MB full IFWI | `up982_bkc\OKSDCRB1.JEN.0030.D61.2512170251_DA50000A02_NA_NA_NA_DMR_IBL1P0_X64_Simics.bin` |
| 30.D61 | 1S/1P | 128MB full IFWI | `up982_bkc\OKSDCRB1.JEN.0030.D61.2512170251_DA80000983_NA_NA_NA_DMR_IBL1P0_X64.bin` |
| 30.D59 | 1S/1P | 128MB full IFWI | `OKSDCRB1.CHA.0030.D59.2512161602_DA80000982_NA_NA_NA_DMR_IBL1P0_X64_stitched_IMH1_A0_DMRAP_Unified_Patch_stitched\OKSDCRB1.CHA.0030.D59.2512161602_DA80000982_NA_NA_NA_DMR_IBL1P0_X64_stitched_IMH1_A0_DMRAP_Unified_Patch_stitched.bin` |
| 30.D43 | 1S/1P | 128MB full IFWI | `OKSDCRB1_86B_2025.50.5.01_0030.D43_80000983_0.688.0_1P0_NonIPClean_Trace_DebugSigned_VIS_stitched\OKSDCRB1_86B_2025.50.5.01_0030.D43_80000983_0.688.0_1P0_NonIPClean_Trace_DebugSigned_VIS_stitched.bin` |
| 29.D60 | 1S/1P | 128MB full IFWI | `OKSDCRB1_86B_2025.47.4.01_0029.D60_8000097E_0.662.0_1P0_NonIPClean_Trace_DebugSigned_VIS\OKSDCRB1_86B_2025.47.4.01_0029.D60_8000097E_0.662.0_1P0_NonIPClean_Trace_DebugSigned_VIS.bin` |
| WW46BKC / 29.Dxx generation | unspecified | 128MB full IFWI | `stitched_C41AE.0.BS.1A03.GN.1_WW46BKC_CoVal_8000097E\stitched_C41AE.0.BS.1A03.GN.1_WW46BKC_CoVal_8000097E.bin` |

## Root-Level Bins

| Version | Socket | Type | Relative path |
| --- | --- | --- | --- |
| 29.D50 | unspecified | 128MB full IFWI | `CRB_29D50_VIS_UP982.bin` |
| 29.D60 | 1S/1P | 128MB full IFWI | `OKSDCRB1_86B_2025.47.4.01_0029.D60_8000097E_0.662.0_1P0_NonIPClean_Trace_DebugSigned_VIS.bin` |
| 29.D50 | unspecified | 64MB split/half IFWI | `po_29d50_up982.bin` |
