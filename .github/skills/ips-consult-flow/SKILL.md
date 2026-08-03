---
name: ips-consult-flow
description: "Use when: the user wants IPS/HSD problem consultation or analysis only. This skill reads an IPS/HSD article, extracts key information, explains likely causes and next steps, and writes a Markdown consultation report. It must not perform hardware actions such as SSH, BKC matching for flashing, power cycle, serial control, firmware flashing, or MLC execution."
---

# IPS / HSD Problem Consultation Skill

Use this skill for `consult` / 问题咨询 tasks.

## Scope

This skill is for analysis-only consultation.

Allowed:

1. Fetch/read the specified IPS/HSD article.
2. Extract key fields and comments.
3. If requested, search for similar IPS/HSD issues and extract reusable experience.
4. If requested, download and analyze customer attachments.
5. Summarize the issue and customer questions.
6. Analyze likely causes and configuration factors.
7. Suggest next steps, required information, or possible debug directions.
8. Save the Markdown report and all task artifacts under `out\<articleId>\`.
9. If requested, notify the configured recipient after the report is ready.

Forbidden:

1. Do not SSH to any machine.
2. Do not enumerate remote BKC folders.
3. Do not select a `.bin` for flashing unless only mentioning that a future debug task would need it.
4. Do not flash firmware.
5. Do not power cycle.
6. Do not open or control serial ports.
7. Do not run MLC or other validation commands.
8. Do not make hardware changes.

If the user asks for hardware validation, switch to `ips-hsd-repro-flow` instead.

## Required Reading

Before fetching HSD data, read:

```text
docs\hsd_python_api_notes.md
```

Use the validated helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <articleId>
```

If Python access fails with a generic 403 or HTML Access Denied response, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <articleId> -ForceCurlDirect
```

Never ask for or store passwords, cookies, SSO tokens, service tokens, or Kerberos ticket contents.

## Extract at Minimum

- HSD/IPS ID
- title
- tenant / subject
- status
- owner / co-owner / support owner / owner org
- priority
- family / release / component
- suspected problem area
- BKC/software version, if available
- problem description
- customer questions
- reproduction notes, if included
- comments and customer blog history
- fix description / root cause / workaround, if available

## Analysis Contract

The report should answer:

1. What is the issue?
2. Who owns it?
3. Which platform/configuration is involved?
4. Which BKC/software version is mentioned, if any?
5. What is the customer's question or concern?
6. What are the most likely causes or configuration factors?
7. Is the issue solved, unresolved, or still unclear?
8. What should the developer/support engineer do next?
9. What information is missing?

For performance issues, distinguish:

- expected architectural behavior
- BIOS/configuration tuning
- tool/version mismatch
- workload mismatch
- actual defect needing reproduction

## Similar IPS Search, If Requested

When the final plan asks to search similar IPS/HSD issues:

1. First read the target IPS/HSD article.
2. Build search terms from title, family, release, component, suspected problem area, tag, error signature, BKC/software version, and important keywords from description/comments.
3. Search HSD/HSDES with focused queries.
4. Prefer issues with the same family/component/problem area.
5. Extract only reusable experience:
   - root cause
   - workaround
   - fix description
   - owner comments
   - configuration knobs
   - known limitations
6. Report similar issue IDs and why they are relevant.
7. If results are noisy or access-limited, say so clearly.

## Customer Attachment Download, If Requested

When the final plan asks to download/analyze customer attachments:

1. Inspect HSD fields such as:
   - `server_platf_ae.bug.download_attached_ips_files`
   - `server_platf_ae.bug.ext_attach_url`
   - attachment/file related fields discovered in `field_matches`.
2. Prefer authenticated download through existing Windows/Kerberos context. Do not ask for passwords, cookies, SSO tokens, or Kerberos ticket contents.
3. Save attachments under:

```text
out\<articleId>\attachments\
```

4. If the download produces a compressed package, extract it under the same directory.
5. Prioritize files whose names include:
   - `Overview`
   - `README`
   - `summary`
   - `config`
   - `BIOS`
   - `MLC`
   - `log`
   - `result`
6. Summarize relevant attachment contents in the report.
7. If download is blocked or the URL is only a browser UI link, record the field/link and the failure reason clearly.

## Completion Notification, If Requested

When the final plan asks to send a completion notification:

1. Finish the HSD consultation report first.
2. Default recipient is the HSD/IPS owner extracted from the article owner field.
3. If the final plan explicitly says to use an override/test recipient, use that recipient instead. During testing, the common override recipient is:

```text
Li, Renlong
```

4. Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To '<owner-or-override-recipient>' -Subject '<subject>' -Body '<body>' -Attachments '<report-path>'
```

By default this displays an Outlook draft. Add `-Send` only when the final plan explicitly says automatic email sending is enabled.

4. Notification body must be a concise, standalone working summary, not merely a report path. Use these sections:
   - `客户机器环境`: platform/model, socket/NUMA or DIMM topology, BKC/BIOS, OS, tool/version, and relevant configuration. Mark unavailable fields as `未获取`; do not infer them.
   - `客户问题`: reported symptom, impact, and customer question.
   - `诊断结果`: analysis conclusion, resolution state, supporting evidence, and explicitly state that no hardware action was performed.
   - `重点关注`: risks, limitations, unverified hypotheses, environmental differences, or decisions requiring follow-up.
   - `下一步研究方向`: concrete validation, data-collection, or owner follow-up actions. State why when no follow-up is needed.
   - `完整报告`: say the Markdown report is attached and include its path.

Subject format:

```text
[Copilot][HSD] <articleId> <task-type> completed - <short status>
```

Body format:

```text
HSD/IPS ID: <id>
标题: <title>
Owner: <owner>
任务类型: <consult/extract>

客户机器环境
- <platform/model, topology, BKC/BIOS, OS, tool/version, key configuration; use “未获取” where unknown>

客户问题
- <symptom, impact, and customer request>

诊断结果
- <conclusion, resolution state, key evidence; hardware actions: none>

重点关注
- <risks, limitations, unverified assumptions, or environment differences>

下一步研究方向
- <concrete next validation or information to collect; or why no action is needed>

完整报告
- Markdown 报告已作为附件：<report path>
```

## Output Report

Save under the current article's task directory:

```text
out\<articleId>\hsd_<articleId>_consult_report.md
```

Required sections:

```markdown
# HSD <articleId> 问题咨询分析

## 1. 基本信息
## 2. 问题摘要
## 3. 客户疑问
## 4. HSD 评论/历史中的关键线索
## 5. 初步原因判断
## 6. 相似 IPS 经验参考（如启用）
## 7. 客户附件分析（如启用）
## 8. 解决程度
## 9. 建议下一步
## 10. 需要补充的信息
## 11. 完成通知（如启用）
## 12. 本次执行范围
```

In "本次执行范围", explicitly state that no hardware action was performed.

## Known Example

HSD `14025984558` / `跨NUMA性能测试问题`:

- Mode: consult only.
- Key conclusion: likely BIOS `Directory Mode Override` / RSF behavior and performance tuning issue.
- `Memory Directory` or `Directory Backed USF` can improve remote NUMA/UPI bandwidth compared with `Inclusive RSF`.
- HSD was complete; customer eventually said `暂时没有问题了`.
- Report path used previously:

```text
out\14025984558\hsd_14025984558_consult_report.md
```
