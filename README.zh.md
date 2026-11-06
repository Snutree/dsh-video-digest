# dsh-video-digest

[English](README.md) | 中文

一个 **DeepSeek Harness 插件**：给 agent 装上 `video-digest` 技能，把本地视频变成
**少量关键帧 + 一张带时间码的拼图**，多模态模型就能真正"看"视频并回答
"这个视频讲了什么"。

**不需要系统装 ffmpeg**：解码走 [PyAV](https://github.com/PyAV-Org/PyAV)，它自带 FFmpeg 库。

```
视频文件 ──► 探测元数据 ──► 采样 N 帧 ──► 场景变化打分 ──► 取 K 张关键帧
                                                              │
                         contact_sheet.jpg  ◄──────────────────┤
                         frames/*.jpg（带时间码）                │
                         summary.json                          │
                                                              ▼
                                                模型读拼图 → 输出时间轴摘要
```

## 为什么需要它

聊天模型看不了视频。工业界的通用做法正是**抽帧 + 变化检测 + 看图**：一分钟的片段，
9 张关键帧加一张拼图就足以概括；录屏、教学、游戏录像、监控、PPT 讲解都适用。

## 装好之后你得到什么

- 会话技能目录里多出一个 `video-digest` 技能（安装后自动发现，不用重启理解系统）。
- `skills/video-digest/scripts/video_digest.py`：三种模式 `info` / `frames` / `audio`。
- `dsh-video-digest` 命令行包装，方便在 DSH 之外先验证环境。

## 环境要求

| 依赖 | 说明 |
| --- | --- |
| DeepSeek Harness `0.2.1+` | 本插件是 bundle（`dsh.bundle.patch`） |
| Node.js `>=22.12.0` | 宿主运行时 |
| Python `3.9+` | 跑抽帧脚本 |
| `av`、`numpy`、`Pillow` | `python -m pip install av`（PyAV 自带 FFmpeg） |

插件本身**没有** npm 运行时依赖。

## 安装

### 从 GitHub 安装（推荐）

编辑 `~/.dsh/profiles/<profile>/package.json`：

```json
{
  "dependencies": {
    "dsh-video-digest": "github:Snutree/dsh-video-digest"
  },
  "dsh": {
    "profile": {
      "bundles": ["...", "dsh-video-digest"]
    }
  }
}
```

然后在 DSH 插件管理器里重新安装该 bundle（或让它重装 profile 依赖）。

### 从本地 tgz 安装

```bash
npm pack
# DSH 插件管理器 -> 安装 bundle -> file:/绝对路径/dsh-video-digest-0.1.0.tgz
```

## 使用

任意会话里直接说：

> 帮我总结一下 D:\videos\lesson.mp4

agent 会加载技能，先 `info` 再 `frames`，读 `contact_sheet.jpg`，最后给出时间轴表格。

也可以手动跑：

```bash
python skills/video-digest/scripts/video_digest.py info   "D:\videos\lesson.mp4"
python skills/video-digest/scripts/video_digest.py frames "D:\videos\lesson.mp4" --samples 200 --shots 12
python skills/video-digest/scripts/video_digest.py audio  "D:\videos\lesson.mp4"
```

或通过包内 CLI：

```bash
npx dsh-video-digest info "D:\videos\lesson.mp4"
```

### 参数

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--samples` | 120 | 参与打分的采样帧数（越大变化检测越准、越慢） |
| `--shots` | 9 | 实际导出的关键帧数 |
| `--start` / `--end` | 全片 | 只处理某一段（秒） |
| `--out` | `./video-digest/<名字>` | 输出目录 |
| `--json` | 关 | 输出机器可读 JSON |

参考耗时：1 分钟 1080p ≈ 10 秒；10 分钟 ≈ 40 秒（普通桌面）。

## 产物

```
<out>/
  frames/frame_01_000008213ms.jpg   # 带时间码的关键帧
  contact_sheet.jpg                 # 3 列拼图，每格带时间码
  summary.json                      # 元数据 + 每帧时间/分数/路径
  audio_16k_mono.wav                # 仅 audio 模式
```

## 已知限制

- **只做画面。** 插件不含语音转写；音轨导出为 16 kHz 单声道 WAV，交给 Whisper 等 ASR。
  技能里明确禁止模型编造对话内容。
- 关键帧是离散的：帧与帧之间的运动没被观察。技能要求模型如实说明，而不是脑补。
- 场景打分是直方图 + 像素差的启发式：切镜头和强运动很准，静止画面需要调大 `--shots`。
- 暂不支持 GPU 加速、OCR 回退、内嵌字幕提取。

## 开发

```bash
npm pack                    # 产出 dsh-video-digest-0.1.0.tgz
node --check lib/index.js   # 插件入口是纯 ESM，无构建步骤
python -m py_compile skills/video-digest/scripts/video_digest.py
```

本地循环：用插件管理器装 tgz，然后让 agent 总结一个视频。技能正文在
`skills/video-digest/SKILL.md`，改完重装即生效。

## 许可证

MIT
