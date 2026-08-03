# IPS/HSD Copilot UI

This document describes the portable local UI for starting IPS/HSD analysis and hardware reproduction through Copilot CLI.

The UI is intentionally implemented with the Python standard library only. No Streamlit, Flask, Node.js, or browser framework is required.

## Files

```text
scripts\ips_copilot_ui.py
scripts\Start-IpsCopilotUi.ps1
config\ips-copilot-ui.template.json
docs\ips_copilot_ui.md
```

## Start the UI

From the kit root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1
```

Default URL:

```text
http://127.0.0.1:8765/
```

Default mode is `subprocess`, which means the UI starts the configured Copilot CLI command and sends the generated prompt automatically.

## Intranet / VPN Access

The default listener is intentionally limited to `127.0.0.1`. Do not expose this UI directly to the public internet: authorized users can start Copilot subprocesses and submit hardware-flow requests.

For users connected through the corporate intranet or VPN, bind the service to this PC's intranet IP and restrict the inbound firewall rule to the approved VPN or intranet CIDR. Keep the default configuration unchanged so a normal local launch remains private.

1. Find the PC's IPv4 address with `Get-NetIPAddress -AddressFamily IPv4`.
2. Start the UI with that address. Replace the example address with the local PC's actual intranet address:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -Host 10.20.30.40 -Port 8765 -NoBrowser
   ```

3. As an administrator, allow only the approved source CIDR through Windows Firewall. Replace `10.20.0.0/16` with the actual corporate VPN/intranet subnet:

   ```powershell
   New-NetFirewallRule -DisplayName 'IPS Copilot UI (VPN only)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress 10.20.0.0/16
   ```

Users then open `http://10.20.30.40:8765/` while connected to the approved intranet or VPN. If the PC's address changes, use a DHCP reservation or update the launch command and shared URL.

The UI does not implement its own user authentication. If access must be available beyond a trusted VPN/intranet segment, place it behind an organization-managed authenticated reverse proxy rather than opening a public firewall rule.

## UI Modes

### 简洁模式

In simple mode, fill in task information and click:

```text
开始执行
```

The UI generates a default plan internally, starts Stage 2, streams output in the UI, and notifies the HSD/IPS owner after completion.

### 详细模式

Detailed mode keeps the original review flow:

1. Generate a Stage 1 execution plan.
2. Edit/confirm the plan.
3. Start Stage 2.

### 全自动模式：多用户 Query 任务

选择 `全自动模式` 后，填写 **创建人姓名**、HSD saved Query ID、轮询间隔和可选的管理汇总收件人，再点击“创建并启动 Query 任务”。每次提交创建一个独立的持久化任务；不同浏览器会话看到相同的任务列表和实时输出，多个 Query 任务可以并行执行。没有全局 Query 并发上限。

任务状态包括 `queued`、`running`、`waiting_resource`、`cancelling`、`completed`、`failed`、`cancelled` 和 `interrupted`。任务元数据、创建人、轮次、当前 IPS、输出、报告入口和取消原因保存在标准库 SQLite 数据库，默认位置为：

```text
out\ui_task_manager.sqlite3
```

服务启动时，上一进程遗留的活动任务会被标记为 `interrupted`，并且**不会**自动恢复或继续任何硬件操作。创建人由 UI 提供，用于工作追溯；本范围不添加反向代理或身份认证功能。

点击任务卡片上的“取消”可提供持久化取消原因。排队任务立即变为 `cancelled`。运行中任务先变为 `cancelling`，停止轮询和新 IPS，并对当前 Copilot 子进程发送终止信号；超过 `automation.cancellationGraceSeconds` 后仍未退出则强制结束。取消并不能撤销已经完成的硬件动作，任务输出会记录状态和原因。

每个任务只处理本任务生命周期内首次发现的 Open IPS，随后按指定间隔继续轮询。全自动模式仍要求 `copilot.mode` 和 `copilot.stage2Mode` 都为 `subprocess`。

### 硬件资源协调

纯 `extract_ips` / `consult` 不申请硬件资源。`debug_repro` 在完成 HSD 提取、非硬件预检和控制机选择后，且在 SSH 写操作、flash、power cycle、串口控制或 MLC 前，必须使用 UI 注入的 `--task-lock` 命令请求该已登记 machine id 的 SQLite 锁；释放操作在 finally 中执行。相同机器默认并发度为 1，因此不同 Query 任务可并行预检或使用不同机器，但不会同时在同一注册机器执行硬件动作。服务端会在正常结束或取消时释放该任务的锁；重启时为防止遗留子进程，`interrupted` 任务的锁会保留，确认旧进程已停止后才可用同一 `--task-lock ... --action release` 命令人工释放。

这是一项对自动 Query 中 Copilot 执行 prompt 的硬性要求：机器不明、锁不可用或任务取消时不得进行推测性硬件活动。手动 Stage 2 不再因为存在自动 Query 任务而被全局阻塞；在手动硬件操作与自动任务可能使用同一控制机时，操作者必须先确认没有活动硬件锁。

配置项：

```json
{
  "automation": {
    "taskDatabasePath": "out\\ui_task_manager.sqlite3",
    "cancellationGraceSeconds": 15,
    "retentionDays": 90,
    "machineLockWaitSeconds": 3600,
    "perMachineConcurrency": { "default": 1 }
  }
}
```

`perMachineConcurrency` 可按注册 machine id 覆盖默认值；安全默认值为 1。没有 `maxQueryConcurrency` 配置项。

### 全自动汇总报告与管理通知

报告页入口为：

```text
<reportBaseUrl>/reports
```

报告索引按任务、Query ID 和轮次显示历史。新任务报告保存到：

```text
out\auto_reports\query_<QueryID>\task_<TaskId>\round_<N>\round.json
```

旧版 `out\auto_reports\query_<QueryID>\round_<N>\round.json` 报告保留并仍可浏览；不会执行破坏性迁移。每轮详情保留 IPS、诊断类型、测试状态、owner 邮件正文和登记的 Markdown 报告链接。管理汇总收件人只收到每轮汇总链接，IPS owner 仍只收到其详细诊断邮件和附件。

配置 `server.reportBaseUrl` 后，管理邮件才会包含可访问的链接；不要将报告页直接暴露到公网。

## Two-Stage Safety Flow

### Stage 1: Generate Plan

The user enters:

- IPS/HSD ID
- machine-selection mode: automatic matching or manual control-machine selection
- SSH control machine from the registered-machine dropdown when manual mode is selected
- task type: extract IPS / consult / debug reproduction
- execution permission level
- whether to search similar IPS/HSD issues for reusable experience
- whether to download and analyze customer attachments
- whether to notify owner/test recipient after completion
- test target
- notes

Then click:

```text
生成执行计划
```

The generated Stage 1 prompt explicitly forbids:

- HSD database access
- SSH connections
- BKC folder enumeration
- flashing
- power cycle
- opening serial ports
- running MLC
- any hardware action

The expected output is a user-facing text plan. Stage 1 only lets AI understand the UI fields and generate the next execution plan. It does **not** actually read the IPS/HSD article.

For example, if the user chooses `consult`, Stage 1 should plan to read the IPS/HSD article in Stage 2 and produce analysis suggestions only. It should not include flashing or MLC execution.

Stage 1 is encapsulated as a skill:

```text
.github\skills\ips-ui-plan-stage\SKILL.md
```

## Machine Selection

The UI loads the registered control machines from:

```text
config\lab-machine-inventory.json
```

### Automatic Matching

Enable:

```text
自动匹配机器（根据 IPS/HSD 提取的平台环境选择）
```

The SSH dropdown is disabled. In Stage 2, Copilot first extracts the IPS/HSD platform, model, topology, and requested test, then applies the inventory's platform aliases and capability rules. GNR/BHS and DMR/Oak Stream cannot be substituted for each other. An unknown or conflicting platform is a blocking result, not a fallback to an arbitrary machine.

### Manual Selection

When automatic matching is disabled, select one of the registered choices, for example:

```text
dbgsh05 (GNR) - debug@10.239.84.53
dbgsh12 (DMR) - debug@10.239.84.44
dbgsh16 (DMR) - debug@10.238.12.230
```

Stage 2 is restricted to the selected machine and must still verify that its platform, BKC, and capabilities match the IPS/HSD request. To add or change a machine, update `config\lab-machine-inventory.json`; the UI dropdown is generated from that file.

### Stage 2: Confirm and Execute

The UI shows the text plan in an editable text area. The user can:

- delete steps
- add steps
- edit SSH host
- edit bin path
- edit MLC commands
- change log capture duration
- disable hardware steps

When Stage 1 finishes, its output is automatically copied into the editable text plan box.

Before execution, the user must check the confirmation checkbox. By default, Stage 2 starts the configured Copilot CLI subprocess and streams output into the Stage 2 output box.

If the UI-spawned Copilot process lacks shell/tool permissions, switch to `handoff` mode in `config\ips-copilot-ui.template.json`:

```json
{
  "copilot": {
    "stage2Mode": "handoff"
  }
}
```

In `handoff` mode, the UI writes the final Stage 2 prompt to:

```text
inbox\ui_tasks\
```

Then copy the generated handoff sentence into the current Copilot CLI session, for example:

```text
请读取并执行 UI 确认后的阶段二任务：C:\Users\<user>\copilot-hardware-flow-kit\inbox\ui_tasks\ui_stage2_task_<timestamp>.md
```

## Task Types

| Task type | Meaning |
| --- | --- |
| `extract_ips` | Extract HSD/IPS information only. No hardware action. |
| `consult` | Analyze the issue and provide suggestions. No hardware action. |
| `debug_repro` | After user confirmation, allow BKC matching, flashing, boot capture, tests, and report generation. |

Consultation mode is encapsulated as:

```text
.github\skills\ips-consult-flow\SKILL.md
```

## Permission Levels

The UI includes an execution permission level field:

| Level | Meaning |
| --- | --- |
| `standard` / 标准授权 | Keep cautious confirmation behavior for high-risk actions. |
| `trusted_plan` / 信任已确认计划 | For commands inside the user-confirmed plan, avoid asking repeatedly for low-risk command-line steps. |
| `maximum` / 最高授权 | Execute necessary commands inside the user-confirmed plan as autonomously as possible. |

Important: this setting expresses the user's intent in the Stage 2 execution prompt. It does **not** bypass Copilot CLI, operating system, SSH, hardware, or enterprise security restrictions. If the current Copilot session or tool layer requires confirmation or lacks permission, that limitation still applies.

## Similar IPS Search

The UI includes an optional checkbox:

```text
检索相似 IPS 获取历史经验
```

When enabled, Stage 1 includes this in the plan. Stage 2 should first read the target IPS/HSD, then use fields such as title, family, release, component, suspected problem area, tag, BKC/software version, and keywords to search for similar IPS/HSD issues. The report should include reusable experience such as root cause, workaround, fix, comments, BIOS knobs, known limitations, and similar issue IDs.

Keep this optional because broad HSD searches can be slow or noisy.

## Customer Attachments

The UI includes an optional checkbox:

```text
下载并分析客户附件
```

When enabled, Stage 2 should inspect HSD attachment fields such as `download_attached_ips_files` and `ext_attach_url`, try to download attachments using the existing Kerberos/Windows context, save them under `out\<id>\attachments\`, extract archives when possible, and prioritize Overview/README/summary/config/log/result/MLC/BIOS files.

If download is blocked by permissions or the field only contains a browser UI link, the report should include the link/field and failure reason.

## Completion Notification

Stage 2 defaults to notifying the HSD/IPS owner extracted from the article.

The UI keeps only one notification option:

```text
自动发送给 HSD owner（不勾选则生成 Outlook 草稿）
```

Stage 2 should finish the report first, then use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To '<hsd-owner>' -Subject '<subject>' -Body '<body>' -Attachments '<report-path>'
```

By default the script displays an Outlook draft instead of sending automatically. If `自动发送给 HSD owner` is checked, Stage 2 should add `-Send`.

Recommended subject:

```text
[Copilot][HSD] <articleId> <task-type> completed - <short status>
```

Recommended body:

```text
HSD/IPS ID: <id>
标题: <title>
Owner: <owner>
任务类型: <consult/extract/debug>

客户机器环境
- 平台/机型、socket/NUMA 或 DIMM 拓扑、BKC/BIOS、OS、测试工具/版本、关键配置；未知项标注“未获取”。

客户问题
- 客户现象、影响和诉求。

诊断结果
- 复现/验证状态、最终结论、关键证据和硬件动作。

重点关注
- 风险、限制、未验证假设或客户与实验室环境差异。

下一步研究方向
- 可执行的验证、配置对比、信息收集或跟进项；无后续动作时说明原因。

完整报告
- Markdown 报告已作为附件：<report path>
```

## Copilot CLI Connection Modes

Configured in:

```text
config\ips-copilot-ui.template.json
```

### Manual Mode

```json
{
  "copilot": {
    "mode": "manual"
  }
}
```

The UI displays the final prompt. The user copies it into Copilot CLI manually.

### Subprocess Mode

```json
{
  "copilot": {
    "mode": "subprocess",
    "stage2Mode": "subprocess",
    "prependCommands": [],
    "command": ["copilot", "--allow-all"],
    "passPrompt": "stdin"
  }
}
```

This is the default mode for both Stage 1 and Stage 2, so the UI can show live Copilot output.

Use Copilot CLI startup flags for permissions. The default command includes:

```text
--allow-all
```

Slash commands such as `/allow-all` are interactive commands and may not execute correctly when sent through subprocess stdin. If you switch Stage 2 to handoff, run `/allow-all` manually in the current Copilot CLI session before pasting the handoff sentence. Permission flags still cannot bypass OS, SSH, hardware, or enterprise security restrictions.

Supported `passPrompt` values:

| Value | Behavior |
| --- | --- |
| `stdin` | Send prompt to process stdin. |
| `argument` | Append prompt as the final command-line argument. |
| `promptFile` | Write prompt to a temporary file and pass the file path. |

If any command argument contains `{prompt_file}`, the UI writes the prompt to a temp file and replaces that token.

Example:

```json
{
  "copilot": {
    "mode": "subprocess",
    "command": ["copilot", "--prompt-file", "{prompt_file}"],
    "passPrompt": "promptFile",
    "timeoutSeconds": 7200,
    "workingDirectory": "."
  }
}
```

## Recommended User Prompt Through the UI

Fill the UI fields like this:

```text
IPS/HSD ID: 14025984558
SSH control machine: dbgsh05.ccr.corp.intel.com
Task type: Debug / 验证
Permission level: 最高授权
Similar IPS search: enabled if historical experience is needed
Customer attachments: enabled if customer uploaded logs/config/package/Overview
Test target: 跨NUMA MLC bandwidth_matrix / latency_matrix / loaded_latency
Notes: 使用 /root/mlc_v3.11b；先生成计划，确认后再烧录；报告及任务产物保存到 out\<IPS_HSD_ID>\。
```

## Migration Notes

For another user or PC:

1. Copy the whole `copilot-hardware-flow-kit` folder.
2. Confirm Python is available through `py`.
3. Confirm Copilot CLI login manually.
4. Update `config\ips-copilot-ui.template.json` defaults:
   - `defaults.sshHost`
   - `copilot.command`
   - `copilot.mode`
5. Start the UI with `scripts\Start-IpsCopilotUi.ps1`.

Do not store SSH keys, SSO tokens, cookies, Kerberos tickets, or passwords in the UI config.

## Important Safety Defaults

- The UI defaults to subprocess mode.
- Stage 2 defaults to subprocess mode so the UI can show live output.
- Hardware execution requires a second confirmation checkbox.
- Stage 1 prompts forbid hardware actions.
- Stage 2 prompt instructs Copilot to follow the user-confirmed text plan and skip steps that were deleted or explicitly disabled.
- Flash failures must stop the flow before boot capture or MLC.
