# Copilot Agents Usage Summary

This README summarizes the current agents under `copilot/agents` and when to use each one.

## Quick Usage Map

| #  | Agent                   | Primary Use                                                                                                                                 | Typical Triggers                                                                                                                             | Creator      | Contributors |
| -- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------ |
| 1  | `flash-worker`          | Cheap, fast delegated worker for focused sub-tasks such as codebase exploration, file comparison, batch extraction, and command triage    | Search for symbols, inspect multiple files, compare outputs, extract structured data, run narrow validation, summarize command results       | Community | Li, Tianyang     |
| 2  | `pae-bios`              | Intel Platform Application Engineering BIOS and firmware support                                                                            | BIOS log analysis, debug dump analysis, BIOS code reading, HSD ticket handling, EDS/BWG/HAS/MAS lookup, RAS IVG, silicon init analysis     | Tang, Wenwei | -            |
| 3  | `pae-bmc`               | Intel Platform Application Engineering BMC and OpenBMC support                                                                             | OpenBMC image build, Redfish update, MCTP debug, PECI/TPMI debug, BMC log analysis, recipe/source navigation, remote BMC operation         | Du, Yang | -            |
| 4  | `pae-gpu`               | Intel Platform Application Engineering GPU support                                                                                          | GPU driver debug, GPU hang or TDR analysis, compute workload issue, GuC/HuC/GSC firmware debug, display or media pipeline issue            | Li, Tianyang | -            |
| 5  | `pae-hardware`          | Intel Platform Application Engineering hardware support                                                                                     | Board bring-up, PCIe or CXL debug, memory subsystem debug, signal integrity analysis, power rail analysis, hardware validation              | Li, Shuai | -            |
| 6  | `token-efficient`       | General-purpose coding agent optimized for lower token usage through worker delegation, output discipline, and efficient search/edit habits | General coding task, repo question, debugging request, refactor, code review, multi-step investigation where token efficiency matters       | Community | Li, Tianyang     |

## Notes

- `flash-worker` is the execution-oriented helper agent intended for delegated sub-tasks rather than direct end-user conversations.
- `token-efficient` is the general-purpose coding mode intended to pair higher-value reasoning with low-cost delegated exploration.
- The `README/` subfolder currently contains supporting documentation for token-efficiency guidance.

## Last Updated

- 2026-07-11