import { type Locator, type Page } from '@playwright/test';
import type { LogLine } from '../fixtures/kestrel';

/**
 * The run page's "Log" viewer (feature 010, FR-012): a collapsed expander with the st.dataframe table and the raw
 * JSON of every kept line. Streamlit renders an expander as a native `<details>/<summary>`, which exposes no
 * button role, so the label is matched with getByText and the disclosure is scoped from it.
 */
export class RunLogViewer {
  readonly logExpander: Locator;
  readonly logTable: Locator;
  readonly logRawLines: Locator;

  constructor(readonly page: Page) {
    // A run opened from the Runs tab renders its own "Log" expander, and the attack result above the tabs renders
    // the same run again, so an unscoped filter matches both. Prefer the Runs tab's viewer, and fall back to the
    // attack result for a run that was just executed but not opened from the Runs tab; the log is the same run.
    const runsLog = page
      .getByRole('tabpanel', { name: 'Runs' })
      .locator('details')
      .filter({ has: page.getByText('Log', { exact: true }) });
    const attackLog = page.locator('details').filter({ has: page.getByText('Log', { exact: true }) });
    this.logExpander = runsLog.or(attackLog).first();
    this.logTable = this.logExpander.getByTestId('stDataFrame');
    this.logRawLines = this.logExpander.locator('pre code').filter({ hasText: '"event": "run.start"' });
  }

  /** Click the "Log" summary; the raw block only becomes visible once the expander is open. */
  async expand(): Promise<void> {
    await this.logExpander.locator('summary').click();
  }

  async rawText(): Promise<string> {
    return this.logRawLines.innerText();
  }

  /** The viewer renders one JSON object per kept line; parse them back in order. */
  async parsedLines(): Promise<LogLine[]> {
    const text = await this.rawText();
    return text
      .split('\n')
      .filter((line) => line.trim().length > 0)
      .map((line) => JSON.parse(line) as LogLine);
  }
}
