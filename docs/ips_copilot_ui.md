# IPS/HSD Copilot UI

This document describes the portable local UI for starting IPS/HSD analysis and hardware reproduction through Copilot CLI.

The UI is intentionally implemented with the Python standard library only. No Streamlit, Flask, Node.js, or browser framework is required.

## Enterprise Workbench Layout

The UI uses an enterprise workbench layout without external frontend dependencies:

- Persistent left navigation for the task workspace, new task, Query task queue, execution console, and reports.
- A top service-status bar plus a dashboard showing the selected mode and loaded Query task counts.
- Card-based forms, consistent status colors, focused output consoles, and responsive behavior for narrow browser windows.
- A light/dark theme toggle. The selected theme and UI mode are saved only in the current browser's local storage.

The visual redesign does not change the existing Stage 1/Stage 2 safety boundary, task APIs, task persistence, or hardware execution behavior.

## Workbench Pages

| URL | Purpose |
| --- | --- |
| `/` | Manual task workbench for simple and detailed IPS/HSD workflows. |
| `/tasks` | Unified view-only task center: track simple execution, plan-review, and automatic Query task status, reports, and automatic hardware resource locks. |
| `/reports` | Historical Query rounds, report summaries, and IPS result details. |
| `/common-issues` | Read-only common-issue search, deterministic grouping, and saved analysis history. |
| `/guide` | User guide covering modes, setup, safe operation, Query coordination, and documentation locations. |

When a user creates an automatic Query task, the server checks for the same numeric Query ID in `queued`, `running`, `waiting_resource`, or `cancelling` state. A duplicate is rejected without changing the existing task; the UI explicitly states that the original task remains running and provides its task link. Terminal tasks do not block a new Query task.

The manual workbench includes reusable templates for IPS extraction, consultation, boot validation, and cross-NUMA MLC validation. Form input is automatically saved as a draft in the current browser's local storage and can be explicitly saved or cleared; drafts are not sent to the UI server until a task is started.

简洁模式的 Debug/验证阶段会先提取 IPS、客户环境与测试诉求，再与已登记机器配置比对。AI 可依据这些已获取的结果生成 `out\<IPS_HSD_ID>\resource_request_draft.md`，其中包含验证背景、配置缺口以及平台、CPU、DIMM、存储和其他依赖的物品清单；无法确认的字段明确标为“待确认”。阶段二必须先写入报告中心摘要并持久化草稿路径；UI 确认链接可访问后，才向任务提交人发送草稿链接通知。审核页使用管理层视图，优先呈现客户影响、所需决策、资源、DDL 和排期影响；寄存器、日志和调试过程仅在必要时置于技术附注。任务提交人填写期望 DDL、资源占用、预计时长和老板收件人；保存人工信息后，点击确认发送才会将草稿作为附件发送给老板。

阶段二完成时必须写入 `out\manual_reports\<task-id>.summary.json`，报告中心据此关联诊断摘要和资源/物品清单草稿。对于 Debug/验证任务，摘要必须包含可读取的 `resource_request_draft.md` 路径；缺少摘要、诊断结果或草稿时，报告中心会明确标记“报告产物未完成”，不会将旧任务残留的同名 IPS 产物误显示为本次结果。

## Common-issue AI analysis

`/common-issues` searches HSD records by a required submitted-date window plus at least one of platform, customer, component, or keywords. Customer supports multiple alternatives separated with `/`, `,`, or `;`; they are combined with OR semantics. It validates ISO `YYYY-MM-DD` dates, range order/window, result limits, and allowed filter characters before constructing EQL. It POSTs the documented HSD API endpoint `https://hsdes-api.intel.com/rest/query/execution/eql?start_at=1` with the JSON shape `{"eql":"select ... where ..."}`. The EQL always includes the date range and a supplied user filter; the default keyword mapping is exact title equality. The selected record fields include `description`; the AI receives only normalized, bounded Title/Description/metadata fields and never performs independent HSD or hardware actions.

After HSD rows are normalized, configured subprocess-mode Copilot may perform a bounded, text-only grouping enrichment. Its prompt forbids tools, skills, terminal/network access, SSH, flashing, power control, serial, MLC, and all hardware actions. Copilot must return the strict JSON grouping schema and cover each IPS ID exactly once. Manual/handoff configuration, timeout, unavailable Copilot, or invalid output transparently produce `analysis_mode: deterministic_fallback`; only validated output is reported as `analysis_mode: ai_enriched`. Deterministic grouping remains the reliable fallback.

Customer-reported problem content is the primary grouping evidence. The model compares reported symptom, trigger/configuration, impact, and observed failure signature before considering titles or metadata. The deterministic fallback is intentionally stricter: without a verified shared sighting, it groups only records whose customer descriptions share at least two meaningful symptom terms. A matching title, platform, component, customer, date, ticket ID, or URL alone never creates a common-problem group.

The normalized grouping context also includes verified reusable-experience fields observed in IPS articles: `fix_description`, `conclusion_type`, `ext_cust_blog_hist`, `customer_project_name`, `release`, `priority`, `article_type`, and `ext_issue_type`, alongside Description, Comments, Root Cause, and Repro/Debug content. Rich-text HTML/CSS is stripped before analysis. Customer symptom and failure evidence determine grouping; fix/history/version/project metadata helps explain whether a shared case is applicable to another team.

Weekly sharing prioritizes `Debug` (and records with no explicit type) as the reusable-problem population. `Question` IPS are lower-priority historical references, but can form a group when they have a clear shared customer symptom or a verified shared sighting. A verified shared `int_sighting_url` is recognized as strong evidence. AI grouping may use a moderately broad problem category when customer descriptions, failure signatures, comments, root-cause notes, or repro/debug evidence indicate the same actionable pattern; it must not widen a group from metadata alone. AI-selected `强证据` or `关联证据` is independently checked against normalized sighting fields and downgraded to `候选证据` when the required verified links are absent.

When at least two otherwise-unmatched IPS each have an `int_sighting_url`, the report also adds **有 int_sighting_url 的 IPS** with tier `关联证据`. This is a reference category for sharing related handling experience: different sighting links are intentionally kept together for discovery, but are not represented as a shared root cause. Same-link records remain in their separate `强证据` group.

This feature is read-only: it never performs SSH, flash, power-cycle, serial, MLC, hardware locking, or other hardware actions. Reports are persisted separately from Query tasks under `out\common_issue_reports\<uuid>\report.json` with a dedicated SQLite index. The template defaults use `server_platf_ae.bug` fields observed in local HSD responses; adjust `eqlFields` only when the target tenant uses different fields. Normalization defensively parses the selected fields.

For report display, a populated IPS `customer_company` value is preferred as the customer name. Existing `customer`, account-name, and nested customer fields remain compatible fallbacks.

Each common-issue group displays an explainable evidence model: a normalized SI/FW sighting ID is preferred when URLs differ only by case, query parameters, or navigation fragments; the report also shows a conservative `0-100` grouping confidence and the exact signals used (shared verified sighting, shared problem keywords, and matching platform/component). `100` is reserved for a shared verified sighting; candidate groups are not proof of the same root cause. Analysts can persist `确认同类`, `建议拆分`, or `排除本组` feedback with an optional note. Feedback is an auditable review record for the saved report; it does not silently retrain grouping or bypass independent Debug validation.

Configuration defaults:

```json
{
  "commonIssueAnalysis": {
    "maxDateRangeDays": 90,
    "defaultResultLimit": 50,
    "maxResultLimit": 200,
    "requestTimeoutSeconds": 120,
    "autoQueryArticleFetchMaxCount": 100,
    "autoQueryArticleFetchConcurrency": 6,
    "autoQueryArticleFetchTimeoutSeconds": 45,
    "autoQuerySightingFetchMaxCount": 100,
    "aiEnrichmentEnabled": true,
    "aiTimeoutSeconds": 120,
    "referenceAiBatchSize": 5,
    "referenceTopCount": 20,
    "eqlFields": {
      "id": "id",
      "title": "title",
      "platform": "platform",
      "customer": "customer",
      "component": "component",
      "submittedDate": "submitted_date",
      "sighting": "server_platf_ae.bug.int_sighting_url",
      "closeReason": "bug.closed_reason"
    },
    "reportDirectory": "out\\common_issue_reports"
  }
}
```

## Automatic Query Top IPS Reference Selection

The automatic Query report ranks each successfully fetched IPS independently; it does **not** group Query records or claim a shared root cause.

1. The UI fetches article bodies for all in-scope Query IPS and sends them to AI in batches of `referenceAiBatchSize` (default `5`) through Copilot CLI non-interactive prompt mode.
2. The transparent 100-point composite score is: problem pattern 0–25, reusable handling 0–30, internal evidence 0–20, resolution maturity 0–15, and applicability 0–10. AI evaluates problem pattern, reusable handling, and applicability from the article body; the application calculates internal evidence and resolution maturity from verified fields and normalized content.
3. For each unique valid `server_platf_ae.bug.int_sighting_url`, the UI read-only fetches the linked SI/FW article once (up to `autoQuerySightingFetchMaxCount`, default `100`) and adds its description, comments, root cause, fix/workaround, and repro/debug details to that IPS's AI context. A verified link contributes 10 internal-evidence points, useful linked SI/FW context contributes 7, and `bug.closed_reason` / `close_reason=internal_*` contributes 3. XML/HTML-formatted sighting fields are normalized to a clickable SI/FW link.
4. Complete/Resolved IPS with a root cause, fix, or workaround receive the full 15 resolution-maturity points. Open IPS receive 8 only when they already provide a concrete handling or debug direction, otherwise 3. Status is never a hard ranking tier.
5. Platform, release, component, customer project, and priority define applicability boundaries; they do not independently prove reusable value. Entries sort directly by composite score, then resolution maturity, reusable handling, and date.
6. Each automatic Query round exposes two separate reports in the report center: **执行报告** for Open-IPS processing, task status, and diagnostics; and **Top IPS** for the AI-ranked reference cards. The execution report contains only a link to Top IPS, avoiding a mixed operations-and-analysis view.
7. The Top IPS page hides processing counters and exposes one expandable **跨团队可复用 IPS 参考规则** panel beside the Top list heading. It describes the composite scoring criteria and the independent-scoring boundary; it is not a per-IPS explanation.

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

Report pages display saved ISO timestamps as local `YYYY-MM-DD HH:mm:ss` text. Recipient email addresses in report summaries and task details are rendered as clickable `mailto:` links; non-email recipient names remain plain text.

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

In simple mode, fill in task information, an optional recipient (email or Outlook name), and click:

```text
开始执行
```

The UI generates a default plan internally, starts Stage 2, streams output in the UI, and records the execution in the report center. When a recipient is filled in, completion notification is sent to that specified user rather than to the HSD/IPS owner.

### 详细模式

Detailed mode keeps the original review flow:

1. Generate a Stage 1 execution plan.
2. Edit/confirm the plan.
3. Start Stage 2.

### 任务中心与多用户自动任务

在工作台选择 **全自动模式** 可快速创建 Query 任务并查看共享任务概览；在左侧导航打开 `/tasks` 可在统一视图中筛选简洁执行、计划审阅和自动 Query 任务，并查看任务状态、下发人和报告入口。任务中心是只读的进展查看页，不提供创建、下发或取消任务操作。简洁模式要求填写 **任务下发人**，用于任务追溯。计划审阅任务在阶段 1 启动后即进入任务中心，并在阶段 2 执行时沿用同一任务记录。自动 Query 填写 **创建人姓名**、HSD saved Query ID、轮询间隔和可选的管理汇总收件人，再从工作台的全自动模式点击“创建并启动任务”。每次提交创建一个独立的持久化任务；不同浏览器会话看到相同的任务列表和实时输出，多个 Query 任务可以并行执行。没有全局 Query 并发上限。相同活动 Query 会被服务端拒绝重复创建，并引导用户查看已有任务。  

如果只需要 Top IPS 参考结果，可勾选 **仅生成共性报告**。该模式单次执行 Query、只读抓取 IPS 与 `int_sighting_url` 内容并进行 AI 参考价值排序；不处理 Open IPS、不启动 Copilot Debug/硬件动作、不轮询。若填写了汇总通知者，任务完成后仍会发送管理汇总通知。任务完成后从任务详情或报告中心打开 Top IPS 参考报告。

任务状态包括 `queued`、`running`、`waiting_resource`、`cancelling`、`completed`、`failed`、`cancelled` 和 `interrupted`。任务元数据、创建人、轮次、当前 IPS、输出、报告入口和取消原因保存在标准库 SQLite 数据库，默认位置为：

```text
out\ui_task_manager.sqlite3
```

服务启动时，上一进程遗留的活动任务会被标记为 `interrupted`，并且**不会**自动恢复或继续任何硬件操作。创建人由 UI 提供，用于工作追溯；本范围不添加反向代理或身份认证功能。

点击任务卡片上的“取消”可提供持久化取消原因。排队任务立即变为 `cancelled`。运行中任务先变为 `cancelling`，停止轮询和新 IPS，并对当前 Copilot 子进程发送终止信号；超过 `automation.cancellationGraceSeconds` 后仍未退出则强制结束。取消并不能撤销已经完成的硬件动作，任务输出会记录状态和原因。

每个任务只对本任务生命周期内首次发现的 Open IPS 执行自动 Debug，随后按指定间隔继续轮询。仅生成共性报告模式会通过 Kerberos 协商认证分页读取 Saved Query 的全部记录；全自动模式仍只读取首个 Query 页，避免扩大自动 Debug 范围。正文分析最多抓取 `autoQueryArticleFetchMaxCount`（默认 100）条 IPS；当 Query 超过该上限时，候选会优先保留全部 Open IPS，再按关闭日期从新到旧填充终态 IPS，直到达到 100 条，以保证最近关闭 IPS 可被评估并在详细矩阵中按 Completed 筛选。若 Open IPS 自身已超过上限，则仅保留提交日期最新的 100 条 Open IPS，并在报告中标记为已分析子集。再对每条入选 IPS 独立评估是否值得作为团队参考案例。不会按 Title 或正文将 Query IPS 归并，也不会由多条记录相似性声明共同根因。`int_sighting_url` 有有效内部链接、`close_reason` 为 `internal_*` 是强结构化信号；最终推荐还必须结合问题现象、触发/配置、影响、故障签名，以及 root cause、fix/workaround 或 repro/debug 内容，判断是否有可复用的处理价值。每条成功抓取正文的 IPS 都会进入 AI 分批评估。有效 `int_sighting_url` 和 `internal_*` 关闭原因是重要加分信号，不再是硬性候选门槛；AI 同时从正文的具体技术症状、触发/影响、评论、诊断/根因/修复/规避/复现方向和适用边界给所有 IPS 评分。Top IPS 使用 100 分综合评分，不再按 Open/Complete 状态硬分层：问题模式 0–25、处理复用 0–30、内部证据 0–20、解决成熟度 0–15、适用范围 0–10。AI 只对正文的前两项及适用范围给分；应用根据已验证的 `int_sighting_url`、SI/FW 正文和 `internal_*` 关闭标签计算内部证据，并根据状态及根因、fix/workaround 或 repro/debug 内容计算解决成熟度。Complete/Resolved 且已具备处理闭环的案例可获得最高成熟度，Open 仅在有明确处理或调试方向时取得部分成熟度。排序直接比较综合分；分数相同时，依次比较解决成熟度、处理复用度和日期。报告只展示排序最高的 Top 20 IPS（通过 `commonIssueAnalysis.referenceTopCount` 配置），不会展示未入选 IPS。`commonIssueAnalysis.referenceAiBatchSize`（默认 5）控制每次送入 AI 的 IPS 数量，`aiTimeoutSeconds` 默认 120 秒；Copilot 使用 `-p` 非交互模式，评分完成后自动退出。若某批次失败，报告明确显示“规则回退正文”及失败原因，不再将固定规则分数标成 AI 分数。`autoQueryArticleFetchConcurrency`（默认 6）和 `autoQueryArticleFetchTimeoutSeconds`（默认 45）限制该只读抓取；超出上限时报告明确标记为“已分析子集”。轮次报告保存抓取请求/成功/失败数、受限或失败的说明及（上限内）失败 ID；无可用正文的 IPS 会标记为内容不足。自动 Query 仍要求 `copilot.mode` 和 `copilot.stage2Mode` 都为 `subprocess`。

Top IPS 页面下半部的详细矩阵展示本轮所有已分析的 IPS，便于按状态、组件或关键词回溯 Query 全量结果。其 Completed 筛选统一包含 `closed`、`complete`、`completed`、`resolved`、`implemented` 和 `verified` 状态；HSD 返回的 `end_date` 和 `end_time` 也会作为关闭日期识别。

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

### 统一报告中心与管理通知

报告页入口为：

```text
<reportBaseUrl>/reports
```

报告中心统一显示简洁模式、详细模式和全自动 Query 的处理记录。简洁和详细模式的输入、最终计划、执行输出和状态保存到：

```text
out\manual_reports\<job-id>.json
```

全自动报告索引按任务、Query ID 和轮次显示历史。新任务报告保存到：

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
- optional recipient (email or Outlook name) for completion notification
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

The UI has an optional recipient field:

```text
发送用户（邮箱或 Outlook 名称）
```

When this field is filled, Stage 2 should finish the report first, then send to that specified user:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To '<specified-user>' -Subject '<subject>' -Body '<body>' -Attachments '<report-path>' -Send
```

When the field is blank, no notification is sent. The UI no longer exposes automatic-send or draft-only behavior, nor a report-output-directory field; task artifacts continue to be saved under `out\<IPS_HSD_ID>\`.

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
    "command": ["copilot", "--allow-all", "--silent", "-p"],
    "passPrompt": "argument"
  }
}
```

This is the default non-interactive mode for Stage 1, Stage 2, and Top IPS scoring. Copilot exits after completing the prompt, allowing the UI to capture the result without waiting for an interactive session.

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
