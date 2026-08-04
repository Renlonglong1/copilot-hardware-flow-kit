# Leaky Bucket Calculator

面向 BIOS/RAS 调试场景的静态网页计算工具，用于完成 DDR 和 PCIe 的 leaky bucket（漏桶）相关计算。工具无需安装软件、无需后端服务，也不会上传输入的寄存器值。

## 功能

- **DDR Drip Time**：根据 DDR 平台、速率、`2ND_CNTR_LIMIT` 和漏桶配置计算滴漏时间。
- **PCIe From Registers**：将 `EXP_BER` 寄存器字段和错误阈值转换为漏桶时间、最小可触发错误率和 BER。
- **PCIe Target BER**：根据目标 BER、错误突发过滤时间和阈值，反算可写入的 PCIe 寄存器值。
- **Reference**：查看 DDR 与 PCIe 所需寄存器字段、平台规则和公式摘要。
- **Copy result**：复制当前计算结果，便于粘贴到调试记录、邮件或问题单中。

支持的 DDR 平台包括 `DDR4 Memory`、`SPR-DDR5`、`HBM2e` 和 `GNR-DDR`；支持 PCIe Gen1 至 Gen5。

## 使用方法

1. 在文件管理器中双击打开 `index.html`。
2. 在左侧选择计算模式。
3. 按页面提示选择平台或 PCIe Generation，并输入十六进制寄存器字段或十进制参数。
4. 单击 **Calculate** 查看结果、已解码字段和公式追踪。
5. 需要记录结果时，单击 **Copy result**。

也可以将本目录解压后直接发给其他用户；请保持外层的 `index.html`、`README.md` 以及 `assets` 子目录的完整目录结构不变。

## DDR Drip Time

输入项：

- DDR 平台与支持的速率。
- 从 `LEAKY_BKT_2ND_CNTR_REG` 读取的 `2ND_CNTR_LIMIT`。
- 漏桶配置：
  - 对 `GNR-DDR`，可输入原始 `LEAKY_BUCKET_CFG`，工具自动按 `bits[11:6]` 和 `bits[5:0]` 解码为 `CFG_HI`、`CFG_LO`。
  - 对其他 DDR 平台，请直接输入解码后的 `CFG_HI` 和 `CFG_LO`。

输出项包括滴漏时间、有效时钟、解码后的配置字段，以及带入实际参数的公式。

注意：`2ND_CNTR_LIMIT = 0` 时，计算使用的乘数为 `4`。原始 `LEAKY_BUCKET_CFG` 自动解码仅适用于 GNR-DDR。

## PCIe From Registers

输入项：

- PCIe Generation。
- `EXP_BER[31:0]`，对应 `LEKBER0.EXP_BER[31:0]`。
- `EXP_BER[49:32]`，对应 `LEKBER1.EXP_BER[17:0]`。
- 错误阈值。

工具输出 `EXP_BER` 十进制值、漏桶时间、最小可触发错误率和 BER。寄存器字段可输入带或不带 `0x` 前缀的十六进制数。

## PCIe Target BER

输入目标 BER、期望的 burst filter interval（ns）、错误阈值和 PCIe Generation。工具会给出：

- `EXP_BER[31:0]` 与 `EXP_BER[49:32]` 的十六进制值。
- 对应平台使用的 `AGGRERR` / `G3AGGRERR` 值。
- 对应平台使用的 `ERRTHRESH` / `G3ERRTHRESH` 值。

若 `EXP_BER[49:32]` 超出 18-bit 字段范围 `0x3FFFF`，工具会显示输入不可编码的提示。

## 运行环境与说明

- 本工具是纯 HTML、CSS 和 JavaScript，不需要 Python、Node.js、npm 或 Web 服务。
- 可直接从本地文件系统打开 `index.html` 使用。
- 页面会尝试从 Google Fonts 加载 Roboto 和 Material Symbols；网络不可用时，计算功能不受影响，但字体或主题图标可能显示为浏览器回退样式。
- 工具不会保存计算历史；关闭或刷新页面后，需重新输入参数。

## 文件说明

- `index.html`：网页入口。
- `README.md`：使用说明。
- `assets/styles.css`：界面样式。
- `assets/app.js`：计算、校验、界面交互和复制功能。
