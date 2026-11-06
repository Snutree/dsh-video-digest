/**
 * dsh-video-digest —— 把 video-digest 技能注册进 DSH 的 skill 注册表。
 *
 * 纯声明式插件：不注册工具、不读写外部状态，只做一件事——
 * 把包内 skills/video-digest/SKILL.md 的内容注册为 `ctx.skills` 的运行时技能，
 * 并把该目录作为资源基目录（resourceBase），供模型按相对路径找 scripts/。
 *
 * @module dsh-video-digest
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** 插件名（与 cordis.patch.yml 的 entry id、包名保持一致）。 */
export const name = 'video-digest';

/** 需要技能注册表服务。 */
export const inject = ['skills'];

const here = dirname(fileURLToPath(import.meta.url));
const skillDir = join(here, '..', 'skills', 'video-digest');
const skillPath = join(skillDir, 'SKILL.md');

const FRONTMATTER = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/u;

/**
 * 去掉 YAML 标量两端的引号。
 * @param value - 原始标量文本。
 * @returns 去引号后的文本。
 */
function unquote(value) {
  const v = value.trim();
  if (v.length >= 2 && ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))) {
    return v.slice(1, -1);
  }
  return v;
}

/**
 * 解析 SKILL.md 的 YAML frontmatter（只支持顶层 key: value，够用且零依赖）。
 * @param raw - 文件全文。
 * @param file - 文件路径，用于报错。
 * @returns 元数据与正文。
 */
function parseSkill(raw, file) {
  const matched = FRONTMATTER.exec(raw);
  if (!matched) throw new Error(`[dsh-video-digest] ${file} 缺少 YAML frontmatter（--- ... ---）`);
  const meta = {};
  for (const line of matched[1].split(/\r?\n/u)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const at = line.indexOf(':');
    if (at <= 0) continue;
    meta[line.slice(0, at).trim()] = unquote(line.slice(at + 1));
  }
  return { meta, body: matched[2] };
}

/**
 * Cordis 插件入口：注册 video-digest 技能。
 * @param ctx - Cordis 上下文（已注入 skills 服务）。
 */
export function apply(ctx) {
  const { meta, body } = parseSkill(readFileSync(skillPath, 'utf8'), skillPath);
  if (!meta.name || !meta.description) {
    throw new Error('[dsh-video-digest] SKILL.md frontmatter 必须包含 name 与 description');
  }

  const registration = {
    name: meta.name,
    description: meta.description,
    whenToUse: meta.whenToUse || meta.when_to_use || undefined,
    content: body,
    path: skillPath,
    source: 'runtime',
    resourceBase: { kind: 'directory', path: skillDir },
    provider: 'dsh-video-digest',
  };

  if (typeof ctx.effect === 'function') {
    ctx.effect(() => ctx.skills.register(registration));
  } else {
    ctx.skills.register(registration);
  }
}
