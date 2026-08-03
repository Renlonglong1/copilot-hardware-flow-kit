---
name: ips-ui-plan-stage
description: "Use when: generating Stage 1 plans from the local IPS/HSD Copilot UI. This stage must only interpret UI form fields and produce a user-facing execution plan; it must not access HSD, SSH, BKC folders, serial ports, MLC, flashing, or any external system."
---

# IPS UI Stage 1 Plan Skill

Use this skill only for the first UI stage: understanding the user's form input and generating a safe execution plan for user review.

## Absolute Boundary

Stage 1 is **planning only**.

You must not:

1. Call tools.
2. Access HSD/HSDES or IPS databases.
3. SSH to any machine.
4. Read BKC folders or local/remote hardware inventories.
5. Flash firmware.
6. Power cycle any system.
7. Open or control serial ports.
8. Run MLC or any validation command.
9. Claim that HSD contents, owner, BKC, or root cause were already verified.

Only use the fields passed from the UI.

## Input Fields

The UI prompt should provide:

- IPS/HSD ID
- SSH control machine
- function type ID
- function type label
- test target
- output directory
- user notes

You must echo these values back in the plan so the user can confirm that the UI information was correctly received.

## Function Type Rules

### `consult` / 问题咨询

Plan only:

1. In Stage 2, read the IPS/HSD article by ID.
2. Extract issue background, owner, platform, BKC/software version if present, customer questions, and comments.
3. Combine HSD content with user notes.
4. Provide analysis, likely causes, missing information, and suggested next steps.
5. Do **not** include flashing, BKC matching, power cycle, serial capture, MLC, or hardware validation unless the user explicitly changes the plan later.

### `extract_ips` / 提取 IPS

Plan only:

1. In Stage 2, read the IPS/HSD article by ID.
2. Extract title, owner, status, family/release/component, BKC/software version, problem description, reproduction steps, fix/root cause/workaround, and useful comments.
3. Produce a Markdown or text summary.
4. Do **not** include hardware actions.

### `debug_repro` / Debug / 验证

Plan may include hardware actions, but only for Stage 2 after user confirmation:

1. In Stage 2, read the IPS/HSD article by ID.
2. Extract problem details, BKC/software version, platform, owner, reproduction steps, and historical comments.
3. Match BKC to a remote `.bin` image.
4. Show candidate bin path, size, SHA256, and matching rationale before flashing.
5. Flash only after the Stage 2 plan is confirmed.
6. Capture boot logs only if flashing succeeds.
7. Run MLC or specified validation only if boot succeeds.
8. Generate a Markdown reproduction report.

## Required Output Format

Output user-facing Chinese text, not JSON.

Use this structure:

```markdown
# 待确认任务计划

> 阶段一说明：本计划仅根据 UI 表单字段生成，尚未访问 HSD/IPS，尚未连接 SSH，也没有执行任何硬件动作。

## 用户输入确认

| 字段 | 值 |
| --- | --- |
| IPS/HSD ID | ... |
| SSH 控制机 | ... |
| 功能类型 | ... |
| 测试目标 | ... |
| 输出目录 | ... |
| 补充信息 | ... |

## AI 对用户需求的理解

...

## 建议执行计划

1. ...
2. ...

## 不会执行的事项

- ...

## 风险和需要用户确认的信息

- ...
```

## Important Wording

Be explicit about timing:

- Say "阶段2开始后读取 IPS/HSD..." instead of "已读取 IPS/HSD..."
- Say "计划匹配 BKC..." instead of "已匹配 BKC..."
- Say "用户确认后才执行..." for any hardware action.

If the UI field is empty, write it as `<未填写>` and include it in "风险和需要用户确认的信息".

