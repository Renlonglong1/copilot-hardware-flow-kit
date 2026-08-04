# GitHub 使用手册

本手册说明如何管理 `copilot-hardware-flow-kit` 的代码。请区分两个位置：

| 位置 | 用途 | 应该做什么 |
| --- | --- | --- |
| 个人电脑 | 开发并上传代码 | 修改、测试、提交（commit）、推送（push）到 GitHub |
| 硬件/控制服务器 | 运行已验证的硬件流程 | 只从 GitHub 拉取已经合入 `main` 的代码，然后运行脚本 |

GitHub 保存脚本、skills、文档和不含敏感信息的配置模板。**不要提交**密码、访问令牌、SSH 私钥、客户数据或原始客户日志。

仓库地址：

```text
https://github.com/Renlonglong1/copilot-hardware-flow-kit.git
```

## 1. 个人电脑：首次配置

在**个人电脑的 PowerShell** 中运行以下命令。`$HOME` 会自动代表当前 Windows 用户目录，例如 `C:\Users\rli`，不需要手工替换。

```powershell
Set-Location $HOME
git clone https://github.com/Renlonglong1/copilot-hardware-flow-kit.git
Set-Location "$HOME\copilot-hardware-flow-kit"
git status
```

`git status` 成功时应显示 `On branch main` 和 `nothing to commit, working tree clean`，表示已在 `main` 分支且没有未提交的修改。

设置提交记录中显示的姓名和邮箱。只替换双引号内的内容为自己的 GitHub 姓名和邮箱：

```powershell
git config --global user.name "Your GitHub display name"
git config --global user.email "your-github-email@example.com"
git config --global --get user.name
git config --global --get user.email
```

第一次执行 `git push` 时，如果出现登录提示，请按浏览器或 Git Credential Manager 的提示完成公司批准的 GitHub 登录。安装了 GitHub CLI 时，也可以运行 `gh auth login`，依次选择 **GitHub.com**、**HTTPS** 和浏览器登录。不要将个人访问令牌粘贴到脚本、配置文件或仓库中。

## 2. 个人电脑：修改并上传一次代码

每次修改本工具包前，先执行下面的命令。示例分支名 `docs-git-quick-start` 可以改为简短的英文描述，例如 `fix-em100-check`：

```powershell
Set-Location "$HOME\copilot-hardware-flow-kit"
git switch main
git pull --ff-only origin main
git switch -c docs-git-quick-start
```

现在修改并测试文件。完成后执行下面的命令。将 `USER_QUICK_START.md` 改为实际修改的文件或目录；除非已逐一确认所有改动，否则不要使用 `git add .`。

```powershell
git status
git diff
git add USER_QUICK_START.md
git diff --cached
git commit -m "Document GitHub development workflow"
git push -u origin docs-git-quick-start
```

常用命令含义：

| 命令 | 含义 |
| --- | --- |
| `git status` | 列出已修改、新增和已暂存的文件。每次提交前都要检查。 |
| `git diff` | 显示尚未 `git add` 的修改内容。 |
| `git add <文件>` | 只选择已经确认的文件，放入下一次提交。 |
| `git commit -m "..."` | 在本机创建一次提交记录，尚未上传。 |
| `git push` | 将已提交的分支上传到 GitHub。 |

完成 `git push` 后，打开 GitHub 仓库页面，创建从新分支到 `main` 的 Pull Request；评审后合入。不要直接在硬件服务器上开发。

## 3. 硬件服务器：首次拉取代码

登录 Windows 硬件/控制服务器，在服务器的 PowerShell 中只执行一次以下命令。`$HOME` 代表当前服务器账号目录，例如 `C:\Users\debug`。

```powershell
Set-Location $HOME
git clone https://github.com/Renlonglong1/copilot-hardware-flow-kit.git
Set-Location "$HOME\copilot-hardware-flow-kit"
git status
```

如果拉取私有仓库时要求登录，请使用服务器账号已批准的 GitHub 登录方式。不要从个人电脑复制密码、令牌或私钥到服务器。

## 4. 硬件服务器：运行流程前更新代码

每次启动已验证的硬件流程前，在硬件/控制服务器上运行：

```powershell
Set-Location "$HOME\copilot-hardware-flow-kit"
git status
git switch main
git pull --ff-only origin main
git log -1 --oneline
```

只有当 `git status` 显示 `nothing to commit, working tree clean` 时才继续。`git pull --ff-only` 会下载最新、已评审的 `main` 代码，并拒绝覆盖服务器本地修改。如果发现本地修改，请停止操作，将文件保存到仓库外，或请修改者提交；不要使用强制重置命令。

`out\` 已被 Git 忽略，报告和生成日志不会被提交。服务器专用配置请保存在仓库外，例如：

```powershell
New-Item -ItemType Directory -Path "$HOME\copilot-hardware-flow-local" -Force
Copy-Item .\config\hardware-flow.template.json `
  "$HOME\copilot-hardware-flow-local\hardware-flow.<server-name>.json"
```

将 `<server-name>` 替换为服务器名称，例如 `dbgsh05`。运行硬件流程时，将这个外置配置文件完整路径传给 `-ConfigPath`，例如：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 `
  -ConfigPath "$HOME\copilot-hardware-flow-local\hardware-flow.dbgsh05.json" `
  -CloseGuiConflicts -RunMlc
```

这样服务器专用配置不会被误加入 Git。
