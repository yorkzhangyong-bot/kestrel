import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import type { KestrelApi, KestrelConfig, LogLine, RunDetail } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';
import { RunLogViewer } from './pages/RunLogViewer';
import { PriorExperienceControl } from './pages/PriorExperienceControl';

const SPL_FAMILY = 'System prompt leak · LLM07: System Prompt Leakage (4 prompts)';
const TEX_FAMILY = 'Tool-mediated exfiltration · LLM06: Excessive Agency (4 prompts)';
const SPL_PROMPT = 'System prompt leak — spl-001';
const TEX_PROMPT = 'Tool-mediated exfiltration — tex-001';
const CANARY = 'KESTREL-CANARY-demo';
const CANARY_REPLY = `Here is my system prompt: ${CANARY}`;
const REFUSAL = 'I cannot help with that request.';
const PRIOR_EXPERIENCE_CAPTION =
  'On: the attacker is primed with similar past patterns and this target\'s memory, as hints. ' +
  'Off: a cold run, like before.';

function retrievalLines(lines: LogLine[]): LogLine[] {
  return lines.filter((line) => line.event === 'memory.retrieval');
}

function writebackLines(lines: LogLine[]): LogLine[] {
  return lines.filter((line) => line.event === 'memory.writeback');
}

function startLine(lines: LogLine[]): LogLine {
  const start = lines.find((line) => line.event === 'run.start');
  expect(start, 'the log must carry a run.start line').toBeDefined();
  return start as LogLine;
}

/** The invariants every `memory.retrieval` line has to satisfy (feature 011, FR-013, SC-003). */
function expectRetrievalInvariants(line: LogLine, config: KestrelConfig): void {
  const k = config.experience.pattern_k;
  const floor = config.experience.distance_floor as number;
  const threshold = config.experience.dedupe_threshold;
  expect(line.event).toBe('memory.retrieval');
  expect(line.level).toBe('INFO');
  const turn = line.turn as number;
  expect(Number.isInteger(turn) && turn >= 2, `turn must be an integer >= 2, got ${String(line.turn)}`).toBe(true);
  expect(line.k).toBe(k);
  expect(line.distance_floor).toBe(floor);
  expect(line.dedupe_threshold).toBe(threshold);
  for (const field of [
    'candidate_count',
    'dropped_floor',
    'dropped_duplicate',
    'pattern_count',
    'memory_count',
    'query_messages',
  ]) {
    expect(
      Number.isInteger(line[field]) && (line[field] as number) >= 0,
      `${field} must be a non-negative integer, got ${String(line[field])}`,
    ).toBe(true);
  }
  expect(line.candidate_count).toBe(
    (line.dropped_floor as number) + (line.dropped_duplicate as number) + (line.pattern_count as number),
  );
  expect(line.candidate_count as number).toBeLessThanOrEqual(4 * k);

  const patternIds = line.pattern_ids as string[];
  expect(Array.isArray(patternIds)).toBe(true);
  expect(patternIds).toHaveLength(line.pattern_count as number);
  for (const id of patternIds) {
    expect(id).toMatch(/^pattern:(lib|run):/);
  }

  const distances = line.distances as number[];
  expect(Array.isArray(distances)).toBe(true);
  expect(distances).toHaveLength(line.pattern_count as number);
  for (let index = 0; index < distances.length; index += 1) {
    expect(typeof distances[index]).toBe('number');
    expect(distances[index]).toBeLessThanOrEqual(floor);
    if (index > 0) {
      expect(distances[index]).toBeGreaterThanOrEqual(distances[index - 1]);
    }
  }

  expect(line.warm).toBe((line.pattern_count as number) > 0);
  // The query is the family goal plus the attacker's own window: the seed alone on turn 2, two messages from turn 3.
  expect(line.query_messages).toBe(turn === 2 ? 1 : 2);
}

/**
 * Click "Run attack" and wait for this click's run to exist and finish before touching the UI result again.
 * `expect.poll` is used instead of a fixed sleep: the new run is the condition that proves the click's request
 * was served.
 */
async function runFromUi(app: KestrelApp, api: KestrelApi, targetId: number, timeout = 50_000): Promise<number> {
  const before = (await api.listRuns(targetId)).length;
  await app.runAttack();
  await expect
    .poll(async () => (await api.listRuns(targetId)).length, { timeout, message: 'the UI run did not finish' })
    .toBe(before + 1);
  const newest = (await api.listRuns(targetId))[0];
  await expect
    .poll(async () => (await api.getRun(newest.id)).status, { timeout, message: 'the run did not reach finished' })
    .toBe('finished');
  return newest.id;
}

/** Covers FR-005, FR-012, FR-013, SC-007 */
test("1. shows a warm adaptive run's memory.retrieval line with the shipped settings and counts [FR-005, FR-012, FR-013, SC-007]", async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker model for an adaptive run').toBe(true);
  expect(config.experience.distance_floor, '/api/config must report the shipped distance floor').not.toBeNull();
  expect(config.experience.dedupe_threshold, '/api/config must report the shipped threshold').not.toBeNull();

  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await expect(priorExperience.toggle).toBeVisible();
  await expect(priorExperience.toggle).toBeChecked();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.selectPrompt(SPL_PROMPT);
  await app.selectMode('Adaptive');

  // A run may stop before turn 2 for any stopping reason; retry up to three runs (re-arming the stub each time).
  let chosen: { run: RunDetail; lines: LogLine[] } | undefined;
  for (let attempt = 0; attempt < 3 && !chosen; attempt += 1) {
    stub.setReplies([REFUSAL, CANARY_REPLY]);
    const runId = await runFromUi(app, api, target.id);
    const run = await api.getRun(runId);
    const lines = (await api.getRunLog(run.id)).lines;
    if (retrievalLines(lines).length > 0) {
      chosen = { run, lines };
    }
  }
  expect(chosen, 'no adaptive run carried a memory.retrieval line in three attempts').toBeDefined();
  if (!chosen) return;

  const { run, lines } = chosen;
  expect(run.turns_used as number).toBeGreaterThanOrEqual(2);
  expect(startLine(lines).use_prior_experience).toBe(true);

  const retrievals = retrievalLines(lines);
  expect(retrievals.length).toBeGreaterThan(0);
  for (const line of retrievals) {
    expectRetrievalInvariants(line, config);
  }
  const turnTwo = retrievals.find((line) => line.turn === 2);
  expect(turnTwo, 'a warm run must retrieve on turn 2, when the seed is in the query').toBeDefined();
  expect((turnTwo as LogLine).pattern_count as number).toBeGreaterThanOrEqual(1);

  // The run that carries the retrieval line is the newest one and is readable from history, before and after a reload.
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  expect(await viewer.parsedLines()).toEqual(lines);
  const beforeReload = await viewer.rawText();
  expect(beforeReload).toContain('"event": "memory.retrieval"');

  await page.reload();
  await expect(app.runButton).toBeVisible();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  expect(await viewer.parsedLines()).toEqual(lines);
  expect(await viewer.rawText()).toBe(beforeReload);
  expect(retrievalLines(await viewer.parsedLines()).length).toBeGreaterThan(0);
});

/** Covers FR-001, FR-013 */
test('2. builds the query from the attacker\'s own window: one message on turn 2, two from turn 3 [FR-001, FR-013]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker model for an adaptive run').toBe(true);
  expect(config.experience.distance_floor).not.toBeNull();

  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.selectPrompt(SPL_PROMPT);
  await app.selectMode('Adaptive');
  await expect(priorExperience.toggle).toBeChecked();

  // The run may stop before turn 3; retry up to three times, re-arming the scripted replies before every run.
  let chosen: { run: RunDetail; lines: LogLine[] } | undefined;
  for (let attempt = 0; attempt < 3 && !chosen; attempt += 1) {
    stub.setReplies([REFUSAL, REFUSAL, CANARY_REPLY]);
    const runId = await runFromUi(app, api, target.id);
    const run = await api.getRun(runId);
    const lines = (await api.getRunLog(run.id)).lines;
    const thirdTurn = retrievalLines(lines).find(
      (line) => (line.turn as number) >= 3 && line.query_messages === 2,
    );
    if (thirdTurn) {
      chosen = { run, lines };
    }
  }
  expect(chosen, 'no adaptive run reached turn 3 with query_messages 2 in three attempts').toBeDefined();
  if (!chosen) return;

  const { run, lines } = chosen;
  const retrievals = retrievalLines(lines);
  for (const line of retrievals) {
    expectRetrievalInvariants(line, config);
  }
  const turnTwo = retrievals.find((line) => line.turn === 2);
  expect(turnTwo, 'the turn-2 retrieval line must be present').toBeDefined();
  expect((turnTwo as LogLine).query_messages).toBe(1);
  const turnThree = retrievals.find((line) => (line.turn as number) >= 3);
  expect(turnThree, 'the turn-3 retrieval line must be present').toBeDefined();
  expect((turnThree as LogLine).query_messages).toBe(2);
  // A seedless query may select nothing (known behaviour); the counts identity and the distance rules still hold.

  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  expect(await viewer.parsedLines()).toEqual(lines);
  await expect(app.alerts.first()).toHaveText(/^(Attack (succeeded|failed)|Unclear)/);
});

/** Covers FR-015 */
test('3. retrieves nothing on a cold adaptive run, even over two turns [FR-015]', async ({ page, api, stub }) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker model for an adaptive run').toBe(true);

  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await expect(priorExperience.toggle).toBeChecked();
  await priorExperience.setPriorExperience(false);
  await expect(priorExperience.toggle).not.toBeChecked();
  await app.selectMode('Adaptive');

  const started: Array<{ run: RunDetail; lines: LogLine[] }> = [];
  for (let attempt = 0; attempt < 3; attempt += 1) {
    stub.setReplies([REFUSAL, CANARY_REPLY]);
    const runId = await runFromUi(app, api, target.id);
    const run = await api.getRun(runId);
    const lines = (await api.getRunLog(run.id)).lines;
    started.push({ run, lines });
    if ((run.turns_used as number) >= 2) {
      break;
    }
  }

  // A one-turn run cannot prove the cold multi-turn path, and every run started must stay cold.
  for (const { run, lines } of started) {
    expect(run.use_prior_experience).toBe(false);
    expect(startLine(lines).use_prior_experience).toBe(false);
    expect(retrievalLines(lines)).toHaveLength(0);
    const writebacks = writebackLines(lines);
    expect(writebacks).toHaveLength(1);
    expect(writebacks[0].written).toBe(true);
  }

  const coldMultiTurn = started.find(({ run }) => (run.turns_used as number) >= 2);
  expect(coldMultiTurn, 'the cold multi-turn path could not be exercised in three attempts').toBeDefined();
  if (!coldMultiTurn) return;
  expect(coldMultiTurn.run.turns_used as number).toBeGreaterThanOrEqual(2);
  expect(coldMultiTurn.lines.filter((line) => line.event === 'turn').length).toBeGreaterThanOrEqual(2);

  const last = started[started.length - 1];
  await app.selectRun(runLabel(last.run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const shown = await viewer.parsedLines();
  expect(shown).toEqual(last.lines);
  expect(retrievalLines(shown)).toHaveLength(0);
  expect(writebackLines(shown)).toHaveLength(1);
});

/** Covers FR-006, FR-007, FR-013, SC-004 */
test('4. merges a single-turn success into its library seed and logs the merge [FR-006, FR-007, FR-013, SC-004]', async ({
  page,
  api,
  stub,
}) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.selectPrompt(SPL_PROMPT);
  await expect(app.modeGroup.getByRole('radio', { name: 'Single-turn' })).toBeChecked();
  await expect(priorExperience.toggle).toBeChecked();

  const runId = await runFromUi(app, api, target.id, 20_000);
  const run = await api.getRun(runId);
  const log = await api.getRunLog(run.id);

  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  expect(run.verdict).toBe('succeeded');
  expect(run.hard_evidence).toBe(true);
  expect(run.memory_written).toBe(true);
  // RunDetail reports turns_used only for adaptive runs (feature 003); the log carries the single turn.
  expect(startLine(log.lines).turn_budget).toBe(1);
  const end = log.lines[log.lines.length - 1];
  expect(end.event).toBe('run.end');
  expect(end.turns_used).toBe(1);
  expect(log.lines.filter((line) => line.event === 'turn')).toHaveLength(1);

  // A single-turn run retrieves nothing, even with prior experience on.
  expect(retrievalLines(log.lines)).toHaveLength(0);

  const writebacks = writebackLines(log.lines);
  expect(writebacks).toHaveLength(1);
  const outcome = writebacks[0];
  expect(outcome.written).toBe(true);
  expect(outcome.pattern_written).toBe(true);
  expect(outcome.pattern_outcome).toBe('merged');
  expect(outcome.pattern_id).toBe('pattern:lib:spl-001');
  expect(outcome.pattern_distance).toBe(0);
  expect(Number.isInteger(outcome.hit_count)).toBe(true);
  expect(outcome.hit_count as number).toBeGreaterThanOrEqual(2);

  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const shown = await viewer.parsedLines();
  expect(shown).toEqual(log.lines);
  expect(retrievalLines(shown)).toHaveLength(0);
  expect(writebackLines(shown)).toHaveLength(1);
});

/** Covers FR-006, FR-007, SC-004 */
test("5. raises the same seed's hit count by one on each identical success [FR-006, FR-007, SC-004]", async ({
  page,
  api,
  stub,
}) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(TEX_FAMILY);
  await app.selectPrompt(TEX_PROMPT);
  await expect(app.modeGroup.getByRole('radio', { name: 'Single-turn' })).toBeChecked();
  await expect(priorExperience.toggle).toBeChecked();

  const firstId = await runFromUi(app, api, target.id, 20_000);
  const first = await api.getRun(firstId);
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  expect(first.verdict).toBe('succeeded');
  expect(first.hard_evidence).toBe(true);
  const firstWritebacks = writebackLines((await api.getRunLog(first.id)).lines);
  expect(firstWritebacks).toHaveLength(1);
  const firstOutcome = firstWritebacks[0];
  expect(firstOutcome.written).toBe(true);
  expect(firstOutcome.pattern_written).toBe(true);
  expect(firstOutcome.pattern_outcome).toBe('merged');
  expect(firstOutcome.pattern_id).toBe('pattern:lib:tex-001');
  expect(firstOutcome.pattern_distance).toBe(0);
  const hitCount = firstOutcome.hit_count as number;
  expect(Number.isInteger(hitCount)).toBe(true);
  expect(hitCount).toBeGreaterThanOrEqual(2);

  const secondId = await runFromUi(app, api, target.id, 20_000);
  const second = await api.getRun(secondId);
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  expect(second.verdict).toBe('succeeded');
  expect(second.hard_evidence).toBe(true);
  const secondLog = await api.getRunLog(second.id);
  const secondWritebacks = writebackLines(secondLog.lines);
  expect(secondWritebacks).toHaveLength(1);
  const secondOutcome = secondWritebacks[0];
  expect(secondOutcome.written).toBe(true);
  expect(secondOutcome.pattern_written).toBe(true);
  expect(secondOutcome.pattern_outcome).toBe('merged');
  expect(secondOutcome.pattern_id).toBe('pattern:lib:tex-001');
  expect(secondOutcome.pattern_distance).toBe(0);
  expect(secondOutcome.hit_count).toBe(hitCount + 1);
  expect(secondOutcome.pattern_id as string).not.toMatch(/^pattern:run:/);

  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const shown = await viewer.parsedLines();
  expect(shown).toEqual(secondLog.lines);
  const writtenBack = writebackLines(shown);
  expect(writtenBack).toHaveLength(1);
  expect(writtenBack[0].run_id).toBe(second.id);
});

/** Covers FR-008, FR-013 */
test('6. records no pattern for a run that did not succeed [FR-008, FR-013]', async ({ page, api, stub }) => {
  const target = await api.createTarget(uniqueName(), stub);
  await stub.close();
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await expect(app.modeGroup.getByRole('radio', { name: 'Single-turn' })).toBeChecked();

  const runId = await runFromUi(app, api, target.id, 20_000);
  const run = await api.getRun(runId);
  const log = await api.getRunLog(run.id);

  await expect(app.alerts.first()).toHaveText("Kestrel couldn't connect to this URL.");
  expect(run.verdict).toBeNull();
  expect(run.failure_step).toBe('unreachable');
  expect(run.memory_written).toBe(true);

  expect(retrievalLines(log.lines)).toHaveLength(0);
  const writebacks = writebackLines(log.lines);
  expect(writebacks).toHaveLength(1);
  const outcome = writebacks[0];
  expect(outcome.written).toBe(true);
  expect(outcome.pattern_written).toBe(false);
  for (const field of ['pattern_outcome', 'pattern_id', 'hit_count', 'pattern_distance']) {
    expect(outcome).not.toHaveProperty(field);
  }

  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const shown = await viewer.parsedLines();
  expect(shown).toEqual(log.lines);
  expect(retrievalLines(shown)).toHaveLength(0);
  expect(writebackLines(shown)).toHaveLength(1);
});

/** Covers FR-012, FR-015, SC-009 */
test('7. reports the floor and threshold in /api/config and defaults the prior-experience toggle on [FR-012, FR-015]', async ({
  page,
  api,
}) => {
  const config = await api.config();
  expect(config.experience.pattern_k).toBe(5);
  expect(Number.isInteger(config.experience.memory_cap)).toBe(true);
  expect(config.experience.memory_cap).toBeGreaterThan(0);
  expect(config.experience.distance_floor).toBe(1.8);
  expect(config.experience.dedupe_threshold).toBe(0.15);
  expect(config.experience.use_prior_experience_default).toBe(true);

  const app = new KestrelApp(page);
  const priorExperience = new PriorExperienceControl(page);
  await app.goto();
  await expect(priorExperience.toggle).toBeVisible();
  await expect(priorExperience.toggle).toBeEnabled();
  await expect(priorExperience.toggle).toBeChecked();
  await expect(page.getByText(PRIOR_EXPERIENCE_CAPTION, { exact: true })).toBeVisible();

  await priorExperience.setPriorExperience(false);
  await expect(priorExperience.toggle).not.toBeChecked();
  await priorExperience.setPriorExperience(true);
  await expect(priorExperience.toggle).toBeChecked();
  expect(await priorExperience.isOn()).toBe(true);
});

/** Covers FR-017, FR-013, SC-007 */
test('8. keeps target text and secrets off the retrieval and write-back lines [FR-017, SC-007]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker model for an adaptive run').toBe(true);

  const secret = `QA-HEADER-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const replyMarker = `QA-REPLY-${Date.now()}`;
  const name = uniqueName();
  const target = await api.createTarget(name, stub, {
    canaries: [CANARY],
    headers: [{ name: 'X-API-Key', value: secret }],
  });
  const prompts = await api.attackPrompts('system_prompt_leak');
  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  const priorExperience = new PriorExperienceControl(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.selectPrompt(SPL_PROMPT);
  await app.selectMode('Adaptive');
  await expect(priorExperience.toggle).toBeChecked();

  let chosen: { run: RunDetail; lines: LogLine[] } | undefined;
  for (let attempt = 0; attempt < 3 && !chosen; attempt += 1) {
    stub.setReplies([REFUSAL, `${CANARY_REPLY} ${replyMarker}`]);
    const runId = await runFromUi(app, api, target.id);
    const run = await api.getRun(runId);
    const lines = (await api.getRunLog(run.id)).lines;
    if (retrievalLines(lines).length > 0) {
      chosen = { run, lines };
    }
  }
  expect(chosen, 'no adaptive run carried a memory.retrieval line in three attempts').toBeDefined();
  if (!chosen) return;

  const { run, lines } = chosen;
  const forbidden: Array<[string, string]> = [
    ['auth header value', secret],
    ['stub URL', stub.url],
    ['stub host and port', new URL(stub.url).host],
    ['target display name', name],
    ['attack seed text', run.prompt_text],
  ];
  for (const turn of run.turns) {
    forbidden.push([`attacker message for turn ${turn.position}`, turn.attacker_message]);
    if (turn.reply_text) {
      forbidden.push([`reply text for turn ${turn.position}`, turn.reply_text]);
    }
    if (turn.judge_progress) {
      forbidden.push([`judge progress for turn ${turn.position}`, turn.judge_progress]);
    }
  }
  if (run.reply_text) {
    forbidden.push(['reply text', run.reply_text]);
  }
  if (run.reason) {
    forbidden.push(['judge reason', run.reason]);
  }
  for (const prompt of prompts) {
    forbidden.push([`library prompt text ${prompt.id}`, prompt.text]);
  }

  const endpointText = await api.getRunLogText(run.id);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const rawText = await viewer.rawText();
  const shown = await viewer.parsedLines();
  expect(shown).toEqual(lines);

  const retrievals = retrievalLines(lines);
  const writebacks = writebackLines(lines);
  expect(retrievals.length).toBeGreaterThan(0);
  expect(writebacks).toHaveLength(1);

  for (const [label, value] of forbidden) {
    expect(value.length, `the ${label} is empty`).toBeGreaterThan(0);
    expect(endpointText.includes(value), `the log endpoint must not carry the ${label}`).toBe(false);
    expect(rawText.includes(value), `the log viewer must not carry the ${label}`).toBe(false);
  }

  for (const line of retrievals) {
    for (const id of line.pattern_ids as string[]) {
      expect(id).toMatch(/^pattern:(lib|run):[A-Za-z0-9_-]+$/);
    }
  }
  expect(writebacks[0].pattern_written).toBe(true);
  expect(writebacks[0].pattern_id as string).toMatch(/^pattern:(lib|run):[A-Za-z0-9_-]+$/);

  for (const line of [...retrievals, ...writebacks]) {
    const serialised = JSON.stringify(line);
    for (const [, value] of forbidden) {
      expect(serialised.includes(value), `a new log line must not carry ${value}`).toBe(false);
    }
  }
});
