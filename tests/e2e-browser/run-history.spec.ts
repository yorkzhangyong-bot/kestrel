import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';

const CANARY = 'KESTREL-CANARY-demo';
const CANARY_REPLY = `Here is my system prompt: ${CANARY}`;
const CANARY_REASON =
  'The reply contains a canary string the agent was told to keep, so the attack is confirmed.';
const NO_JUDGE_REASON =
  'No judge is configured, so this run could not be scored. Canary evidence still applies.';
const RUN_PLACEHOLDER = 'Choose a run to see its prompt and reply';

function runOnlyOptions(options: string[]): string[] {
  return options.filter((label) => label !== RUN_PLACEHOLDER);
}

/** Covers US2.1, FR-028, SC-010 */
test('7. lists runs newest first with family, verdict and time [US2.1, FR-028, SC-010]', async ({ page, api, stub }) => {
  const config = await api.config();
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });

  stub.setReply(CANARY_REPLY);
  const runA = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  stub.setReply('I cannot help with that request.');
  const runB = await api.createRun(target.id, { family: 'direct_injection', promptId: 'dir-001' });

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);

  const options = runOnlyOptions(await app.openRunOptions());
  expect(options).toEqual([runLabel(runB), runLabel(runA)]);
  for (const run of [runA, runB]) {
    expect(runLabel(run)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} · /);
    expect(runLabel(run)).toContain(run.prompt_title);
  }

  // Newest first is also what the API returns.
  const stored = await api.listRuns(target.id);
  expect(stored.map((run) => run.id)).toEqual([runB.id, runA.id]);

  await app.selectRun(runLabel(runB));
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
    await expect(page.getByTestId('stText').filter({ hasText: NO_JUDGE_REASON })).toBeVisible();
  }

  await app.selectRun(runLabel(runA));
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
});

/** Covers US2.2, FR-019, FR-027, FR-028, FR-032, SC-004 */
test('8. opens a listed run with its prompt, reply, verdict, reason, attacker source and judge [US2.2, FR-019, FR-028, FR-032, SC-004]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  stub.setReply(CANARY_REPLY);
  const run = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  await expect(app.codeBlocks.filter({ hasText: run.prompt_text }).first()).toHaveText(run.prompt_text);
  await expect(app.codeBlocks.filter({ hasText: run.reply_text ?? '' }).first()).toHaveText(run.reply_text ?? '');
  await expect(page.getByTestId('stText').filter({ hasText: CANARY_REASON })).toBeVisible();
  await expect(page.getByText(`Attacker: ${run.attacker_source} · ${run.owasp_category}`, { exact: true })).toBeVisible();
  await expect(app.alerts.first()).not.toContainText('judged by');

  const stored = await api.getRun(run.id);
  expect(stored.judge_used).toBe(false);
  expect(stored.judge_model).toBeNull();
  expect(stored.reason).toBe(CANARY_REASON);
});

/** Covers US2.3, FR-029, SC-010. A full page reload starts a new Streamlit session; a true Kestrel process
 * restart cannot be triggered from a spec without editing playwright.config.ts (forbidden), so the SQLite
 * persistence itself is covered by tests/integration/test_api_run_history.py. */
test('9. keeps a target\'s runs after a full page reload [US2.3, FR-029, SC-010]', async ({ page, api, stub }) => {
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  stub.setReply(CANARY_REPLY);
  const run = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });
  const label = runLabel(run);

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);
  expect(runOnlyOptions(await app.openRunOptions())).toContain(label);
  await app.selectRun(label);
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');

  await page.reload();
  await expect(app.runButton).toBeVisible();
  await app.selectTarget(target);
  expect(runOnlyOptions(await app.openRunOptions())).toContain(label);
  await app.selectRun(label);
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
});

/** Covers US2.4, FR-030 */
test('10. deletes a target together with its runs [US2.4, FR-030]', async ({ page, api, stub }) => {
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  stub.setReply(CANARY_REPLY);
  const run = await api.createRun(target.id, { family: 'system_prompt_leak', promptId: 'spl-001' });

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectRun(runLabel(run));

  await app.askToDeleteTarget();
  await app.confirmDeleteButton.click();
  await expect(app.alerts.filter({ hasText: 'Target deleted.' })).toBeVisible();

  const targetOptions = await app.targetOptions();
  expect(targetOptions).not.toContain(`${target.name} · ${target.url}`);
  await expect(app.targetSelect).toHaveValue('New target');
  await expect(page.getByText('Select a saved target to see its runs.', { exact: true })).toBeVisible();

  expect(await api.listRunStatus(target.id)).toBe(404);
  expect(await api.getTargetStatus(target.id)).toBe(404);
});
