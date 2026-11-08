import { test, expect, uniqueName } from './fixtures/kestrel';
import type { TargetDetail } from './fixtures/kestrel';
import { KestrelApp } from '../pages/KestrelApp';

const CANARY = 'KESTREL-CANARY-demo';

/** Covers FR-024, FR-025 */
test('13. rejects a canary under 8 characters and accepts exactly 8 [FR-024, FR-025]', async ({ page, api, stub }) => {
  const name = uniqueName();
  const app = new KestrelApp(page);
  await app.goto();

  await app.displayName.fill(name);
  await app.endpointUrl.fill(stub.url);
  await app.endpointUrl.blur();
  await app.testConnectionButton.click();
  await expect(app.alerts.filter({ hasText: /Connection works · status 200/ })).toBeVisible();

  await app.addCanary('1234567');
  await app.setPermission(true);
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'A canary string must be at least 8 characters.' }).first()).toBeVisible();
  expect(await api.findTargetByName(name)).toBeUndefined();

  const canary = app.canaryInputs.first();
  await canary.fill('12345678');
  await canary.blur();
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'Target saved.' })).toBeVisible();

  const summary = await api.findTargetByName(name);
  expect(summary).toBeDefined();
  const saved = await api.getTarget((summary as TargetDetail).id);
  api.track(saved.id);
  expect(saved.canaries).toEqual(['12345678']);

  await app.selectTarget(saved);
  await expect(app.canaryInputs).toHaveCount(1);
  await expect(app.canaryInputs.first()).toHaveValue('12345678');
  await expect(app.canaryInputs.first()).toHaveAttribute('type', 'text');
});

/** Covers FR-024 */
test('14. rejects a duplicate canary on the same target [FR-024]', async ({ page, api, stub }) => {
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await expect(app.canaryInputs).toHaveCount(1);
  await expect(app.canaryInputs.first()).toHaveValue(CANARY);

  await app.addCanary(CANARY);
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'This canary string appears more than once.' }).first()).toBeVisible();
  expect((await api.getTarget(target.id)).canaries).toEqual([CANARY]);
});

/** Covers FR-024 */
test('15. shows canaries in full and changes them without a new connection test [FR-024]', async ({
  page,
  api,
  stub,
}) => {
  const target = await api.createTarget(uniqueName(), stub, { canaries: [CANARY] });
  const app = new KestrelApp(page);

  await app.goto();
  await app.selectTarget(target);
  await expect(app.canaryInputs).toHaveCount(1);
  await expect(app.canaryInputs.first()).toHaveValue(CANARY);
  await expect(app.canaryInputs.first()).toHaveAttribute('type', 'text');

  await app.addCanary('SECOND-CANARY-VALUE');
  await app.saveTargetButton.click();
  await expect(app.alerts.filter({ hasText: 'Target saved.' })).toBeVisible();
  expect((await api.getTarget(target.id)).canaries).toEqual([CANARY, 'SECOND-CANARY-VALUE']);

  await page.reload();
  await expect(app.runButton).toBeVisible();
  await app.selectTarget(target);
  expect(await app.canaryValues()).toEqual([CANARY, 'SECOND-CANARY-VALUE']);
});
