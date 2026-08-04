RAS-TEST SKILL README
=====================

User-facing document only.
This file is for humans reading the skill usage notes.
The ras-test skill does not need to review this file during execution.

1. What this skill does

ras-test is an end-to-end Intel RAS workflow skill.
It helps the user complete three phases:

- Phase 1: Generate a RAK Python test script from a RAS scenario, IVG recipe, or existing notes
- Phase 2: Send the script to a remote debug machine, run it with RAK, and download the logs
- Phase 3: Analyze the downloaded RAK log package and summarize PASS/FAIL and root cause

This skill is intended for Intel server RAS validation scenarios such as:
- Memory CE/UE
- SDDC / ADDDC
- CSMI thresholding
- PCIe AER
- UPI RAS
- Sparing / patrol scrub / PPR
- CScripts-based injection
- EINJ-based cases when explicitly requested


2. Skill structure

ras-test/
|- SKILL.md
|- README.txt
|- rak_remote_config.ini
|- rak-testscript-generator/
|- rak-remote-runner/
`- rak-log-analyzer/

Sub-skills:
- rak-testscript-generator: generate or review RAK Python test scripts
- rak-remote-runner: upload and run a RAK script on a remote machine
- rak-log-analyzer: analyze the downloaded RAK logs


3. How to use this skill

Typical prompts:
- Generate rak based RAS testscripts and run it remotely
- Review this RAK script, run it on the debug machine, and analyze the logs
- Run testscript on the remote machine and analyze the result
- Analyze the RAK logs under ./rak_results/XXX

Typical workflow:
- If the user only has a scenario or IVG recipe, ras-test starts from Phase 1
- If the user already has a .py script, ras-test skips Phase 1 and starts from Phase 2
- After the remote run completes, ras-test can continue to Phase 3 and analyze the logs


4. Workspace requirements

Before using this skill, create a workspace for the RAS task.
The workspace must contain:

- IVG documents or extracted IVG text used as the test source
- Cscripts User Guide or extracted command reference material when the scenario depends on CScripts commands

Other files in the workspace are typically generated or added during usage, for example:
- generated RAK test scripts
- downloaded RAK logs
- support files created during execution or analysis

Recommended workspace layout at the beginning:

<workspace>/
|- IVG/
|  |- <platform IVG PDF or extracted text>
|- Cscripts_User_Guide/
|  |- <user guide PDF or extracted notes>
`- <other files created later during usage>

Typical workspace layout after using the skill:

<workspace>/
|- IVG/
|  |- <platform IVG PDF or extracted text>
|- Cscripts_User_Guide/
|  |- <user guide PDF or extracted notes>
|- rak_results/
|- <generated or existing RAK scripts>.py
`- <support files>

Notes:
- IVG content is used to understand validation intent, expected flow, and pass/fail targets
- Cscripts User Guide content is used to confirm exact CScripts command syntax and supported usage
- If the workflow is based on IVG but the command details are not grounded by references, the skill should ask for the relevant guide excerpt instead of guessing


5. Required user preparation

5.1 Prepare the local workspace

The user should prepare a dedicated VS Code workspace containing:
- IVG documents for the target platform family
- Cscripts User Guide material if the case depends on CScripts injection or register operations

Only these two inputs are mandatory at the beginning.
Other files, such as generated test scripts and the rak_results directory, are usually created during the workflow.

5.2 Prepare the remote config file

Edit this file before remote execution:
- ./rak_remote_config.ini

Required fields in rak_remote_config.ini:
- host: remote debug machine IP or hostname
- port: SSH port, usually 22
- user: remote SSH username
- password: remote SSH password
- rak_path: remote directory where rak_cui.exe is installed
- case_dir: remote directory where test scripts will be uploaded
- rak_result_dir: local directory where logs will be downloaded
- timeout: maximum run time in minutes

Common optional or per-run field:
- case_file: local script path for the script being executed

The user should update case_file to point to the script that will be run.

5.3 Prepare the remote machine

The remote debug machine must be ready before running Phase 2:
- OpenSSH Server must be enabled and reachable
- The target account must allow SSH login
- RAK must already be installed on the remote machine
- rak_cui.exe must exist under the configured rak_path
- The remote upload directory must exist or be creatable by the user account
- The remote machine must already have the required debug environment, probe access, and platform connectivity

If the case depends on CScripts or ITP access, the remote machine should also already have:
- a working debug probe connection
- required OpenIPC / CScripts environment installed and licensed
- target system powered on and reachable
- any platform-specific debug preconditions satisfied


6. Local software requirements

On the local machine:
- Python must be available
- paramiko must be installed


7. Usage by phase

Phase 1 - Script Generation
- Use when the user provides a scenario, recipe, IVG excerpt, or partial script
- The skill asks for the platform family if missing: OKS, BHS, or EGS
- The skill should not invent RAK APIs, BIOS knobs, or CScripts commands

Phase 2 - Remote Deployment and Execution
- Use when the user already has a final .py script or after Phase 1 completes
- The script is uploaded to the remote case_dir
- The remote machine runs the case with rak_cui.exe
- Logs are downloaded to the local rak_result_dir

Phase 3 - Log Analysis
- Use after Phase 2 or when the user provides a local RAK log package path
- Analyze the RAK HTML report and log files such as:
  - *_cscript.log
  - *_serial.log
  - *_SOL.log
  - *_result.log when available
  - *_BMC_cmd.log when available
- Summarize PASS/FAIL, assertion failures, run-control issues, BIOS flow, and OS/BMC evidence


8. Common failure points

- Missing IVG or guide material for a platform-specific case
- Incorrect remote SSH credentials
- Wrong rak_path or missing rak_cui.exe
- Remote machine not ready for debug or probe connection unstable
- CScripts / OpenIPC / halt() issues on the remote platform
- Logs downloaded successfully but case itself failed inside RAK

When analyzing failures, distinguish between:
- runner success: file upload, remote launch, log download all succeed
- case success: the RAK test itself passes inside the downloaded report/logs


9. Recommended operating model

Best practice for users:
- Put IVG and User Guide documents in the workspace first
- Confirm rak_remote_config.ini is correct before remote execution
- Keep one script per test scenario
- Run the script remotely through ras-test
- Analyze the downloaded logs immediately after execution


10. Summary

ras-test is a three-phase workflow skill for Intel RAS automation:
- generate the test script
- run it remotely with RAK
- analyze the result logs

To use it successfully, the user should prepare:
- a workspace with IVG and User Guide material
- a valid rak_remote_config.ini file
- a remote machine with RAK already installed and usable debug environment
