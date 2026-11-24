import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The inert sample agent outputs of `tests/fixtures/unsafe_output_cases.json` (feature 013). Every text is test
 * data that nothing executes or fetches: a `positive` case matches exactly its named pattern, a `negative` case
 * matches no pattern at all (the contract's precision obligation). The cases live there, not here, so the detector
 * tests and this browser spec read the same reviewed samples.
 */
export interface UnsafeCase {
  pattern: string;
  kind: 'positive' | 'negative';
  text: string;
}

const CASES: UnsafeCase[] = JSON.parse(
  readFileSync(join(__dirname, '..', '..', 'fixtures', 'unsafe_output_cases.json'), 'utf8'),
).cases as UnsafeCase[];

/** Every case, optionally for one named pattern and one kind. */
export function unsafeCases(pattern?: string, kind?: UnsafeCase['kind']): UnsafeCase[] {
  return CASES.filter(
    (candidate) =>
      (pattern === undefined || candidate.pattern === pattern) && (kind === undefined || candidate.kind === kind),
  );
}

/** The first positive case for a pattern, or the first whose text contains `contains`. */
export function positiveCase(pattern: string, contains?: string): string {
  const match = unsafeCases(pattern, 'positive').find(
    (candidate) => contains === undefined || candidate.text.includes(contains),
  );
  if (!match) throw new Error(`no positive ${pattern} case${contains ? ` containing ${contains}` : ''}`);
  return match.text;
}

/** The first negative case for a pattern, or the first whose text contains `contains`. */
export function negativeCase(pattern: string, contains?: string): string {
  const match = unsafeCases(pattern, 'negative').find(
    (candidate) => contains === undefined || candidate.text.includes(contains),
  );
  if (!match) throw new Error(`no negative ${pattern} case${contains ? ` containing ${contains}` : ''}`);
  return match.text;
}
