# PCIe Header Log Decoder

一个无需安装、可离线运行的浏览器工具，用于解析 PCIe TLP Header Log 中的 DWORD（DW）字段。输入原始 Header DWORD 后，工具会按所选模式解码 TLP 类型、长度、Requester/Completer ID、地址、Tag、Byte Enable、Completion Status，以及部分 Message、Prefix、OHC 和 IDE 相关字段。

## 功能

- 支持 **Non-Flit** 和 **Flit** 两种 TLP 模式。
- 支持每个 DWORD 使用十六进制或十进制输入。
- 支持按 DWORD 进行字节交换，适用于日志中的字节序与 PCIe Header 定义不一致的场景。
- 自动识别并解析常见 TLP：
  - Memory / I/O Read 与 Write
  - Configuration Read 与 Write（Type 0 / Type 1）
  - Completion（含 Completion Status、Byte Count、Lower Address）
  - Message（含 LTR、OBFF、IDE、Vendor Defined Message 等）
  - Flit Mode Local TLP Prefix 与部分 OHC 内容
  - Non-Flit IDE TLP Prefix
- 以表格形式展示字段名称和解码后的值，同时显示处理后的原始 TLP Header DWORD。

## 使用方法

1. 在浏览器中直接打开 [pcie_header_log_decoder.html](pcie_header_log_decoder.html)。不需要 Web 服务器、安装依赖或网络连接。
2. 选择 **Mode**：
   - **Non-Flit**：解析传统 Non-Flit Mode TLP Header；可输入 `HDR1` 至 `HDR5`。
   - **Flit**：解析 Flit Mode TLP Header；可输入 `HDR1` 至 `HDR9`。
3. 根据日志的 DWORD 字节序选择 **DWORD Byte Order**：
   - **As entered**：按输入值原样解析，默认选项。
   - **Byte swap**：对每个 32-bit DWORD 单独交换字节顺序后再解析。
4. 将 Header Log 的 DWORD 填入相应的 `HDR` 输入框。
5. 点击 **Decode**，或在任一输入框中按 Enter。
6. 在右侧查看摘要、完整字段表和最终用于解析的 TLP Header DWORD。

点击 **Load Sample** 可恢复内置的 Non-Flit 示例并立即解码。

## 输入格式与限制

每个 HDR 输入框对应一个无符号 32-bit DWORD。支持以下格式：

```text
0x70000001
0X3800107F
939524097
```

输入值必须介于 `0x00000000` 和 `0xFFFFFFFF`（即 0 至 4294967295）之间。

- `HDR1` 至 `HDR4` 始终必填。
- Non-Flit 模式下，最多使用 `HDR1` 至 `HDR5`；`HDR5` 可用于识别 IDE TLP Prefix。
- Flit 模式下，可使用 `HDR1` 至 `HDR9`，以覆盖扩展 Header Content（OHC）或厂商定义内容。
- 切换到 Non-Flit 模式时，`HDR6` 至 `HDR9` 会被禁用；如需输入这些 DWORD，请选择 Flit 模式。

## 示例

页面内置的示例值如下：

```text
HDR1: 0x70000001
HDR2: 0x3800107F
HDR3: 0x00001AB4
HDR4: 0x010000CC
```

使用默认的 **Non-Flit** 和 **As entered** 设置后，点击 **Decode** 即可查看 Message With Data TLP 的路由、Requester ID、Tag、Message Code、Vendor ID 和 Vendor Message 等字段。

## 结果说明

解码结果顶部会显示三个摘要字段：

- **Mode**：当前使用的解码模式。
- **TLP Type**：TLP Type 编码及对应的名称。
- **Length**：TLP Length；对于无数据 Message TLP，显示为 `0`。

下方表格按 TLP 类型显示适用字段。例如：

- 请求 TLP：Requester ID、Tag、地址、First/Last DWORD Byte Enable、AT、PH。
- Configuration TLP：Target ID、Register、Byte Enable。
- Completion TLP：Completer ID、Requester ID、Byte Count、Lower Address、Completion Status。
- Message TLP：Routing、Message Code，以及 LTR、OBFF、IDE 或 Vendor Defined Message 的相关内容。

BDF 字段会同时提供十六进制和十进制格式，例如 `0x12:0x03.0x1 | 18:3.1`。

## 常见问题

### 出现 `HDR1-HDR4 are required`

前四个 Header DWORD 中至少有一个为空。请补全 `HDR1`、`HDR2`、`HDR3` 和 `HDR4`。

### 出现 `HDRn must be a 32-bit value`

该输入不是有效的 32-bit 无符号整数。请检查是否使用了合法的十进制数，或以 `0x` / `0X` 开头的十六进制数，并确保数值没有超出 `0xFFFFFFFF`。

### 解码出的 TLP Type 无效或字段不符合预期

请依次检查：

1. 是否选对了 Non-Flit 或 Flit 模式。
2. 日志中的 DWORD 是否需要选择 **Byte swap**。
3. DWORD 的顺序是否与 `HDR1` 至 `HDRn` 的顺序一致。
4. 日志是否包含足够的 Header / OHC DWORD。

## 文件

- [pcie_header_log_decoder.html](pcie_header_log_decoder.html)：工具页面与解码逻辑。
- [README.md](README.md)：本使用说明。
