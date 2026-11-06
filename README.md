# dsh-video-digest

[English](README.md) | [中文](README.zh.md)

A **DeepSeek Harness plugin** that gives your agent a `video-digest` skill. Three layers,
composable, so a chat model can actually "read" a video:

| Layer | What it gives you | Command | Needs |
| --- | --- | --- | --- |
| 1 | **Picture** — scene-change keyframes + one contact sheet | `frames` | `av`, `numpy`, `pillow` |
| 2 | **Sound** — local speech-to-text with timestamps | `transcribe` | `+ faster-whisper` (optional) |
| 3 | **Burned-in subtitles** — deduplicated caption strips | `captions` | `av`, `numpy`, `pillow` |

No ffmpeg CLI required: decoding goes through [PyAV](https://github.com/PyAV-Org/PyAV),
which ships its own FFmpeg libraries. ASR runs **locally** via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) — nothing is uploaded.

## Install

**In DSH**, install the bundle from GitHub:

```jsonc
// ~/.dsh/profiles/<profile>/package.json
{
  "dependencies": { "dsh-video-digest": "github:Snutree/dsh-video-digest" },
  "dsh": { "profile": { "bundles": ["...", "dsh-video-digest"] } }
}
```

or, in the plugin manager, install `github:Snutree/dsh-video-digest`.

**Python side**, one command prepares everything:

```bash
python skills/video-digest/scripts/video_digest.py doctor    # what is missing
python skills/video-digest/scripts/video_digest.py setup --with-asr
# slow network in CN: add --mirror https://pypi.tuna.tsinghua.edu.cn/simple
```

`setup` installs `av`, `numpy`, `pillow` (layer 1/3) and, with `--with-asr`,
`faster-whisper` (layer 2). Models download automatically on first `transcribe`.

## Use

Just ask in any session:

> 这个视频讲了什么故事？`D:\videos\clip.mp4`

The skill picks the right layer, runs it, reads the artifacts, and answers with a timeline.
Manual use:

```bash
S=skills/video-digest/scripts/video_digest.py

python $S info       "D:\v.mp4"
python $S frames     "D:\v.mp4" --samples 200 --shots 12
python $S transcribe "D:\v.mp4" --model small --language zh
python $S captions   "D:\v.mp4" --step 0.6
python $S audio      "D:\v.mp4"
```

Bundled bin (same thing, finds Python for you):

```bash
npx dsh-video-digest transcribe "D:\v.mp4" --language zh
```

## Commands

### `doctor` / `setup`

| Flag | Meaning |
| --- | --- |
| `doctor --json` | machine-readable dependency report |
| `setup --with-asr` | install core + ASR dependencies |
| `setup --mirror URL` | pip index mirror |
| `setup --force` | reinstall even if present |

### `frames`

| Flag | Default | Meaning |
| --- | --- | --- |
| `--samples` | 120 | frames decoded for scoring |
| `--shots` | 9 | keyframes written |
| `--start` / `--end` | whole clip | section only (seconds) |
| `--max-width` | 1280 | keyframe width cap |
| `--json` | off | machine-readable result |

### `transcribe`

| Flag | Default | Meaning |
| --- | --- | --- |
| `--model` | `small` | `base` fast/rough · `small` recommended · `medium`/`large-v3` slower, better |
| `--language` | auto | `zh` for Chinese |
| `--device` | `cpu` | `cuda` if you have an NVIDIA GPU |
| `--compute-type` | `int8` | `float16` on GPU |
| `--prompt` | — | initial prompt, helps punctuation/context |
| `--start` / `--end` | whole clip | timestamps stay absolute |

Model download sizes: `base` ≈ 145 MB, `small` ≈ 460 MB, `medium` ≈ 1.5 GB.
CPU speed reference: 5–6 min of audio with `small` int8 ≈ 1–3 min.

### `captions`

Extracts text burned into the picture (the "gameplay background + hard subtitles" genre).
Flags: `--step 0.6`, `--band-top 0.66`, `--band-bottom 0.995`, `--min-pixels 400`,
`--diff 0.30`, `--per-sheet 8`. Bright HUD elements can cause false positives; raise
`--min-pixels` / `--diff` or narrow the band.

## Output

```
<out>/
  frames/frame_01_000008213ms.jpg   # timecoded keyframes
  contact_sheet.jpg                 # 3-column sheet
  summary.json                      # metadata + per-shot time/score
  audio_16k_mono.wav                # 16 kHz mono (ASR input)
  transcript_small.txt / .json      # [start-end] text segments
  captions/subs_01.jpg …            # caption strips
  captions/captions.json            # caption timestamps
```

## Why three layers

A chat model cannot watch video or hear audio. The honest decomposition is:

- **picture** — sample frames, score change, show the model a handful of images;
- **sound** — transcribe locally, give the model text with timecodes;
- **hard subtitles** — when the text is already on the pixels, extract it instead of
  transcribing (no model download, works offline).

The skill tells the agent which layer to pick, and forbids inventing what it did not observe.

## Limitations

- Frames are discrete; motion between them is not observed. The skill requires the agent to
  say so instead of hallucinating.
- ASR is a model: homophones and proper nouns can be wrong. Quotes should be treated as
  raw material, corrected from context or picture.
- `captions` uses a brightness/saturation heuristic; game HUDs produce false positives.
- No GPU required, but no GPU acceleration is enabled by default.
- Transcription is local (nothing uploaded), yet transcripts are written to disk — clean up
  if the material is private.

## Development

```bash
npm pack
node --check lib/index.js
python -m py_compile skills/video-digest/scripts/video_digest.py
python skills/video-digest/scripts/video_digest.py doctor
```

Skill body: `skills/video-digest/SKILL.md`. Plugin entry: `lib/index.js` (registers the skill
into `ctx.skills` with the package's `skills/video-digest` directory as `resourceBase`).

## License

MIT
