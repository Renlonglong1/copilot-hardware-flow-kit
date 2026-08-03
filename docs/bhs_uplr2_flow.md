# BHS uPLR2 Emulator + PowerSplitter 流程

## 目标服务器

```text
debug@10.239.84.53
```

主机名：

```text
DBGSH05
```

## GUI 流程

1. 在 PowerSplitter 中把电源开关全部 `off`
2. 在 `smucmd.exe` / EM100 GUI 中先 `stop`
3. `OpenFile` 选择 BHS uPLR2 `.bin`
4. 点击 `Batch`
5. 点击 `Run`
6. 在 PowerSplitter 中把电源开关全部 `on`

## CLI 等价流程

PowerSplitter 关电：

```bat
PowerSplitterCL.exe poweroff
```

Emulator stop/download/verify/start：

```bat
smucmd.exe --stop --set MX66U1G45G -d "C:\Users\debug\Desktop\BKC\uPLR2\BHSDCRB1.IPC.3545.P03.2511062122_GB01000405_GA10000680_SC03000393_RB0A000133_SP_IP_Clean_Debug_PRQ_DAM_Enabled_1.bin" -v --start
```

PowerSplitter 开电：

```bat
PowerSplitterCL.exe poweron
```

## 已确认参数

| 项 | 值 |
|---|---|
| 服务器 | `debug@10.239.84.53` |
| 芯片型号 | `MX66U1G45G` |
| bin 文件 | `C:\Users\debug\Desktop\BKC\uPLR2\BHSDCRB1.IPC.3545.P03.2511062122_GB01000405_GA10000680_SC03000393_RB0A000133_SP_IP_Clean_Debug_PRQ_DAM_Enabled_1.bin` |
| bin 大小 | `67108864` bytes |
| smucmd 入口 | `C:\Users\debug\Desktop\smucmd.exe - Shortcut.lnk` |
| smucmd 实际程序 | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe` |
| PowerSplitterCL | `C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe` |

## 本地封装脚本

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2Flow.ps1
```

## 当前验证结果

时间：2026-06-17

执行结果：

1. `PowerSplitterCL.exe poweroff` 返回 `ExitCode=0`
2. `smucmd.exe --stop --set MX66U1G45G -d <bin> -v --start` 输出 `No device is connected!`
3. `PowerSplitterCL.exe poweron` 返回 `ExitCode=0`

结论：PowerSplitter 上下电命令可执行，但 EM100 / DediProg 设备当前未被 `smucmd.exe` 识别。`smucmd.exe` 遇到 `No device is connected!` 仍可能返回 `ExitCode=0`，因此脚本必须检查输出文本，不能只看退出码。

## 复测前检查

1. 确认 EM100 / DediProg 设备 USB 已连接到 `DBGSH05`
2. 确认 Windows 设备管理器能识别 DediProg 设备
3. 先运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-Emulator.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -Action help
```

再运行完整流程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2Flow.ps1
```

