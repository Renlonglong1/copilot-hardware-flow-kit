# Copilot HSD 硬件 Debug 链路说明

Copyright (c) Team PAE FW.  
Author: Li Renlong  
Nickname: longlin

对应的 draw.io 流程图文件：

```text
docs\copilot_hsd_hardware_debug_chain.drawio
```

## 1. 目标

这个流程图描述的是一个长期目标：通过 **Copilot CLI + 脚本**，把下面两条已经验证过的流程串联起来：

1. HSD 问题单读取、文章字段抽取、AI 摘要和初步问题分析。
2. 内部硬件复现、BIOS 烧录、启动日志抓取、MLC 测试和结果分析。

最终希望提升开发者的工作效率：当 HSD 中出现新的问题单时，Copilot CLI 可以协助提取关键信息，生成问题摘要和初步判断；如果问题需要复现，则进一步根据问题单中的配置，在内部机器上搭建相同或相近的环境进行测试和分析。

## 2. 当前状态

目前两条流程已经分别单独跑通：

| 流程 | 状态 | 关键证据 |
|---|---|---|
| HSD 分析流程 | 已验证 | 可以检索文章、抽取字段、生成摘要和初步判断 |
| 硬件验证流程 | 已验证 | SSH、EM100 烧录、COM3/COM4 启动日志抓取、MLC baseline 均已跑通 |

当前这两条流程 **还没有完全自动联动**。后续工作是把 HSD 中提取到的配置信息，自动转换成内部硬件复现实验计划。

## 3. 流程图结构

draw.io 图中分成四个泳道。

### 3.1 HSD / Issue Intake

这个泳道表示问题输入来源。

主要步骤：

1. HSD 中出现新的 issue 或 bug。
2. Copilot 使用 `scripts\Invoke-HsdArticleFetch.ps1` 检索文章。
3. 脚本抽取关键信息，例如 title、status、description、comments、customer blog history、attachments、platform、component 和配置线索。

已验证的 fallback 命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <article-id> -ForceCurlDirect
```

当 Python API 访问返回 generic HTML `403 Access Denied` 时，使用这个 fallback。

### 3.2 Copilot CLI + AI Reasoning

这个泳道表示 Copilot 的分析和面向开发者的输出。

主要步骤：

1. 生成简洁的问题摘要。
2. 识别客户诉求、问题现象、平台、组件和缺失信息。
3. 给出初步问题推测或 debug 方向。
4. 判断是否需要内部复现。

如果不需要复现，Copilot 可以直接输出：

```text
问题摘要 + 建议 + 需要补充的数据
```

如果需要复现，Copilot 应根据 HSD 中的配置生成复现实验计划。

### 3.3 Portable Flow Kit

这个泳道表示可迁移的知识和自动化脚本库。

核心内容包括：

```text
README.md
USER_QUICK_START.md
.github\copilot-instructions.md
docs\*.md
config\hardware-flow.<server>.json
scripts\*.ps1
```

这个 kit 中保存：

1. 已验证命令。
2. 服务器相关配置。
3. 已知风险点和恢复规则。
4. HSD 字段抽取逻辑。
5. 硬件自动化脚本。
6. 历史 debug 过程中沉淀下来的经验。

当前已经验证过的重要经验：

```text
EM100.exe / Emulator.exe 会占用 EM100，导致 smucmd 访问失败。
smucmd 不能只看退出码，必须检查输出关键字。
远端 PowerShell 命令过长可能失败，应复制 helper 脚本到远端后用 powershell -File 执行。
COM3 串口命令 marker 可能被 echo 回显，必须确认真实 shell prompt 和保存的结果文件。
HSD Python requests 可能遇到 generic 403，需要使用 curl --noproxy "*" fallback。
```

### 3.4 Internal Hardware Reproduction

这个泳道表示实验室内部硬件复现路径。

主要步骤：

1. 准备内部硬件服务器和 SSH 访问。
2. 检查 DediProg EM100、PowerSplitter、串口和目标 BIOS 镜像。
3. 关电并通过 `smucmd.exe` 烧录。
4. 在开电前先打开 COM3/COM4。
5. 抓取完整原始启动日志。
6. 通过 COM3 登录 Host OS。
7. 运行 MLC baseline 并保存日志。
8. 把实验结果反馈给 Copilot 继续分析。

已验证的一键命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

## 4. 关键规则

### 烧录成功后才能开始串口长时间抓取

不要在 EM100 烧录失败的情况下开始 COM3/COM4 长时间抓取。

烧录成功必须同时包含：

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

### 不保存 HSD 凭据

使用用户当前 Windows/Kerberos 登录态。不要询问或保存：

```text
passwords
cookies
SSO tokens
service tokens
Kerberos ticket contents
SSH private keys
```

### AI 输出必须基于证据

Copilot 输出时应区分：

```text
HSD 中的已知事实
硬件日志中的观测证据
初步问题推测
建议的下一步行动
尚未确认的假设
```

## 5. 未来联动计划

未来最关键的联动点是：

```text
HSD 中抽取到的配置信息
```

和：

```text
内部硬件复现配置
```

预期未来自动化流程：

1. 解析 HSD 文章字段。
2. 识别平台、CPU、BIOS/IFWI、DIMM、BMC、OS、测试项和日志需求。
3. 生成或选择匹配的 `config\hardware-flow.<server>.json`。
4. 运行对应的硬件验证脚本。
5. 分析 COM3/COM4/MLC 日志。
6. 生成面向开发者的报告。

目标最终输出：

```text
HSD 问题摘要
初步 root cause 推测
内部复现实验计划
实验执行结果
日志证据
建议修复方向或下一步 debug 行动
```

## 6. 如何使用这个流程图

打开 draw.io 文件：

```text
docs\copilot_hsd_hardware_debug_chain.drawio
```

这个流程图可以用于：

1. 向团队解释长期的 Copilot 辅助 debug 工作流。
2. 新 Copilot 环境迁移时作为参考。
3. 作为后续自动化开发的设计基线，用于把 HSD 分析和内部硬件复现连接起来。

## 7. 所有权说明

```text
Team: Team PAE FW
Author: Li Renlong
Nickname: longlin
Purpose: Copilot-assisted HSD analysis, hardware reproduction, debug automation, and knowledge reuse
```

本文档和对应的 draw.io 文件仅用于授权范围内的内部开发、验证和 debug 工作。
