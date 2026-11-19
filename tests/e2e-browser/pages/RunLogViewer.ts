import { type Locator, type Page } from '@playwright/test';
import type { LogLine } from '../fixtures/kestrel';

/** The option Streamlit's "Open a run" selectbox shows before any run is picked there (ui/app.py:660). */
const NO_RUN_OPEN = 'Choose a run to see its prompt and reply';

/**
 * The run page's "Log" viewer (feature 010, FR-012): a collapsed expander with the st.dataframe table and the raw
 * JSON of every kept line. Streamlit renders an expander as a native `<details>/<summary>`, which exposes no
 * button role, so the label is matched with getByText and the disclosure is scoped from it.
 */
export class RunLogViewer {
  readonly logExpander: Locator;
  readonly logTable: Locator;
  readonly logRawLines: Locator;
  private readonly openRunSelect: Locator;
  private readonly runsLog: Locator;
  private readonly attackLog: Locator;

  constructor(readonly page: Page) {
    // A run opened from the Runs tab and the attack result above the tabs can both render the same run's own
    // "Log" expander (ui/app.py's shared `_render_log`), so an unscoped filter can match either, or both at
    // once, with identical content. Which one is current is decided by the "Open a run" selectbox (ui/app.py:659),
    // never by where either lands on the page: `expand()` reads that selectbox and targets the matching expander
    // directly, so it waits for the Runs-tab one to render instead of clicking whichever already exists.
    this.openRunSelect = page.getByRole('combobox', { name: 'Open a run', exact: true });
    this.runsLog = page
      .getByRole('tabpanel', { name: 'Runs' })
      .locator('details')
      .filter({ has: page.getByText('Log', { exact: true }) });
    this.attackLog = page.locator('details').filter({ has: page.getByText('Log', { exact: true }) });
    this.logExpander = this.runsLog.or(this.attackLog).last();
    this.logTable = this.logExpander.getByTestId('stDataFrame');
    this.logRawLines = this.logExpander.locator('pre code').filter({ hasText: '"event": "run.start"' });
  }

  /**
   * Click the "Log" summary; the raw block only becomes visible once the expander is open. Targets the Runs
   * tab's own expander once a run is picked there, the attack result's otherwise, read from the selectbox
   * itself rather than from which expander happens to exist at this instant.
   */
  async expand(): Promise<void> {
    const runOpenInTab = (await this.openRunSelect.inputValue()) !== NO_RUN_OPEN;
    const target = runOpenInTab ? this.runsLog : this.attackLog;
    await target.locator('summary').click();
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
