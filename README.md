# Copilot Hardware Flow Kit

This folder is a portable knowledge and automation kit for running hardware flows through Copilot + SSH.

Current validated flow:

```text
BHS uPLR2 robust full flow
server: debug@10.239.84.53
flash: DediProg EM100 / smucmd.exe
power: PowerSplitterCL.exe
serial: COM3=GNR CPU, COM4=BMC, 115200 8N1
known good run: C:\Users\debug\Desktop\flow_logs\20260623_093722
```

## Start Here

For system ownership transfer and successor onboarding, see
`docs\SYSTEM_HANDOVER.zh-CN.md` and the matching Word document
`docs\SYSTEM_HANDOVER.zh-CN.v1.1.docx`.

For a new Copilot environment, read in this order:

1. `docs\AI_QUICK_INDEX.md`
2. `.github\copilot-instructions.md`
3. Only the skill/doc matching the task

For a strict no-hardware-action machine inventory, start with
`docs\lab_machine_readonly_audit_2026-08-06.md`. It records the dedicated-identity
and host-key policy, reachable hosts, and explicit audit blockers.

For the split between portable repository files and this computer's untracked runtime
profiles, read `docs\local_runtime_profiles.md`.

For the development rules that keep personal-PC code changes independent from
deployment-machine settings, read `docs\development_deployment_contract.md`.

## Directory Structure

```text
copilot-hardware-flow-kit\
  README.md
  copilot-instructions.md
  .github\
    copilot-instructions.md
    skills\
      bhs-hardware-flow\
        SKILL.md
      ips-ui-plan-stage\
        SKILL.md
      ips-consult-flow\
        SKILL.md
      ips-hsd-repro-flow\
        SKILL.md
      common-ps-py-commands\
        SKILL.md
  config\
    hardware-flow.template.json
    hardware-flow.dbgsh05.json
    hardware-flow.json
    ips-copilot-ui.template.json
    ai-task-router.json
  docs\
    migration_to_new_copilot.md
    bhs_uplr2_robust_full_flow.md
    bhs_uplr2_flow.md
    emulator_powersplitter_cli_notes.md
    AI_QUICK_INDEX.md
    hsd_python_api_notes.md
    ips_copilot_ui.md
    ips_hsd_repro_skill_usage.md
    common_ps_py_commands.md
    ssh_passwordless.md
  scripts\
    Invoke-Remote.ps1
    Test-SshAccess.ps1
    Invoke-Emulator.ps1
    Invoke-PowerSplitter.ps1
    Invoke-HardwareFlow.ps1
    Invoke-BhsUplr2Flow.ps1
    Invoke-BhsUplr2ValidatedFlow.ps1
    Invoke-RemoteBootCapture.ps1
    Capture-SerialPort.ps1
    Invoke-RemoteMlcSerial.ps1
    Send-OwnerNotification.ps1
    Start-IpsCopilotUi.ps1
    ips_copilot_ui.py
```

## Local IPS/HSD Copilot UI

Start the portable local UI:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1
```

Default URL:

```text
http://127.0.0.1:8765/
```

The UI has two modes:

1. 简洁模式：fill in task information, click `开始执行`, and wait for the result/owner notification.
2. 详细模式：generate and edit the execution plan first, then confirm execution.

The UI also has an execution permission level. `最高授权` tells Copilot to avoid repeated questions for commands inside the user-confirmed plan, but it cannot bypass Copilot CLI, OS, SSH, hardware, or enterprise security restrictions.

The UI can optionally include "检索相似 IPS 获取历史经验" in the plan. When enabled, Stage 2 should search HSD/HSDES for similar issues and summarize reusable root cause, workaround, fix, comments, or configuration experience.

The UI can also include "下载并分析客户附件" in the plan. When enabled, Stage 2 should inspect HSD attachment fields, try to download customer packages with the existing Kerberos/Windows context, extract them under `out\<id>\attachments\`, and summarize Overview/config/log/result files in the report.

The UI defaults to notifying the HSD/IPS owner after Stage 2. If `自动发送给 HSD owner` is checked, Stage 2 should add `-Send`; otherwise it creates an Outlook draft. The subject should include `[Copilot][HSD]`, article ID, task type, and short status; the body should include owner, conclusion summary, and report path.

Stage 1 is encapsulated as:

```text
.github\skills\ips-ui-plan-stage\SKILL.md
```

By default Stage 1 and Stage 2 both run in `subprocess` mode, so the UI output boxes can show Copilot output. If the UI-spawned Copilot process lacks shell/tool permissions, change `copilot.stage2Mode` to `handoff` in `config\ips-copilot-ui.template.json`.

The UI starts Copilot subprocesses with `--allow-all` by default. This enables broad Copilot CLI permissions when supported, but it cannot bypass OS, SSH, hardware, or enterprise security restrictions.

More details:

```text
docs\ips_copilot_ui.md
```

Common reusable PowerShell/Python command templates:

```text
.github\skills\common-ps-py-commands\SKILL.md
docs\common_ps_py_commands.md
```

## Recommended Prompt

```text
请按 BHS uPLR2 robust full flow 跑一遍：
服务器：debug@10.239.84.53
bin 文件：C:\Users\debug\Desktop\BKC\uPLR2\BHSDCRB1.IPC.3545.P03.2511062122_GB01000405_GA10000680_SC03000393_RB0A000133_SP_IP_Clean_Debug_PRQ_DAM_Enabled_1.bin
芯片型号：MX66U1G45G
串口：COM3=GNR CPU，COM4=BMC
串口抓取时间：10分钟
要求：烧录失败立即诊断和自恢复；烧录成功后再开电抓串口；保存完整原始日志后再分析。
```

## Recommended IPS/HSD Reproduction Prompt

```text
请使用 ips-hsd-repro-flow skill，帮我分析并验证 IPS/HSD <文章ID>。

目标：
1. 从 HSD database 提取问题描述、owner、BKC/软件版本、平台配置、客户复现步骤、fix/root cause/workaround。
2. 根据 BKC 在远端 BKC 文件夹中匹配合适的 .bin 镜像。
3. SSH 到对应控制机，执行烧录、启动日志抓取和 MLC/指定测试。
4. 判断是否复现，并输出问题解决程度和初步原因推测。
5. 保存 Markdown 报告到 copilot-hardware-flow-kit\out。

测试类型：<例如 跨NUMA MLC bandwidth_matrix / boot only / 指定命令>
平台/机器：<如果知道就写；不知道可让 Copilot 自动判断>
```

更完整的示例见：

```text
docs\ips_hsd_repro_skill_usage.md
```

## Core Safety Rule

Flash failure is a blocking event. If `smucmd` fails, diagnose and recover immediately. Do not wait 10 minutes for serial logs after a failed flash.

## One-Pass Validated Command

After copying this kit to a new Copilot machine and confirming the server-specific config, use the validated wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

This wrapper performs SSH precheck, optional EM100 GUI conflict cleanup, PowerSplitter poweroff, `smucmd` programming with keyword validation, COM3/COM4 raw boot capture, boot-log analysis, and optional COM3 MLC baseline execution.

## Success Evidence

Flash success requires:

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

Full flow success requires saved COM3/COM4 logs and boot evidence:

```text
COM3: CentOS Stream 9 / gnr-bkc login
COM4: U-Boot / Linux / OpenBMC / login
```

## MLC Test Tool Notes

MLC-related knowledge has been added for portability:

```text
docs\mlc_command_manual.md
```

Validated current Host OS MLC installation:

```text
/root/mlc_v3.11b/mlc
Intel(R) Memory Latency Checker - v3.11b
```

Validated MLC test result directories:

```text
/root/mlc_v3.11b/copilot_mlc_results_20260623_094808
/root/mlc_v3.11b/copilot_mlc_results_20260623_094928
```

Validated commands include:

```bash
./mlc
./mlc --idle_latency
./mlc --latency_matrix
./mlc --bandwidth_matrix
./mlc --peak_injection_bandwidth
./mlc --loaded_latency
./mlc --c2c_latency
./mlc --memory_bandwidth_scan
```

Each command result was saved as an individual `.log` file under the result directory. For a migrated environment, ask Copilot to read `docs\mlc_command_manual.md` before running MLC tests.

## HSDES / HSD Python API Notes

HSDES database search and extraction knowledge has been added for portability:

```text
docs\hsd_python_api_notes.md
```

Use it when migrating this Copilot setup to preserve HSD article lookup, query ID/EQL execution, field extraction, attachment handling, and issue summarization. Validated local setup uses Python 3.14.5 with `requests`, `requests-kerberos`, `certifi`, and `truststore`; HSD API calls should use Kerberos auth plus `truststore.inject_into_ssl()` on Windows.

Validated HSD helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId 14027366976
```

If Python HSD access returns generic HTML `403 Access Denied`, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId 14027366976 -ForceCurlDirect
```
