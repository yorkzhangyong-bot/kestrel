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
    this.logExpander = page.locator('details').filter({ has: page.getByText('Log', { exact: true }) });
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
