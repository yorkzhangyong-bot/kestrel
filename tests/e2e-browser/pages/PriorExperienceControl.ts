import { type Locator, type Page, expect } from '@playwright/test';

/**
 * The "Use prior experience" control in the Attack panel (feature 011, FR-015). Streamlit renders `st.toggle` as a
 * checkbox input with `role="switch"`, not `role="checkbox"`, so it is matched by its switch role and accessible
 * name. Like the permission checkbox, the native input is covered by its label, so the label is what to click.
 */
export class PriorExperienceControl {
  readonly toggle: Locator;

  constructor(readonly page: Page) {
    this.toggle = page.getByRole('switch', { name: 'Use prior experience', exact: true });
  }

  async isOn(): Promise<boolean> {
    return this.toggle.isChecked();
  }

  async setPriorExperience(checked: boolean): Promise<void> {
    if ((await this.toggle.isChecked()) !== checked) {
      await this.page.getByText('Use prior experience', { exact: true }).click();
    }
    await expect(this.toggle).toBeChecked({ checked });
  }
}
