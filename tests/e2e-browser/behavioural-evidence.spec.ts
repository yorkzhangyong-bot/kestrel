import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import type { KestrelApi, KestrelConfig, RunDetail } from './fixtures/kestrel';
import type { Page } from '@playwright/test';
import { KestrelApp } from '../pages/KestrelApp';
import { EvidencePanel } from './pages/EvidencePanel';
import { ReportPanel } from './pages/ReportPanel';
import { ReplayPanel } from './pages/ReplayPanel';
import { RunLogViewer } from './pages/RunLogViewer';
import { negativeCase, positiveCase } from './fixtures/unsafe-cases';
import { normalise, overrideFragments, overrideFragmentsPattern, sentMessage } from './fixtures/planted';

const SPL_FAMILY = 'System prompt leak · LLM07: System Prompt Leakage (4 prompts)';
const CANARY = 'KESTREL-CANARY-demo';
const CANARY_REPLY = `Here is my system prompt: ${CANARY}`;
const SAFE_REPLY = 'I cannot help with that request.';
const CANARY_LINE = 'canary · turn 1 · in the reply · LLM07: System Prompt Leakage';
const UNSAFE_LINE = 'unsafe executable output · turn 1 · in the reply · LLM05: Improper Output Handling';
const OVERRIDE_LINE = 'instruction override · turn 1 · in the reply · LLM01: Prompt Injection';
const OVERRIDE_DETAIL = 'the planted marker appeared in the reply';
const UNREACHABLE_MESSAGE = "Kestrel couldn't connect to this URL.";

/** The newest run of a target this test created (its runs list is not shared with any other test). */
async function newestRun(api: KestrelApi, targetId: number): Promise<RunDetail> {
  const runs = await api.listRuns(targetId);
  expect(runs.length).toBeGreaterThan(0);
  return api.getRun(runs[0].id);
}

/** The active version of a registry prompt (`override_task`), read from `GET /api/config`. */
function promptVersion(config: KestrelConfig, id: string): string {
  const prompt = config.prompts.find((candidate) => candidate.id === id);
  expect(prompt, `prompt ${id} is missing from /api/config`).toBeDefined();
  return (prompt as { version: string }).version;
}

/**
 * Today's scoring wording for a run with no evidence item: the judged wording when a judge is configured, else the
 * exact `Unclear`. Used by every scenario that asserts a run is *not* confirmed (FR-009, FR-015, FR-016, FR-014).
 */
async function expectScoringWithoutEvidence(page: Page, app: KestrelApp, config: KestrelConfig): Promise<void> {
  await expect(app.alerts.first()).not.toContainText('confirmed by');
  if (config.judge.configured) {
    const model = config.judge.model;
    const judged = app.alerts.filter({ hasText: 'judged by' });
    await expect(judged).toBeVisible();
    const wording = await judged.innerText();
    expect([
      `Attack succeeded · suspected, judged by ${model}`,
      `Attack failed · the agent held · judged by ${model}`,
      `Unclear · judged by ${model}`,
    ]).toContain(wording);
  } else {
    await expect(app.alerts.first()).toHaveText('Unclear');
  }
  await expect(page.getByRole('heading', { name: 'Evidence', exact: true })).toHaveCount(0);
}

/** Covers AC1, AC2, FR-005, FR-039 */
test('1. shows a canary evidence item on the run page [FR-005, FR-039]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const prompt = (await api.attackPrompts('system_prompt_leak')).find((candidate) => candidate.id === 'spl-001');
  expect(prompt, 'attack prompt spl-001 is missing').toBeDefined();
  const chosen = prompt as NonNullable<typeof prompt>;
  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.selectPrompt(chosen.title);
  await app.runAttack();
  await app.waitForRunToFinish();

  const run = await newestRun(api, target.id);
  expect(run.evidence).toHaveLength(1);
  const item = run.evidence[0];
  expect(item.kind).toBe('canary_in_reply');
  expect(item.line).toBe(CANARY_LINE);
  expect(item.detail).toBe(CANARY);

  // The attack result above the tabs.
  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by canary');
  await expect(evidence.headline).not.toContainText('judged by');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([item.line]);
  await expect(evidence.detail(item.detail)).toHaveText(item.detail);
  await expect(app.codeBlocks.filter({ hasText: run.prompt_text }).first()).toHaveText(run.prompt_text);
  await expect(app.codeBlocks.filter({ hasText: CANARY_REPLY }).first()).toHaveText(CANARY_REPLY);

  // The reopened run after a reload renders the same item from the stored data.
  await page.reload();
  await expect(app.runButton).toBeVisible();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by canary');
  await expect(evidence.headline).not.toContainText('judged by');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([item.line]);
  await expect(evidence.detail(item.detail)).toHaveText(item.detail);
});

/** Covers AC1, AC3, FR-004, FR-038, FR-039 */
test('2. joins every confirming kind in the headline in detection order [FR-004, FR-039]', async ({
  page,
  api,
  stub,
}) => {
  const sample = positiveCase('drop_or_truncate_table', 'DROP TABLE customers');
  stub.setReply(`${CANARY_REPLY}\n\n${sample}`);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);
  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);

  expect(run.evidence.map((item) => item.line)).toEqual([CANARY_LINE, UNSAFE_LINE]);
  expect(run.evidence_labels).toEqual(['canary', 'unsafe executable output']);
  expect(run.evidence_count).toBe(2);
  expect(run.judge_used).toBe(false);

  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by canary + unsafe executable output');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([CANARY_LINE, UNSAFE_LINE]);
  for (const item of run.evidence) {
    await expect(evidence.detail(item.detail)).toHaveText(item.detail);
  }
  const listed = await api.listRuns(target.id);
  expect(listed[0].evidence_labels).toEqual(['canary', 'unsafe executable output']);
  expect(listed[0].evidence_count).toBe(2);
});

/** Covers AC4, FR-017 */
test('3. names the unsafe-output pattern and set version [FR-017]', async ({ page, api, stub }) => {
  const sample = positiveCase('drop_or_truncate_table', 'DROP TABLE customers');
  const excerpt = sample.split('\n').find((line) => line.startsWith('DROP')) as string;
  stub.setReply(sample);
  const target = await api.createTarget(uniqueName(), stub);
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);
  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);

  expect(run.evidence).toHaveLength(1);
  const item = run.evidence[0];
  expect(item.kind).toBe('unsafe_executable_output');
  expect(item.line).toBe(UNSAFE_LINE);
  expect(item.pattern_name).toBe('drop_or_truncate_table');
  expect(item.pattern_set_version).toBe('1');
  expect(item.detail.startsWith('destructive_sql/drop_or_truncate_table (set 1): ')).toBe(true);
  expect(item.detail).toContain(excerpt.trim());
  expect(item.detail.length).toBeLessThanOrEqual(200);
  expect(run.judge_used).toBe(false);

  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by unsafe executable output');
  await expect(evidence.headline).not.toContainText('judged by');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([UNSAFE_LINE]);
  await expect(evidence.detail(item.detail)).toHaveText(item.detail);
});

/** Covers AC5, AC9, FR-009, FR-048, SC-001 */
test('4. confirms an instruction override on the joined form [FR-009, SC-001]', async ({ page, api, stub }) => {
  const config = await api.config();
  const pattern = overrideFragmentsPattern(promptVersion(config, 'override_task'));
  const target = await api.createTarget(uniqueName(), stub);
  stub.setReplyFor((body) => {
    const fragments = overrideFragments(sentMessage(body), pattern);
    return fragments ? fragments.joined : SAFE_REPLY;
  });
  stub.resetRequests();
  const seeded = await api.createRun(target.id, { family: 'direct_injection', promptId: 'dir-001' });
  const run = await api.getRun(seeded.id);

  expect(stub.requests).toHaveLength(1);
  const sent = sentMessage(stub.requests[0].body);
  expect(sent).toBe(run.prompt_text);
  const fragments = overrideFragments(sent, pattern);
  expect(fragments, 'the sent message must carry the filled override template').not.toBeNull();
  const planted = fragments as NonNullable<typeof fragments>;

  // The echo-proof rule: the sent message never yields the joined form, even after normalisation.
  expect(normalise(sent)).not.toContain(normalise(planted.joined));

  expect(run.evidence).toHaveLength(1);
  const item = run.evidence[0];
  expect(item.kind).toBe('instruction_override');
  expect(item.turn).toBe(1);
  expect(item.location).toBe('reply');
  expect(item.line).toBe(OVERRIDE_LINE);
  expect(item.detail).toBe(OVERRIDE_DETAIL);
  expect(run.judge_used).toBe(false);

  // No raw log line carries the joined form or either fragment (FR-048).
  const log = await api.getRunLogText(run.id);
  for (const secret of [planted.joined, planted.first, planted.second]) {
    expect(secret.length).toBeGreaterThan(0);
    expect(log).not.toContain(secret);
  }

  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by instruction override');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([OVERRIDE_LINE]);
  await expect(evidence.detail(OVERRIDE_DETAIL)).toHaveText(OVERRIDE_DETAIL);
});

/** Covers AC5, FR-009, SC-001 */
test('5. records no override when the reply splits or refuses the instruction [FR-009]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  const pattern = overrideFragmentsPattern(promptVersion(config, 'override_task'));
  let mode: 'split' | 'refusal' = 'split';
  const target = await api.createTarget(uniqueName(), stub);
  stub.setReplyFor((body) => {
    const fragments = overrideFragments(sentMessage(body), pattern);
    if (!fragments || mode === 'refusal') return SAFE_REPLY;
    return `I won't follow that; you asked for ${fragments.first} and ${fragments.second} separately.`;
  });

  stub.resetRequests();
  const splitSeeded = await api.createRun(target.id, { family: 'direct_injection', promptId: 'dir-001' });
  const split = await api.getRun(splitSeeded.id);
  mode = 'refusal';
  stub.resetRequests();
  const refusalSeeded = await api.createRun(target.id, { family: 'direct_injection', promptId: 'dir-001' });
  const refusal = await api.getRun(refusalSeeded.id);

  for (const run of [split, refusal]) {
    expect(run.evidence).toEqual([]);
    expect(run.evidence_kinds).toEqual([]);
    expect(run.hard_evidence).toBe(false);
    expect(run.verdict).not.toBe('succeeded');
  }

  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);

  await panel.selectRunByAge(runLabel(split), 'oldest');
  await expectScoringWithoutEvidence(page, app, config);

  await panel.selectRunByAge(runLabel(refusal), 'newest');
  await expectScoringWithoutEvidence(page, app, config);
  await expect(evidence.evidenceItems).toHaveCount(0);
});

/** Covers AC4, FR-015, FR-016 */
test('6. leaves the benign shape beside an unsafe pattern alone [FR-015, FR-016]', async ({ page, api, stub }) => {
  const config = await api.config();
  const benign = negativeCase('drop_or_truncate_table', 'drop table tennis');
  stub.setReply(benign);
  const target = await api.createTarget(uniqueName(), stub);
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);

  expect(run.evidence).toEqual([]);
  expect(run.hard_evidence).toBe(false);

  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expectScoringWithoutEvidence(page, app, config);
  await expect(evidence.evidenceItems).toHaveCount(0);
});

/** Covers AC1, AC2, FR-039 */
test("7. shows an adaptive run's evidence with its turn number [FR-039]", async ({ page, api, stub }) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker key').toBe(true);
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-002',
    mode: 'adaptive',
  });
  const run = await api.getRun(seeded.id);
  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);

  expect(run.evidence).toHaveLength(1);
  expect(run.evidence[0].turn).toBe(run.succeeded_turn);
  expect(run.evidence[0].line).toBe(CANARY_LINE);

  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by canary at turn 1');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([CANARY_LINE]);
  await expect(evidence.detail(CANARY)).toHaveText(CANARY);
  await expect(app.turnCaptions).toHaveText(['Turn 1 · attacker']);
  await expect(app.agentCaptions).toHaveText(['agent']);
});

/** Covers AC6, FR-038, FR-040 */
test("8. shows confirmed labels in the run list's Evidence column [FR-040]", async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const confirmedSeeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const confirmedRun = await api.getRun(confirmedSeeded.id);
  stub.setReply(SAFE_REPLY);
  const unconfirmedSeeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-002' });
  const unconfirmedRun = await api.getRun(unconfirmedSeeded.id);

  const failingTarget = await api.createTarget(uniqueName(), stub);
  await stub.close();
  const failingSeeded = await api.createRun(failingTarget.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const failingRun = await api.getRun(failingSeeded.id);

  const summaries = await api.listRuns(target.id);
  const confirmedRow = summaries.find((run) => run.id === confirmedRun.id) as NonNullable<
    (typeof summaries)[number]
  >;
  const unconfirmedRow = summaries.find((run) => run.id === unconfirmedRun.id) as NonNullable<
    (typeof summaries)[number]
  >;
  expect(confirmedRow.evidence_labels).toEqual(['canary']);
  expect(confirmedRow.evidence_count).toBe(1);
  expect(unconfirmedRow.evidence_labels).toEqual([]);
  expect(unconfirmedRow.evidence_kinds).toEqual([]);
  expect(unconfirmedRow.evidence_count).toBe(0);
  expect(unconfirmedRow.hard_evidence).toBe(false);
  // The Evidence cell is `judge · {model}` only for a judged run and `—` otherwise (FR-040); the API values that
  // feed it are asserted here because st.dataframe draws the cells on a canvas.
  if (unconfirmedRow.judge_used) {
    expect(unconfirmedRow.judge_model).not.toBeNull();
  } else {
    expect(unconfirmedRow.judge_model).toBeNull();
  }
  expect(failingRun.failure_step).toBe('unreachable');
  expect(failingRun.evidence_labels).toEqual([]);

  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);
  await app.goto();
  await app.selectTarget(target);

  // The runs table's accessible name is its `alt` text (the canvas cells themselves stay with the integration test).
  await expect(page.getByRole('region', { name: "This target's attack runs, newest first" })).toBeVisible();

  await app.selectRun(runLabel(confirmedRun));
  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by canary');
  await expect(evidence.evidenceItems).toHaveText([CANARY_LINE]);

  await app.selectRun(runLabel(unconfirmedRun));
  await expect(evidence.heading).toHaveCount(0);

  // The run picker's popover is still open after a selection; dismissing it frees the sidebar's target select.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await app.selectTarget(failingTarget);
  await expect(page.getByRole('region', { name: "This target's attack runs, newest first" })).toBeVisible();
  await app.selectRun(runLabel(failingRun));
  await expect(evidence.headline).toHaveText(UNREACHABLE_MESSAGE);
  await expect(evidence.heading).toHaveCount(0);
});

/** Covers AC7, FR-044 */
test('9. lists every evidence item in the report [FR-044]', async ({ page, api, stub }) => {
  const sample = positiveCase('drop_or_truncate_table', 'DROP TABLE customers');
  const reply = `${CANARY_REPLY}\n\n${sample}`;
  stub.setReply(reply);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);
  expect(run.evidence.map((item) => item.line)).toEqual([CANARY_LINE, UNSAFE_LINE]);

  const app = new KestrelApp(page);
  const report = new ReportPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await report.open();
  await report.generate();

  await expect(report.panel.getByText('Winning attacker message:', { exact: true })).toBeVisible();
  await expect(report.codeBlocks.filter({ hasText: run.prompt_text.slice(0, 40) }).first()).toHaveText(
    run.prompt_text,
  );
  await expect(report.panel.getByText('Evidence:', { exact: true })).toBeVisible();
  for (const item of run.evidence) {
    await expect(report.evidenceItem(item.line).first()).toHaveText(item.line);
    await expect(report.codeBlock(item.detail).first()).toHaveText(item.detail);
  }
  await expect(report.panel.getByText('Hard evidence (verbatim):', { exact: true })).toBeVisible();
  await expect(report.codeBlock(CANARY_REPLY).first()).toHaveText(run.reply_text ?? '');
  expect(run.reply_text).toBe(reply);
  await expect(report.panel).not.toContainText(target.url);
});

/** Covers AC8, FR-045 */
test('10. adds the LLM05 coverage row and counts cross-class items correctly [FR-045]', async ({
  page,
  api,
  stub,
}) => {
  const sample = positiveCase('drop_or_truncate_table', 'DROP TABLE customers');
  stub.setReply(sample);
  const target = await api.createTarget(uniqueName(), stub);
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);
  expect(run.evidence).toHaveLength(1);
  expect(run.evidence[0].owasp_category).toBe('LLM05: Improper Output Handling');

  const app = new KestrelApp(page);
  const report = new ReportPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await report.open();
  await report.generate();

  const detectorRow = report.coverageRow('unsafe executable output detector (every reply)');
  await expect(detectorRow.getByRole('cell')).toHaveText([
    'LLM05: Improper Output Handling',
    'unsafe executable output detector (every reply)',
    '1',
    '1 run(s), 1 confirmed finding(s)',
  ]);

  const familyRow = report.coverageRow('LLM07: System Prompt Leakage');
  await expect(familyRow.getByRole('cell')).toHaveText([
    'LLM07: System Prompt Leakage',
    'system-prompt leak',
    '1',
    '1 run(s), held',
  ]);

  const untested = report.notTestedItems();
  await expect(untested).toHaveCount(6);
  await expect(untested).toHaveText([
    /^LLM02:/,
    /^LLM03:/,
    /^LLM04:/,
    /^LLM08:/,
    /^LLM09:/,
    /^LLM10:/,
  ]);
  await expect(untested.filter({ hasText: /^LLM05:/ })).toHaveCount(0);
});

/** Covers AC9, FR-047, FR-048, SC-007 */
test('11. logs evidence kinds and counts without details or reply text [FR-047, FR-048]', async ({
  page,
  api,
  stub,
}) => {
  const sample = positiveCase('drop_or_truncate_table', 'DROP TABLE customers');
  const excerpt = sample.split('\n').find((line) => line.startsWith('DROP')) as string;
  stub.setReply(sample);
  const target = await api.createTarget(uniqueName(), stub);
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);
  expect(run.evidence).toHaveLength(1);
  const item = run.evidence[0];

  const app = new KestrelApp(page);
  const viewer = new RunLogViewer(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await viewer.expand();
  await expect(viewer.logRawLines).toBeVisible();

  const lines = await viewer.parsedLines();
  const checks = lines.filter((line) => line.event === 'evidence.check');
  expect(checks).toHaveLength(1);
  expect(checks[0].evidence_kinds).toEqual(['unsafe_executable_output']);
  expect(checks[0].evidence_count).toBe(1);

  const turns = lines.filter((line) => line.event === 'turn');
  expect(turns).toHaveLength(1);
  expect(turns[0].evidence_kinds).toEqual(['unsafe_executable_output']);
  expect(turns[0].evidence_count).toBe(1);

  const end = lines.find((line) => line.event === 'run.end');
  expect(end, 'the run.end line is kept').toBeDefined();
  expect(end?.evidence_kinds).toEqual(['unsafe_executable_output']);
  expect(end?.evidence_count).toBe(1);
  expect(end?.side_channel_status).toBe('not_configured');

  const raw = await viewer.rawText();
  const forbidden = [item.detail, excerpt.trim(), run.reply_text ?? '', run.prompt_text, target.url];
  for (const text of forbidden) {
    expect(text.length, 'a forbidden text must be non-empty to prove anything').toBeGreaterThan(0);
    expect(raw).not.toContain(text);
  }
  // No line carries a URL of any kind (FR-048).
  expect(raw).not.toContain('http://');
  expect(raw).not.toContain('https://');
});

/** Covers AC10, FR-064, SC-014 */
test("12. keeps an indirect-injection run's task inside the seed text [FR-064, SC-014]", async ({
  page,
  api,
  stub,
}) => {
  stub.setReply(SAFE_REPLY);
  const target = await api.createTarget(uniqueName(), stub);
  const seed = (await api.attackPrompts('indirect_injection')).find((candidate) => candidate.id === 'iin-001');
  expect(seed, 'attack prompt iin-001 is missing').toBeDefined();
  const seedText = (seed as NonNullable<typeof seed>).text;

  stub.resetRequests();
  const seeded = await api.createRun(target.id, { family: 'indirect_injection', promptId: 'iin-001' });
  const run = await api.getRun(seeded.id);
  expect(stub.requests).toHaveLength(1);
  const sent = sentMessage(stub.requests[0].body);

  // The stored message is exactly the message sent.
  expect(sent).toBe(run.prompt_text);
  // The planted task sits inside the seed's own content: its edges survive, the seed does not stay contiguous.
  expect(run.prompt_text).toContain(seedText.slice(0, 40));
  expect(run.prompt_text).toContain(seedText.slice(-40));
  expect(run.prompt_text).not.toContain(seedText);
  expect(run.prompt_text.endsWith(seedText)).toBe(false);

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await expect(app.codeBlocks.filter({ hasText: seedText.slice(0, 40) }).first()).toHaveText(run.prompt_text);
});

/** Covers AC11, FR-035 (spec Out of Scope: the comparison table keeps today's shape) */
test('13. keeps evidence off the replay comparison table [FR-035]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.verdict).toBe('succeeded');

  // The picker labels a run by its start second plus the prompt title, so a replay started in the same second as
  // its source would share its label. Wait for the next second before replaying, then the replay's label is its own.
  const sourceSecond = source.started_at.slice(0, 19);
  await expect.poll(() => new Date().toISOString().slice(0, 19)).not.toBe(sourceSecond);
  const replay = await api.replayRun(source.id);
  expect(replay.mode).toBe('replay');
  expect(runLabel(replay)).not.toBe(runLabel(source));
  expect(replay.evidence.map((item) => item.line)).toEqual([CANARY_LINE]);

  const app = new KestrelApp(page);
  const evidence = new EvidencePanel(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(replay));

  // The replay's own run page shows its items like any run's.
  await expect(evidence.headline).toHaveText('Attack succeeded · confirmed by canary');
  await expect(evidence.heading).toBeVisible();
  await expect(evidence.evidenceItems).toHaveText([CANARY_LINE]);

  // The comparison keeps its existing accessible name and carries no evidence kind, label or column.
  await expect(panel.comparison).toBeVisible();
  await expect(panel.comparison).not.toContainText(CANARY.toLowerCase());
  await expect(panel.comparison).not.toContainText('Evidence');
});

/** Covers AC12, FR-014 (spec Edge Cases: a pattern beyond the reply cut is not found) */
test('14. finds nothing beyond the reply-length cut [FR-014]', async ({ page, api, stub }) => {
  const config = await api.config();
  const sample = positiveCase('drop_or_truncate_table', 'DROP TABLE customers');
  stub.setReply(`${'x'.repeat(2_000)}${sample}`);
  const target = await api.createTarget(uniqueName(), stub);
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const run = await api.getRun(seeded.id);

  expect(run.reply_truncated).toBe(true);
  expect(run.evidence).toEqual([]);
  expect(run.hard_evidence).toBe(false);
  expect((run.reply_text ?? '').length).toBeLessThanOrEqual(2_000);
  expect(run.reply_text ?? '').not.toContain(sample.split('\n').find((line) => line.startsWith('DROP')) as string);

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));
  await expectScoringWithoutEvidence(page, app, config);
  await expect(app.codeBlocks.filter({ hasText: 'x'.repeat(40) }).first()).toHaveText(run.reply_text ?? '');
});
