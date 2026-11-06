# Changelog

## v0.2.0 — 2026-11-07

### 新增

- **`transcribe` 子命令**：本地语音转写（faster-whisper），带时间戳；支持 `--model`
  （base/small/medium/large-v3）、`--language`、`--prompt`、`--device/--compute-type`、
  `--start/--end` 分段（时间戳保持绝对）。
- **`captions` 子命令**：抽取"烧制在画面上的字幕"——顺序解码、白字掩膜检测、
  掩膜差异去重、拼成字幕表，输出 `captions.json`。适合"游戏画面 + 硬字幕"类短视频。
- **`doctor` 子命令**：检查 Python/依赖，`--json` 可机器读。
- **`setup` 子命令**：一条命令安装依赖；`--with-asr` 同时装 faster-whisper，
  `--mirror` 支持 pip 镜像，`--user`/`--force`/`--pip-args` 透传。
- `audio` 支持 `--start/--end` 片段导出。
- `info` 增加音轨序号、码率、`has_video`/`has_audio` 字段。
- 技能正文升级为三层工作流（画面 / 声音 / 硬字幕），补首次使用与隐私提示。

### 变更

- 脚本改为**延迟导入**依赖：缺少 `av`/`numpy`/`pillow` 时给出明确安装指引，而不是抛栈。
- 版本号统一到 `0.2.0`，`--version` 可用。

### 兼容

- 0.1.0 的 `info` / `frames` / `audio` 用法保持兼容。

## v0.1.0 — 2026-11-07

- 首个版本：`info` 元数据、`frames` 场景变化抽关键帧 + 拼图、`audio` 导出 16k 单声道 WAV。
- 插件通过 `ctx.skills.register()` 注册 `video-digest` 技能，`resourceBase` 指向包内技能目录。
- 提供 `dsh-video-digest` bin 包装。
