# Emulator CLI 与 PowerSplitterCL 操作备忘

本文档记录服务器 `debug@10.239.84.44` 上已学习到的两个工具命令，方便后续直接按文档操作。

## 1. DediProg Emulator CLI

### 位置

桌面快捷方式，以这个为准：

```bat
C:\Users\debug\Desktop\smucmd.exe - Shortcut.lnk
```

快捷方式实际指向：

```bat
C:\Program Files (x86)\DediProg\Emulator\smucmd.exe
```

核心 CLI 程序：

```bat
C:\Program Files (x86)\DediProg\Emulator\smucmd.exe
```

使用说明手册：

```bat
C:\Program Files (x86)\DediProg\EM100\help.pdf
```

注意：不要把 `Emulator--CLI.lnk` 当主入口；它指向 `Smucmd.bat`，会打开常驻命令窗口。自动化/SSH 场景必须直接调用 `smucmd.exe`，也就是 `smucmd.exe - Shortcut.lnk` 的目标。

### 帮助命令

```bat
cd /d "C:\Program Files (x86)\DediProg\Emulator"
smucmd.exe -h
smucmd.exe --help
```

### GUI 流程与 CLI 对应关系

GUI 操作流程：

1. 点击 `Stop`
2. 点击 `OpenFile` 选择 `.bin` 文件
3. 点击 `Batch`
4. 点击 `Run`

CLI 对应方式：

```bat
cd /d "C:\Program Files (x86)\DediProg\Emulator"
smucmd.exe --stop --set <chip型号> -d "C:\path\file.bin" -v --start
```

EM100 手册中的命令行组合示例说明：用户可以把一系列命令写在一起，例如：

```bat
smucmd --stop --set MX25L3205 -d c:\file.bin -v --start
```

含义是：先停止 emulation，使 PC 可以下载到 EM100Pro 或从 EM100Pro 上传到 PC；然后选择 `MX25L3205` 芯片，把 `c:\file.bin` 下载到 EM100Pro 并 verify；最后启动 emulation mode。

### 常用命令

```bat
cd /d "C:\Program Files (x86)\DediProg\Emulator"

smucmd.exe -h
smucmd.exe --stop
smucmd.exe --set M25P80
smucmd.exe --set M25P80 -d "C:\path\file.bin" -v
smucmd.exe --set M25P80 -r "C:\path\dump.bin"
smucmd.exe --set M25P80 -b
smucmd.exe --set M25P80 -s
smucmd.exe -f "C:\path\file.bin"
smucmd.exe --stop --set M25P80 -d "C:\path\file.bin" -v --start
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `--set <chip>` | 设置芯片型号 |
| `--stop` | 停止 emulation mode |
| `--start` | 启动 emulation mode |
| `-c`, `--check` | 检查 emulator 状态和固件 |
| `-b`, `--blank` | 空白检查，需配合 `--set` |
| `-r <file>` | 读取 emulator 内容到文件，需配合 `--set` |
| `-d <file>` | 下载 bin/hex/s19 文件到 emulator，需配合 `--set` |
| `-s`, `--sum` | 显示已下载内容 checksum，需配合 `--set` |
| `-f <file>`, `--fsum <file>` | 显示文件 checksum |
| `-v`, `--verify` | 下载后校验，只配合 `-d` |
| `-a <addr>` | 起始地址，只配合 `-d` / `-r` |
| `-l <length>` | 读/写长度，只配合 `-d` / `-r` |
| `-x <byte>` | 下载时用指定字节填充剩余区域，只配合 `-d` |
| `-t`, `--truncate` | 文件大于芯片容量时截断，只配合 `-d` |
| `--device <n>` | 指定 USB 序号设备 |
| `--device-SN <SN>` | 指定设备序列号 |
| `--hold <1|2|3>` | `--start` 时设置 HOLD pin 状态 |
| `--reset <ms>` | `--start` 时复位目标系统 |
| `--enter-4byte-mode <1|2>` | 4-byte address mode 开关 |

### 芯片型号配置

芯片型号来自配置目录：

```bat
C:\Program Files (x86)\DediProg\Emulator\config\EM100Pro-G2
```

已观察到约 702 个 `.cfg` 芯片配置，例如：`M25P80`、`W25*`、`MX25*`、`GD25*`、`EN25*`、`AT25*` 等。

## 2. PowerSplitterCL

### 位置

```bat
C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe
```

工作目录：

```bat
C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript
```

### 帮助命令

```bat
PowerSplitterCL.exe /?
PowerSplitterCL.exe -help
PowerSplitterCL.exe help
PowerSplitterCL.exe --help
PowerSplitterCL.exe -h
```

帮助输出：

```text
Example commands:
1.poweron
2.poweroff
3.powercycle 10
4.portpower 1 true
```

### 常用命令

```bat
cd /d "C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript"

PowerSplitterCL.exe poweron
PowerSplitterCL.exe poweroff
PowerSplitterCL.exe powercycle 10
PowerSplitterCL.exe portpower 1 true
PowerSplitterCL.exe portpower 1 false
```

### 已验证操作

| 时间 | 服务器 | 命令 | 结果 |
|---|---|---|---|
| 2026-06-16 | `debug@10.239.84.44` | `PowerSplitterCL.exe poweroff` | `ExitCode=0` |

### 配置文件

```bat
C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\psconfig.xml
```

已观察到：

| 配置项 | 值 |
|---|---|
| `NumberOfConnectedDevices` | `1` |
| `PortControlEnable` | `true` |
| 端口名称 | `Port-1` 到 `Port-5`，以及 `P.Cycle` |
| `PsCycleLoops` | `1` |
| `PsCycleDelayPwrOff` | `20` |
| `PsCycleDelayPwrON` | `50` |

## 3. 联合操作参考

关电：

```bat
cd /d "C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript"
PowerSplitterCL.exe poweroff
```

下载 bin 到 Emulator 并启动 emulation：

```bat
cd /d "C:\Program Files (x86)\DediProg\Emulator"
smucmd.exe --stop --set <chip型号> -d "C:\path\file.bin" -v --start
```

开电：

```bat
cd /d "C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript"
PowerSplitterCL.exe poweron
```
