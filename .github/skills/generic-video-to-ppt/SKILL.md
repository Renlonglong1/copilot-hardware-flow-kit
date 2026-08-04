---
name: generic-video-to-ppt
description: "视频内容解析与PPT生成技能。Use when: 解析会议录屏/培训视频内容, 提取视频关键帧, 音频转文字, 提取重点/Q&A, 用视频截图生成PPT。Triggers: video to ppt, 视频转PPT, 解析视频, 会议录屏, training recording, extract frames, 视频重点, 视频问答."
argument-hint: "<video_path>  [--template <pptx_template>] [--interval <seconds>] [--output <output.pptx>]"
---

# Video-to-PPT (视频解析 & PPT 生成)

从会议录屏或培训视频中自动提取关键帧、转录音频、总结重点和 Q&A，
并基于 PPT 模板生成清晰、可审阅、可追溯时间点的演示文稿。

## 使用前必问 (Pre-Use Q&A)

> **路径不写死在本技能里**。所有本机路径都从 `config.json` 读取（该文件已被 `.gitignore` 忽略，不会上传）。
> 首次使用请复制 `config.example.json` 为 `config.json` 并填写；若字段为空，**必须先向用户逐一询问**再继续。

在开始生成前，**必须先向用户确认以下输入**（缺失就问，不要猜、不要用示例路径）：

0. **输入 / 输出信息**（优先读 `config.json`，缺失则询问）：
   - **视频文件路径？**（`video_path`，例如拖入或粘贴 `.mp4` 完整路径）
   - **视频名称 / 主题？**（`video_name`，用于标题与输出文件命名）
   - **模板文件路径？**（`template_path`，`.pptx` 模板；无则用默认布局）
   - **生成文件放在哪？**（`output_dir` 输出目录 + `output_name` 输出文件名）

1. **这个视频属于哪个产品/项目？**（例如 NVL / GNR / DMR / CWF / MTL …）
   - HAS 检索通过 codesign 插件（`codesign-ask-specs-and-wikis`）完成，而 **codesign 不允许猜项目**，必须显式指定。
   - 用户只要附一句"这是 NVL 的"或"这是 GNR 的"，即可把链接挂到正确产品的 HAS 上。
   - 拿到项目后，先用 `codesign-get-spec-sources` 校验项目 ID 是否存在，再按视频主题检索真实 HAS 文档/章节，自动生成 `has_refs.json`（关键词 + label + 真实链接）。
2. **是否需要中英文对照？**（默认开启）
3. **是否需要人工润色的通顺中文总结？**（推荐：读转录后生成 `curated.json`，避免逐字机翻产生语义错误）

> 说明：抽帧/转录/排版/双语/超链接/问答分页为全自动；"通顺中文总结"与"HAS 真实链接"需按上面两步介入，效果才能与样例 deck 一致。

## Output Quality Requirements (强制输出质量)

- 字体必须清晰可读：正文优先 13-16pt，避免 11pt 以下小字
- 文字区必须高对比：深色文字 + 浅色文字底板（不要让黑字直接压在深色背景上）
- 每页不只是截图：必须包含“标题 + 时间点 + 结构化要点（bullet）”
- 必须生成总结页：按时间段汇总关键结论
- 必须保留时间点追踪：每页备注（Notes）记录该页对应的时间戳/时间段
- 必须记录完整 Q&A：不仅汇总，还要保留每条问题和答案（无法确认答案时要明确标注）
- 备注中要包含原始转录片段（带时间）用于人工复核
- 默认开启中英文对照：每条要点优先显示 EN + ZH 两行

## When to Use

- 解析培训视频/会议录屏的内容
- 从视频中提取关键画面截图
- 音频转文字（支持中英文）
- 自动提取视频中的重点和 Q&A
- 用视频截帧 + 文字摘要生成 PPT
- 基于现有 PPT 模板填充视频内容

## Dependencies

Python packages (install via `pip install`):

```
opencv-python>=4.8
moviepy>=1.0.3
openai-whisper>=20231117
python-pptx>=0.6.21
Pillow>=10.0
numpy>=1.24
```

可选（GPU 加速 Whisper）:
```
torch>=2.0
```

## Pipeline Overview

```
┌──────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────┐
│  Video   │────▶│ Frame Extract│────▶│  Transcribe │────▶│ Generate │
│  (.mp4)  │     │  (OpenCV)    │     │  (Whisper)  │     │   PPT    │
└──────────┘     └──────────────┘     └─────────────┘     └──────────┘
                        │                      │                  │
                        ▼                      ▼                  ▼
                  key_frames/           transcript.json      output.pptx
                  (PNG images)          + summary.json       (from template)
```

## Verified Quick Run (本机已跑通，下次直接用)

> 路径全部从 `config.json` 读取，不写死在脚本里。缺字段时先问用户。

```powershell
$py = "python"
$skillRoot = Join-Path $env:USERPROFILE ".copilot\skills\generic-video-to-ppt"
$cfg = Get-Content (Join-Path $skillRoot "config.json") -Raw | ConvertFrom-Json
$video = $cfg.video_path
$tpl   = $cfg.template_path
$name  = if ($cfg.video_name) { $cfg.video_name } else { [IO.Path]::GetFileNameWithoutExtension($video) }
$outDir = if ($cfg.output_dir) { $cfg.output_dir } else { Split-Path $video -Parent }
$outName = if ($cfg.output_name) { $cfg.output_name } else { "$name.pptx" }
$out  = Join-Path $outDir $outName
$work = Join-Path $outDir "_video_work__$name"
$env:PYTHONIOENCODING="utf-8"
& $py (Join-Path $skillRoot "scripts\video_to_ppt.py") `
  --video $video --template $tpl --output $out `
  --interval $cfg.interval --whisper-model $cfg.whisper_model --language $cfg.language --max-slides $cfg.max_slides `
  --work-dir $work --keep-intermediate
```

固定要点（避免重复踩坑）：

- **配置**：先 `Copy-Item config.example.json config.json` 并填写路径；`config.json` 不上传。
- **Python**：优先使用已安装依赖的解释器（系统 Python 或虚拟环境均可）。
- **模板**：建议将模板文件放在本地稳定目录，避免云同步中的临时锁文件影响读取。
- **抽帧**：用固定 `--interval 75`，**不要**加 `--scene-detect`（静态讲稿场景检测只出 2 帧）。
- **编码**：必须 `$env:PYTHONIOENCODING="utf-8"`；脚本里 stderr 的 FP16/CPU 警告会让 PowerShell 报 exit 1，是假错，产物正常。
- **codesign**：脚本路径在 `.copilot`（gitignored），grep 需 `includeIgnoredFiles=true`，或直接用 read_file 绝对路径。
- **精细版**：要更多内容页就把 `--interval` 降到 30~45。

## One-Click Run

### 完整流程：视频 → PPT

> 下面的 `<...>` 均为占位符：请用用户提供的值（或 `config.json` 中的字段）替换，不要直接写死真实路径。推荐 `--interval 45 --whisper-model medium` 以提升问答识别与过渡页捕捉。

```powershell
python $env:USERPROFILE\.copilot\skills\generic-video-to-ppt\scripts\video_to_ppt.py `
  --video "<video_path>" `
  --template "<template_path>" `
  --output "<output_dir>\<output_name>.pptx" `
  --interval 45 `
  --whisper-model medium `
  --max-slides 35 `
  --keep-intermediate
```

参数说明：

| 参数 | 含义 | 默认值 |
|---|---|---|
| `--video` | 输入视频文件路径 | (必填) |
| `--template` | PPT 模板文件 (.pptx) | (必填) |
| `--output` | 输出 PPT 路径 | 由 config/询问决定 |
| `--interval` | 关键帧提取间隔（秒） | 60 |
| `--whisper-model` | Whisper 模型大小 (tiny/base/small/medium/large) | base |
| `--scene-detect` | 启用场景切换检测自动截帧 | False |
| `--max-slides` | PPT 最大页数 | 30 |
| `--no-bilingual` | 关闭中英文对照（默认开启） | False |
| `--keep-intermediate` | 保留中间产物便于复盘与二次编辑 | False |

### 单步操作

#### 1. 只提取关键帧

```powershell
python $env:USERPROFILE\.copilot\skills\generic-video-to-ppt\scripts\extract_frames.py `
  --video "video.mp4" --output-dir frames/ --interval 60 --scene-detect
```

#### 2. 只转录音频

```powershell
python $env:USERPROFILE\.copilot\skills\generic-video-to-ppt\scripts\transcribe_video.py `
  --video "video.mp4" --model base --output transcript.json
```

#### 3. 只生成 PPT（已有帧和文字）

```powershell
python $env:USERPROFILE\.copilot\skills\generic-video-to-ppt\scripts\generate_ppt.py `
  --frames-dir frames/ --transcript transcript.json `
  --template template.pptx --output output.pptx
```

## Frame Extraction Strategy

1. **固定间隔采样**：每 N 秒取一帧（默认 60s）
2. **场景切换检测**：对比相邻帧的直方图差异，差异超过阈值时截帧
3. **去重**：相似度 > 95% 的帧自动去除（避免静止画面重复截取）
4. **画面质量过滤**：跳过模糊/全黑/全白帧

## Transcription & Summarization

- 使用 OpenAI Whisper 本地模型进行语音识别（支持中英文混合）
- 按时间段分割文本，与对应帧关联
- 提取结构化信息：
  - **重点 (Key Points)**：每段的核心论述
  - **Q&A**：识别问答对话模式
  - **术语 (Terms)**：专业术语高亮

## PPT Generation Rules

1. 使用模板的第一个 slide layout 作为内容页布局
2. 每张 slide = 一个关键帧截图 + 对应时间段的结构化文字摘要（bullet）
3. 标题 = 时间戳 + 该段主题
4. 图片占 slide 60%，文字区占 40%
5. 最后额外生成：
   - 总结页 (Summary)
  - Q&A 汇总页（分页，保留全部问答）
   - 术语表页 (Glossary)
6. 每页备注 (Notes) 强制写入：
  - 当前页时间点（frame timestamp）
  - 对应段落时间范围（segment range）
  - 原始转录内容（按时间）
  - 该段识别出的 Q&A（问题+答案）

## Acceptance Checklist

- 每张内容页的文字是否肉眼清晰（100% 缩放可读）
- 每张内容页是否存在明确时间点
- Summary 页是否覆盖全程关键结论
- Q&A 是否完整记录（而不是仅前几条）
- Notes 是否包含时间范围 + 原文 + Q&A 追踪

## Files

| File | Purpose |
|---|---|
| [config.example.json](./config.example.json) | 配置模板：复制为 `config.json` 填入本机路径（视频/模板/输出） |
| [scripts/video_to_ppt.py](./scripts/video_to_ppt.py) | 主编排脚本：串联全流程 |
| [scripts/extract_frames.py](./scripts/extract_frames.py) | 视频帧提取（OpenCV） |
| [scripts/transcribe_video.py](./scripts/transcribe_video.py) | 音频转录（Whisper） |
| [scripts/generate_ppt.py](./scripts/generate_ppt.py) | PPT 生成（python-pptx） |

## Notes

- Whisper `base` 模型约 150MB，首次运行会自动下载
- 1 小时视频 + base 模型，CPU 转录约 10-15 分钟；GPU 约 2-3 分钟
- 视频文件过大时建议先用 `--interval 120` 减少帧数
- PPT 模板需至少包含一个 slide layout；建议用带 placeholder 的模板效果更佳
- 双语翻译优先尝试在线接口；网络受限时自动降级为本地规则翻译（仍保留 EN/ZH 对照结构）
