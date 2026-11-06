# dsh-video-digest

[English](README.md) | [中文](README.zh.md)

A **DeepSeek Harness plugin** that gives your agent a `video-digest` skill: it turns a local
video file into a handful of keyframes plus one contact sheet, so a multimodal model can
actually "read" the video — with timecodes — and answer "what happens in this video?".

No ffmpeg CLI required: decoding goes through [PyAV](https://github.com/PyAV-Org/PyAV),
which ships its own FFmpeg libraries.

```
video file ──► probe ──► sample N frames ──► scene-change score ──► top K keyframes
                                                                        │
                              contact_sheet.jpg  ◄──────────────────────┤
                              frames/*.jpg (timecoded)                  │
                              summary.json                              │
                                                                        ▼
                                                        model reads the sheet,
                                                        writes a timeline digest
```

## Why

Chat models can't watch video. The standard trick — and what this plugin automates — is
**frame sampling + change detection + visual reading**. Nine frames and one contact sheet
are enough to summarise a one-minute clip, and it works for screen recordings, tutorials,
gameplay, surveillance footage and slide decks alike.

## What you get

- A `video-digest` skill registered into the session skill catalog (auto-discovered, no
  restart of the app required after install).
- `skills/video-digest/scripts/video_digest.py` — zero-dependency-on-ffmpeg CLI with three
  modes: `info`, `frames`, `audio`.
- `dsh-video-digest` bin wrapper for testing outside DSH.

## Requirements

| Dependency | Notes |
| --- | --- |
| DeepSeek Harness `0.2.1+` | plugin is a bundle (`dsh.bundle.patch`) |
| Node.js `>=22.12.0` | host runtime |
| Python `3.9+` | for the extraction script |
| `av`, `numpy`, `Pillow` | `python -m pip install av` (PyAV bundles FFmpeg) |

The plugin itself has no runtime npm dependencies.

## Install

### From GitHub (recommended)

Add to `~/.dsh/profiles/<profile>/package.json`:

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

then reinstall profile dependencies (the DSH plugin manager does this for you when you
install a bundle from a spec).

### From a local tarball

```bash
npm pack
# then in the DSH plugin manager: install bundle  ->  file:/absolute/path/dsh-video-digest-0.1.0.tgz
```

## Use

In any session:

> 帮我总结一下 D:\videos\lesson.mp4

The agent loads the skill, runs `info` then `frames`, reads `contact_sheet.jpg`, and answers
with a timeline table. You can also drive the script directly:

```bash
python skills/video-digest/scripts/video_digest.py info   "D:\videos\lesson.mp4"
python skills/video-digest/scripts/video_digest.py frames "D:\videos\lesson.mp4" --samples 200 --shots 12
python skills/video-digest/scripts/video_digest.py audio  "D:\videos\lesson.mp4"
```

Or through the bundled bin:

```bash
npx dsh-video-digest info "D:\videos\lesson.mp4"
```

### Parameters

| Flag | Default | Meaning |
| --- | --- | --- |
| `--samples` | 120 | frames decoded for scoring (more = better change detection, slower) |
| `--shots` | 9 | keyframes written out |
| `--start` / `--end` | full clip | process a section only (seconds) |
| `--out` | `./video-digest/<name>` | output directory |
| `--json` | off | machine-readable result |

Rough timings: 1 min 1080p ≈ 10 s, 10 min ≈ 40 s on a normal desktop.

## Output

```
<out>/
  frames/frame_01_000008213ms.jpg   # timecoded keyframes
  contact_sheet.jpg                 # 3-column sheet with timecodes
  summary.json                      # metadata + per-shot time/score/path
  audio_16k_mono.wav                # audio mode only
```

## Limitations

- **Visual only.** There is no speech-to-text in this plugin; audio is exported as a 16 kHz
  mono WAV so you can feed it to Whisper or any ASR. The skill explicitly forbids inventing
  dialogue.
- Keyframes are discrete: motion between them is not observed. The skill instructs the model
  to say so instead of hallucinating.
- Scene-change scoring is a histogram + pixel-diff heuristic. It works well on cuts and
  strong motion; static footage needs a higher `--shots`.
- No GPU, no OCR fallback, no subtitle extraction (yet).

## Development

```bash
npm pack                    # produces dsh-video-digest-0.1.0.tgz
node --check lib/index.js   # plugin entry is plain ESM, no build step
python -m py_compile skills/video-digest/scripts/video_digest.py
```

Local loop: install the tarball in the DSH plugin manager, then ask an agent to summarise a
video. The skill body lives in `skills/video-digest/SKILL.md` — edit it and the change is
picked up on the next session (install refreshes the package copy).

## License

MIT
