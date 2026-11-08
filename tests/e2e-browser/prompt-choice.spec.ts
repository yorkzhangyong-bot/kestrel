import { test, expect, runLabel, uniqueName } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';

const SPL_FAMILY = 'System prompt leak · LLM07: System Prompt Leakage (4 prompts)';
const DIRECT_FAMILY = 'Direct prompt injection · LLM01: Prompt Injection (4 prompts)';

/** Covers US3.1, FR-008, FR-032 */
test('11. sends the exact prompt the user picked [US3.1, FR-008, FR-032]', async ({ page, api, stub }) => {
  const target = await api.createTarget(uniqueName(), stub);
  stub.setReply('The agent refused.');
  const prompts = await api.attackPrompts('system_prompt_leak');
  const chosen = prompts.find((prompt) => prompt.id === 'spl-002');
  expect(chosen).toBeDefined();
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(SPL_FAMILY);

  expect(await app.promptSelect.inputValue()).toBe('');
  expect(await app.promptOptions()).toContain('Kestrel picks one');

  await app.selectPrompt(chosen?.title ?? '');
  await expect(app.codeBlocks.filter({ hasText: chosen?.text ?? '' }).first()).toHaveText(chosen?.text ?? '');

  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  expect(stub.requests).toHaveLength(1);
  expect(stub.jsonBodies[0].message).toBe(chosen?.text);
  await expect(app.codeBlocks.filter({ hasText: chosen?.text ?? '' }).first()).toHaveText(chosen?.text ?? '');

  const newest = (await api.listRuns(target.id))[0];
  expect(newest.prompt_id).toBe('spl-002');
  expect(await app.openRunOptions()).toContain(runLabel(newest));
});

/** Covers US3.2, FR-007 */
test('12. picks one prompt when none is chosen and names it in the result [US3.2, FR-007]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub);
  stub.setReply('The agent refused.');
  const prompts = await api.attackPrompts('direct_injection');
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await app.selectFamily(DIRECT_FAMILY);

  stub.resetRequests();
  await app.runAttack();
  await app.waitForRunToFinish();

  expect(stub.requests).toHaveLength(1);
  const sent = stub.jsonBodies[0].message as string;
  const matches = prompts.filter((prompt) => prompt.text === sent);
  expect(matches).toHaveLength(1);
  const picked = matches[0];

  await expect(app.codeBlocks.filter({ hasText: sent }).first()).toHaveText(sent);
  const newest = (await api.listRuns(target.id))[0];
  expect(newest.prompt_id).toBe(picked.id);
  expect(newest.prompt_title).toBe(picked.title);
  expect(await app.openRunOptions()).toContain(runLabel(newest));
});
