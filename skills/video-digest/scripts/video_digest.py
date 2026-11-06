#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video-digest 0.2.0 —— 视频提炼三件套（PyAV 抽帧 + faster-whisper 转写 + 烧制字幕抽取）

零 ffmpeg CLI 依赖：解码走 PyAV（自带 FFmpeg 库）。
ASR 走 faster-whisper（可选，按需安装；模型首次运行时自动下载）。

子命令
------
  doctor                      检查依赖是否齐全
  setup [--with-asr] [--mirror URL]   安装依赖（默认只装抽帧所需）
  info      <video>           元数据
  frames    <video>           场景变化抽关键帧 + 拼图
  audio     <video>           导出 16k 单声道 WAV
  transcribe <video>          语音转写（带时间戳）
  captions  <video>           抽取"烧制在画面上的字幕"（去重 + 拼表）

用法示例
--------
  python video_digest.py doctor
  python video_digest.py setup --with-asr
  python video_digest.py frames "D:/v.mp4" --samples 200 --shots 12
  python video_digest.py transcribe "D:/v.mp4" --model small --language zh
  python video_digest.py captions "D:/v.mp4" --step 0.6
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

try:  # Windows 控制台常为 GBK，中文输出会乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

MICROS = 1_000_000
VERSION = "0.2.0"

# (import 名, pip 名, 用途)
CORE_DEPS = [
    ("av", "av", "PyAV 视频解码（自带 FFmpeg）"),
    ("numpy", "numpy", "帧打分"),
    ("PIL", "pillow", "拼图渲染"),
]
ASR_DEPS = [
    ("faster_whisper", "faster-whisper", "语音转写（可选）"),
]


# ------------------------------------------------------------------ 基础工具
def die(msg: str, code: int = 2):
    print(f"[video-digest] {msg}", file=sys.stderr)
    sys.exit(code)


def has_module(mod: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def need_av():
    try:
        import av  # noqa: F401
    except ImportError:
        die("缺少 PyAV。先运行：python video_digest.py setup")
    import av

    return av


def need_np():
    try:
        import numpy as np
    except ImportError:
        die("缺少 numpy。先运行：python video_digest.py setup")
    return np


def need_pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        die("缺少 Pillow。先运行：python video_digest.py setup")
    return Image, ImageDraw, ImageFont


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


def default_out(video: str) -> str:
    name = os.path.splitext(os.path.basename(video))[0][:60]
    return os.path.join(os.getcwd(), "video-digest", name)


def font(size: int):
    _Image, _ImageDraw, ImageFont = need_pil()
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def duration_of(container) -> float:
    if container.duration:
        return container.duration / MICROS
    st = container.streams.video[0] if container.streams.video else None
    if st is not None and st.duration:
        return float(st.duration * st.time_base)
    return 0.0


# ------------------------------------------------------------------ doctor / setup
def cmd_doctor(a) -> int:
    rows = []
    for mod, pkg, desc in CORE_DEPS + ASR_DEPS:
        rows.append({
            "module": mod,
            "package": pkg,
            "installed": has_module(mod),
            "purpose": desc,
            "core": any(mod == m for m, _, _ in CORE_DEPS),
        })
    if a.json:
        print(json.dumps({"python": sys.version.split()[0], "executable": sys.executable, "deps": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"python  {sys.version.split()[0]}  ({sys.executable})")
        for r in rows:
            mark = "OK  " if r["installed"] else ("MISS" if r["core"] else "opt ")
            print(f"  [{mark}] {r['package']:<16} {r['purpose']}")
        missing_core = [r["package"] for r in rows if r["core"] and not r["installed"]]
        if missing_core:
            print(f"\n缺少核心依赖：{' '.join(missing_core)}")
            print("安装：python video_digest.py setup")
        if not all(r["installed"] for r in rows if not r["core"]):
            print("\n语音转写未安装（可选）：python video_digest.py setup --with-asr")
    ok = all(r["installed"] for r in rows if r["core"])
    return 0 if ok else 1


def cmd_setup(a) -> int:
    pkgs = []
    for mod, pkg, _ in CORE_DEPS:
        if a.force or not has_module(mod):
            pkgs.append(pkg)
    if a.with_asr:
        for mod, pkg, _ in ASR_DEPS:
            if a.force or not has_module(mod):
                pkgs.append(pkg)
    if not pkgs:
        print("依赖已齐全，无需安装。")
        return 0

    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if a.mirror:
        cmd += ["-i", a.mirror]
    if a.user:
        cmd.append("--user")
    if a.pip_args:
        cmd += a.pip_args.split()
    cmd += pkgs
    print("运行：", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    if rc != 0:
        die(f"pip 安装失败（退出码 {rc}）。可尝试 --mirror https://pypi.tuna.tsinghua.edu.cn/simple", rc)
    print("安装完成。")
    return 0


# ------------------------------------------------------------------ info
def probe(path: str) -> dict:
    av = need_av()
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
        for idx, a in enumerate(c.streams.audio):
            cc = a.codec_context
            info["audio"].append({
                "index": idx,
                "codec": cc.name,
                "channels": cc.channels,
                "sample_rate": cc.sample_rate,
                "bitrate": cc.bit_rate,
                "language": (a.metadata or {}).get("language"),
            })
        info["has_audio"] = bool(info["audio"])
        info["has_video"] = v is not None
        return info


def cmd_info(a) -> int:
    info = probe(a.video)
    if a.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"文件      {info['path']}")
    print(f"大小      {info['size_human']}   时长 {info['duration_human']}   容器 {info['format']}")
    v = info["video"]
    if v:
        print(f"画面      {v['width']}x{v['height']}  {v['fps']}fps  {v['codec']}  {v['pix_fmt']}")
    print(f"音轨      {info['audio'] or '无'}")
    return 0


# ------------------------------------------------------------------ frames
def _normalize(frame, np):
    img = frame.to_image().convert("L")
    w, h = img.size
    scale = 96.0 / max(w, h)
    if scale < 1:
        from PIL import Image

        img = img.resize((max(16, int(w * scale)), max(16, int(h * scale))), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _hist(gray, np):
    h = np.histogram(gray, bins=16, range=(0.0, 1.0))[0].astype(np.float32)
    return h / max(1.0, h.sum())


def _decode_at(container, vstream, t: float):
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


def extract_frames(path: str, out_dir: str, samples: int, shots: int,
                   start: float = 0.0, end: float = 0.0, max_w: int = 1280) -> dict:
    av = need_av()
    np = need_np()
    Image, _, _ = need_pil()
    os.makedirs(out_dir, exist_ok=True)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    with av.open(path) as c:
        if not c.streams.video:
            die("该文件没有视频流（只有音频？可改用 audio / transcribe 子命令）")
        vstream = c.streams.video[0]
        dur = duration_of(c)
        t0 = max(0.0, start)
        t1 = end if end and end > t0 else dur
        if t1 <= t0:
            die("无效时间范围：--end 必须大于 --start")
        span = t1 - t0
        n = max(8, int(samples))
        times = [t0 + span * i / n for i in range(n)]

        gray_list, hist_list = [], []
        for t in times:
            f = _decode_at(c, vstream, t)
            if f is None:
                continue
            g = _normalize(f, np)
            gray_list.append(g)
            hist_list.append(_hist(g, np))

        if not gray_list:
            die("解码失败：未拿到任何帧")

        scores = [0.0]
        for i in range(1, len(gray_list)):
            if gray_list[i].shape != gray_list[i - 1].shape:
                scores.append(1.0)
                continue
            hdiff = 0.5 * float(np.abs(hist_list[i] - hist_list[i - 1]).sum())
            pdiff = float(np.abs(gray_list[i] - gray_list[i - 1]).mean())
            scores.append(round(min(1.0, 0.7 * hdiff + 0.9 * pdiff), 4))

        min_gap = span / max(2, shots * 1.4)
        chosen, used = [0], [times[0]]
        for idx in sorted(range(len(times)), key=lambda i: scores[i], reverse=True):
            if len(chosen) >= shots:
                break
            if scores[idx] < 0.012:
                continue
            if all(abs(times[idx] - u) >= min_gap for u in used):
                chosen.append(idx)
                used.append(times[idx])
        step = len(times) // max(2, shots)
        for idx in range(0, len(times), max(1, step)):
            if len(chosen) >= shots:
                break
            if all(abs(times[idx] - u) >= min_gap * 0.8 for u in used):
                chosen.append(idx)
                used.append(times[idx])

        saved = []
        for k, idx in enumerate(sorted(set(chosen))):
            t = times[idx]
            f = _decode_at(c, vstream, t)
            if f is None:
                continue
            img = f.to_image()
            if img.width > max_w:
                img = img.resize((max_w, int(img.height * max_w / img.width)), Image.Resampling.LANCZOS)
            name = f"frame_{k + 1:02d}_{int(t * 1000):09d}ms.jpg"
            fp = os.path.join(frames_dir, name)
            img.save(fp, quality=88)
            saved.append({"index": k + 1, "time_s": round(t, 2), "time": ts(t),
                          "score": scores[idx], "path": fp, "w": img.width, "h": img.height})

    sheet = make_sheet(saved, os.path.join(out_dir, "contact_sheet.jpg"))
    return {"duration_s": round(dur, 3), "duration": ts(dur), "sampled": len(gray_list),
            "shots": saved, "contact_sheet": sheet}


def make_sheet(shots: list, out_path: str):
    if not shots:
        return None
    Image, ImageDraw, _ = need_pil()
    cols = 3
    cell_w, cell_h, pad, label_h = 426, 240, 8, 26
    rows = (len(shots) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell_w + (cols + 1) * pad,
                               rows * (cell_h + label_h) + (rows + 1) * pad), (18, 18, 20))
    d = ImageDraw.Draw(canvas)
    f = font(18)
    for i, s in enumerate(shots):
        r, cidx = divmod(i, cols)
        x = pad + cidx * (cell_w + pad)
        y = pad + r * (cell_h + label_h + pad)
        try:
            im = Image.open(s["path"]).convert("RGB").resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            canvas.paste(im, (x, y))
        except Exception:
            d.rectangle([x, y, x + cell_w, y + cell_h], fill=(40, 40, 44))
        d.text((x + 4, y + cell_h + 4), f"{i + 1:02d}  {s['time']}", fill=(230, 230, 235), font=f)
    canvas.save(out_path, quality=88)
    return out_path


def cmd_frames(a) -> int:
    out = a.out or default_out(a.video)
    res = extract_frames(a.video, out, a.samples, a.shots, a.start, a.end, a.max_width)
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


# ------------------------------------------------------------------ audio
def dump_audio(path: str, out_dir: str, rate: int = 16000,
               start: float = 0.0, end: float = 0.0) -> dict:
    av = need_av()
    os.makedirs(out_dir, exist_ok=True)
    suffix = "" if not start and not end else f"_{int(start * 1000)}_{int((end or 0) * 1000)}"
    out_wav = os.path.join(out_dir, f"audio_16k_mono{suffix}.wav")
    with av.open(path) as c:
        if not c.streams.audio:
            die("该文件没有音轨，无法导出音频")
        astream = c.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        total = 0
        with wave_open(out_wav, rate) as w:
            for frame in c.decode(astream):
                t = frame.time or 0.0
                dur = float(frame.samples) / float(frame.sample_rate or rate)
                if end and t >= end:
                    break
                if t + dur <= start:
                    continue
                for rf in resampler.resample(frame):
                    data = rf.to_ndarray()
                    w.writeframes(data.tobytes())
                    total += data.size
            for rf in resampler.resample(None) or []:
                data = rf.to_ndarray()
                w.writeframes(data.tobytes())
                total += data.size
    return {"audio": out_wav, "sample_rate": rate, "start_s": start,
            "duration_s": round(total / rate, 2), "size_bytes": os.path.getsize(out_wav)}


def wave_open(path: str, rate: int):
    import wave

    class _W:
        def __enter__(self):
            self.w = wave.open(path, "wb")
            self.w.setnchannels(1)
            self.w.setsampwidth(2)
            self.w.setframerate(rate)
            return self.w

        def __exit__(self, *exc):
            self.w.close()
            return False

    return _W()


def cmd_audio(a) -> int:
    out = a.out or default_out(a.video)
    res = dump_audio(a.video, out, a.rate, a.start, a.end)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ transcribe
def cmd_transcribe(a) -> int:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("缺少 faster-whisper。先运行：python video_digest.py setup --with-asr", 3)

    out = a.out or default_out(a.video)
    audio = dump_audio(a.video, out, 16000, a.start, a.end)["audio"]
    print(f"音轨  {audio}", flush=True)
    print(f"模型  {a.model}（首次运行会自动下载到本地缓存）...", flush=True)

    model = WhisperModel(a.model, device=a.device, compute_type=a.compute_type)
    segments, info = model.transcribe(
        audio,
        language=a.language or None,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        beam_size=a.beam,
        initial_prompt=a.prompt or None,
    )
    offset = a.start or 0.0
    rows = []
    txt_path = os.path.join(out, f"transcript_{a.model}.txt")
    json_path = os.path.join(out, f"transcript_{a.model}.json")
    with open(txt_path, "w", encoding="utf-8") as fh:
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            s0, s1 = round(seg.start + offset, 2), round(seg.end + offset, 2)
            line = f"[{s0:7.2f}-{s1:7.2f}] {text}"
            print(line, flush=True)
            fh.write(line + "\n")
            rows.append({"start": s0, "end": s1, "text": text})
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"language": info.language, "duration": round(info.duration, 2),
                   "model": a.model, "segments": rows}, fh, ensure_ascii=False, indent=2)
    print(f"\n完成：{len(rows)} 段 -> {txt_path}", flush=True)
    return 0


# ------------------------------------------------------------------ captions
def extract_captions(path: str, out_dir: str, step: float = 0.6,
                     band_top: float = 0.66, band_bottom: float = 0.995,
                     min_pixels: int = 400, diff: float = 0.30,
                     strip_w: int = 1200, per_sheet: int = 8) -> dict:
    av = need_av()
    np = need_np()
    Image, ImageDraw, _ = need_pil()
    os.makedirs(out_dir, exist_ok=True)

    kept = []
    last_mask = None
    with av.open(path) as c:
        if not c.streams.video:
            die("该文件没有视频流，无法抽取画面字幕")
        vs = c.streams.video[0]
        h = vs.codec_context.height
        y0, y1 = int(h * band_top), int(h * band_bottom)
        next_t = 0.0
        for frame in c.decode(vs):
            t = frame.time or 0.0
            if t < next_t:
                continue
            next_t = t + step
            arr = frame.to_ndarray(format="rgb24")[y0:y1]
            r = arr[:, :, 0].astype(np.int16)
            g = arr[:, :, 1].astype(np.int16)
            b = arr[:, :, 2].astype(np.int16)
            mx = np.maximum(np.maximum(r, g), b)
            mn = np.minimum(np.minimum(r, g), b)
            mask = (mx > 225) & ((mx - mn) < 40)
            if int(mask.sum()) < min_pixels:
                continue
            small = mask[::3, ::3]
            if last_mask is not None and small.shape == last_mask.shape:
                if np.logical_xor(small, last_mask).sum() / max(1, last_mask.sum()) < diff:
                    continue
            last_mask = small
            img = Image.fromarray(arr)
            img = img.resize((strip_w, int(img.height * strip_w / img.width)), Image.Resampling.LANCZOS)
            kept.append((t, img))

    sheets = []
    for i in range(0, len(kept), per_sheet):
        chunk = kept[i:i + per_sheet]
        strip_h = chunk[0][1].height
        pad, label_h = 6, 26
        H = len(chunk) * (strip_h + label_h + pad) + pad
        sheet = Image.new("RGB", (strip_w + pad * 2, H), (16, 16, 18))
        d = ImageDraw.Draw(sheet)
        f = font(18)
        for j, (t, img) in enumerate(chunk):
            y = pad + j * (strip_h + label_h + pad)
            sheet.paste(img, (pad, y))
            d.text((pad + 4, y + strip_h + 2), ts(t), fill=(235, 235, 240), font=f)
        p = os.path.join(out_dir, f"subs_{i // per_sheet + 1:02d}.jpg")
        sheet.save(p, quality=90)
        sheets.append(p)

    result = {
        "captions": len(kept),
        "sheets": sheets,
        "items": [{"time_s": round(t, 2), "time": ts(t)} for t, _ in kept],
    }
    with open(os.path.join(out_dir, "captions.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    return result


def cmd_captions(a) -> int:
    out = a.out or os.path.join(default_out(a.video), "captions")
    res = extract_captions(a.video, out, a.step, a.band_top, a.band_bottom,
                           a.min_pixels, a.diff, a.strip_width, a.per_sheet)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    print(f"候选字幕条 {res['captions']} 条，共 {len(res['sheets'])} 张表")
    for p in res["sheets"]:
        print("  ", p)
    print(f"清单  {os.path.join(out, 'captions.json')}")
    return 0


# ------------------------------------------------------------------ CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="video_digest.py",
        description=f"video-digest {VERSION} —— 视频提炼：抽帧 / 转写 / 字幕抽取（无需 ffmpeg CLI）",
    )
    ap.add_argument("--version", action="version", version=f"video-digest {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="检查依赖")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("setup", help="安装依赖")
    p.add_argument("--with-asr", action="store_true", help="同时安装 faster-whisper")
    p.add_argument("--mirror", default=None, help="pip 镜像，如 https://pypi.tuna.tsinghua.edu.cn/simple")
    p.add_argument("--user", action="store_true", help="传给 pip --user")
    p.add_argument("--force", action="store_true", help="已安装也重装")
    p.add_argument("--pip-args", default=None, help="额外 pip 参数")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("info", help="视频元数据")
    p.add_argument("video")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("frames", help="抽关键帧 + 拼图")
    p.add_argument("video")
    p.add_argument("--samples", type=int, default=120, help="采样帧数（默认 120）")
    p.add_argument("--shots", type=int, default=9, help="输出关键帧数（默认 9）")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=0.0)
    p.add_argument("--max-width", type=int, default=1280)
    p.add_argument("--out", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_frames)

    p = sub.add_parser("audio", help="导出 16k 单声道 WAV")
    p.add_argument("video")
    p.add_argument("--rate", type=int, default=16000)
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=0.0)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_audio)

    p = sub.add_parser("transcribe", help="语音转写（faster-whisper）")
    p.add_argument("video")
    p.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3")
    p.add_argument("--language", default=None, help="如 zh；默认自动识别")
    p.add_argument("--device", default="cpu", help="cpu / cuda / auto")
    p.add_argument("--compute-type", default="int8", help="int8 / int8_float16 / float16 / float32")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--prompt", default=None, help="initial_prompt，可给上下文提升准确率")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=0.0)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("captions", help="抽取画面上的烧制字幕")
    p.add_argument("video")
    p.add_argument("--step", type=float, default=0.6, help="采样间隔秒")
    p.add_argument("--band-top", type=float, default=0.66, help="字幕带起始高度比例")
    p.add_argument("--band-bottom", type=float, default=0.995)
    p.add_argument("--min-pixels", type=int, default=400, help="字幕像素下限")
    p.add_argument("--diff", type=float, default=0.30, help="去重阈值")
    p.add_argument("--strip-width", type=int, default=1200)
    p.add_argument("--per-sheet", type=int, default=8)
    p.add_argument("--out", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_captions)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
