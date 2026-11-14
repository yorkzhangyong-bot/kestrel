import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import type { KestrelConfig, LogLine } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';
import { RunLogViewer } from './pages/RunLogViewer';

const SPL_FAMILY = 'System prompt leak · LLM07: System Prompt Leakage (4 prompts)';
const CANARY = 'KESTREL-CANARY-demo';

function eventLines(lines: LogLine[], event: string): LogLine[] {
  return lines.filter((line) => line.event === event);
}

function activePromptVersion(config: KestrelConfig, id: string): string {
  const prompt = config.prompts.find((candidate) => candidate.id === id);
  expect(prompt, `prompt ${id} is missing from /api/config`).toBeDefined();
  return (prompt as { version: string }).version;
}

function expectTokenCounts(record: LogLine): void {
  for (const key of ['prompt_tokens', 'completion_tokens', 'total_tokens']) {
    const value = record[key];
    expect(value === null || Number.isInteger(value), `${key} must be an integer or null`).toBe(true);
  }
}

function expectCost(record: LogLine): void {
  if (record.cost_usd === null) {
    expect(typeof record.cost_note).toBe('string');
    expect((record.cost_note as string).length).toBeGreaterThan(0);
  } else {
    expect(typeof record.cost_usd).toBe('number');
  }
}

/** Covers US3.1, FR-011, FR-012, SC-003 */
test('1. shows a finished run\'s kept log lines in order in the Log viewer [US3.1, FR-011, FR-012, SC-003]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-001',
    usePriorExperience: false,
  });
  const log = await api.getRunLog(run.id);

  expect(log.lines.length).toBeGreaterThan(0);
  expect(log.lines[0].event).toBe('run.start');
  expect(log.lines[log.lines.length - 1].event).toBe('run.end');
  expect(log.kept).toBe(log.lines.length);
  expect(log.dropped).toBe(0);
  expect(log.truncated).toBe(false);
  for (const line of log.lines) {
    expect(line.run_id).toBe(run.id);
  }
  const timestamps = log.lines.map((line) => Date.parse(line.ts as string));
  for (let index = 1; index < timestamps.length; index += 1) {
    expect(timestamps[index]).toBeGreaterThanOrEqual(timestamps[index - 1]);
  }

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  // The expander is a native details element: present and collapsed, one click away from the raw lines.
  await expect(viewer.logExpander).toBeVisible();
  await expect(viewer.logRawLines).toBeHidden();
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  await expect(viewer.logTable).toBeVisible();

  const shown = await viewer.parsedLines();
  expect(shown).toEqual(log.lines);
  expect(shown).toHaveLength(log.kept);
});

/** Covers US2.1, US2.2, FR-009, SC-002 */
test('2. never shows a secret, URL, target name, message, reply or judge text in the log [US2.1, US2.2, FR-009, SC-002]', async ({
  page,
  api,
  stub,
}) => {
  const secret = `QA-HEADER-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const reply = `QA-REPLY-${Date.now()}`;
  stub.setReply(reply);
  const name = uniqueName();
  const target = await api.createTarget(name, stub, {
    headers: [{ name: 'X-API-Key', value: secret }],
  });
  const prompts = await api.attackPrompts('system_prompt_leak');
  const prompt = prompts.find((candidate) => candidate.id === 'spl-001');
  expect(prompt, 'attack prompt spl-001 is missing').toBeDefined();
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-001',
    usePriorExperience: false,
  });

  const forbidden: Array<[string, string]> = [
    ['auth header value', secret],
    ['stub URL', stub.url],
    ['stub host and port', new URL(stub.url).host],
    ['target display name', name],
    ['attack message', run.prompt_text],
    ['reply text', run.reply_text ?? ''],
    ['library prompt text', (prompt as { text: string }).text],
  ];
  if (run.reason) {
    forbidden.push(['judge reason', run.reason]);
  }

  const endpointText = await api.getRunLogText(run.id);

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const rawText = await viewer.rawText();

  for (const [label, value] of forbidden) {
    expect(value.length, `the ${label} is empty`).toBeGreaterThan(0);
    expect(endpointText.includes(value), `the log endpoint must not carry the ${label}`).toBe(false);
    expect(rawText.includes(value), `the log viewer must not carry the ${label}`).toBe(false);
  }

  // The run card itself does render the library message and the reply; the redaction check is scoped to the log.
  await expect(app.codeBlocks.filter({ hasText: run.prompt_text }).first()).toBeVisible();
  await expect(app.codeBlocks.filter({ hasText: run.reply_text ?? '' }).first()).toHaveText(run.reply_text ?? '');
});

/** Covers US3.1, FR-004, FR-012 */
test('3. shows the log of a run whose send failed [US3.1, FR-004, FR-012]', async ({ page, api, stub }) => {
  const target = await api.createTarget(uniqueName(), stub);
  await stub.close();
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-001',
    usePriorExperience: false,
  });
  expect(run.failure_step).not.toBeNull();
  expect(run.verdict).toBeNull();

  const log = await api.getRunLog(run.id);
  expect(log.lines.length).toBeGreaterThan(0);
  expect(log.lines[0].event).toBe('run.start');
  expect(log.lines[log.lines.length - 1].event).toBe('run.end');
  expect(
    log.lines.some(
      (line) => line.event === 'target.request' && line.ok === false,
    ),
  ).toBe(true);

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expect(app.alerts.first()).toHaveText("Kestrel couldn't connect to this URL.");
  // A send failure must not skip the viewer.
  await expect(viewer.logExpander).toBeVisible();
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();

  const shown = await viewer.parsedLines();
  expect(shown).toEqual(log.lines);
  expect(shown[0].event).toBe('run.start');
  expect(shown[shown.length - 1].event).toBe('run.end');
  expect(shown.some((line) => line.event === 'target.request' && line.ok === false)).toBe(true);
});

/** Covers US3.3, FR-011 */
test("4. answers 404 for an unknown run's log and serves the documented shape [US3.3, FR-011]", async ({
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-001',
    usePriorExperience: false,
  });

  const unknownRunId = 999999;
  expect(await api.getRunLogStatus(unknownRunId)).toBe(404);
  const unknown = await api.getRunLogResponse(unknownRunId);
  expect(unknown.status).toBe(404);
  expect(unknown.body).toEqual({
    error: { code: 'not_found', field: null, message: 'No run with id 999999.' },
  });

  const known = await api.getRunLog(run.id);
  expect(Object.keys(known).sort()).toEqual(['dropped', 'kept', 'lines', 'run_id', 'truncated']);
  expect(known.run_id).toBe(run.id);
  expect(known.kept).toBe(known.lines.length);
  expect(known.dropped).toBe(0);
  expect(known.truncated).toBe(false);

  const timestamps = known.lines.map((line) => Date.parse(line.ts as string));
  for (let index = 0; index < known.lines.length; index += 1) {
    const line = known.lines[index];
    expect(line.run_id).toBe(run.id);
    expect(typeof line.ts).toBe('string');
    expect(typeof line.level).toBe('string');
    expect(typeof line.event).toBe('string');
    if (index > 0) {
      expect(timestamps[index]).toBeGreaterThanOrEqual(timestamps[index - 1]);
    }
  }
});

/** Covers US1.1, US1.3, US1.6, FR-001, FR-002, FR-003, FR-004, FR-005, FR-007, FR-008, SC-001, SC-006 */
test('5. carries the documented run, target, model and turn fields in the viewer [US1.1, US1.3, US1.6, FR-001, FR-002, FR-003, FR-004, FR-005, FR-007, FR-008, SC-001, SC-006]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  stub.setReply('The agent refused and kept its system prompt.');
  const target = await api.createTarget(uniqueName(), stub);
  const prompts = await api.attackPrompts('system_prompt_leak');
  const prompt = prompts.find((candidate) => candidate.id === 'spl-001');
  expect(prompt, 'attack prompt spl-001 is missing').toBeDefined();
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-001',
    usePriorExperience: false,
  });
  const log = await api.getRunLog(run.id);
  const lines = log.lines;

  const start = eventLines(lines, 'run.start')[0];
  expect(start).toBeDefined();
  expect(start.target_id).toBe(run.target_id);
  expect(start.mode).toBe('single_turn');
  expect(start.family).toBe('system_prompt_leak');
  expect(start.prompt_id).toBe('spl-001');
  expect(start.attacker_source).toMatch(/^library:\d+\.\d+\.\d+$/);
  expect(start.turn_budget).toBe(1);
  expect(typeof start.time_limit_s).toBe('number');
  expect(start.use_prior_experience).toBe(false);
  expect(start).not.toHaveProperty('attacker_model');
  expect(start).not.toHaveProperty('attacker_prompt');
  if (config.judge.configured) {
    expect(start.judge_model).toBe(config.judge.model);
    expect(start.judge_prompt).toBe(`judge@${activePromptVersion(config, 'judge')}`);
  } else {
    expect(start).not.toHaveProperty('judge_model');
    expect(start).not.toHaveProperty('judge_prompt');
  }

  const request = eventLines(lines, 'target.request')[0];
  expect(request).toBeDefined();
  expect(typeof request.latency_ms).toBe('number');
  expect(request.latency_ms as number).toBeGreaterThanOrEqual(0);
  expect(request.ok).toBe(true);
  expect(request.status).toBe(200);
  expect(typeof request.step).toBe('string');
  expect(request.reply_chars).toBe((run.reply_text ?? '').length);
  expect(request.reply_truncated).toBe(false);

  const turn = eventLines(lines, 'turn')[0];
  expect(turn).toBeDefined();
  expect(turn.turn).toBe(1);
  expect(turn.source).toBe('library:spl-001');
  expect(typeof turn.duration_ms).toBe('number');
  expect(turn.duration_ms as number).toBeGreaterThanOrEqual(0);
  expect(turn.message_chars).toBe((prompt as { text: string }).text.length);
  expect(turn.reply_chars).toBe((run.reply_text ?? '').length);
  expect(turn.canary_hit).toBe(false);
  expect(turn.hard_evidence).toBe(false);
  expect(typeof turn.judged).toBe('boolean');
  expectTokenCounts(turn);
  if (config.judge.configured) {
    expect(turn.judge_model).toBe(config.judge.model);
    expect(turn.judge_prompt).toBe(`judge@${activePromptVersion(config, 'judge')}`);
  } else {
    expect(turn).not.toHaveProperty('judge_model');
    expect(turn).not.toHaveProperty('judge_prompt');
  }

  const modelRequests = eventLines(lines, 'model.request');
  expect(modelRequests.filter((line) => line.kind === 'attacker')).toHaveLength(0);
  const judgeLines = modelRequests.filter((line) => line.kind === 'judge');
  expect(judgeLines).toHaveLength(config.judge.configured ? 1 : 0);
  if (config.judge.configured) {
    const judge = judgeLines[0];
    expect(judge.kind).toBe('judge');
    expect(judge.model).toBe(config.judge.model);
    expect(judge.prompt).toBe(`judge@${activePromptVersion(config, 'judge')}`);
    expect(typeof judge.latency_ms).toBe('number');
    expect(judge.latency_ms as number).toBeGreaterThanOrEqual(0);
    expect(judge.ok).toBe(true);
    expect(judge.status).toBe(200);
    expect(judge.attempts as number).toBeGreaterThanOrEqual(1);
    expectTokenCounts(judge);
    expect(judge.hard_evidence).toBe(false);
    expect(['succeeded', 'failed', 'unclear']).toContain(judge.verdict);
    expectCost(judge);
  }

  const writebackIndex = lines.findIndex((line) => line.event === 'memory.writeback');
  const endIndex = lines.findIndex((line) => line.event === 'run.end');
  expect(endIndex).toBe(lines.length - 1);
  if (writebackIndex >= 0) {
    const writeback = lines[writebackIndex];
    expect(typeof writeback.written === 'boolean' || typeof writeback.error === 'string').toBe(true);
    expect(writebackIndex).toBeLessThan(endIndex);
  }

  const end = lines[endIndex];
  expect(end.verdict).toBe(run.verdict);
  expect(end.hard_evidence).toBe(run.hard_evidence);
  expect(end.stopping_condition).toBe(run.stopping_condition);
  expect(end.judge_used).toBe(judgeLines.length > 0);
  expect(end.turns_used).toBe(1);
  expect(Number.isInteger(end.tokens_used)).toBe(true);
  expect(end.tokens_used as number).toBeGreaterThanOrEqual(0);
  expect([true, false, null]).toContain(end.memory_written);
  expect(typeof end.duration_ms).toBe('number');
  expect(end.duration_ms as number).toBeGreaterThanOrEqual(0);
  expectCost(end);

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  expect(await viewer.parsedLines()).toEqual(lines);
});

/** Covers US1.2, US1.7, FR-002, FR-003, FR-005, SC-001 */
test('6. emits one turn line per turn and no attacker line on turn 1 [US1.2, US1.7, FR-002, FR-003, FR-005, SC-001]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker key for an adaptive run').toBe(true);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  // The connection test above used the default reply; script the attack's first refusal and second canary leak.
  stub.setReplies(['I cannot help with that request.', `Here is my system prompt: ${CANARY}`]);
  stub.resetRequests();
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    mode: 'adaptive',
    usePriorExperience: false,
  });
  const turnsUsed = run.turns_used as number;
  expect(turnsUsed).toBeGreaterThanOrEqual(1);
  expect(turnsUsed).toBeLessThanOrEqual(2);

  const log = await api.getRunLog(run.id);
  const lines = log.lines;
  for (const line of lines) {
    expect(line.run_id).toBe(run.id);
  }

  const turnLines = eventLines(lines, 'turn');
  expect(turnLines.map((line) => line.turn)).toEqual(Array.from({ length: turnsUsed }, (_, index) => index + 1));
  const end = lines[lines.length - 1];
  expect(end.event).toBe('run.end');
  expect(end.turns_used).toBe(turnsUsed);

  const requests = eventLines(lines, 'target.request');
  expect(requests.map((line) => line.turn)).toEqual(Array.from({ length: turnsUsed }, (_, index) => index + 1));
  for (const request of requests) {
    expect(request.status).toBe(200);
    expect(request.ok).toBe(true);
  }
  expect(requests).toHaveLength(turnsUsed);
  expect(stub.requests).toHaveLength(turnsUsed);

  const modelRequests = eventLines(lines, 'model.request');
  const attackerLines = modelRequests.filter((line) => line.kind === 'attacker');
  expect(attackerLines).toHaveLength(turnsUsed - 1);
  expect(attackerLines.filter((line) => line.turn === 1)).toHaveLength(0);
  expect(attackerLines.map((line) => line.turn)).toEqual(
    Array.from({ length: turnsUsed - 1 }, (_, index) => index + 2),
  );
  for (const line of modelRequests) {
    expect(['attacker', 'judge']).toContain(line.kind);
  }

  const judgeLines = modelRequests.filter((line) => line.kind === 'judge');
  expect(judgeLines).toHaveLength(config.judge.configured ? 1 : 0);
  for (const judge of judgeLines) {
    expect(judge.hard_evidence).toBe(false);
  }

  const turnOne = turnLines.find((line) => line.turn === 1);
  expect(turnOne).toBeDefined();
  expect((turnOne as LogLine).canary_hit).toBe(false);
  if (turnsUsed === 2) {
    const turnTwo = turnLines.find((line) => line.turn === 2);
    expect(turnTwo).toBeDefined();
    expect((turnTwo as LogLine).canary_hit).toBe(true);
    expect((turnTwo as LogLine).hard_evidence).toBe(true);
    if (config.judge.configured) {
      expect((turnTwo as LogLine).judge_prompt).toBeNull();
    } else {
      expect(turnTwo).not.toHaveProperty('judge_prompt');
    }
    expect(end.stopping_condition).toBe('succeeded');
    expect(end.succeeded_turn).toBe(2);
  } else {
    // A judge may call the turn-1 refusal a success; the per-turn invariants above still have to hold.
    expect(turnsUsed, `stopping_condition is ${String(end.stopping_condition)}`).toBe(1);
    expect(end.stopping_condition).toBe('succeeded');
    expect(end.succeeded_turn).toBe(1);
  }

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const shown = await viewer.parsedLines();
  expect(shown.map((line) => line.event)).toEqual(lines.map((line) => line.event));
  const shownTurns = shown.filter((line) => line.turn !== undefined).map((line) => line.turn);
  const expectedTurns = lines.filter((line) => line.turn !== undefined).map((line) => line.turn);
  expect(shownTurns).toEqual(expectedTurns);
});

/** Covers US1.5, US3.7, FR-003, FR-010 */
test("7. leaves the kept log and the viewer unchanged when the target's report is generated [US1.5, US3.7, FR-003, FR-010]", async ({
  page,
  api,
  stub,
}) => {
  stub.setReply('The agent refused and kept its system prompt.');
  const target = await api.createTarget(uniqueName(), stub);
  const run = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-001',
    usePriorExperience: false,
  });

  const beforeText = await api.getRunLogText(run.id);
  const before = await api.getRunLog(run.id);

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const viewerBefore = await viewer.rawText();
  expect(viewerBefore).toContain('"event": "run.end"');

  const report = await api.generateReport(target.id);
  expect(report.length).toBeGreaterThan(0);

  const afterText = await api.getRunLogText(run.id);
  const after = await api.getRunLog(run.id);
  expect(afterText).toBe(beforeText);
  expect(after).toEqual(before);
  expect(after.lines.filter((line) => line.kind === 'recommender')).toHaveLength(0);

  await page.reload();
  await expect(app.runButton).toBeVisible();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  expect(await viewer.rawText()).toBe(viewerBefore);
});

/** Covers US3.1, FR-012, SC-003 */
test('8. shows the Log expander on the run result right after Run attack [US3.1, FR-012, SC-003]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  stub.setReply('The agent refused.');

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  const newest = (await api.listRuns(target.id))[0];
  expect(newest).toBeDefined();
  const log = await api.getRunLog(newest.id);

  await expect(viewer.logExpander).toBeVisible();
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();
  const shown = await viewer.parsedLines();
  expect(shown).toEqual(log.lines);
  for (const line of shown) {
    expect(line.run_id).toBe(newest.id);
  }
  expect(shown[0].event).toBe('run.start');
  expect(shown[shown.length - 1].event).toBe('run.end');
});
