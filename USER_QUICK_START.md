# Copilot Hardware Flow Kit - User Quick Start

Copyright (c) Team PAE FW.

Author: Li Renlong  
Nickname: longlin

This document is for internal users who want to quickly set up a new PC or Copilot environment and bring Copilot into the hardware development and debug workflow.

# sample

请使用 ips-hsd-repro-flow skill，帮我分析并验证 IPS/HSD <文章ID>。

目标：
1. 从 HSD database 提取问题描述、owner、BKC/软件版本、平台配置、客户复现步骤、fix/root cause/workaround。
2. 根据 BKC 匹配远端 .bin 镜像。
3. SSH 到对应控制机，执行烧录、启动日志抓取和 MLC/指定测试。
4. 判断是否复现，并输出问题解决程度和初步原因推测。
5. 保存 Markdown 报告到 copilot-hardware-flow-kit\out。

测试类型：跨NUMA MLC bandwidth_matrix
平台/机器：如果不确定，请自动从 HSD 和配置中判断

更短也可以：

请用 ips-hsd-repro-flow skill 处理 HSD 14025984558：提取问题和 BKC，匹配远端 bin，烧录复现，跑 MLC，最后生成复现报告。





## 1. Copy the Kit

Copy the whole folder to your local PC:

```text
C:\Users\rli\copilot-hardware-flow-kit
```

Recommended location on a new PC:

```text
C:\Users\<your-user>\copilot-hardware-flow-kit
```

Keep the directory structure unchanged.

## Optional: Start the Local IPS/HSD Copilot UI

The kit includes a portable local web UI for IPS/HSD analysis and hardware reproduction planning:

```powershell
cd C:\Users\rli\copilot-hardware-flow-kit

powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1
```

Start without opening a local browser:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -NoBrowser
```

Open:

```text
http://10.239.79.61:8765/
```

The UI has three modes:

1. 简洁模式：fill in task information, click `开始执行`, and wait for the result/owner notification.
2. 详细模式：generate/edit the plan first, then confirm execution.
3. 全自动模式：enter the creator name and HSD Query ID to create a persistent Query task. Multiple Query tasks can run in parallel; use `共享 Query 任务管理` to monitor output, current IPS, status, reports, and cancel a task.

The configured UI address can change if the PC's intranet IP changes. Check and update `server.host` and `server.reportBaseUrl` in `config\ips-copilot-ui.template.json`, then restart the UI. The inbound firewall rule must use the same local IP.

Optional: enable `检索相似 IPS 获取历史经验` when you want Copilot to search HSD/HSDES for similar issues and include reusable experience in the analysis/report.

Optional: enable `下载并分析客户附件` when customers uploaded log/config/package/Overview files and you want Copilot to include them in the report.

Stage 2 defaults to notifying the HSD/IPS owner. Enable `自动发送给 HSD owner` only when you want the script to add `-Send` and send without manual review; otherwise it opens an Outlook draft.

Stage 2 defaults to subprocess mode so the UI can show live output. If the UI-spawned Copilot process lacks shell/tool permissions, set `copilot.stage2Mode` to `handoff` in `config\ips-copilot-ui.template.json`.

The default UI Copilot command includes `--allow-all`. Use startup flags for subprocess permissions; interactive slash commands such as `/allow-all` may not execute when sent through subprocess stdin.

Details:

```text
docs\ips_copilot_ui.md
```

## 2. Install and Log In to Copilot CLI

Install or open GitHub Copilot CLI, then log in:

```text
/login
```

Useful Copilot CLI commands:

```text
/model       Select model
/cwd         Check or change working directory
/memory      Check cross-session memory
/resume      Resume previous sessions
/help        Show help
```

Set the working directory to this kit:

```text
/cwd C:\Users\<your-user>\copilot-hardware-flow-kit
```

Then ask Copilot to read:

```text
docs\AI_QUICK_INDEX.md
README.md
.github\copilot-instructions.md
```

For token savings, read `docs\AI_QUICK_INDEX.md` first and only open the detailed skill/doc matching the task.

## 3. Configure Server-Specific Settings

Copy the template:

```powershell
Copy-Item .\config\hardware-flow.template.json .\config\hardware-flow.<server-name>.json
```

Update these fields:

```text
ssh.user
ssh.host
remote.emulator.exe
remote.powerSplitter.exe
remote.serial.ports.cpu
remote.serial.ports.bmc
flow.defaultBinFile
flow.logRoot
hostOs.mlcDir
```

For the validated DBGSH05 setup, use:

```text
config\hardware-flow.dbgsh05.json
```

## 4. Prepare SSH

The hardware scripts use passwordless SSH. Configure it once for each Windows control server; do not use RDP as the automation transport.

### 4.1 Configure the Windows Control Server

Log in to the target Windows server through its approved management method (for example, RDP) and open an **Administrator PowerShell** window. Install and enable the built-in OpenSSH Server:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}
```

If `sshd` is already installed, run only the service and firewall commands. Confirm that TCP port 22 is allowed by any applicable network policy.

### 4.2 Create a Local SSH Key

On the Copilot PC, confirm that the Windows OpenSSH client is available, then create a dedicated Ed25519 key only if you do not already have one:

```powershell
Get-Command ssh, ssh-keygen
ssh-keygen -t ed25519 -f "$HOME\.ssh\id_ed25519" -C "copilot-hardware-flow"
Get-Content "$HOME\.ssh\id_ed25519.pub"
```

Keep the private key at `$HOME\.ssh\id_ed25519`; never copy it to the server or commit it to this repository. Do not share the private key, passwords, tokens, or Kerberos ticket contents.

### 4.3 Authorize the Public Key on the Control Server

Copy **only** the public-key line printed by the preceding command to the target server. For a non-administrator account, save it as:

```text
C:\Users\<remote-user>\.ssh\authorized_keys
```

For an account in the local `Administrators` group, the default Windows OpenSSH configuration commonly uses:

```text
C:\ProgramData\ssh\administrators_authorized_keys
```

On the target server, restrict the authorized-keys file so that the remote account (or `Administrators` for the administrator file) and `SYSTEM` can read it. Consult the target server's `C:\ProgramData\ssh\sshd_config` if its administrator-key path has been customized, then restart the service after configuration changes:

```powershell
Restart-Service sshd
```

### 4.4 Verify Passwordless Access

Verify connectivity with a harmless command. Replace the user and host with the server-specific `ssh.user` and `ssh.host` values:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 <remote-user>@<host> "hostname"
```

`BatchMode=yes` ensures the command fails rather than prompting for a password. After it succeeds, confirm passwordless SSH from your Copilot PC to the configured Windows hardware server:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json
```

If the connection fails, inspect the target server's OpenSSH logs and verify that `sshd` is running, port 22 is reachable, the public key is in the correct authorized-keys file, and the file permissions meet the target's OpenSSH policy.

## 5. Run the Validated One-Pass Hardware Flow

For BHS uPLR2 / DBGSH05, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

This command performs:

1. SSH precheck.
2. BIN hash and tool path checks.
3. DediProg EM100 GUI conflict cleanup.
4. PowerSplitter poweroff.
5. EM100 `smucmd.exe` flash and verify.
6. COM3/COM4 raw boot log capture.
7. Boot evidence analysis.
8. Optional MLC baseline test through COM3.

Important rule:

```text
Do not start long serial capture unless flash has already passed.
```

Flash success requires all of:

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

## 6. Run HSD Article Lookup

For HSD/HSDES article extraction:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <article-id>
```

If Python access returns generic HTML `403 Access Denied`, use the validated curl direct fallback:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <article-id> -ForceCurlDirect
```

Never ask users for passwords, cookies, SSO tokens, service tokens, or Kerberos ticket contents. Use the existing Windows/Kerberos login context.

## 7. Recommended Copilot Prompt

Use this prompt after the kit is copied and config is updated:

```text
请先阅读 C:\Users\<your-user>\copilot-hardware-flow-kit 中的 README.md、.github\copilot-instructions.md、docs\migration_to_new_copilot.md。
然后按 BHS uPLR2 validated flow 跑一遍：
配置文件：config\hardware-flow.<server-name>.json
要求：烧录失败立即诊断和自恢复；烧录成功后再开电抓 COM3/COM4；保存完整原始日志后再分析；最后跑 MLC baseline。
```

## 8. Development Workflow With Copilot

Recommended daily workflow:

1. Put reusable knowledge into `docs\`.
2. Put repeatable commands into `scripts\`.
3. Put server-specific values into `config\`.
4. Ask Copilot to update this kit whenever a new issue is debugged or a new flow is validated.
5. Keep raw logs on the hardware server under timestamped folders.

Do not commit credentials, private keys, customer secrets, or internal tokens into this kit.

## 9. Ownership and Copyright Notice

This kit is maintained for Team PAE FW hardware enablement, debug, and automation workflows.

```text
Team: Team PAE FW
Author: Li Renlong
Nickname: longlin
Purpose: Copilot-assisted hardware flow migration, automation, debug, and knowledge reuse
```

All scripts and documents in this kit are intended for authorized internal development and validation use only. Redistribution outside the approved team or project scope requires approval from the owner or responsible team.
