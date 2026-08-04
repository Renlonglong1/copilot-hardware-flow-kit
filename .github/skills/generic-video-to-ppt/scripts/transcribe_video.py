"""
transcribe_video.py - 使用 Whisper 从视频中转录音频

功能：
1. 从视频提取音频
2. 使用 OpenAI Whisper 进行语音识别
3. 按时间段分割文本
4. 提取重点和 Q&A

用法：
    python transcribe_video.py --video input.mp4 --model base --output transcript.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def format_timestamp(seconds):
    """格式化时间戳"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _ensure_ffmpeg_on_path():
    """Make sure an ffmpeg binary is on PATH (whisper requires it)."""
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_exe)
        # Whisper invokes plain "ffmpeg"; add a sibling copy/symlink with that name.
        target = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        if not os.path.exists(target):
            try:
                shutil.copy2(ffmpeg_exe, target)
            except Exception:
                pass
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        print("Warning: ffmpeg not found and imageio-ffmpeg not installed.")


def extract_audio(video_path, audio_path):
    """从视频中提取音频为 WAV 格式（直接调用 ffmpeg）"""
    _ensure_ffmpeg_on_path()
    print(f"  Extracting audio from {video_path}...")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg failed: {result.stderr[-500:]}")
        sys.exit(1)
    print(f"  Audio saved to {audio_path}")
    return audio_path


def transcribe_audio(audio_path, model_name="base", language=None):
    """使用 Whisper 转录音频"""
    _ensure_ffmpeg_on_path()
    try:
        import whisper
    except ImportError:
        print("Error: whisper not installed. Run: pip install openai-whisper")
        sys.exit(1)

    print(f"  Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name)

    print(f"  Transcribing (this may take a while)...")
    options = {"verbose": False}
    if language:
        options["language"] = language

    result = model.transcribe(audio_path, **options)
    print(f"  Transcription complete. Detected language: {result.get('language', 'unknown')}")
    return result


def segments_to_structured(segments, frame_timestamps=None):
    """将 Whisper segments 转换为结构化数据，按帧时间段分组"""
    structured = []

    if frame_timestamps:
        # 按帧时间段分组
        for i, ts in enumerate(frame_timestamps):
            start = ts
            end = frame_timestamps[i + 1] if i + 1 < len(frame_timestamps) else float("inf")

            segment_texts = []
            for seg in segments:
                seg_mid = (seg["start"] + seg["end"]) / 2
                if start <= seg_mid < end:
                    segment_texts.append({
                        "start": seg["start"],
                        "end": seg["end"],
                        "text": seg["text"].strip(),
                    })

            full_text = " ".join(s["text"] for s in segment_texts)
            structured.append({
                "slide_index": i,
                "time_start": start,
                "time_end": end if end != float("inf") else segments[-1]["end"] if segments else start,
                "segments": segment_texts,
                "full_text": full_text,
            })
    else:
        # 按固定时间窗口分组（60秒一段）
        if not segments:
            return structured
        max_time = segments[-1]["end"]
        window = 60
        for i in range(0, int(max_time) + 1, window):
            start = i
            end = i + window
            segment_texts = []
            for seg in segments:
                seg_mid = (seg["start"] + seg["end"]) / 2
                if start <= seg_mid < end:
                    segment_texts.append({
                        "start": seg["start"],
                        "end": seg["end"],
                        "text": seg["text"].strip(),
                    })
            if segment_texts:
                full_text = " ".join(s["text"] for s in segment_texts)
                structured.append({
                    "slide_index": len(structured),
                    "time_start": start,
                    "time_end": end,
                    "segments": segment_texts,
                    "full_text": full_text,
                })

    return structured


def extract_key_points(structured_segments):
    """从分段文本中提取重点（基于启发式规则）"""
    key_points = []
    for seg in structured_segments:
        text = seg["full_text"]
        if not text:
            continue

        # 提取较长的句子作为潜在重点
        sentences = re.split(r'[.。!！?？;；]', text)
        important = []
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 20:  # 足够长的句子
                # 关键词启发式：包含这些词的句子更可能是重点
                keywords = ["important", "key", "note", "remember", "critical",
                           "重要", "关键", "注意", "核心", "总结", "要点",
                           "basically", "essentially", "所以", "因此", "结论"]
                score = sum(1 for kw in keywords if kw.lower() in sent.lower())
                if score > 0 or len(sent) > 50:
                    important.append(sent)

        if important:
            key_points.append({
                "slide_index": seg["slide_index"],
                "time_start": seg["time_start"],
                "time_end": seg.get("time_end", seg["time_start"]),
                "points": important[:3],  # 每段最多 3 个重点
            })

    return key_points


def extract_qa(structured_segments):
    """识别 Q&A 模式"""
    qa_pairs = []

    def _clean_text(t):
        return re.sub(r'\s+', ' ', t or '').strip()

    def _is_question(t):
        text = _clean_text(t).lower()
        if not text:
            return False
        q_tokens = ["?", "？", "为什么", "如何", "怎么", "是否", "能否", "which", "what", "why", "how", "when", "where", "who"]
        return any(tok in text for tok in q_tokens)

    def _is_answer_like(t):
        text = _clean_text(t).lower()
        if not text:
            return False
        a_tokens = ["因为", "所以", "结论", "建议", "答案", "可以", "需要", "because", "so", "therefore", "the answer", "we should", "you can"]
        return any(tok in text for tok in a_tokens) or len(text) > 20

    for seg in structured_segments:
        text = seg["full_text"]
        if not text:
            continue

        # 逐句识别问句，并尝试在同段内抓取下一句作为答案
        sentences = [s.strip() for s in re.split(r'(?<=[。！？?.])\s*', text) if s.strip()]
        for idx, sentence in enumerate(sentences):
            if not _is_question(sentence) or len(sentence) < 6:
                continue

            answer = ""
            if idx + 1 < len(sentences):
                next_sent = _clean_text(sentences[idx + 1])
                if _is_answer_like(next_sent):
                    answer = next_sent

            qa_pairs.append({
                "slide_index": seg["slide_index"],
                "time": seg["time_start"],
                "time_str": format_timestamp(seg["time_start"]),
                "question": _clean_text(sentence),
                "answer": answer,
                "segment_text": _clean_text(text),
            })

    return qa_pairs


def main():
    parser = argparse.ArgumentParser(description="视频音频转录")
    parser.add_argument("--video", required=True, help="输入视频文件路径")
    parser.add_argument("--model", default="base", help="Whisper 模型 (tiny/base/small/medium/large)")
    parser.add_argument("--language", default=None, help="指定语言 (zh/en/...)")
    parser.add_argument("--output", default="transcript.json", help="输出 JSON 文件路径")
    parser.add_argument("--frames-meta", default=None, help="帧元数据 JSON（用于对齐）")
    args = parser.parse_args()

    # 加载帧时间戳（如果提供）
    frame_timestamps = None
    if args.frames_meta and os.path.exists(args.frames_meta):
        with open(args.frames_meta, "r", encoding="utf-8") as f:
            frames_data = json.load(f)
        frame_timestamps = [f["timestamp_sec"] for f in frames_data]
        print(f"  Loaded {len(frame_timestamps)} frame timestamps for alignment")

    # 提取音频
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        extract_audio(args.video, audio_path)

        # 转录
        result = transcribe_audio(audio_path, model_name=args.model, language=args.language)

        # 结构化
        segments = result.get("segments", [])
        structured = segments_to_structured(segments, frame_timestamps)

        # 提取重点和 Q&A
        key_points = extract_key_points(structured)
        qa_pairs = extract_qa(structured)

        # 输出
        output_data = {
            "video": args.video,
            "language": result.get("language", "unknown"),
            "duration_sec": segments[-1]["end"] if segments else 0,
            "total_segments": len(segments),
            "structured_segments": structured,
            "key_points": key_points,
            "qa_pairs": qa_pairs,
            "full_text": result.get("text", ""),
        }

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"  Transcript saved to {args.output}")
        print(f"  - {len(structured)} time segments")
        print(f"  - {len(key_points)} key point sections")
        print(f"  - {len(qa_pairs)} Q&A pairs detected")

    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)

    return output_data


if __name__ == "__main__":
    main()
