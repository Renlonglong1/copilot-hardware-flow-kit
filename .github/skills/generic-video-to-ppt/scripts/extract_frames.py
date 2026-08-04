"""
extract_frames.py - 从视频中提取关键帧

支持两种策略：
1. 固定时间间隔采样
2. 场景切换检测（基于直方图差异）

用法：
    python extract_frames.py --video input.mp4 --output-dir frames/ --interval 60
    python extract_frames.py --video input.mp4 --output-dir frames/ --scene-detect
"""

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np


def is_blank_frame(frame, black_thresh=10, white_thresh=245, ratio=0.95):
    """检测全黑或全白帧"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    black_ratio = np.sum(gray < black_thresh) / gray.size
    white_ratio = np.sum(gray > white_thresh) / gray.size
    return black_ratio > ratio or white_ratio > ratio


def is_blurry(frame, threshold=50.0):
    """检测模糊帧（Laplacian 方差）"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    return variance < threshold


def frame_similarity(frame1, frame2):
    """计算两帧的直方图相似度"""
    hist1 = cv2.calcHist([frame1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist2 = cv2.calcHist([frame2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    return cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)


def scene_change_score(frame1, frame2):
    """计算场景切换分数（直方图差异）"""
    return 1.0 - frame_similarity(frame1, frame2)


def extract_frames_interval(video_path, output_dir, interval_sec=60, max_frames=50):
    """按固定时间间隔提取帧（使用 seek，快速）"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0

    print(f"Video: {video_path}")
    print(f"  FPS: {fps:.1f}, Duration: {duration_sec:.0f}s, Total frames: {total_frames}")
    print(f"  Extracting every {interval_sec}s (expect ~{int(duration_sec/interval_sec)} frames)")

    extracted = []
    prev_frame = None
    t = 0.0
    while t < duration_sec and len(extracted) < max_frames:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ret, frame = cap.read()
        if not ret:
            break

        if is_blank_frame(frame):
            t += interval_sec
            continue

        # near-duplicate dedup (skip almost identical consecutive frames)
        if prev_frame is not None and frame_similarity(frame, prev_frame) > 0.9999:
            t += interval_sec
            continue

        timestamp_sec = t
        timestamp_str = f"{int(timestamp_sec//3600):02d}h{int((timestamp_sec%3600)//60):02d}m{int(timestamp_sec%60):02d}s"
        filename = f"frame_{len(extracted):04d}_{timestamp_str}.png"
        filepath = os.path.join(output_dir, filename)
        cv2.imwrite(filepath, frame)
        extracted.append({
            "index": len(extracted),
            "frame_idx": int(timestamp_sec * fps),
            "timestamp_sec": timestamp_sec,
            "timestamp_str": timestamp_str,
            "filename": filename,
            "filepath": filepath,
        })
        prev_frame = frame.copy()
        print(f"  [{len(extracted):3d}] {timestamp_str} -> {filename}")
        t += interval_sec

    cap.release()
    print(f"  Extracted {len(extracted)} frames to {output_dir}")
    return extracted


def extract_frames_scene_detect(video_path, output_dir, threshold=0.4, min_gap_sec=10, max_frames=50):
    """基于场景切换检测提取帧"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    min_gap_frames = int(fps * min_gap_sec)

    print(f"Video: {video_path}")
    print(f"  Scene detection threshold={threshold}, min_gap={min_gap_sec}s")

    extracted = []
    prev_frame = None
    last_extract_idx = -min_gap_frames
    frame_idx = 0

    # 始终提取第一帧
    ret, frame = cap.read()
    if ret and not is_blank_frame(frame):
        timestamp_str = "00h00m00s"
        filename = f"frame_0000_{timestamp_str}.png"
        filepath = os.path.join(output_dir, filename)
        cv2.imwrite(filepath, frame)
        extracted.append({
            "index": 0,
            "frame_idx": 0,
            "timestamp_sec": 0,
            "timestamp_str": timestamp_str,
            "filename": filename,
            "filepath": filepath,
        })
        prev_frame = frame.copy()
        last_extract_idx = 0

    frame_idx = 1
    # 每隔若干帧采样检测场景切换（每 0.5 秒一次）
    sample_interval = max(1, int(fps * 0.5))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0 and prev_frame is not None:
            score = scene_change_score(prev_frame, frame)
            if score > threshold and (frame_idx - last_extract_idx) > min_gap_frames:
                if not is_blank_frame(frame) and not is_blurry(frame):
                    timestamp_sec = frame_idx / fps
                    timestamp_str = f"{int(timestamp_sec//3600):02d}h{int((timestamp_sec%3600)//60):02d}m{int(timestamp_sec%60):02d}s"
                    filename = f"frame_{len(extracted):04d}_{timestamp_str}.png"
                    filepath = os.path.join(output_dir, filename)
                    cv2.imwrite(filepath, frame)
                    extracted.append({
                        "index": len(extracted),
                        "frame_idx": frame_idx,
                        "timestamp_sec": timestamp_sec,
                        "timestamp_str": timestamp_str,
                        "filename": filename,
                        "filepath": filepath,
                    })
                    last_extract_idx = frame_idx

                    if len(extracted) >= max_frames:
                        break

            prev_frame = frame.copy()

        frame_idx += 1

    cap.release()
    print(f"  Extracted {len(extracted)} frames (scene detect) to {output_dir}")
    return extracted


def main():
    parser = argparse.ArgumentParser(description="从视频中提取关键帧")
    parser.add_argument("--video", required=True, help="输入视频文件路径")
    parser.add_argument("--output-dir", default="frames", help="输出帧目录")
    parser.add_argument("--interval", type=int, default=60, help="固定间隔采样秒数")
    parser.add_argument("--scene-detect", action="store_true", help="使用场景切换检测")
    parser.add_argument("--threshold", type=float, default=0.4, help="场景切换阈值")
    parser.add_argument("--min-gap", type=int, default=10, help="场景检测最小间隔秒数")
    parser.add_argument("--max-frames", type=int, default=50, help="最大帧数")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    if args.scene_detect:
        frames = extract_frames_scene_detect(
            args.video, args.output_dir,
            threshold=args.threshold,
            min_gap_sec=args.min_gap,
            max_frames=args.max_frames,
        )
    else:
        frames = extract_frames_interval(
            args.video, args.output_dir,
            interval_sec=args.interval,
            max_frames=args.max_frames,
        )

    # 保存帧信息到 JSON
    import json
    meta_path = os.path.join(args.output_dir, "frames_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False, indent=2)
    print(f"  Frame metadata saved to {meta_path}")

    return frames


if __name__ == "__main__":
    main()
