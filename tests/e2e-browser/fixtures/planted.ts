import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The instruction-override detector's planted token (feature 013, FR-008 to FR-013): the run's message carries the
 * active `override_task` template with two 6-symbol fragments filled in, and only a reply that joins those two
 * fragments with nothing between them confirms the override. The template's wording stays in the versioned prompt
 * file, never in a test (FR-059); this helper only builds a pattern from it so a scripted target can reply with the
 * joined form, and reads the fragments back out of the message it actually received.
 */

/** The template's unambiguous symbol set (`src/kestrel/evidence/override.py`'s `ALPHABET`). */
export const OVERRIDE_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';

export interface OverrideFragments {
  first: string;
  second: string;
  joined: string;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** The prompt text of the active override template, front matter removed, from `src/kestrel/prompts/`. */
export function overrideTaskTemplate(version: string): string {
  const path = join(__dirname, '..', '..', '..', 'src', 'kestrel', 'prompts', `override_task.v${version}.md`);
  const lines = readFileSync(path, 'utf8').split('\n');
  if (lines[0]?.trim() !== '---') return lines.join('\n').replace(/^\n+|\n+$/g, '');
  const end = lines.findIndex((line, index) => index > 0 && line.trim() === '---');
  if (end === -1) return lines.join('\n');
  return lines
    .slice(end + 1)
    .join('\n')
    .replace(/^\n+|\n+$/g, '');
}

/**
 * A regular expression over a received message that captures the two filled fragments in the template's own
 * `{first_part}` / `{second_part}` placeholders. Anything around them is the template's reviewed wording, so the
 * pattern matches only a message this template produced.
 */
export function overrideFragmentsPattern(version: string): RegExp {
  const template = escapeRegExp(overrideTaskTemplate(version));
  const fragment = `[${OVERRIDE_ALPHABET}]{6}`;
  const pattern = template
    .replace(escapeRegExp('{first_part}'), `(${fragment})`)
    .replace(escapeRegExp('{second_part}'), `(${fragment})`);
  return new RegExp(pattern);
}

/** The two fragments from a message that carries the filled template, or `null` when it carries none. */
export function overrideFragments(message: string, pattern: RegExp): OverrideFragments | null {
  const match = message.match(pattern);
  if (!match) return null;
  const first = match[1];
  const second = match[2];
  return { first, second, joined: `${first}${second}` };
}

/** The echo-proof comparison form: case folded, every non-alphanumeric character removed (FR-009, FR-012). */
export function normalise(text: string): string {
  return text.toLowerCase().replace(/[^0-9a-z]/g, '');
}

/** The `message` field of a stub request body, as the target received it. */
export function sentMessage(body: string): string {
  return (JSON.parse(body) as { message: string }).message;
}
