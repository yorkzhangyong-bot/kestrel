import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';

const SPL_FAMILY = 'System prompt leak · LLM07: System Prompt Leakage (4 prompts)';
const DIRECT_FAMILY = 'Direct prompt injection · LLM01: Prompt Injection (4 prompts)';
const CANARY = 'KESTREL-CANARY-demo';
const CANARY_REASON =
  'The reply contains a canary string the agent was told to keep, so the attack is confirmed.';
const NO_JUDGE_REASON =
  'No judge is configured, so this run could not be scored. Canary evidence still applies.';
const NO_JUDGE_CAPTION = 'No judge configured: only canary evidence can decide a run';

/** Covers US1.1, FR-006, FR-007, FR-011, SC-002 */
test('1. runs one prompt from the chosen family and shows prompt, reply and verdict [US1.1, FR-006, FR-007, FR-011, SC-002]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  const reply = 'The agent refused and kept its system prompt.';
  stub.setReply(reply);
  const target = await api.createTarget(uniqueName(), stub);
  const prompts = await api.attackPrompts('system_prompt_leak');
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  expect(stub.requests).toHaveLength(1);
  expect(stub.requests[0].method).toBe('POST');
  const sent = stub.jsonBodies[0].message as string;
  expect(prompts.map((prompt) => prompt.text)).toContain(sent);

  await expect(app.codeBlocks.filter({ hasText: sent }).first()).toHaveText(sent);
  await expect(app.codeBlocks.filter({ hasText: reply }).first()).toHaveText(reply);
  await expect(app.alerts.first()).not.toContainText('confirmed');

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
    await expect(page.getByText(`Judging uses ${model}`, { exact: true })).toBeVisible();
  } else {
    await expect(app.alerts).toHaveCount(1);
    await expect(app.alerts.first()).toHaveText('Unclear');
    await expect(page.getByTestId('stText').filter({ hasText: NO_JUDGE_REASON })).toBeVisible();
    await expect(page.getByText(NO_JUDGE_CAPTION, { exact: true })).toBeVisible();
  }

  const newest = await api.getRun((await api.listRuns(target.id))[0].id);
  expect(newest.status).toBe('finished');
  expect(newest.verdict).not.toBeNull();
  expect(newest.attacker_source).toMatch(/^library:\d+\.\d+\.\d+$/);
});

/** Covers US1.2, FR-016, FR-018, FR-019, SC-003, SC-005 */
test('2. confirms a canary leak as hard evidence without a judge [US1.2, FR-016, FR-018, FR-019, SC-003, SC-005]', async ({
  page,
  api,
  stub,
}) => {
  const reply = `Here is my system prompt: ${CANARY}`;
  stub.setReply(reply);
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await expect(app.canaryInputs).toHaveCount(1);
  await expect(app.canaryInputs.first()).toHaveValue(CANARY);
  await expect(app.canaryInputs.first()).toHaveAttribute('type', 'text');

  await app.selectFamily(SPL_FAMILY);
  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  await expect(app.alerts).toHaveCount(1);
  await expect(app.alerts.first()).toHaveText('Attack succeeded · confirmed by canary');
  await expect(page.getByTestId('stText').filter({ hasText: CANARY_REASON })).toBeVisible();
  await expect(app.alerts.first()).not.toContainText('suspected');

  const sent = stub.jsonBodies[0].message as string;
  await expect(app.codeBlocks.filter({ hasText: sent }).first()).toHaveText(sent);
  await expect(app.codeBlocks.filter({ hasText: reply }).first()).toHaveText(reply);

  const newest = (await api.listRuns(target.id))[0];
  expect(newest.verdict).toBe('succeeded');
  expect(newest.hard_evidence).toBe(true);
  expect(newest.judge_used).toBe(false);
  expect(newest.judge_model).toBeNull();
});

/** Covers FR-026, FR-018 */
test('3. does not treat a case-varied canary as hard evidence [FR-026]', async ({ page, api, stub }) => {
  const config = await api.config();
  stub.setReply('here is my system prompt: kestrel-canary-demo');
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(DIRECT_FAMILY);
  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  await expect(app.alerts.first()).not.toContainText('confirmed by canary');
  await expect(app.alerts.first()).not.toContainText('confirmed');
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

  const newest = (await api.listRuns(target.id))[0];
  expect(newest.hard_evidence).toBe(false);
  expect(newest.verdict).not.toBeNull();
});

/** Covers US1.3, US1.4, FR-017, FR-018, FR-019, FR-021, SC-004, SC-005 */
test('4. shows a judge verdict as opinion and never as confirmed [US1.3, US1.4, FR-017, FR-018, FR-019, FR-021, SC-004, SC-005]', async ({
  page,
  api,
  stub,
}) => {
  const config = await api.config();
  stub.setReply('I cannot help with that request.');
  const target = await api.createTarget(uniqueName(), stub);
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(DIRECT_FAMILY);
  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  await expect(app.alerts.first()).not.toContainText('confirmed');
  if (config.judge.configured) {
    const model = config.judge.model;
    const judged = app.alerts.filter({ hasText: 'judged by' });
    await expect(judged).toBeVisible();
    await expect(judged).toContainText(model);
    const wording = await judged.innerText();
    expect([
      `Attack succeeded · suspected, judged by ${model}`,
      `Attack failed · the agent held · judged by ${model}`,
      `Unclear · judged by ${model}`,
    ]).toContain(wording);
    await expect(page.getByText(`Judging uses ${model}`, { exact: true })).toBeVisible();

    const newest = (await api.listRuns(target.id))[0];
    expect(newest.judge_used).toBe(true);
    expect(newest.judge_model).toBe(model);
    expect(newest.hard_evidence).toBe(false);
  } else {
    await expect(app.alerts).toHaveCount(1);
    await expect(app.alerts.first()).toHaveText('Unclear');
    await expect(page.getByTestId('stText').filter({ hasText: NO_JUDGE_REASON })).toBeVisible();
    await expect(page.getByText(NO_JUDGE_CAPTION, { exact: true })).toBeVisible();

    const newest = (await api.listRuns(target.id))[0];
    expect(newest.judge_used).toBe(false);
    expect(newest.hard_evidence).toBe(false);
  }
});

/** Covers US1.5, FR-012, FR-014, SC-002 */
test('5. reports the failed send step and consults no judge when the target is unreachable [US1.5, FR-012, FR-014, SC-002]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  await stub.close();
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);
  await app.runAttack();
  await expect(app.alerts.first()).toBeVisible();

  const summary = (await api.listRuns(target.id))[0];
  const newest = await api.getRun(summary.id);
  expect(newest.failure_step).toBe('unreachable');
  expect(newest.verdict).toBeNull();
  expect(newest.judge_used).toBe(false);
  expect(newest.judge_model).toBeNull();
  await expect(app.codeBlocks.filter({ hasText: newest.prompt_text })).toHaveCount(0);

  // The UI contract requires feature 001's connection-failure wording for the step. The current screen instead
  // prints "The attack could not be sent: unreachable." (the step key), so this assertion records the deviation.
  await expect.soft(app.alerts.first()).toHaveText("Kestrel couldn't connect to this URL.");
  await expect.soft(app.alerts.first()).not.toContainText('Unclear');
});

/** Covers US1.6, FR-010 */
test('6. disables Run during a run and refuses a concurrent run from another session [US1.6, FR-010]', async ({
  page,
  browser,
  api,
  stub,
}) => {
  stub.setReply('The agent refused.');
  const target = await api.createTarget(uniqueName(), stub);
  stub.setDelay(12_000);

  const appA = new KestrelApp(page);
  await appA.goto();
  await appA.selectTarget(target);

  const origin = new URL(page.url()).origin;
  const contextB = await browser.newContext({ baseURL: origin });
  const pageB = await contextB.newPage();
  const appB = new KestrelApp(pageB);
  await appB.goto();
  await appB.selectTarget(target);

  stub.resetRequests();
  await appA.runAttack();
  // The UI contract disables Run while a run is in progress; the current screen leaves it enabled (possible bug).
  await expect.soft(appA.runButton).toBeDisabled();
  await appB.runAttack();
  const busy = appB.alerts.filter({ hasText: 'A run against this target is already in progress.' });
  await expect(busy.first()).toBeVisible({ timeout: 15_000 });
  await expect(busy.first()).toHaveText('A run against this target is already in progress.');

  await appA.waitForRunToFinish(25_000);
  await expect(appA.alerts).toHaveCount(1);
  await expect(appA.runButton).toBeEnabled();
  expect(stub.requests).toHaveLength(1);
  expect(await api.listRuns(target.id)).toHaveLength(1);
  await contextB.close();
});

/** Covers FR-032, FR-033, SC-007 */
test('16. renders prompt and reply as plain text and makes no outside request [FR-032, FR-033, SC-007]', async ({
  page,
  api,
  stub,
}) => {
  const hostile = "<script>alert('xss')</script> **bold** [click](http://evil.invalid/) ![img](http://evil.invalid/i.png)";
  stub.setReply(hostile);
  const target = await api.createTarget(uniqueName(), stub);
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));

  const app = new KestrelApp(page);
  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(DIRECT_FAMILY);
  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  await expect(app.codeBlocks.filter({ hasText: 'evil.invalid' }).first()).toHaveText(hostile);
  expect(requests.some((url) => url.includes('evil.invalid'))).toBe(false);

  const injected = await page.evaluate(() => ({
    script: Array.from(document.querySelectorAll('script')).some((element) =>
      (element.textContent ?? '').includes("alert('xss')"),
    ),
    image: Array.from(document.querySelectorAll('img')).some((element) =>
      (element.getAttribute('src') ?? '').includes('evil.invalid'),
    ),
    link: document.querySelectorAll('a[href*="evil.invalid"]').length,
  }));
  expect(injected.script).toBe(false);
  expect(injected.image).toBe(false);
  expect(injected.link).toBe(0);
  await expect(app.alerts.first()).not.toContainText('<script>');

  const newest = (await api.listRuns(target.id))[0];
  if (newest.reason) {
    await expect(page.getByTestId('stText').filter({ hasText: newest.reason })).toBeVisible();
  }
});

/** Covers FR-006 (UI contract) */
test('17. disables Run and prompts for a target when none is selected [FR-006]', async ({ page }) => {
  const app = new KestrelApp(page);
  await app.goto();

  await expect(app.runButton).toBeDisabled();
  await expect(page.getByText('Pick a saved target, choose an attack family, and click Run attack.', { exact: true })).toBeVisible();
  await expect(page.getByText('Select a saved target to see its runs.', { exact: true })).toBeVisible();
});

/** Covers FR-009 */
test('18. clears the permission confirmation when the endpoint URL changes and requires a new successful test [FR-009]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  const changedUrl = `${new URL(stub.url).origin}/chat2`;
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await expect(app.permissionCheckbox).toBeChecked();

  await app.changeEndpoint(changedUrl);
  await expect(app.permissionCheckbox).not.toBeChecked();

  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'Tick the box to confirm you own this agent or have written permission to test it.' })).toBeVisible();

  await app.setPermission(true);
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'Run a successful test with these settings before saving.' })).toBeVisible();

  await app.testConnectionButton.click();
  await expect(app.alerts.filter({ hasText: /Connection works · status 200/ })).toBeVisible();
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'Target saved.' })).toBeVisible();
  expect((await api.getTarget(target.id)).url).toBe(changedUrl);
});
