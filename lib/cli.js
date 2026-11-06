#!/usr/bin/env node
/**
 * 命令行入口：dsh-video-digest <info|frames|audio> <视频> [...args]
 * 在 DSH 之外直接调用同一套 Python 脚本，方便先验证环境再装插件。
 */
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, '..', 'skills', 'video-digest', 'scripts', 'video_digest.py');
const passthrough = process.argv.slice(2);

const candidates = [
  process.env.DSH_VIDEO_DIGEST_PYTHON,
  process.platform === 'win32' ? 'python' : 'python3',
  process.platform === 'win32' ? 'py' : 'python',
].filter(Boolean);

let lastError = null;
for (const candidate of candidates) {
  const args = candidate === 'py' ? ['-3', script, ...passthrough] : [script, ...passthrough];
  const result = spawnSync(candidate, args, {
    stdio: 'inherit',
    env: { ...process.env, PYTHONIOENCODING: process.env.PYTHONIOENCODING || 'utf-8' },
  });
  if (result.error && result.error.code === 'ENOENT') {
    lastError = result.error;
    continue;
  }
  process.exit(result.status ?? 1);
}

console.error('[dsh-video-digest] 找不到可用的 Python。请安装 Python 3.9+，或把解释器路径写进 DSH_VIDEO_DIGEST_PYTHON。');
if (lastError) console.error(String(lastError.message || lastError));
process.exit(1);
