# dsh-video-digest

[English](README.md) | 中文

一个 **DeepSeek Harness 插件**：给 agent 装上 `video-digest` 技能。三层能力，按需组合，
让聊天模型真正"读"得懂视频：

| 层 | 拿到什么 | 命令 | 需要 |
| --- | --- | --- | --- |
| 1 | **画面**：场景变化关键帧 + 一张拼图 | `frames` | `av`、`numpy`、`pillow` |
| 2 | **声音**：本地语音转写，带时间戳 | `transcribe` | `+ faster-whisper`（可选） |
| 3 | **画面硬字幕**：去重后的字幕条 | `captions` | `av`、`numpy`、`pillow` |

**不需要系统装 ffmpeg**：解码走 [PyAV](https://github.com/PyAV-Org/PyAV)，它自带 FFmpeg 库。
语音转写用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，**纯本地**，不上传。

## 安装

**DSH 侧**：从 GitHub 装 bundle：

```jsonc
// ~/.dsh/profiles/<profile>/package.json
{
  "dependencies": { "dsh-video-digest": "github:Snutree/dsh-video-digest" },
  "dsh": { "profile": { "bundles": ["...", "dsh-video-digest"] } }
}
```

或在插件管理器里安装 `github:Snutree/dsh-video-digest`。

**Python 侧**：一条命令备齐依赖：

```bash
python skills/video-digest/scripts/video_digest.py doctor    # 看缺什么
python skills/video-digest/scripts/video_digest.py setup --with-asr
# 国内网络慢：加 --mirror https://pypi.tuna.tsinghua.edu.cn/simple
```

`setup` 装 `av`/`numpy`/`pillow`（1、3 层）；加 `--with-asr` 再装 `faster-whisper`（2 层）。
模型在首次 `transcribe` 时自动下载。

## 使用

任意会话里直接问：

> 这个视频讲了什么故事？`D:\videos\clip.mp4`

技能会自己选层、执行、读产物，最后给时间轴摘要。也可以手动跑：

```bash
S=skills/video-digest/scripts/video_digest.py

python $S info       "D:\v.mp4"
python $S frames     "D:\v.mp4" --samples 200 --shots 12
python $S transcribe "D:\v.mp4" --model small --language zh
python $S captions   "D:\v.mp4" --step 0.6
python $S audio      "D:\v.mp4"
```

也可以用包内 CLI（自动找 Python）：

```bash
npx dsh-video-digest transcribe "D:\v.mp4" --language zh
```

## 命令说明

### `doctor` / `setup`

| 参数 | 含义 |
| --- | --- |
| `doctor --json` | 机器可读的依赖报告 |
| `setup --with-asr` | 装核心依赖 + ASR 依赖 |
| `setup --mirror URL` | pip 镜像 |
| `setup --force` | 已装也重装 |

### `frames`

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--samples` | 120 | 参与打分的采样帧数 |
| `--shots` | 9 | 导出的关键帧数 |
| `--start` / `--end` | 全片 | 只处理某段（秒） |
| `--max-width` | 1280 | 关键帧宽度上限 |
| `--json` | 关 | 机器可读输出 |

### `transcribe`

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--model` | `small` | `base` 快而糙 · `small` 推荐 · `medium`/`large-v3` 更准更慢 |
| `--language` | 自动 | 中文用 `zh` |
| `--device` | `cpu` | 有 N 卡用 `cuda` |
| `--compute-type` | `int8` | GPU 上用 `float16` |
| `--prompt` | 无 | initial prompt，改善标点与上下文 |
| `--start` / `--end` | 全片 | 时间戳保持绝对时间 |

模型下载体积：`base` ≈ 145MB、`small` ≈ 460MB、`medium` ≈ 1.5GB。
CPU 参考速度：5–6 分钟音频 + `small` int8 ≈ 1–3 分钟。

### `captions`

抽取"烧在画面上"的字幕，适合"游戏画面 + 硬字幕"这类短视频。
参数：`--step 0.6`、`--band-top 0.66`、`--band-bottom 0.995`、`--min-pixels 400`、
`--diff 0.30`、`--per-sheet 8`。白色 HUD 数字会造成误检，可调大 `--min-pixels`/`--diff`
或收窄条带。

## 产物

```
<out>/
  frames/frame_01_000008213ms.jpg   # 带时间码的关键帧
  contact_sheet.jpg                 # 3 列拼图
  summary.json                      # 元数据 + 每帧时间/分数
  audio_16k_mono.wav                # 16k 单声道（ASR 输入）
  transcript_small.txt / .json      # [起-止] 文本分段
  captions/subs_01.jpg …            # 字幕条拼表
  captions/captions.json            # 字幕时间清单
```

## 为什么是三层

聊天模型既看不了视频也听不到声音，诚实的拆法就是：

- **画面**：采样 → 打分 → 只给模型看少量图；
- **声音**：本地转写 → 给模型带时间码的文本；
- **硬字幕**：文字已经在画面上时直接抽，不用下模型、可离线。

技能里写清了怎么选层，并禁止模型编造没观察到的内容。

## 已知限制

- 关键帧是离散的，帧间运动没被观察；技能要求模型如实说明，不许脑补。
- ASR 是模型，同音字/专有名词会错；引用要当原始素材，用上下文或画面校订。
- `captions` 用亮度/饱和度启发式，游戏 HUD 会误检。
- 不要求 GPU，但默认也没开 GPU 加速。
- 转写全程本地、不上传，但文本会落盘；私密素材用完记得清理。

## 开发

```bash
npm pack
node --check lib/index.js
python -m py_compile skills/video-digest/scripts/video_digest.py
python skills/video-digest/scripts/video_digest.py doctor
```

技能正文在 `skills/video-digest/SKILL.md`；插件入口 `lib/index.js` 把技能注册进
`ctx.skills`，并把包内 `skills/video-digest` 目录作为 `resourceBase`。

## 许可证

MIT
