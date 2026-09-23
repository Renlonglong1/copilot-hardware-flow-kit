# SSH 免密连接记录

## Historical Target Server

```text
debug@10.239.84.44
```

## Historical Connection Record

The following is historical evidence only and is not permission to connect without
the current dedicated-identity and host-key policy:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 debug@10.239.84.44 "cd"
```

已观察到远端默认目录：

```text
C:\Users\debug
```

远端默认 shell 表现为 Windows `cmd` 环境，因此 Linux 命令如 `pwd` 不适用；应使用：

```bat
cd
dir
```

或通过 SSH 调用 PowerShell：

```powershell
ssh debug@10.239.84.44 "powershell -NoProfile -Command ""Get-ChildItem"""
```

## 验证脚本

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1
```

## 默认 SSH 失败时：先加载本机运行时配置

直接调用 `ssh -o BatchMode=yes debug@<host>` 时，OpenSSH 可能没有选中目标机专用
私钥；即使本机的 `config\local\hardware-flow.json` 已配置 `identityFile` 和
`hostKeyAlias`，直接 SSH 命令也不会读取该 JSON。若返回：

```text
Permission denied (publickey,password,keyboard-interactive).
```

先不要执行 flash、PowerSplitter、串口或 MLC，但也不要直接将其报告为
“无法 SSH 连接”或主机不可达。优先通过会解析本机运行时配置的连接检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1
```

若输出 `SSH_OK`，说明本机已配置的目标专用身份文件与已验证的主机密钥可用；
后续硬件脚本应保持使用该同一本机配置。仅当此检查也失败时，才继续诊断密钥、
主机密钥或网络。

### 诊断

若 `Test-SshAccess.ps1` 失败，查看默认 SSH 实际会尝试的身份文件：

```powershell
ssh -G debug@<host> | Select-String '^(hostname|user|identityfile|identitiesonly|userknownhostsfile) '
```

若本机运行时配置没有可用身份文件，但已经安全地配置了某台目标机专用私钥，
可显式指定该密钥进行只读验证。不要打印、复制或提交私钥内容：

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes `
  -i "$HOME\.ssh\<target-specific-key>" debug@<ip> "echo SSH_OK"
```

`SSH_OK` 且退出码为 `0` 说明网络、主机密钥和该身份文件均正常。优先将
`identityFile` 与 `hostKeyAlias` 保存在忽略的 `config\local\hardware-flow.json`，
让所有硬件脚本复用。也可在本机的 `C:\Users\<user>\.ssh\config`（不提交到仓库）
添加对应 `Host` 的 `IdentityFile` 和 `IdentitiesOnly yes` 配置。不得将私钥内容
提交到仓库。

### Dedicated Identity and Host-Key Policy (Current)

For a read-only lab audit, use a target-specific local identity **and** a dedicated
known-hosts file. Both must remain outside the repository. Require:

```text
BatchMode=yes
IdentitiesOnly=yes
PasswordAuthentication=no
KbdInteractiveAuthentication=no
PreferredAuthentications=publickey
StrictHostKeyChecking=yes
UserKnownHostsFile=<dedicated local known_hosts>
GlobalKnownHostsFile=NUL
```

If the dedicated known-hosts file lacks an entry, stop. Do not use
`StrictHostKeyChecking=accept-new`, `StrictHostKeyChecking=no`, password
authentication, default identities, or an interactive prompt to reach the host.

On 2026-08-06 this rule prevented an audit of `dbgsh12` / `10.239.84.44`; its reported
down state remains unverified. See `docs\lab_machine_readonly_audit_2026-08-06.md`.

### 主机名的主机密钥校验失败

若 IP 连接正常、但主机名连接报：

```text
Host key verification failed.
```

通常是因为 `known_hosts` 仅记录了 IP，而未记录主机名。先使用已验证的 IP 主机密钥作为别名进行一次安全验证：

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes `
  -o HostKeyAlias=<verified-ip> -i "$HOME\.ssh\<target-specific-key>" `
  debug@<ip> "echo SSH_OK"
```

不要用 `StrictHostKeyChecking=no` 绕过校验；若同一 IP 已有的主机密钥不匹配，应停止并由实验室管理员确认远端主机密钥是否变更。

## 注意事项

1. 不要在文档或脚本中保存私钥内容。
2. 使用 `BatchMode=yes` 可以避免 SSH 卡在密码输入。
3. 使用 `ConnectTimeout` 避免网络异常时长时间等待。
4. 远端路径使用 Windows 风格反斜杠，例如 `C:\Users\debug`。
5. 目标为 Windows `cmd` 默认 shell 时，远端连通性探测使用 `echo SSH_OK`；PowerShell 命令须显式以 `powershell -NoProfile -Command` 调用。

## 已验证

| 时间 | 服务器 | 命令 | 结果 |
|---|---|---|---|
| 2026-06-16 | `debug@10.239.84.44` | `ssh -o BatchMode=yes -o ConnectTimeout=10 debug@10.239.84.44 "cd & dir"` | 成功列出 `C:\Users\debug` |
| 2026-08-06 | `debug@10.239.84.53` (DBGSH05) | 显式使用本机目标专用身份文件并复用已验证 IP 主机密钥 | `SSH_OK`，退出码 0 |
| 2026-08-06 | `debug@10.238.12.230` (DBGSH16) | 显式使用本机目标专用身份文件并复用已验证 IP 主机密钥 | `SSH_OK`，退出码 0 |
