# Common safe entry points

Run commands from the repository root. Create and review local profiles using
`README.md` before any external or hardware operation.

```powershell
python -m unittest discover -s .\scripts -p test_ips_copilot_ui.py -q
py -m py_compile .\scripts\ips_copilot_ui.py .\scripts\extract_hsd_article.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -NoBrowser
```

HSD fetch requires approved network and identity but no hardware access:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <ARTICLE_ID> -ForceCurlDirect
```

SSH precheck contacts the configured control machine and is not an offline test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1 -ConfigPath .\config\local\hardware-flow.json
```

For authorized hardware commands use `docs\bhs_uplr2_robust_full_flow.md`.
All host/address examples in the command skill are documentation placeholders,
not known-good assets. Obtain actual values from the approved ignored profile.
