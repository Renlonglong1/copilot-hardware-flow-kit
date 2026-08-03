# Common PowerShell / Python Command Templates

This is the human-readable companion to:

```text
.github\skills\common-ps-py-commands\SKILL.md
```

Use that skill when you need ready-to-run commands for:

- HSD article fetch
- HSD raw field inspection
- local UI start and validation
- SSH host identity checks
- EM100 / DediProg precheck
- PowerSplitter
- BHS one-pass validated flow
- boot capture
- MLC serial execution
- report path conventions

The goal is to reduce repeated AI reasoning and token usage. Prefer copying commands from the skill instead of re-deriving PowerShell syntax.

## Most Common Commands

Start UI:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1
```

Fetch HSD:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <ARTICLE_ID> -ForceCurlDirect
```

Run validated BHS flow:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

Validate local scripts:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
py -m py_compile .\scripts\ips_copilot_ui.py .\scripts\extract_hsd_article.py
```

Create an Outlook notification draft. The body should use the worker-focused `客户机器环境`、`客户问题`、`诊断结果`、`重点关注`、`下一步研究方向`、`完整报告` sections defined in `docs\ips_copilot_ui.md`; attach the full Markdown report:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To 'Li, Renlong' -Subject 'HSD <ARTICLE_ID> analysis completed' -Body '<SUMMARY_AND_REPORT_PATH>' -Attachments 'out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_consult_report.md'
```

## Important Shortcuts

Use Copilot CLI startup permission flag for subprocesses:

```text
copilot --allow-all
```

Do not rely on sending this through subprocess stdin:

```text
/allow-all
```

It is an interactive slash command and may be interpreted as normal prompt text.
