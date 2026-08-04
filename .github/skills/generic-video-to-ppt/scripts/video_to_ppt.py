"""
video_to_ppt.py - 主编排脚本：视频 → 帧提取 → 音频转录 → PPT 生成

一键完成全流程。

用法：
    python video_to_ppt.py --video "video.mp4" --template "template.pptx" --output "output.pptx"
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# 添加脚本目录到 path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from extract_frames import extract_frames_interval, extract_frames_scene_detect
from transcribe_video import extract_audio, transcribe_audio, segments_to_structured, extract_key_points, extract_qa
from generate_ppt import generate_ppt


def main():
    parser = argparse.ArgumentParser(description="视频 → PPT 全流程")
    parser.add_argument("--video", required=True, help="输入视频文件路径")
    parser.add_argument("--template", required=True, help="PPT 模板文件路径")
    parser.add_argument("--output", default="output.pptx", help="输出 PPT 路径")
    parser.add_argument("--interval", type=int, default=60, help="帧提取间隔（秒）")
    parser.add_argument("--scene-detect", action="store_true", help="使用场景切换检测")
    parser.add_argument("--whisper-model", default="base", help="Whisper 模型 (tiny/base/small/medium/large)")
    parser.add_argument("--language", default=None, help="音频语言 (zh/en/...)")
    parser.add_argument("--max-slides", type=int, default=30, help="PPT 最大页数")
    parser.add_argument("--work-dir", default=None, help="工作目录（存放中间文件）")
    parser.add_argument("--keep-intermediate", action="store_true", help="保留中间文件")
    parser.add_argument("--no-bilingual", action="store_true", help="关闭中英文对照显示")
    args = parser.parse_args()

    # 验证输入
    if not os.path.exists(args.video):
        print(f"Error: Video file not found: {args.video}")
        sys.exit(1)
    if not os.path.exists(args.template):
        print(f"Error: Template file not found: {args.template}")
        sys.exit(1)

    # 设置工作目录
    if args.work_dir:
        work_dir = args.work_dir
    else:
        video_stem = Path(args.video).stem
        # 清理文件名中的特殊字符
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in video_stem)[:50]
        work_dir = os.path.join(os.path.dirname(args.output) or ".", f"_video_work_{safe_name}")

    os.makedirs(work_dir, exist_ok=True)
    frames_dir = os.path.join(work_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    print("=" * 60)
    print("Video-to-PPT Pipeline")
    print("=" * 60)
    print(f"  Video:    {args.video}")
    print(f"  Template: {args.template}")
    print(f"  Output:   {args.output}")
    print(f"  Work dir: {work_dir}")
    print()

    # ─── Step 1: 提取关键帧 ───
    print("=" * 60)
    print("Step 1/3: Extracting key frames...")
    print("=" * 60)

    if args.scene_detect:
        frames = extract_frames_scene_detect(
            args.video, frames_dir,
            max_frames=args.max_slides + 5,
        )
    else:
        frames = extract_frames_interval(
            args.video, frames_dir,
            interval_sec=args.interval,
            max_frames=args.max_slides + 5,
        )

    if not frames:
        print("Error: No frames extracted!")
        sys.exit(1)

    # 保存帧元数据
    frames_meta_path = os.path.join(frames_dir, "frames_meta.json")
    with open(frames_meta_path, "w", encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False, indent=2)
    print(f"  {len(frames)} frames extracted.\n")

    # ─── Step 2: 转录音频 ───
    print("=" * 60)
    print("Step 2/3: Transcribing audio...")
    print("=" * 60)

    audio_path = os.path.join(work_dir, "audio.wav")
    transcript_path = os.path.join(work_dir, "transcript.json")

    try:
        extract_audio(args.video, audio_path)

        result = transcribe_audio(audio_path, model_name=args.whisper_model, language=args.language)
        segments = result.get("segments", [])

        # 按帧时间段分组
        frame_timestamps = [f["timestamp_sec"] for f in frames]
        structured = segments_to_structured(segments, frame_timestamps)

        # 提取重点和 Q&A
        key_points = extract_key_points(structured)
        qa_pairs = extract_qa(structured)

        # 保存转录结果
        transcript_data = {
            "video": args.video,
            "language": result.get("language", "unknown"),
            "duration_sec": segments[-1]["end"] if segments else 0,
            "total_segments": len(segments),
            "structured_segments": structured,
            "key_points": key_points,
            "qa_pairs": qa_pairs,
            "full_text": result.get("text", ""),
        }

        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, ensure_ascii=False, indent=2)

        print(f"  Transcription complete.")
        print(f"  - Language: {result.get('language', 'unknown')}")
        print(f"  - Segments: {len(structured)}")
        print(f"  - Key points: {len(key_points)}")
        print(f"  - Q&A pairs: {len(qa_pairs)}\n")

    finally:
        if os.path.exists(audio_path) and not args.keep_intermediate:
            os.unlink(audio_path)

    # ─── Step 3: 生成 PPT ───
    print("=" * 60)
    print("Step 3/3: Generating PPT...")
    print("=" * 60)

    generate_ppt(frames_dir, transcript_path, args.template, args.output,
                max_slides=args.max_slides, bilingual=not args.no_bilingual)

    # 清理（可选）
    if not args.keep_intermediate:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"\n  Intermediate files cleaned up.")

    print("\n" + "=" * 60)
    print(f"Done! PPT saved to: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
