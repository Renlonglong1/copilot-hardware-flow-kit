# IPS / HSD 硬件复现 Skill 使用说明

这个 skill 用于把一次 IPS/HSD 问题处理成完整闭环：

```text
HSD/IPS ID
-> 提取问题、owner、BKC、复现步骤
-> 匹配远端 BKC .bin
-> SSH 到控制机
-> 烧录 BKC
-> 抓启动日志
-> 跑 MLC 或指定测试
-> 输出 Markdown 复现报告
```

Skill 文件：

```text
.github\skills\ips-hsd-repro-flow\SKILL.md
```

## 下一次如何告诉 Copilot

推荐直接给出下面这种 prompt：

```text
请使用 ips-hsd-repro-flow skill，帮我分析并验证 IPS/HSD <文章ID>。

目标：
1. 从 HSD database 提取这个 IPS 的关键信息：问题描述、owner、BKC/软件版本、平台配置、客户复现步骤、fix/root cause/workaround。
2. 根据提取到的 BKC，在远端 BKC 文件夹中匹配合适的 .bin 镜像。
3. SSH 到对应控制机，执行烧录、启动日志抓取和 MLC/指定测试。
4. 判断是否复现，并输出问题解决程度和初步原因推测。
5. 保存 Markdown 报告到 copilot-hardware-flow-kit\out。

IPS/HSD ID：<文章ID>
测试类型：<例如 跨NUMA MLC bandwidth_matrix / boot only / MLC latency_matrix / 指定命令>
平台/机器：<如果知道就写，例如 BHS 2S / GNR-SP / dbgsh05；不知道可让 Copilot 自动从 HSD 和配置中判断>
特殊要求：<例如 必须使用 MLC v3.11b；需要对比 Directory Mode；抓日志 10 分钟>
```

## 针对本次类似问题的 sample

```text
请使用 ips-hsd-repro-flow skill，帮我分析并验证 IPS/HSD 14025984558。

这是一个跨 NUMA 性能问题。请从 HSD 提取 owner、BKC、问题描述、客户原始 MLC 结果和评论里的 root cause 线索。
然后根据 HSD 中的 BKC，在远端 BKC 目录匹配合适的 .bin，SSH 到对应控制机进行烧录，抓 COM3/COM4 启动日志，并使用 /root/mlc_v3.11b 运行：

./mlc --bandwidth_matrix
./mlc --latency_matrix
./mlc --loaded_latency

最后请保存 Markdown 报告到 copilot-hardware-flow-kit\out，报告里要包含：
1. 是否复现
2. MLC 实测结果
3. 与客户原始结果的差异
4. 问题解决程度
5. 初步原因推测
```

## 更短的 sample

```text
请用 ips-hsd-repro-flow skill 处理 HSD 14025984558：提取问题和 BKC，匹配远端 bin，烧录复现，跑 MLC，最后生成复现报告。
```

## 如果只想先分析、不烧录

```text
请用 ips-hsd-repro-flow skill 先分析 HSD <文章ID>，只提取问题、owner、BKC、复现步骤和初步原因；先不要烧录，先输出分析报告。
```

## 如果要指定机器和 bin

```text
请用 ips-hsd-repro-flow skill 处理 HSD <文章ID>。
控制机固定使用 debug@dbgsh05.ccr.corp.intel.com。
bin 固定使用 C:\Users\debug\Desktop\BKC\<folder>\<image>.bin。
请烧录后抓 10 分钟 COM3/COM4，并运行 MLC bandwidth_matrix，输出 Markdown 报告。
```

