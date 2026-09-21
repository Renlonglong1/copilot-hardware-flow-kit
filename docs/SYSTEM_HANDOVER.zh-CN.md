# Copilot Hardware Flow Kit 系统任务交接文档

版本：1.0 | 编制日期：2026-09-21 | 状态：技术交接稿，待责任人签收

本文面向接任开发者、部署运维人员与实验室负责人。内容依据编制时的本地工作区代码和配套文档整理，不代表已经完成真实硬件验收、账号转移或 GitHub 发布。文中不包含凭据、客户工单正文或实际实验室接入信息。

## 1. 交接摘要与责任人

本系统将 Copilot CLI、IPS/HSD 问题分析、Windows 本地 Web 工作台及远程硬件脚本组合为可复用工具包。主要目标是从问题输入、执行计划、信息提取和授权复现，到报告归档和通知形成闭环。系统不是独立的企业身份认证平台，也不是保证无人值守成功的硬件调度服务。

| 项目 | 交接内容 |
| --- | --- |
| 系统名称 | Copilot Hardware Flow Kit |
| 当前 GitHub 目标 | https://github.com/Renlonglong1/copilot-hardware-flow-kit |
| 编制依据 | 本地 main 工作区；起始 HEAD 为 48ceb39；工作区另有未发布修改 |
| 原作者记录 | USER_QUICK_START.md 署名 Li Renlong；具体移交职责由本人确认 |
| 移交人 / 接收人 | 待填写 / 待填写 |
| 业务负责人 / 备份维护人 | 待填写 / 待填写 |
| 实验室负责人 / 安全审批人 | 待填写 / 待填写 |
| 正式交接日期 / 支持截止日期 | 待填写 / 待填写 |
| 发布依据 | 以 GitHub 实际可见分支和提交为准；不将本地提交视为上传成功 |

交接范围包括源代码、核心技能、配置模板、运行方法、报告数据位置、维护约束及待办事项。企业账号授权、真实机器配置、客户数据、内部参考资料和软件许可证应通过公司批准渠道单独移交，不随 GitHub 代码包发送。

## 2. 功能范围与工作边界

| 模块 | 已有功能 | 接任者必须理解的边界 |
| --- | --- | --- |
| 手动工作台 | 简洁执行、详细计划审阅、模板及表单草稿 | 简洁模式可直接进入阶段二；详细模式先审阅计划 |
| IPS/HSD 提取与咨询 | 获取文章、提取问题信息、分析建议 | 可以访问获准的 HSD；禁止 SSH、烧录、电源、串口及 MLC |
| Debug / 验证 | 机器匹配、镜像选择、烧录、启动日志、可选 MLC | 必须满足授权、平台匹配及硬件前置条件 |
| 自动 Query | 持久化任务、轮询、Open IPS 处理、资源锁、取消 | 同一活动 Query 拒绝重复；跨主机不共享本地锁 |
| Top IPS 参考 | 独立评分、参考案例排序、只生成参考报告模式 | 不等于自动证明共同根因；只读模式不开展硬件 Debug |
| 共性问题分析 | 条件检索、分组证据、AI 增强及规则回退、反馈 | 分组用于经验发现，候选证据不是已验证根因 |
| 报告和通知 | 历史报告、资源申请草稿、Outlook 通知 | 草稿生成、程序成功、邮件送达是不同状态 |
| 通用技能库 | BIOS、BMC、GPU、硬件、文档等辅助能力 | 技能存在不代表每个领域已在本部署环境验证 |

### 2.1 两阶段安全边界

阶段一只使用用户在 UI 输入的字段生成计划，不读取 HSD，不连接 SSH，不枚举远端 BKC，不执行烧录、电源、串口或测试。阶段二按选定任务类型执行；提取/咨询任务仍不得触发硬件操作。

Debug / 验证需要先核对目标平台、机器、镜像、测试意图及资源占用。BHS/GNR 与 OKS/DMR 不可互相替代；未知或冲突的平台应停止并报告，不自动选择任意空闲机器。

当前 UI 模板的 copilot.mode 与 copilot.stage2Mode 均为 subprocess。handoff 是权限不适配时的接力模式，会生成任务文件供具备权限的交互会话接手；handoff 作业显示完成，仅表示接力文件生成，不证明硬件任务已完成。

### 2.2 授权与副作用

模板中的 Copilot 命令含 --allow-all。它不能绕过操作系统、企业安全或 SSH 限制，但会扩大子进程可执行的操作范围。UI 上的权限说明和提示词约束不能替代隔离、身份认证和人工审批。

本次交接编制不执行 SSH、工单下载、烧录、电源操作、串口控制、MLC 或邮件发送。正式接收验收应另行安排获准的测试窗口。

## 3. 系统架构与数据流

```text
浏览器
  -> Start-IpsCopilotUi.ps1
  -> ips_copilot_ui.py：HTTP 服务 / 任务管理 / 报告中心
       -> 阶段一：表单 -> 计划
       -> 阶段二：Copilot CLI 子进程，或 handoff 文件
            -> 提取/咨询：HSD 获取 -> 内容分析 -> 报告
            -> Debug：本地配置 -> SSH 控制机 -> 获准硬件流程
       -> Query 后台任务 -> SQLite 状态 / 本地机器锁
       -> out：工单产物、任务状态、报告、资源申请与通知记录
       -> Outlook：草稿或经授权发送
```

| 层次 | 主要技术 | 维护重点 |
| --- | --- | --- |
| Web 与业务编排 | Python 标准库、ThreadingHTTPServer、内嵌页面 | 核心业务集中在单个大文件；变更需覆盖状态与报告链路 |
| 本地执行包装 | PowerShell、Python Launcher | 参数、配置解析、工具路径与退出状态 |
| AI 执行 | Copilot CLI 子进程 | 登录、命令版本、权限、提示词传递、超时及取消 |
| HSD 接入 | Python 请求或 curl.exe 协商认证 | 企业网络、受信证书、当前 Windows/Kerberos 身份 |
| 远端控制 | OpenSSH / SCP、Windows 控制机 | 独立身份、主机指纹、设备占用和远端工具 |
| 状态与产物 | SQLite、JSON、Markdown、原始日志 | 持久化一致性、备份、保留期及访问限制 |

## 4. 代码和文档导航

| 路径 | 职责 / 阅读时机 |
| --- | --- |
| docs\AI_QUICK_INDEX.md | 首读索引，只展开与任务有关的文档 |
| scripts\ips_copilot_ui.py | UI、提示词、任务队列、机器锁、HSD 查询和报告 |
| scripts\test_ips_copilot_ui.py | 现有离线 UI 回归测试 |
| scripts\Start-IpsCopilotUi.ps1 | UI 启动及本地配置选择 |
| scripts\Resolve-LocalConfig.ps1 | 硬件配置解析、SSH 身份参数构造 |
| scripts\Invoke-HsdArticleFetch.ps1 | HSD 获取与提取链路入口 |
| scripts\extract_hsd_article.py | 原始 JSON 的离线摘要提取 |
| scripts\Invoke-BhsUplr2ValidatedFlow.ps1 | SSH 预检、关电、烧录、启动捕获和可选 MLC |
| scripts\Invoke-Emulator.ps1 | EM100 操作与烧录日志判定 |
| scripts\Invoke-PowerSplitter.ps1 | 电源控制包装 |
| scripts\Invoke-RemoteBootCapture.ps1 | 远端 CPU/BMC 串口捕获与启动分析 |
| scripts\Capture-SerialPort.ps1 | 串口原始日志采集 |
| scripts\Invoke-RemoteMlcSerial.ps1 | 串口上的 Host OS MLC 命令及产物校验 |
| scripts\Send-OwnerNotification.ps1 | Outlook 通知及附件处理 |
| .github\skills | 分领域操作约束、参考资料与辅助脚本 |
| config\*.template.json | 可移植配置模板，不等于可直接运行的部署配置 |
| config\local | 本机配置，Git 忽略，禁止提交 |
| docs\development_deployment_contract.md | 开发代码与部署配置的强制边界 |
| docs\local_runtime_profiles.md | 本地配置查找顺序 |
| docs\ips_copilot_ui.md | 完整 UI 与自动任务说明 |
| docs\git_usage_guide.md | 开发端提交和部署端拉取流程 |
| learningfile | 内部参考资料；不属于可默认发布的交接代码包 |

核心工作流技能为 ips-ui-plan-stage、ips-consult-flow、ips-hsd-repro-flow、ips-auto-flow、bhs-hardware-flow 和 common-ps-py-commands。新增或迁移技能时，应保留其许可证，并单独核对参考文件和脚本的发布资格。

## 5. 环境、依赖与账号交接

| 环境 / 依赖 | 用途 | 接收要求 |
| --- | --- | --- |
| Windows 与 PowerShell | 本地 UI 包装和远端控制 | 使用批准的版本；保留脚本执行策略审批 |
| Python 3 与 py.exe | UI、提取器和测试 | UI 使用标准库；新机器实际验证兼容性，不臆定最低版本 |
| Git / GitHub 访问 | 拉取与发布 | 接收人使用本人企业批准身份；仓库成员权限另行分配 |
| Copilot CLI 与授权 | 计划及阶段二 AI | 接收人自行登录；记录获准版本和可用模型 |
| curl.exe / 企业认证 | HSD 协商认证 | 确认 curl 支持协商认证、网络及文章/Query 访问权限 |
| 可选 Python HSD 依赖 | requests、requests-kerberos、truststore 等 | 只在使用 Python 请求路线时按现有文档安装 |
| OpenSSH / SCP | 控制机远程执行 | 配置获准身份文件和经核对的主机指纹 |
| EM100 / PowerSplitter | 烧录与电源 | 工具、驱动、USB 连接、芯片型号和设备归属 |
| CPU/BMC 串口 | 原始日志与 Host 控制 | 端口映射、波特率和独占使用窗口 |
| Host OS / MLC | 测试执行 | 工具版本、安装路径、root 权限及 msr 模块条件 |
| 桌面版 Outlook COM | 草稿或发送邮件 | 使用接收人的获准邮箱；先草稿后发送验收 |

不要通过聊天、文档、Git、命令记录或测试数据传递密码、令牌、Cookie、Kerberos 票据内容或 SSH 私钥。私钥由接收人按公司流程新建/授权；需要口令的操作通过批准的运行时机制提供。原人员离职时撤销的是个人权限，不应直接删除共享服务身份。

## 6. 新机器部署步骤

以下命令在仓库根目录运行，示例仅使用占位或本机路径。不要把旧文档中的历史 IP、镜像和路径当作默认值。

### 6.1 获取代码与核对基线

```powershell
git clone https://github.com/Renlonglong1/copilot-hardware-flow-kit.git
Set-Location .\copilot-hardware-flow-kit
git status --short
git log -1 --oneline
py --version
Get-Command git, py, powershell, ssh, scp, curl.exe, copilot
```

仓库访问依赖批准的 GitHub 身份；不能访问时由管理员授予权限，不交换原维护人的令牌。交接签收表记录真实拉取的分支及完整提交号。

### 6.2 创建本机配置

```powershell
New-Item -ItemType Directory -Path .\config\local -Force
Copy-Item .\config\hardware-flow.template.json .\config\local\hardware-flow.json
Copy-Item .\config\ips-copilot-ui.template.json .\config\local\ips-copilot-ui.json
```

仅首次部署且目标文件不存在时复制；已有本地配置先备份，禁止用模板覆盖现有部署参数。填写 ssh.user/host、远端工具与镜像路径、串口、电源工具及日志目录。identityFile 和 hostKeyAlias 的可选占位值必须替换为真实获准值，或在不使用时设为空，不能原样保留。

模板中的芯片、设备序列号、COM3/COM4、CPU 启动关键字及 Host OS 路径也是示例，必须逐项核对。禁止写入私钥内容或口令。

硬件配置查找顺序：显式 -ConfigPath → COPILOT_HARDWARE_FLOW_CONFIG → config\local\hardware-flow.json → $HOME\copilot-hardware-flow-local\hardware-flow.json。找不到可用配置应在任何硬件动作前失败。

UI 启动包装默认优先 config\local\ips-copilot-ui.json，否则使用 loopback 模板；显式 -ConfigPath 可覆盖。非模板 UI 配置会合并模板默认值。machineMatching.inventoryPath 应指向本机经批准的机器清单，而不是未经复核的历史实验室快照。

### 6.3 先本地 UI，再进行分级验收

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -NoBrowser
```

默认访问 http://127.0.0.1:8765/。先确认工作台、任务中心、报告中心和使用指南可打开，再做“仅生成计划”的无外部副作用验收。不要为了检查 UI 能否启动而提交真实 Debug 或自动 Query 任务。

UI 没有自带身份认证。保持本机监听；确需内网共享时，使用批准的访问控制/认证代理并限制防火墙来源，同时正确配置 server.reportBaseUrl。不得直接暴露公网。

## 7. 主要业务操作规程

### 7.1 手动提取与咨询

选择 extract_ips 或 consult，填写获准工单 ID、问题目标和下发人。详细模式先生成并审阅计划，确认其中没有硬件动作。阶段二通过已有身份获取 HSD，输出摘要、结论和信息不足项。

查看本任务报告和通知状态，不以终端退出码代替报告验收。客户附件及原始 JSON 仅存内部受控目录；相似 IPS 的处理经验需要说明适用版本及平台边界。

### 7.2 Debug / 验证

先核对平台、CPU/DIMM/拓扑、BKC/镜像、机器可用性、授权窗口、芯片、日志目录和通知对象。有资源缺口时生成资源申请草稿，明确待确认字段，不把缺少设备解释为已完成验证。

下面是获准后的连接预检，不属于离线测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1 -ConfigPath .\config\local\hardware-flow.json
```

要求 SSH_OK；普通 ssh 命令不读取硬件配置，不能以其结果替代该预检。不得使用 StrictHostKeyChecking=no 绕过指纹核对。

下列命令会实际关电、烧录、开电、抓取串口并运行 MLC，只能在已批准且独占目标设备的窗口执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\local\hardware-flow.json -CloseGuiConflicts -RunMlc
```

- 烧录判定必须同时包含 Download Complete、Verify Pass、Emulator is in Emulation mode、Authentication Pass，不能只看退出码。
- 烧录失败立即停止后续启动捕获和测试；诊断 USB、设备占用、镜像和工具后再决定是否重试。
- 出现 No device is connected! 时核对 DediProg USB；如需清理 GUI 占用，只处理已确认的 EM100.exe / Emulator.exe 具体 PID。
- 先打开 CPU/BMC 原始日志采集，再上电；保留完整采集窗口，不能因最初无输出便宣告失败。
- MLC 的串口必须已进入可用 root shell，或由批准的运行时凭据机制登录；当前包装不会把本地口令自动传到远端进程。
- 保留原始串口日志、镜像版本/哈希、MLC 输出及异常；把“脚本完成”“系统启动”“问题复现”分别写入结论。

### 7.3 Query 自动任务

从工作台全自动模式提交创建人、Query ID、轮询间隔及必要通知对象。模板最小轮询间隔为 60 分钟，同一活动 Query 不重复创建。任务中心用于只读观察，创建/取消使用工作台提供的相应操作，不假定所有页面都可发起操作。

任务状态包括 queued、running、waiting_resource、cancelling、completed、failed、cancelled、interrupted。服务重启会把遗留活动任务标为 interrupted，不自动恢复硬件动作。取消可能终止 Copilot 子进程，但不能撤销已发生的烧录或电源动作；必须核对远端设备是否仍在执行。

全自动 Debug 仅处理任务生命周期内首次发现的 Open IPS，并继续轮询。它只读取首个 Query 页，以避免扩大硬件执行范围。“仅生成共性报告”是单次只读参考分析，支持分页取 Query，不启动硬件 Debug，也不轮询。

自动任务依赖 copilot.mode 和 stage2Mode 同为 subprocess。机器锁在本机 SQLite 中，不构成多部署实例之间的分布式锁，也不能推定独立命令行或人工操作自动受到同一锁保护。

### 7.4 共性分析、Top IPS 与资源申请

共性检索要求日期窗口和至少一个有效筛选条件；默认最多 90 天，默认结果数 50、上限 200。AI 输出必须通过结构和证据校验；不可用时显式显示规则回退，不把回退结果伪装成 AI 结论。

Query 的 Top IPS 对每条工单独立评分，不按相似文本合并共同根因。默认正文上限 100、AI 批次 5、Top 列表 20；超限、正文获取失败或 AI 失败时需阅读报告中的子集/回退说明，不能解释为所有记录均完成分析。

Debug 资源申请需先持久化 summary.json 和可读取的 resource_request_draft.md，再通知下发人。下发人补充 DDL、资源占用、预计时长和收件人后，明确确认才发送给审批人。没有报告摘要/草稿时，应显示产物未完成，不能沿用同一 IPS 的旧结果。

## 8. 数据、日志、备份与恢复

| 数据 | 默认位置 | 交接方式 |
| --- | --- | --- |
| 自动任务数据库 | out\ui_task_manager.sqlite3 | 受控备份；含任务状态、输出和资源锁 |
| 手动执行记录 | out\manual_reports\<job-id>.json | 与报告目录一并内部移交 |
| 手动报告摘要 | out\manual_reports\<job-id>.summary.json | 关联本次报告和草稿，不以旧同名文件替代 |
| Query 轮次报告 | out\auto_reports\query_<ID>\task_<TaskId>\round_<N>\round.json | 保持任务、轮次及文件层级 |
| 旧 Query 报告 | out\auto_reports\query_<ID>\round_<N>\round.json | 兼容历史读取，不做破坏性迁移 |
| 共性分析报告 | out\common_issue_reports\<uuid>\report.json | 同时保留相应索引数据 |
| HSD 原始/提取产物 | out\<ID>\hsd_<ID>_raw.json 等 | 含内部/客户信息，不入 GitHub |
| 资源申请草稿 | out\<ID>\resource_request_draft.md | 人工审批信息由接收人核对 |
| handoff 任务 | inbox\ui_tasks\ui_stage2_task_*.md | 可能含工单信息，仅内部移交 |
| 远端启动与 MLC 日志 | 本机配置中的远端 flow.logRoot；Host 的 MLC 结果目录 | 从实际运行记录登记路径，不写死历史目录 |
| 本机配置与 SSH 信任配置 | config\local 及本机获准存储 | 单独受控迁移；不复制原人员私钥 |

维护前先停止接收新任务，逐项确认活动任务和设备状态。等待任务安全结束；如取消任务，核对远端进程和硬件状态。停止本服务后再复制 out 与本地配置，或使用数据库支持的一致性备份方式；禁止只复制正在写入的 SQLite 主文件并假定完整。

备份应包含版本号、时间、访问权限、文件清单和完整性记录。备份中的客户数据仍受原保密和保留要求约束，不得通过公开附件或代码仓库转交。模板 retentionDays 为 90，但接任者应核对代码实际清理范围和企业策略，不把一个配置值当作完整备份/销毁制度。

恢复时先在隔离位置还原同版本代码与数据，配置接收人身份并保持 loopback 启动。确认历史报告可读，遗留任务按 interrupted 处理，机器锁和远端状态经人工核对后再开新任务。不得通过删除数据库强行解决锁等待。

## 9. 日常运维与故障定位

| 现象 | 优先检查 | 不应采取的做法 |
| --- | --- | --- |
| UI 无法启动 | Python Launcher、配置 JSON、端口占用、启动控制台输出 | 随意结束其他 Python 进程 |
| 外部打不开报告 | reportBaseUrl、监听地址、批准的网络/认证代理规则 | 临时开放公网或所有来源 |
| Copilot 子进程无输出/超时 | 已登录身份、命令参数、passPrompt、超时和输出 | 无限重试；把 handoff 完成当硬件成功 |
| HSD 403/Access Denied | 企业网络、当前身份权限、证书、既有 curl 路线 | 收集他人口令、Cookie 或关闭 TLS 校验 |
| SSH 拒绝或指纹冲突 | 实际本地配置、身份路径、已批准的主机指纹 | 禁用主机校验；默认认为设备损坏 |
| EM100 找不到设备 | USB 枚举、物理连接、工具与明确的 GUI PID 占用 | 烧录失败后仍等待启动串口 |
| 串口无输出/占用 | COM 映射、波特率、独占情况、采集窗口与电源状态 | 打开第二个终端争用同一串口 |
| MLC 登录或结果失败 | root shell、远端运行时凭据、MLC 路径、msr、结果 EXIT 状态 | 把命令回显当作成功；将口令写入脚本 |
| Query waiting_resource | 锁所属任务、同机任务、人工与外部占用 | 直接删除锁或数据库 |
| 服务重启后 interrupted | 原任务报告、远端进程和硬件实际状态 | 认为系统已自动续跑 |
| 报告产物未完成 | 本次任务 summary、诊断文件及草稿可读取性 | 复用历史同 IPS 结果掩盖缺失 |
| 通知没有送达 | Outlook COM、当前邮箱、草稿/发送模式与回退产物 | 将生成 .eml 或草稿视为已发送 |

日常检查重点是异常任务、磁盘空间、备份、报告链接和资源占用；每次变更后记录代码版本、配置变更及影响范围。处理故障先保全原始证据，再做获准操作。

## 10. 开发、回归与发布

### 10.1 维护约束

开发机只提交代码、可发布技能、文档和可移植模板。部署机只拉取批准版本并维护本机配置。新增机器相关值必须进入模板和本地配置契约，不在代码中硬编码开发者目录或实际目标地址。

核心 UI 是大文件，改动应同时考虑 API、页面、任务状态、报告存储、通知和离线测试。涉及路径/报告的变更要维持历史读取兼容；涉及取消/锁的变更要避免重复 Debug。

### 10.2 无硬件回归

在仓库根目录使用现有测试：

```powershell
python -m unittest discover -s .\scripts -p test_ips_copilot_ui.py -q
py -m py_compile .\scripts\ips_copilot_ui.py .\scripts\extract_hsd_article.py
git diff --check
```

现有 UI 测试覆盖任务状态、取消、锁、报告、配置合并、提示词和共性分析等逻辑，使用 mock 隔离外部操作。它们不证明真实 HSD 身份、Outlook 发送、SSH、烧录、启动和 MLC 可用。硬件与外部系统验收须独立记录。

### 10.3 GitHub 发布

用户指定的目标为现有仓库。上传资格与仓库可见性必须在发布前核对；私有仓库也不是上传凭据或内部客户数据的理由。

- 按明确清单暂存，不使用未经审阅的 git add .。
- 排除 out、inbox、config\local、私钥、令牌、原始客户数据、内部 PDF 和实际实验室配置。
- 对已被 Git 跟踪的排除项，仅新增 .gitignore 不会将其移出提交。
- 若历史提交已包含内部资料，删除当前文件也不会清除历史；须由仓库管理员决定受控历史清理或另建无历史的可发布快照，不擅自强推。
- 采用交接分支和评审流程，确认可访问的远程提交后才记录“上传完成”。

部署端更新前确认工作区干净，先保全本机配置与数据，再拉取批准版本。回滚应部署已知良好提交；如果更改过数据格式，应连同兼容备份一起恢复，不以 git reset --hard 处理用户数据。

## 11. 当前状态、限制与优先待办

编制时本地已有较多未发布修改，涉及 Query 分析、资源申请/通知、本地配置隔离、SSH 身份及实验室资料。起始提交不包含全部当前工作区能力。不能把工作区现状描述为远端 main 已发布版本。

| 优先级 | 事项 | 原因 / 完成标准 | 建议责任人 |
| --- | --- | --- | --- |
| P0 | 完成发布边界审查和 GitHub 身份授权 | 排除内部文件及历史泄露风险；取得实际远程提交 | 仓库管理员 |
| P0 | 接任人权限和资产登记 | GitHub、Copilot、HSD、控制机、邮箱分别获权；不复用离职者秘密 | 负责人 / IT |
| P0 | 本地配置与获准机器清单落地 | 所有占位值替换，身份及指纹核对，资源归属明确 | 运维 / 实验室 |
| P0 | 网络访问边界 | UI 无内建认证；共享部署须有批准的访问控制 | 安全 / 运维 |
| P1 | 真实系统验收 | 获准窗口完成 HSD、硬件、日志、MLC 和通知的分项签收 | 接任维护人 |
| P1 | 多实例与人工占用协调 | 本地 SQLite 锁不覆盖其他 UI 实例或手工命令 | 平台负责人 |
| P1 | MLC 迁移适配 | 源码仍有特定 Host prompt 与串口日志文件名假设 | 硬件维护人 |
| P1 | 文档示例统一 | 部分旧指南仍用历史主机/配置示例；以本地配置契约为准 | 文档维护人 |
| P1 | 备份与恢复演练 | 确认数据库/报告一致恢复，不自动继续中断硬件动作 | 运维 |
| P2 | 依赖与版本基线 | 核心工具版本、安装来源及升级策略未形成单一锁定清单 | 开发维护人 |
| P2 | 提取器边界 | 离线提取器只取 data[0]，HTML 清洗为启发式 | 开发维护人 |

以上是交接时可确认的限制和待办，不是新增的缺陷修复承诺。历史“已验证”记录只证明当时的特定设备与版本，不证明所有平台注册机器当前在线或已经兼容。

## 12. 资产与未结任务登记表

敏感字段仅填写内部资产编号或批准的保存位置，不填写口令、客户正文和私钥。真实 IP、身份文件路径、镜像清单等在内部受控副本中管理，不补入 GitHub 文档。

| 资产类别 | 交接记录 | 负责人 / 确认状态 |
| --- | --- | --- |
| 代码发布 | 分支：待填写；提交号：待填写；审批记录：待填写 | 待填写 |
| UI 部署 | 资产编号：待填写；启动方式：待填写；受控配置位置：待填写 | 待填写 |
| 控制机 / SUT | 平台、硬件资源、负责人和预约渠道：待填写 | 待填写 |
| 工具与许可证 | EM100、PowerSplitter、MLC、Copilot、Outlook：待填写 | 待填写 |
| 企业权限 | HSD/Query、GitHub、SSH、邮箱授权工单：待填写 | 待填写 |
| 内部参考资料 | 文档目录、访问授权、禁止外发标记：待填写 | 待填写 |
| 数据备份 | 受控位置、时间、完整性记录、保留规则：待填写 | 待填写 |
| 未完成任务 | 内部台账位置、任务状态、下一步、截止日：待填写 | 待填写 |
| 紧急支持 | 主维护人、备份维护人、实验室和 IT 联系渠道：待填写 | 待填写 |

未结任务应逐项登记“任务标识、业务影响、已完成动作、剩余工作、阻塞、证据位置、负责人、DDL”。本次未读取运行数据库与客户资料，因此不伪造正在运行的任务清单；由移交人从实际部署环境导出到内部台账。

## 13. 接收验收与离职退出清单

| 序号 | 验收项 | 通过标准 / 证据 | 接收签字 |
| --- | --- | --- | --- |
| 1 | 文档接收 | Markdown 与 Word 内容一致，可阅读和检索 | 待填写 |
| 2 | 仓库接收 | 接任人可访问批准分支；记录真实提交号 | 待填写 |
| 3 | 环境与配置 | 工具可用、本地配置隔离、敏感项不在 Git | 待填写 |
| 4 | UI 与阶段一 | 本地页面可用；生成计划无 HSD/硬件副作用 | 待填写 |
| 5 | 提取 / 咨询 | 获准样例产出可读报告，无硬件动作 | 待填写 |
| 6 | 自动任务与恢复 | 状态/重复拒绝/报告可用；重启不自动续跑硬件 | 待填写 |
| 7 | 硬件流程 | 获准样例四项烧录证据、完整 CPU/BMC 日志及实际测试结果 | 待填写 |
| 8 | 通知 | 草稿内容、收件人、链接、附件及授权发送结果分别确认 | 待填写 |
| 9 | 备份恢复 | 隔离恢复后历史报告可读，配置和硬件状态经人工核对 | 待填写 |
| 10 | 未结任务 | 每项有责任人、证据、下一步和 DDL | 待填写 |
| 11 | 权限退出 | 接任人独立身份可用后，按审批撤销离职人员个人权限 | 待填写 |

建议按“阅读与环境 → 只读业务 → 获准硬件 → 备份恢复 → 独立值守”分阶段完成接收。移交人、接收人和负责人分别签字，未完成验收项不得仅因离职日期临近而标记通过。

## 14. 后续文档维护

本 Markdown 是内容维护源；Word 为同内容排版副本。修改架构、配置契约、数据路径、关键安全规则或发布方式后，应更新两种格式及版本日期。

配套阅读顺序：docs\AI_QUICK_INDEX.md → docs\development_deployment_contract.md → docs\local_runtime_profiles.md → docs\ips_copilot_ui.md → 与任务匹配的技能及操作指南。存在示例冲突时，以当前源代码、配置模板与经批准的部署配置为准，必要时登记差异，不猜测生产环境。

移交人签字：________________    接收人签字：________________

负责人签字：________________    日期：________________
