---
name: common-ps-py-commands
description: "Use when: needing common PowerShell/Python commands for this hardware flow kit, including HSD fetch, UI start, SSH precheck, EM100 flash, PowerSplitter, boot capture, MLC serial execution, report paths, and validation commands. This skill reduces repeated reasoning and token usage by providing ready-to-run templates."
---

# Common PowerShell / Python Commands Skill

Use this skill as a command template library. Prefer these commands instead of re-deriving syntax.

Assume kit root:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
```

## 1. Validate Local Kit

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
py -m py_compile .\scripts\ips_copilot_ui.py .\scripts\extract_hsd_article.py
Get-Content .\config\ips-copilot-ui.template.json -Raw | ConvertFrom-Json | Out-Null
Get-Content .\config\hardware-flow.dbgsh05.json -Raw | ConvertFrom-Json | Out-Null
```

## 2. Start Local IPS/HSD UI

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1
```

No browser:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Start-IpsCopilotUi.ps1 -NoBrowser
```

Validation port:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
py .\scripts\ips_copilot_ui.py --config .\config\ips-copilot-ui.template.json --no-browser --port 8770 --copilot-mode manual
```

## 3. HSD Article Fetch

Default:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <ARTICLE_ID>
```

Force Kerberos curl direct:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <ARTICLE_ID> -ForceCurlDirect
```

Outputs:

```text
out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_raw.json
out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_extracted.json
out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_extracted.txt
```

## 4. Inspect HSD Raw Fields

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
$env:PYTHONIOENCODING='utf-8'
@'
import json, re
article_id = '<ARTICLE_ID>'
row = json.load(open(f'out/{article_id}/hsd_{article_id}_raw.json', encoding='utf-8'))['data'][0]
for key in sorted(row):
    value = row[key]
    if value in (None, '', [], {}):
        continue
    if re.search(r'(owner|title|status|priority|family|release|component|bkc|bios|ifwi|cpu|platform|attach|file|overview|root|cause|fix|workaround|comment|blog|hist)', key, re.I):
        text = str(value).replace('\r', ' ').replace('\n', ' ')
        print(f'{key}: {text[:800]}')
'@ | py -
```

## 5. SSH / Host Identity Precheck

Use FQDN and temporary known_hosts if host key aliases are confusing:

```powershell
$kh = Join-Path $env:TEMP 'known_hosts_dbgsh05_copilot'
$script = @'
$ProgressPreference='SilentlyContinue'
Write-Output '---HOST---'; hostname
Write-Output '---IP---'
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -like '10.*'} |
  Select-Object IPAddress,InterfaceAlias | Format-Table -AutoSize
Write-Output '---BKC---'
Get-ChildItem 'C:\Users\debug\Desktop\BKC' -Directory |
  Sort-Object Name | Select-Object Name | Format-Table -AutoSize
'@
$enc=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
ssh -o BatchMode=yes -o ConnectTimeout=10 -o UserKnownHostsFile=$kh -o StrictHostKeyChecking=accept-new debug@dbgsh05.ccr.corp.intel.com "powershell.exe -NoProfile -NonInteractive -EncodedCommand $enc"
```

Known mapping:

```text
dbgsh05.ccr.corp.intel.com -> 10.239.84.53, BHS/GNRSP BKC, COM3/COM4
dbgsh12.ccr.corp.intel.com -> 10.239.84.44, OKS/Johnson City BKC
```

## 6. BHS One-Pass Validated Flow

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

## 7. EM100 / DediProg Precheck

```powershell
$kh = Join-Path $env:TEMP 'known_hosts_dbgsh05_copilot'
$script = @'
$smu='C:\Program Files (x86)\DediProg\Emulator\smucmd.exe'
Write-Output '=== GUI/DEDIPROG PROCESSES ==='
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'EM100|Emulator|smucmd|DediProg' -or $_.CommandLine -match 'EM100|Emulator|smucmd|DediProg' } |
  Select-Object ProcessId,Name,CommandLine | Format-Table -AutoSize -Wrap
Write-Output '=== USB ==='
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.Name -match 'DediProg|EM100' -or $_.DeviceID -match 'VID_04B4|VID_04D8' } |
  Select-Object Name,Status,DeviceID | Format-Table -AutoSize -Wrap
Write-Output '=== SMUCMD CHECK ==='
Set-Location -LiteralPath 'C:\Program Files (x86)\DediProg\Emulator'
& $smu -c
Write-Output "SMUCMD_CHECK_EXIT=$LASTEXITCODE"
'@
$enc=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
ssh -o BatchMode=yes -o ConnectTimeout=10 -o UserKnownHostsFile=$kh -o StrictHostKeyChecking=accept-new debug@dbgsh05.ccr.corp.intel.com "powershell.exe -NoProfile -NonInteractive -EncodedCommand $enc"
```

## 8. Close EM100 GUI Conflict by PID

```powershell
$kh = Join-Path $env:TEMP 'known_hosts_dbgsh05_copilot'
$script = @'
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match '^(EM100|Emulator)\.exe$' } |
  ForEach-Object {
    Write-Output "Stopping PID=$($_.ProcessId) Name=$($_.Name)"
    Stop-Process -Id $_.ProcessId -ErrorAction Continue
  }
'@
$enc=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
ssh -o BatchMode=yes -o ConnectTimeout=10 -o UserKnownHostsFile=$kh -o StrictHostKeyChecking=accept-new debug@dbgsh05.ccr.corp.intel.com "powershell.exe -NoProfile -NonInteractive -EncodedCommand $enc"
```

## 9. PowerSplitter

Through existing wrapper:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-PowerSplitter.ps1 -Action poweroff -ConfigPath .\config\hardware-flow.dbgsh05.json
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-PowerSplitter.ps1 -Action poweron -ConfigPath .\config\hardware-flow.dbgsh05.json
```

## 10. Program EM100

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-Emulator.ps1 -Action program -Chip MX66U1G45G -BinFile '<REMOTE_BIN_PATH>' -ConfigPath .\config\hardware-flow.dbgsh05.json
```

Flash success keywords:

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

Failure keywords:

```text
No device is connected!
Verify Fail
Authentication Fail
Download failed
ERROR
```

## 11. Boot Capture

Prefer wrapper:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts
```

Remote helper direct use only if needed:

```powershell
scp .\scripts\Capture-SerialPort.ps1 debug@dbgsh05.ccr.corp.intel.com:C:/Users/debug/Desktop/flow_logs/Capture-SerialPort.ps1
scp .\scripts\Invoke-RemoteBootCapture.ps1 debug@dbgsh05.ccr.corp.intel.com:C:/Users/debug/Desktop/flow_logs/Invoke-RemoteBootCapture.ps1
```

## 12. MLC Serial Run

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
scp .\scripts\Invoke-RemoteMlcSerial.ps1 debug@dbgsh05.ccr.corp.intel.com:C:/Users/debug/Desktop/flow_logs/Invoke-RemoteMlcSerial.ps1
```

Then execute remote script with `powershell -ExecutionPolicy Bypass -File` or use `Invoke-BhsUplr2ValidatedFlow.ps1 -RunMlc`.

Validated MLC path:

```text
/root/mlc_v3.11b
```

## 13. Report Paths

Consult report:

```text
out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_consult_report.md
```

Reproduction report:

```text
out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_<topic>_repro_report.md
```

Attachments:

```text
out\<ARTICLE_ID>\attachments\
```

## 14. Completion Notification

Create Outlook draft:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To 'Li, Renlong' -Subject 'HSD <ARTICLE_ID> analysis completed' -Body '<SUMMARY_AND_REPORT_PATH>' -Attachments 'out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_consult_report.md'
```

Send automatically only if explicitly requested:

```powershell
Set-Location -LiteralPath 'C:\Users\rli\copilot-hardware-flow-kit'
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To 'Li, Renlong' -Subject 'HSD <ARTICLE_ID> analysis completed' -Body '<SUMMARY_AND_REPORT_PATH>' -Attachments 'out\<ARTICLE_ID>\hsd_<ARTICLE_ID>_consult_report.md' -Send
```

Recommended subject:

```text
[Copilot][HSD] <ARTICLE_ID> <task-type> completed - <short status>
```

Recommended body:

```text
HSD/IPS ID: <id>
标题: <title>
Owner: <owner>
任务类型: <consult/extract/debug>

客户机器环境
- <platform/model, topology, BKC/BIOS, OS, tool/version, and key configuration; mark unavailable fields as “未获取”>

客户问题
- <symptom, impact, and customer request>

诊断结果
- <reproduction/validation state, final conclusion, key evidence, and hardware actions>

重点关注
- <risks, limitations, unverified assumptions, or environment differences>

下一步研究方向
- <concrete validation, configuration comparison, data collection, or follow-up; state why if no action is needed>

完整报告
- Markdown 报告已作为附件：<report path>
```

## 15. UI Copilot Permissions

Subprocess command should use startup flag, not stdin slash command:

```json
"command": ["copilot", "--allow-all"]
```

Do not rely on sending `/allow-all` through stdin; it may be interpreted as prompt text.
