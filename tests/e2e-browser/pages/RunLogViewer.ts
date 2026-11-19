import { type Locator, type Page } from '@playwright/test';
import type { LogLine } from '../fixtures/kestrel';

/**
 * What the "Open a run" selectbox (key `open_run` in ui/app.py) shows while no run is open in the Runs tab: the
 * label its None option renders with, or an empty value if that selection is ever reset through session state.
 * Playwright reads the Prompt selectbox as '' after ui/app.py resets it to None (prompt-choice.spec.ts).
 */
const NO_RUN_OPEN: ReadonlySet<string> = new Set(['Choose a run to see its prompt and reply', '']);

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
    // A run opened from the Runs tab and the attack result above the tabs can both render a "Log" expander
    // (ui/app.py's shared `_render_log`), so an unscoped filter can match either, or both at once. `expand()`
    // decides which one to open from the "Open a run" selectbox, not from which expander exists at that instant,
    // so after a run is picked there it waits for the Runs-tab expander to render. The read locators below do not
    // use that decision: they take the last "Log" expander on the page. That is the one `expand()` opened only
    // because the Runs tab renders below the attack result and no other "Log" expander exists; if the layout
    // changes, derive them from the same selectbox decision instead.
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
    const runOpenInTab = !NO_RUN_OPEN.has(await this.openRunSelect.inputValue());
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
