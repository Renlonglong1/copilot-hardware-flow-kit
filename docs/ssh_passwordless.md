# SSH 免密连接记录

## 目标服务器

```text
debug@10.239.84.44
```

## 已跑通的连接方式

本机已能通过 SSH 免密连接远端 Windows 服务器：

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

## 注意事项

1. 不要在文档或脚本中保存私钥内容。
2. 使用 `BatchMode=yes` 可以避免 SSH 卡在密码输入。
3. 使用 `ConnectTimeout` 避免网络异常时长时间等待。
4. 远端路径使用 Windows 风格反斜杠，例如 `C:\Users\debug`。

## 已验证

| 时间 | 服务器 | 命令 | 结果 |
|---|---|---|---|
| 2026-06-16 | `debug@10.239.84.44` | `ssh -o BatchMode=yes -o ConnectTimeout=10 debug@10.239.84.44 "cd & dir"` | 成功列出 `C:\Users\debug` |
