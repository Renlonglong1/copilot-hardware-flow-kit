# Copilot Hardware Flow Kit 新电脑迁移指南

本文用于将 Copilot Hardware Flow Kit 部署到新的 Windows 电脑。目标是让新电脑能够安全地运行本地 UI、HSD/IPS 分析，以及在完成授权后运行硬件流程。

> **边界：** Git 仓库只提供可移植的代码、模板和文档。SSH 私钥、主机信任记录、个人登录状态、本机运行配置、真实实验室地址和客户日志都不应迁移到 Git 或提交到仓库。

## 1. 迁移范围与前提

| 能力 | 是否依赖 SSH | 新电脑还需要具备的条件 |
| --- | --- | --- |
| 本地 UI、指南和仅生成计划 | 否 | Python、Git、Copilot CLI 及本人登录 |
| HSD 提取、咨询、只读共性分析 | 否 | 企业网络/VPN、HSD 权限；AI 分析还需要 Copilot CLI |
| 浏览历史报告 | 否 | 单独迁移经批准的 `out\` 数据和索引；Git 不包含这些数据 |
| Outlook 草稿或通知 | 否 | 当前 Windows 用户的 Outlook 和邮箱配置 |
| 远端预检、烧录、电源、串口、MLC | 是 | 新 SSH 身份、控制机授权、网络、主机信任和硬件配置 |

新电脑的 SSH 能力必须独立建立。不要复制旧电脑的私钥、`known_hosts`、ssh-agent 状态或旧电脑的个人 SSH 配置。

## 2. 安装并验证本机基础工具

安装或确认以下工具，并使用本人已获授权的账号登录：

- Git
- Python（命令为 `py`）
- GitHub Copilot CLI（命令为 `copilot`）
- Windows PowerShell
- OpenSSH Client（硬件流程需要 `ssh`、`scp`、`ssh-keygen`、`ssh-add`）
- 企业网络或 VPN；如需 HSD 功能，还需要 HSD 访问权限

克隆仓库并核对环境：

```powershell
git clone https://github.com/Renlonglong1/copilot-hardware-flow-kit.git
Set-Location .\copilot-hardware-flow-kit
git status --short
py --version
Get-Command git, py, powershell, ssh, scp, ssh-keygen, ssh-add, copilot
```

无法访问仓库时，应由管理员授予新用户的 GitHub 权限；不要共享或迁移其他人的令牌。

## 3. 创建新电脑的本机配置

本机配置保存在被 Git 忽略的位置，不应提交：

```powershell
New-Item -ItemType Directory -Path .\config\local -Force
Copy-Item .\config\hardware-flow.template.json .\config\local\hardware-flow.json
Copy-Item .\config\ips-copilot-ui.template.json .\config\local\ips-copilot-ui.json
```

若目标文件已存在，先备份并核对，不能用模板直接覆盖已验证的本机配置。

### 3.1 `hardware-flow.json` 必须核对的字段

| 区域 | 需要按新环境确认的内容 |
| --- | --- |
| `ssh` | 控制机账号、主机名/IP、超时、`identityFile`、可选 `hostKeyAlias` |
| `remote.emulator` | EM100 / DediProg 工具路径、芯片型号、设备序列号 |
| `remote.powerSplitter` | PowerSplitter 可执行文件和配置路径 |
| `remote.serial` | CPU/BMC 串口号和串口参数 |
| `flow` | BIOS 镜像路径和哈希、日志目录、烧录与启动关键字、超时和重试策略 |
| `hostOs` | Host OS 登录用户、MLC 路径和已验证结果目录 |

模板中的芯片、设备序列号、串口、远端路径、镜像和启动关键字都只是示例，必须逐项确认。配置中只能保存**私钥文件路径**，绝不能写入私钥内容、密码、令牌或 Cookie。

硬件脚本解析配置的优先级为：

1. 显式 `-ConfigPath`
2. `COPILOT_HARDWARE_FLOW_CONFIG` 环境变量
3. `config\local\hardware-flow.json`
4. `$HOME\copilot-hardware-flow-local\hardware-flow.json`

### 3.2 本机 UI 和机器清单

- 默认 UI 仅监听 `127.0.0.1`，通常不需要修改模板。
- 只有需要通过企业内网/VPN 访问时，才在 `config\local\ips-copilot-ui.json` 设置本机 LAN 地址和对应的 `server.reportBaseUrl`。
- UI 没有内建认证。不得暴露到公网；内网共享时必须限制 Windows 防火墙来源，并使用组织批准的访问控制方案。
- 机器匹配应使用本机获批准的机器清单。不要把历史实验室快照当作新环境的活动配置。

## 4. 新电脑 SSH 配置与授权

远程操作通常连接安装了 EM100 和 PowerSplitter 的 Windows 控制机，而不是直接连接被测 Linux Host OS。

### 4.1 安装或确认 OpenSSH Client

```powershell
Get-Command ssh, scp, ssh-keygen, ssh-add
ssh -V
```

若未安装，应由 IT 或获准管理员在管理员 PowerShell 中安装 OpenSSH Client。新电脑仅作为客户端时，无需启用 OpenSSH Server。

### 4.2 生成新电脑专用密钥

在新电脑的实际运行用户下生成新的专用密钥；不要覆盖已有密钥：

```powershell
New-Item -ItemType Directory -Path "$HOME\.ssh" -Force
$keyPath = Join-Path $HOME '.ssh\hardware_flow_ed25519'
if ((Test-Path $keyPath) -or (Test-Path "$keyPath.pub")) {
    throw 'Key file already exists; do not overwrite it.'
}
ssh-keygen -t ed25519 -a 64 -f $keyPath
```

私钥只保留在新电脑受控目录中。仅将 `.pub` 公钥通过批准渠道交给控制机管理员，由管理员授权到实际远端登录账号。不要发送私钥，不要把保护口令写进命令、脚本、配置或聊天记录。

如密钥设置了保护口令，应按企业策略使用 ssh-agent，并确保 UI 与命令行由同一个 Windows 用户运行：

```powershell
ssh-add "$HOME\.ssh\hardware_flow_ed25519"
ssh-add -l
```

### 4.3 建立可信主机记录

从控制机管理员或可信资产记录取得 SSH 主机公钥的 SHA256 指纹。扫描得到的公钥必须与该可信指纹逐项一致，才可加入本机专用 `known_hosts`。

在 `$HOME\.ssh\config` 中为该控制机添加专用 Host 段，并保持以下安全策略：

```text
Host REPLACE_WITH_APPROVED_HOST
    BatchMode yes
    IdentitiesOnly yes
    PreferredAuthentications publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    StrictHostKeyChecking yes
    UserKnownHostsFile "C:\\Users\\YOUR_USER\\.ssh\\known_hosts.hardware"
    GlobalKnownHostsFile NUL
```

禁止使用 `StrictHostKeyChecking=no` 或 `accept-new` 来绕过主机指纹核对。

### 4.4 绑定 SSH 身份到本机硬件配置

仅更新 `config\local\hardware-flow.json` 的 `ssh` 对象，且填写实际获批准的用户、主机和私钥**路径**：

```json
{
  "ssh": {
    "user": "REPLACE_WITH_APPROVED_USER",
    "host": "REPLACE_WITH_APPROVED_HOST",
    "connectTimeoutSeconds": 10,
    "identityFile": "C:\\Users\\YOUR_USER\\.ssh\\hardware_flow_ed25519",
    "hostKeyAlias": ""
  }
}
```

当前脚本从 JSON 读取目标、身份文件和主机别名；专用 `known_hosts` 的路径及严格校验策略应在本机 OpenSSH 配置中维护。

## 5. 分级验收

### 5.1 先验证本地 UI

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -NoBrowser
```

默认地址为 `http://127.0.0.1:8765/`。确认工作台、任务中心、报告中心和使用指南能打开；先执行“仅生成计划”的无副作用验证，不要用真实 Debug 或自动 Query 来测试安装。

### 5.2 验证 SSH，且不执行硬件操作

先检查有效 OpenSSH 配置和端口连通性：

```powershell
ssh -G REPLACE_WITH_APPROVED_HOST |
    Select-String '^(hostname|userknownhostsfile|stricthostkeychecking|batchmode|identitiesonly) '
Test-NetConnection -ComputerName REPLACE_WITH_APPROVED_HOST -Port 22
```

随后运行仓库提供的无硬件动作预检：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1 -ConfigPath .\config\local\hardware-flow.json
$LASTEXITCODE
```

通过条件为输出 `SSH_OK` 且退出码为 `0`。该检查不会烧录、断电、抓串口或运行 MLC。

### 5.3 硬件流程前的单独确认

`SSH_OK` 只表示连接与认证成功。进入硬件流程前，仍需确认：

- 控制机上的 EM100 / DediProg、PowerSplitter 和串口工具路径有效。
- USB 设备、EM100 设备序列号和串口映射正确，且工具未被 GUI 进程占用。
- 目标 BIOS 镜像、哈希、芯片型号和日志目录正确。
- 控制机账号拥有所需的工具与设备访问权限。
- MLC 及 Host OS 所需前提已单独满足。

烧录成功必须同时确认以下信息：

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

若出现 `No device is connected!`、`Verify Fail`、`Authentication Fail`、`Download failed` 或 `ERROR`，必须停止后续启动日志抓取与 MLC 操作，先修复烧录问题。

## 6. 交接验收清单

- [ ] 已用本人账号克隆仓库，并完成 Git、Python 和 Copilot CLI 验证。
- [ ] 已具备企业网络/VPN、HSD 和 GitHub 所需授权。
- [ ] 已创建且核对 `config\local\hardware-flow.json`。
- [ ] 已按需创建 `config\local\ips-copilot-ui.json`，未暴露公网。
- [ ] 已登记经批准的机器清单，未采用未经核对的历史配置。
- [ ] 已安装 OpenSSH Client，并由本人生成新的受保护密钥。
- [ ] 控制机管理员已授权新公钥到正确的远端账号。
- [ ] 已独立核对控制机主机指纹并启用严格主机校验。
- [ ] `Test-SshAccess.ps1` 输出 `SSH_OK` 且退出码为 `0`。
- [ ] 已逐项核对远端工具、设备、串口、镜像和 MLC 前提，之后才执行硬件流程。

## 7. 常见问题定位

| 现象 | 优先检查项 |
| --- | --- |
| 找不到 `ssh` 或 `scp` | OpenSSH Client 是否安装、终端是否重开、UI 的 PATH 是否一致 |
| TCP 连接超时或拒绝 | 企业网络/VPN、控制机地址、端口、sshd 服务和防火墙规则 |
| `Host key verification failed` | 专用 `known_hosts` 路径、Host 段匹配、主机指纹或别名 |
| `Permission denied (publickey)` | 远端账号、公钥授权位置和 ACL、SSH Match 规则、本机 `identityFile` |
| 手动可登录但预检失败 | 手动连接是否依赖交互式密码；检查 agent、`BatchMode`、运行用户和 SSH 实现 |
| SSH 成功但硬件命令失败 | 分别检查远端工具路径、账号权限、设备占用和硬件配置；不要将其误判为 SSH 问题 |

