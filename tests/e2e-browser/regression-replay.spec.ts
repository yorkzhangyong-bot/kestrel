import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import type { KestrelApi, RunDetail } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';
import { MULTI_TURN_CAPTION, OUTCOME_LABELS, ReplayPanel } from './pages/ReplayPanel';
import type { Locator, Page } from '@playwright/test';

const SPL_FAMILY = 'System prompt leak · LLM07: System Prompt Leakage (4 prompts)';
const CANARY = 'KESTREL-CANARY-demo';
const CANARY_SECOND = 'KESTREL-CANARY-SECOND';
const CANARY_REPLY = `Here is my system prompt: ${CANARY}`;
const SAFE_REPLY = 'I cannot help with that request.';
const CANARY_REASON = 'The reply contains a canary string the agent was told to keep, so the attack is confirmed.';
const NOT_SUCCEEDED_REASON = 'Only a succeeded run can be replayed.';
const IN_PROGRESS_REASON = "A run still in progress can't be replayed.";
const OTHER_RUN_REASON = 'A run against this target is already in progress.';
const UNREACHABLE_MESSAGE = "Kestrel couldn't connect to this URL.";

/** The newest run of a target this test created (its runs list is not shared with any other test). */
async function newestRun(api: KestrelApi, targetId: number): Promise<RunDetail> {
  const runs = await api.listRuns(targetId);
  expect(runs.length).toBeGreaterThan(0);
  return api.getRun(runs[0].id);
}

/** One headline metric card's value, located by its label. */
function metricValue(page: Page, label: string): Locator {
  return page
    .getByTestId('stMetric')
    .filter({ has: page.getByTestId('stMetricLabel').getByText(label, { exact: true }) })
    .getByTestId('stMetricValue');
}

/** One section of the Markdown report, from its heading to the next `##` heading. */
function reportSection(markdown: string, heading: string): string {
  const start = markdown.indexOf(`## ${heading}`);
  expect(start, `the report has no ${heading} section`).toBeGreaterThanOrEqual(0);
  const rest = markdown.slice(start + heading.length + 3);
  const end = rest.indexOf('\n## ');
  return (end === -1 ? rest : rest.slice(0, end)).trim();
}

function findingCount(markdown: string): number {
  return (reportSection(markdown, 'Findings').match(/^### /gm) ?? []).length;
}

/** Covers AC1, AC7, FR-012, FR-013, FR-014, FR-016, FR-017, FR-038, FR-041 */
test('1. replays a succeeded single-turn run as fixed and shows the side-by-side [FR-012, FR-013, FR-014, FR-017, FR-041]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.judge.configured, 'the API must be started with a judge to score a refusing reply').toBe(true);

  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.verdict).toBe('succeeded');
  expect(source.hard_evidence).toBe(true);

  stub.setReply(SAFE_REPLY);
  stub.resetRequests();

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));

  await expect(panel.replayButton).toBeEnabled();
  await panel.clickReplay();
  await expect(panel.outcomeLine('fixed')).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');
  expect(replay.source_run_id).toBe(source.id);
  expect(replay.replay_outcome).toBe('fixed');
  expect(replay.attacker_model).toBeNull();
  expect(replay.judge_used).toBe(true);
  expect(replay.judge_model).toBe(config.judge.model);
  expect([
    replay.family,
    replay.owasp_category,
    replay.prompt_id,
    replay.prompt_title,
    replay.prompt_text,
  ]).toEqual([source.family, source.owasp_category, source.prompt_id, source.prompt_title, source.prompt_text]);

  const comparison = replay.comparison;
  expect(comparison, 'a finished replay carries its comparison').not.toBeNull();
  expect(comparison?.source_run_id).toBe(source.id);
  expect(comparison?.replay_run_id).toBe(replay.id);
  expect(comparison?.outcome).toBe('fixed');
  expect(comparison?.turns).toHaveLength(1);
  expect(comparison?.turns[0].sent).toBe(true);
  expect(comparison?.multi_turn_caption).toBeNull();

  await expect(panel.outcomeLine('fixed')).toBeVisible();
  await expect(panel.replayOfRun(source.id)).toBeVisible();
  await expect(panel.comparison).toBeVisible();

  await panel.selectRunByAge(runLabel(source), 'oldest');
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
});

/** Covers AC2, FR-010, FR-013, FR-016, FR-017, FR-023 */
test('2. a multi-turn replay is still vulnerable and stops at the first success [FR-010, FR-013, FR-016, FR-017]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker for an adaptive source').toBe(true);

  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  stub.setReplies(['The agent refused.', CANARY_REPLY]);
  const seeded = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-002',
    mode: 'adaptive',
  });
  const source = await api.getRun(seeded.id);
  expect(source.turns_used).toBe(2);
  expect(source.succeeded_turn).toBe(2);
  expect(source.hard_evidence).toBe(true);
  const recorded = source.turns.map((turn) => turn.attacker_message);
  expect(recorded).toHaveLength(2);

  stub.setReply(CANARY_REPLY);
  stub.resetRequests();

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));
  await panel.clickReplay();
  await expect(panel.outcomeLine('still vulnerable')).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');
  expect(replay.source_run_id).toBe(source.id);
  expect(replay.replay_outcome).toBe('still_vulnerable');
  expect(replay.turns_used).toBe(1);
  expect(replay.turns).toHaveLength(1);
  expect(replay.turns[0].attacker_message).toBe(recorded[0]);

  expect(stub.requests).toHaveLength(1);
  expect(stub.jsonBodies[0].message).toBe(recorded[0]);

  const comparison = replay.comparison;
  expect(comparison).not.toBeNull();
  expect(comparison?.turns).toHaveLength(2);
  expect(comparison?.turns.map((turn) => turn.sent)).toEqual([true, false]);
  expect(comparison?.outcome).toBe('still_vulnerable');
  expect(comparison?.multi_turn_caption).toBe(MULTI_TURN_CAPTION);

  await expect(panel.outcomeLine('still vulnerable')).toBeVisible();
  await expect(panel.multiTurnCaption).toHaveText(MULTI_TURN_CAPTION);
  await expect(panel.replayOfRun(source.id)).toBeVisible();
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary at turn 2');
});

/** Covers AC3, FR-015, FR-016, FR-019, FR-041 */
test('3. an unreachable target makes the replay inconclusive [FR-015, FR-016, FR-019]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.verdict).toBe('succeeded');
  expect(source.hard_evidence).toBe(true);

  await stub.close();

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));
  await panel.clickReplay();
  await expect(panel.outcomeLine('inconclusive')).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');
  expect(replay.source_run_id).toBe(source.id);
  expect(replay.replay_outcome).toBe('inconclusive');
  expect(replay.failure_message).toBe(UNREACHABLE_MESSAGE);

  await expect(panel.outcomeLine('inconclusive')).toBeVisible();
  await expect(panel.replayOfRun(source.id)).toBeVisible();
  await expect(panel.comparison).toBeVisible();

  await panel.selectRunByAge(runLabel(replay), 'newest');
  await expect(app.alerts.first()).toHaveText(UNREACHABLE_MESSAGE);
  await expect(panel.outcomeLine('inconclusive')).toBeVisible();
  await expect(panel.comparison).toBeVisible();

  const unchanged = await api.getRun(source.id);
  expect(unchanged.verdict).toBe('succeeded');
  expect(unchanged.hard_evidence).toBe(true);
});

/** Covers AC4, FR-001, FR-002, FR-022, FR-024, FR-025, FR-026, FR-045, SC-001, SC-003, SC-008 */
test('4. resends the recorded messages verbatim with no attacker call or memory touch [FR-001, FR-002, FR-022, FR-024, FR-025, FR-026]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker for an adaptive source').toBe(true);
  const secret = `QA-HEADER-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const target = await api.createTarget(uniqueName(), stub, {
    canaries: [CANARY],
    headers: [{ name: 'X-API-Key', value: secret }],
  });
  stub.setReplies(['The agent refused.', CANARY_REPLY]);
  const seeded = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-002',
    mode: 'adaptive',
  });
  const source = await api.getRun(seeded.id);
  expect(source.hard_evidence).toBe(true);
  const recorded = source.turns.map((turn) => turn.attacker_message);
  expect(recorded.length).toBeGreaterThanOrEqual(2);

  stub.setReply(SAFE_REPLY);
  stub.resetRequests();

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));
  await panel.clickReplay();
  await expect(panel.outcome).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');
  expect(replay.source_run_id).toBe(source.id);
  expect(replay.attacker_model).toBeNull();
  expect(replay.memory_written).toBeNull();

  const sent = replay.turns.length;
  expect(sent).toBeGreaterThanOrEqual(1);
  expect(stub.requests).toHaveLength(sent);
  for (let index = 0; index < sent; index += 1) {
    expect(stub.jsonBodies[index].message).toBe(recorded[index]);
  }

  const log = await api.getRunLog(replay.id);
  expect(log.lines.filter((line) => line.event === 'model.request' && line.kind === 'attacker')).toHaveLength(0);
  expect(log.lines.filter((line) => line.event === 'memory.retrieval')).toHaveLength(0);
  expect(log.lines.filter((line) => line.event === 'memory.writeback')).toHaveLength(0);
  expect(log.lines.find((line) => line.event === 'run.start')?.source_run_id).toBe(source.id);
  expect(log.lines.find((line) => line.event === 'run.end')?.replay_outcome).toBe(replay.replay_outcome);
  for (const line of log.lines.filter((candidate) => candidate.event === 'turn')) {
    expect(line).not.toHaveProperty('attacker_model');
    expect(line).not.toHaveProperty('attacker_prompt');
  }

  const logged = JSON.stringify(log.lines);
  for (const text of [recorded[0], SAFE_REPLY, source.reply_text ?? '', CANARY, secret, target.url]) {
    expect(text.length, 'the forbidden text must be non-empty to prove anything').toBeGreaterThan(0);
    expect(logged).not.toContain(text);
  }
  if (replay.reason) {
    expect(logged).not.toContain(replay.reason);
  }

  await panel.selectRunByAge(runLabel(replay), 'newest');
  await expect(panel.captions.filter({ hasText: /^attacker / })).toHaveCount(0);
  await expect(app.alerts.filter({ hasText: 'could not be written to the experience store' })).toHaveCount(0);
  await expect(page.getByText(secret, { exact: false })).toHaveCount(0);
});

/** Covers AC1, AC8, FR-038, FR-040 */
test('5. replays the just-finished run from the result card [FR-038, FR-040]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const prompt = (await api.attackPrompts('system_prompt_leak')).find((candidate) => candidate.id === 'spl-001');
  expect(prompt, 'attack prompt spl-001 is missing').toBeDefined();

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.selectPrompt((prompt as NonNullable<typeof prompt>).title);
  await app.selectMode('Single-turn');
  await app.runAttack();
  await app.waitForRunToFinish();

  const afterAttack = await api.listRuns(target.id);
  expect(afterAttack).toHaveLength(1);
  const source = await api.getRun(afterAttack[0].id);
  expect(source.verdict).toBe('succeeded');
  expect(source.hard_evidence).toBe(true);

  // No run is opened, so the result card's Replay is the only one on the page.
  await expect(panel.replayButton).toHaveCount(1);
  await expect(panel.replayButton).toBeEnabled();
  await panel.clickReplay();
  await expect(panel.outcome).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.id).not.toBe(source.id);
  expect(replay.mode).toBe('replay');
  expect(replay.source_run_id).toBe(source.id);
  expect(Object.keys(OUTCOME_LABELS)).toContain(replay.replay_outcome);
  await expect(panel.outcomeLine(OUTCOME_LABELS[replay.replay_outcome as string])).toBeVisible();
  await expect(panel.replayOfRun(source.id)).toBeVisible();
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
});

/** Covers AC8, FR-004, FR-040, FR-042 */
test('6. a failed-to-send run shows the disabled Replay button and its reason [FR-004, FR-040]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  await stub.close();
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.failure_step).toBe('unreachable');
  expect(source.verdict).toBeNull();
  expect(source.replayable).toBe(false);
  expect(source.replay_blocked_reason).toBe(NOT_SUCCEEDED_REASON);
  const runsBefore = (await api.listRuns(target.id)).length;

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));

  await expect(panel.replayButton).toBeDisabled();
  await expect(panel.blockedReason(NOT_SUCCEEDED_REASON)).toHaveText(NOT_SUCCEEDED_REASON);
  await expect(app.alerts.first()).toHaveText(UNREACHABLE_MESSAGE);
  expect((await api.listRuns(target.id)).length).toBe(runsBefore);
});

/** Covers AC6, AC8, AC12, FR-005, FR-019, FR-039, FR-040, FR-041 */
test('7. opens a replay run with its own result, outcome and source reference [FR-005, FR-019, FR-039, FR-041]', async ({
  page,
  api,
  stub,
}) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));
  // Replayed from the run's own card: the UI takes seconds, so the replay's run-picker label (its start second
  // plus the prompt title) is distinct from the source's, and the replay can be opened by name below.
  await panel.clickReplay();
  await expect(panel.outcomeLine('still vulnerable')).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.replay_outcome).toBe('still_vulnerable');

  const runs = await api.listRuns(target.id);
  const replayRow = runs.find((run) => run.id === replay.id);
  const sourceRow = runs.find((run) => run.id === source.id);
  expect(replayRow?.mode).toBe('replay');
  expect(replayRow?.source_run_id).toBe(source.id);
  expect(sourceRow?.source_run_id).toBeNull();

  await panel.selectRunByAge(runLabel(replay), 'newest');

  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  await expect(app.codeBlocks.filter({ hasText: replay.prompt_text }).first()).toHaveText(replay.prompt_text);
  await expect(app.codeBlocks.filter({ hasText: replay.reply_text ?? '' }).first()).toHaveText(replay.reply_text ?? '');
  await expect(app.texts.filter({ hasText: replay.reason ?? '' })).toBeVisible();
  await expect(panel.outcomeLine('still vulnerable')).toBeVisible();
  await expect(panel.replayOfRun(source.id)).toBeVisible();
  await expect(panel.comparison).toBeVisible();
  await expect(panel.replayButton).toBeDisabled();
  const ofReplay = `This run is itself a replay of run #${source.id}.`;
  await expect(panel.blockedReason(ofReplay)).toHaveText(ofReplay);
});

/** Covers AC6, FR-041 */
test('8. the Replay of run #N button opens the source run [FR-041]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(source));
  await expect(panel.replayButton).toBeEnabled();
  await panel.clickReplay();
  await expect(panel.outcome).toBeVisible({ timeout: 60_000 });
  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');

  await panel.selectRunByAge(runLabel(replay), 'newest');
  await expect(panel.replayButton).toBeDisabled();
  await panel.replayOfRun(source.id).click();
  await expect(panel.openRunSelect).toHaveValue(runLabel(source));
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  await expect(panel.replayButton).toBeEnabled();
});

/** Covers AC2, FR-014, FR-041 */
test('9. shows the multi-turn caption only for a multi-message source [FR-014, FR-041]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker for an adaptive source').toBe(true);

  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  stub.setReplies(['The agent refused.', CANARY_REPLY]);
  const adaptiveSeeded = await api.createRun(target.id, {
    family: 'system_prompt_leak',
    promptId: 'spl-002',
    mode: 'adaptive',
  });
  const adaptiveSource = await api.getRun(adaptiveSeeded.id);
  expect(adaptiveSource.turns).toHaveLength(2);

  stub.setReply(CANARY_REPLY);
  const singleSeeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const singleSource = await api.getRun(singleSeeded.id);
  expect(singleSource.turns).toHaveLength(0);

  stub.setReply(SAFE_REPLY);
  const adaptiveReplay = await api.replayRun(adaptiveSource.id);
  const singleReplay = await api.replayRun(singleSource.id);
  expect(adaptiveReplay.comparison?.turns).toHaveLength(2);
  expect(adaptiveReplay.comparison?.multi_turn_caption).toBe(MULTI_TURN_CAPTION);
  expect(singleReplay.comparison?.turns).toHaveLength(1);
  expect(singleReplay.comparison?.multi_turn_caption).toBeNull();
  expect(singleReplay.replay_outcome).toBe('fixed');

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await panel.selectRunByAge(runLabel(adaptiveReplay), 'newest');

  await expect(panel.outcome).toBeVisible();
  await expect(panel.multiTurnCaption).toHaveText(MULTI_TURN_CAPTION);
  const captionFollowsOutcome = await panel.outcome.evaluate((element, caption: string) => {
    const paragraphs = Array.from(document.querySelectorAll('p'));
    const match = paragraphs.find((node) => (node.textContent ?? '').trim() === caption);
    if (!match) return false;
    return (element.compareDocumentPosition(match) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
  }, MULTI_TURN_CAPTION);
  expect(captionFollowsOutcome).toBe(true);

  await panel.selectRunByAge(runLabel(singleReplay), 'newest');
  await expect(panel.outcome).toBeVisible();
  await expect(panel.multiTurnCaption).toHaveCount(0);
});

/** Covers AC8, FR-004, FR-006, FR-040 */
test('11. in-progress and concurrent runs give their own disabled reasons [FR-004, FR-006]', async ({
  page,
  browser,
  api,
  stub,
}) => {
  const config = await api.config();
  expect(config.attacker.configured, 'the API must be started with an attacker for an adaptive run').toBe(true);

  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.verdict).toBe('succeeded');
  stub.setDelay(12_000);

  const appA = new KestrelApp(page);
  await appA.goto();
  await appA.selectTarget(target);
  await appA.selectFamily(SPL_FAMILY);
  await appA.selectMode('Adaptive');

  // Second context ready before the slow run starts, so its one-shot budget is spent on the assertions below.
  const origin = new URL(page.url()).origin;
  const contextB = await browser.newContext({ baseURL: origin });
  const pageB = await contextB.newPage();
  const appB = new KestrelApp(pageB);
  const panelB = new ReplayPanel(pageB);
  await appB.goto();

  await appA.runAttack();

  await expect
    .poll(
      async () => {
        const runs = await api.listRuns(target.id);
        for (const run of runs) {
          if (run.id === source.id) continue;
          if ((await api.getRun(run.id)).status === 'in_progress') return run.id;
        }
        return null;
      },
      { timeout: 30_000, message: 'the adaptive run never appeared in progress' },
    )
    .not.toBeNull();

  // Selecting the target here fetches the runs list fresh, so it already holds the in-progress run.
  await appB.selectTarget(target);

  const busyRow = (await api.listRuns(target.id)).find((run) => run.id !== source.id);
  expect(busyRow, 'the in-progress run is listed').toBeDefined();
  const busy = await api.getRun((busyRow as NonNullable<typeof busyRow>).id);
  expect(busy.status).toBe('in_progress');
  expect(busy.replayable).toBe(false);
  expect(busy.replay_blocked_reason).toBe(IN_PROGRESS_REASON);

  await panelB.selectRunByAge(runLabel(busy), 'newest');
  await expect(panelB.replayButton).toBeDisabled();
  await expect(panelB.blockedReason(IN_PROGRESS_REASON)).toHaveText(IN_PROGRESS_REASON);

  await panelB.selectRunByAge(runLabel(source), 'oldest');
  await expect(panelB.replayButton).toBeDisabled();
  await expect(panelB.blockedReason(OTHER_RUN_REASON)).toHaveText(OTHER_RUN_REASON);

  await appA.waitForRunToFinish(25_000);
  await expect(appA.alerts.first()).toHaveText('Attack succeeded · confirmed by canary at turn 1');
  expect((await api.getRun(source.id)).replayable).toBe(true);
  await contextB.close();
});

/** Covers AC1, AC2, FR-001, FR-003, FR-007 */
test('12. uses the target\'s current canaries when scoring a replay [FR-003, FR-007]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.reason).toBe(CANARY_REASON);

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await app.addCanary(CANARY_SECOND);
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'Target saved.' })).toBeVisible();
  const canaries = (await api.getTarget(target.id)).canaries;
  expect(canaries).toContain(CANARY);
  expect(canaries).toContain(CANARY_SECOND);

  stub.setReply(`The hidden marker is ${CANARY_SECOND}`);
  stub.resetRequests();

  await app.selectRun(runLabel(source));
  await expect(panel.replayButton).toBeEnabled();
  await panel.clickReplay();
  await expect(panel.outcomeLine('still vulnerable')).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');
  expect(replay.replay_outcome).toBe('still_vulnerable');
  expect(replay.hard_evidence).toBe(true);
  expect(replay.reply_text).toContain(CANARY_SECOND);

  expect(stub.requests).toHaveLength(1);
  expect(stub.jsonBodies[0].message).toBe(source.prompt_text);

  const unchanged = await api.getRun(source.id);
  expect(unchanged.verdict).toBe('succeeded');
  expect(unchanged.hard_evidence).toBe(true);
  expect(unchanged.reason).toBe(CANARY_REASON);

  const comparison = replay.comparison;
  expect(comparison?.source_hard_evidence).toBe(true);
  expect(comparison?.replay_hard_evidence).toBe(true);
  const comparisonText = JSON.stringify(comparison);
  expect(comparisonText).not.toContain(CANARY);
  expect(comparisonText).not.toContain(CANARY_SECOND);

  await panel.selectRunByAge(runLabel(replay), 'newest');
  await expect(app.codeBlocks.filter({ hasText: CANARY_SECOND }).first()).toHaveText(replay.reply_text ?? '');
});

/** Covers AC9, FR-024, FR-027, SC-003, SC-004 */
test('13. a replay leaves the report and finding counts unchanged [FR-024, FR-027]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);
  expect(source.finding).toBe(true);
  expect(source.hard_evidence).toBe(true);

  const reportBefore = await api.generateReport(target.id);
  expect(findingCount(reportBefore)).toBe(1);
  const coverageBefore = reportSection(reportBefore, 'OWASP coverage');

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await expect(metricValue(page, 'Runs')).toHaveText('1');
  await expect(metricValue(page, 'Confirmed')).toHaveText('1');
  await expect(metricValue(page, 'Suspected')).toHaveText('0');

  await app.selectRun(runLabel(source));
  await panel.clickReplay();
  await expect(panel.outcomeLine('still vulnerable')).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  expect(replay.mode).toBe('replay');
  expect(replay.verdict).toBe('succeeded');
  expect(replay.finding).toBe(false);
  expect(replay.memory_written).toBeNull();

  const reportAfter = await api.generateReport(target.id);
  expect(findingCount(reportAfter)).toBe(findingCount(reportBefore));
  expect(reportSection(reportAfter, 'OWASP coverage')).toBe(coverageBefore);
  expect(reportSection(reportAfter, 'Findings')).toBe(reportSection(reportBefore, 'Findings'));
  expect(reportAfter.toLowerCase()).not.toContain('replay');

  await expect(metricValue(page, 'Runs')).toHaveText('2');
  await expect(metricValue(page, 'Confirmed')).toHaveText('1');
  await expect(metricValue(page, 'Suspected')).toHaveText('0');

  await panel.selectRunByAge(runLabel(replay), 'newest');
  await expect(app.alerts.filter({ hasText: 'could not be written to the experience store' })).toHaveCount(0);
});

/** Covers AC12, FR-039 */
test('15. lists a replay with mode replay and its source id [FR-039]', async ({ page, api, stub }) => {
  stub.setReply(CANARY_REPLY);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const seeded = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const source = await api.getRun(seeded.id);

  const app = new KestrelApp(page);
  const panel = new ReplayPanel(page);
  await app.goto();
  await app.selectTarget(target);
  await expect(page.getByRole('region', { name: "This target's attack runs, newest first" })).toBeVisible();
  await app.selectRun(runLabel(source));
  await panel.clickReplay();
  await expect(panel.outcome).toBeVisible({ timeout: 60_000 });

  const replay = await newestRun(api, target.id);
  const runs = await api.listRuns(target.id);
  const replayRow = runs.find((run) => run.id === replay.id);
  const sourceRow = runs.find((run) => run.id === source.id);
  expect(replayRow?.mode).toBe('replay');
  expect(replayRow?.source_run_id).toBe(source.id);
  expect(sourceRow?.source_run_id).toBeNull();

  await panel.selectRunByAge(runLabel(replay), 'newest');
  await expect(panel.outcome).toBeVisible();
  await expect(panel.comparison).toBeVisible();
});
