# 系统交接交付记录

交付日期：2026-09-21

## 交接文档

- Markdown：`docs\SYSTEM_HANDOVER.zh-CN.md`
- Word 最新本地版：`docs\SYSTEM_HANDOVER.zh-CN.v1.1.docx`

v1.1 新增第 6.4、6.5 节：新电脑功能依赖边界与 SSH 首次配置、授权和验收。
原 Word 当时处于占用状态，因此本地新版另存；原文件未被强行关闭或覆盖。
GitHub 上的标准文件名 `docs\SYSTEM_HANDOVER.zh-CN.docx` 已更新为 v1.1。

正文覆盖系统架构、功能边界、部署、账号权限、任务操作、数据备份恢复、
维护发布、风险待办、资产登记与接收签字。责任人、实际资产与验收签字仍需
交接双方填写；文档编制不代表已执行真实硬件验收。

## GitHub 交付

- 仓库：<https://github.com/Renlonglong1/copilot-hardware-flow-kit>
- 可见性：Private
- 分支：`handover/2026-09-21-portable`
- 首次交付提交：`95799d2cabe4d743b67fbc32bd49ba4818fba52c`
- v1.1 文档更新提交：`7d79b78390873107424d8b761c91bb0d5ec9f708`
- 分支地址：<https://github.com/Renlonglong1/copilot-hardware-flow-kit/tree/handover/2026-09-21-portable>
- 发布文件数：467

本次发布的是独立、无旧历史的脱敏可移交版本，包含全部核心顶层脚本、
六个核心流程技能、可移植通用工具、模板与两份交接文档。
具体范围见该分支的 `docs\DELIVERY_SCOPE.md`。

内部参考资料、实际实验室清单/配置、BKC 数据、客户资料、运行数据库/日志、
凭据及依赖内部资料的扩展技能不在新分支中，需通过公司批准渠道单独交接。
新机器按发布分支 README 配置本地机器清单和硬件参数后才能使用真实硬件。

原本地工作区、原 main 和既有历史未被覆盖或删除。旧历史中已有内部资料
不会因新建脱敏分支而消失；如需清理，由仓库管理员另行审批处理。
