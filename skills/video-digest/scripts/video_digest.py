#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video_digest.py —— 不依赖 ffmpeg CLI 的视频快速提炼工具（PyAV + Pillow + numpy）

用法:
  python video_digest.py info   <video> [--json]
  python video_digest.py frames <video> [--samples 120] [--shots 9] [--start 0] [--end 0] [--out DIR]
  python video_digest.py audio  <video> [--out DIR]

设计: 1) 均匀采样 + 场景变化打分 -> 挑关键帧; 2) 导出关键帧 JPEG 与拼图 contact sheet;
      3) 可选导出 16k 单声道 wav, 供 whisper 等 ASR 使用; 4) summary.json 供 agent 读取。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import wave

try:  # Windows 控制台常为 GBK，中文输出会乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - 旧版 Python / 被重定向的流
    pass

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MICROS = 1_000_000


# ---------------------------------------------------------------- helpers
def ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if h else f"{m:02d}:{s:06.3f}"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def duration_of(container) -> float:
    if container.duration:
        return container.duration / MICROS
    st = container.streams.video[0] if container.streams.video else None
    if st is not None and st.duration:
        return float(st.duration * st.time_base)
    return 0.0


def font(size: int):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _normalize(frame) -> np.ndarray:
    """RGB frame -> float32 HxW luminance, long side <= 96."""
    img = frame.to_image().convert("L")
    w, h = img.size
    scale = 96.0 / max(w, h)
    if scale < 1:
        img = img.resize((max(16, int(w * scale)), max(16, int(h * scale))), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _hist(gray: np.ndarray) -> np.ndarray:
    h = np.histogram(gray, bins=16, range=(0.0, 1.0))[0].astype(np.float32)
    return h / max(1.0, h.sum())


def _decode_at(container, vstream, t: float):
    """Seek to t and return the first frame with time >= t."""
    try:
        container.seek(int(t / float(vstream.time_base)), stream=vstream, backward=True)
    except Exception:
        return None
    for frame in container.decode(vstream):
        ft = frame.time
        if ft is None:
            continue
        if ft >= t - 0.01:
            return frame
    return None


# ---------------------------------------------------------------- modes
def probe(path: str) -> dict:
    with av.open(path) as c:
        v = c.streams.video[0] if c.streams.video else None
        dur = duration_of(c)
        info = {
            "path": os.path.abspath(path),
            "size_bytes": os.path.getsize(path),
            "size_human": human(os.path.getsize(path)),
            "format": c.format.name if c.format else None,
            "duration_s": round(dur, 3),
            "duration_human": ts(dur) if dur else None,
            "video": None,
            "audio": [],
            "subtitle_streams": len(c.streams.subtitles),
        }
        if v is not None:
            fr = v.average_rate
            info["video"] = {
                "codec": v.codec_context.name,
                "width": v.codec_context.width,
                "height": v.codec_context.height,
                "fps": round(float(fr), 3) if fr else None,
                "frames_est": int(round(dur * float(fr))) if dur and fr else None,
                "pix_fmt": v.codec_context.pix_fmt,
            }
        for a in c.streams.audio:
            info["audio"].append({
                "codec": a.codec_context.name,
                "channels": a.codec_context.channels,
                "sample_rate": a.codec_context.sample_rate,
                "language": (a.metadata or {}).get("language"),
            })
        info["has_audio"] = bool(info["audio"])
        return info


def extract_frames(path: str, out_dir: str, samples: int, shots: int,
                   start: float = 0.0, end: float = 0.0, max_w: int = 1280) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    with av.open(path) as c:
        vstream = c.streams.video[0]
        dur = duration_of(c)
        t0 = max(0.0, start)
        t1 = end if end and end > t0 else dur
        if t1 <= t0:
            raise SystemExit("无效时间范围")
        span = t1 - t0
        n = max(8, int(samples))
        times = [t0 + span * i / n for i in range(n)]

        gray_list, hist_list = [], []
        for t in times:
            f = _decode_at(c, vstream, t)
            if f is None:
                continue
            g = _normalize(f)
            gray_list.append(g)
            hist_list.append(_hist(g))

        if not gray_list:
            raise SystemExit("解码失败: 未拿到任何帧")

        scores = [0.0]
        for i in range(1, len(gray_list)):
            if gray_list[i].shape != gray_list[i - 1].shape:
                scores.append(1.0)
                continue
            hdiff = 0.5 * float(np.abs(hist_list[i] - hist_list[i - 1]).sum())
            pdiff = float(np.abs(gray_list[i] - gray_list[i - 1]).mean())
            scores.append(round(min(1.0, 0.7 * hdiff + 0.9 * pdiff), 4))

        # 均匀覆盖 + 场景突变优先
        min_gap = span / max(2, shots * 1.4)
        chosen, used = [], []
        for idx in [0]:
            chosen.append(idx)
            used.append(times[idx])
        candidates = sorted(range(len(times)), key=lambda i: scores[i], reverse=True)
        for idx in candidates:
            if len(chosen) >= shots:
                break
            if scores[idx] < 0.012:
                continue
            if all(abs(times[idx] - u) >= min_gap for u in used):
                chosen.append(idx)
                used.append(times[idx])
        # 覆盖不足时补均匀点
        step = len(times) // max(2, shots)
        for idx in range(0, len(times), max(1, step)):
            if len(chosen) >= shots:
                break
            if all(abs(times[idx] - u) >= min_gap * 0.8 for u in used):
                chosen.append(idx)
                used.append(times[idx])
        chosen = sorted(set(chosen))

        # 第二遍: 按选中时间重新取全尺寸帧
        saved = []
        for k, idx in enumerate(chosen):
            t = times[idx]
            f = _decode_at(c, vstream, t)
            if f is None:
                continue
            img = f.to_image()
            if img.width > max_w:
                h = int(img.height * max_w / img.width)
                img = img.resize((max_w, h), Image.Resampling.LANCZOS)
            name = f"frame_{k + 1:02d}_{int(t * 1000):09d}ms.jpg"
            fp = os.path.join(frames_dir, name)
            img.save(fp, quality=88)
            saved.append({"index": k + 1, "time_s": round(t, 2), "time": ts(t),
                          "score": scores[idx], "path": fp, "w": img.width, "h": img.height})

    sheet = make_sheet(saved, os.path.join(out_dir, "contact_sheet.jpg"), dur)
    return {"duration_s": round(dur, 3), "duration": ts(dur), "sampled": len(gray_list),
            "shots": saved, "contact_sheet": sheet}


def make_sheet(shots: list, out_path: str, dur: float) -> str | None:
    if not shots:
        return None
    cols = 3
    cell_w, cell_h = 426, 240
    rows = (len(shots) + cols - 1) // cols
    pad = 8
    label_h = 26
    W = cols * cell_w + (cols + 1) * pad
    H = rows * (cell_h + label_h) + (rows + 1) * pad
    canvas = Image.new("RGB", (W, H), (18, 18, 20))
    d = ImageDraw.Draw(canvas)
    f = font(18)
    for i, s in enumerate(shots):
        r, cidx = divmod(i, cols)
        x = pad + cidx * (cell_w + pad)
        y = pad + r * (cell_h + label_h + pad)
        try:
            im = Image.open(s["path"]).convert("RGB")
            im = im.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            canvas.paste(im, (x, y))
        except Exception:
            d.rectangle([x, y, x + cell_w, y + cell_h], fill=(40, 40, 44))
        d.text((x + 4, y + cell_h + 4), f"{i + 1:02d}  {s['time']}", fill=(230, 230, 235), font=f)
    canvas.save(out_path, quality=88)
    return out_path


def dump_audio(path: str, out_dir: str, rate: int = 16000) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    out_wav = os.path.join(out_dir, "audio_16k_mono.wav")
    with av.open(path) as c:
        if not c.streams.audio:
            return {"audio": None, "reason": "no audio stream"}
        astream = c.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        total = 0
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            for frame in c.decode(astream):
                for rf in resampler.resample(frame):
                    data = rf.to_ndarray()
                    w.writeframes(data.tobytes())
                    total += data.size
            for rf in resampler.resample(None) or []:
                data = rf.to_ndarray()
                w.writeframes(data.tobytes())
                total += data.size
    return {"audio": out_wav, "sample_rate": rate,
            "duration_s": round(total / rate, 2),
            "size_bytes": os.path.getsize(out_wav)}


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description="视频快速提炼（无需 ffmpeg CLI）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info")
    p.add_argument("video")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("frames")
    p.add_argument("video")
    p.add_argument("--samples", type=int, default=120, help="采样帧数(默认120，长视频可加到300)")
    p.add_argument("--shots", type=int, default=9, help="输出关键帧数量(默认9)")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=0.0)
    p.add_argument("--out", default=None)
    p.add_argument("--json", action="store_true", help="以 JSON 打印结果")

    p = sub.add_parser("audio")
    p.add_argument("video")
    p.add_argument("--out", default=None)
    p.add_argument("--rate", type=int, default=16000)

    a = ap.parse_args(argv)

    if a.cmd == "info":
        info = probe(a.video)
        if a.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(f"文件      {info['path']}")
            print(f"大小      {info['size_human']}   时长 {info['duration_human']}   容器 {info['format']}")
            v = info["video"]
            if v:
                print(f"画面      {v['width']}x{v['height']}  {v['fps']}fps  {v['codec']}  {v['pix_fmt']}")
            print(f"音轨      {info['audio'] or '无'}")
        return 0

    if a.cmd == "frames":
        out = a.out or os.path.join(os.getcwd(), "video-digest",
                                    os.path.splitext(os.path.basename(a.video))[0][:60])
        res = extract_frames(a.video, out, a.samples, a.shots, a.start, a.end)
        res["video"] = probe(a.video)
        summary = os.path.join(out, "summary.json")
        with open(summary, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        if a.json:
            print(json.dumps(res, ensure_ascii=False))
            return 0
        print(f"时长 {res['duration']}  采样 {res['sampled']} 帧  关键帧 {len(res['shots'])} 张")
        for s in res["shots"]:
            print(f"  {s['index']:02d}  {s['time']:>10}  score={s['score']:.3f}  {s['path']}")
        print(f"拼图  {res['contact_sheet']}")
        print(f"摘要  {summary}")
        return 0

    if a.cmd == "audio":
        out = a.out or os.path.join(os.getcwd(), "video-digest",
                                    os.path.splitext(os.path.basename(a.video))[0][:60])
        res = dump_audio(a.video, out, a.rate)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())
