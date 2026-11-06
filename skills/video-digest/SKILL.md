---
name: video-digest
description: 把本地视频"读"成可理解内容：元数据、场景关键帧拼图、语音转写（faster-whisper，本地）、画面烧制字幕抽取。用于视频摘要、拉片、剧情还原、录屏/教学/监控内容提炼、按字幕或台词找时间点。
whenToUse: 用户给出视频文件（mp4/mkv/mov/webm/avi…）并要求总结、分析、理解、还原其内容，或问"这个视频讲了什么/讲了什么故事/说了什么"，或需要按画面、台词、字幕定位时间点时。
---

# 视频提炼（video-digest）

视频模型看不到连续画面，也听不到声音。本技能把视频拆成**模型能读的东西**，分三层，按需组合：

| 层 | 能力 | 命令 | 说明 |
|---|---|---|---|
| 1 | 画面 | `frames` | 抽关键帧 + 拼图，模型看画面 |
| 2 | 声音 | `transcribe` | 本地 ASR 转文字（带时间戳），拿到旁白/台词/剧情 |
| 3 | 画面上的字幕 | `captions` | 烧制字幕去重成表，适合"游戏画面+字幕"类短视频 |

**默认先判断视频类型**：画面本身是内容（教学/录屏/实拍）→ 用 1；故事在旁白里（短剧/游戏画面配解说）→ 优先 2；有硬字幕且不便装 ASR → 3。

## 0. 首次使用：环境自检

脚本基目录见 `<skill_resources>`，脚本为 `scripts/video_digest.py`；下文用 `$S` 代指该脚本的绝对路径，`<python>` 指可用的 Python 3.9+（优先 `DSH_VIDEO_DIGEST_PYTHON`，否则 `python` / `py -3` / `python3`）。

```bash
<python> "$S" doctor
```

- 核心依赖（av / numpy / pillow）缺失 → 运行 `<python> "$S" setup`
- 需要转写（第 2 层）且 `faster-whisper` 未装 → 运行 `<python> "$S" setup --with-asr`
- 国内网络慢：`setup` 加 `--mirror https://pypi.tuna.tsinghua.edu.cn/simple`
- 找不到 Python → 明确告知用户需要 Python 3.9+，**不要假装抽过帧或听过音频**

> 装包会改用户环境、下模型会占磁盘和带宽：**先问一句**再执行 `setup --with-asr`（首次转写会额外下载模型：base≈145MB、small≈460MB、medium≈1.5GB）。

## 1. 元数据

```bash
<python> "$S" info "<视频路径>"
```

拿时长/分辨率/帧率/音轨数量与编码。时长决定抽帧参数；无音轨就别承诺转写。

## 2. 画面：抽关键帧

```bash
<python> "$S" frames "<视频路径>" --samples 120 --shots 9 --out "<输出目录>"
```

| 时长 | samples | shots |
| --- | --- | --- |
| < 2 min | 90 | 9 |
| 2–10 min | 200 | 12 |
| 10–60 min | 400 或分段 | 12–16 |
| > 1 h | 必须分段 `--start/--end` | 每段 9 |

产物：`frames/*.jpg`（文件名含毫秒时间码）、`contact_sheet.jpg`（3 列拼图带时间码）、`summary.json`。
`score` 是相邻采样帧的画面变化分（0–1），高 = 切镜头/强运动。

读图顺序：先读 `contact_sheet.jpg` 拿全貌，需要细节再读单帧。

## 3. 声音：转写（faster-whisper，纯本地）

```bash
<python> "$S" transcribe "<视频路径>" --model small --language zh --out "<输出目录>"
```

- 模型选择：`base` 快而糙；`small` 中文可用（默认推荐）；`medium` 更准但慢 3–5 倍；`large-v3` 最准最慢。
- 中文视频建议显式 `--language zh`；可加 `--prompt "以下是普通话讲述的一段故事。"` 提升标点与连贯性。
- 只处理片段：`--start 60 --end 180`（时间戳会自动加上偏移）。
- 产物：`transcript_<model>.txt`（`[起-止] 文本`）、`transcript_<model>.json`、`audio_16k_mono.wav`。
- 纯 CPU 参考速度：5–6 分钟音频、`small` int8 ≈ 1–3 分钟；有 NVIDIA 卡可 `--device cuda --compute-type float16`。

转写使用要交代清楚：

- 这是 **ASR 转写**，同音字/专有名词可能出错；引用原文时保留，不确定处标注。
- 转写是**原始素材**，不要直接当结论；要结合画面或上下文校订。
- 涉及隐私内容：本地处理，不上传；但输出文件会落盘，用完可提醒用户清理。

## 4. 画面上烧制的字幕（可选）

```bash
<python> "$S" captions "<视频路径>" --step 0.6
```

顺序解码一次，按 0.6s 采样画面下部条带，用"高亮度低饱和"掩膜找字幕，掩膜差异去重，输出 `subs/NN.jpg` 字幕表。
适合抖音/快手类"背景画面 + 硬字幕"视频。缺点：游戏 HUD 的白色数字会造成误检（条数偏多），必要时调 `--diff 0.4`、`--min-pixels 800` 或收窄 `--band-top`。

## 5. 输出格式

```
## 总览
一句话概括（类型/主体/发生了什么）

## 时间轴
| 时间 | 画面 / 台词 |
| --- | --- |
| 00:00 | … |

## 关键点 / 结论
- …
```

硬性要求：

- 每个结论都要能对上时间码；**不要编造没观察到的细节**（帧间动作、未转写到的对话）。
- 分不清"画面里看到的"和"从语音/字幕推断的"，要标注来源。
- 看不清/没覆盖：直接说"该段抽帧未覆盖"，不要猜。
- 故事类视频：先给**人物关系与主线**，再按时间轴给情节，最后给主题/落点。

## 6. 常见问题

- **中文乱码**：脚本已把 stdout 切 UTF-8；必要时 `PYTHONIOENCODING=utf-8` 或用 `--json`。
- **超长视频**：>1 小时先分段（`--start/--end`），再对关键段细化。
- **超大文件 seek 慢**：先 `info`；必要时只处理片段。
- **抽帧全是同一画面**（监控/静止讲课）：调大 `--shots` 或提高采样密度。
- **只有声音没有画面**：`frames` 会明确报错，改用 `audio`/`transcribe`。
- **首次转写卡在下载**：换 `HF_ENDPOINT=https://hf-mirror.com` 重试。
