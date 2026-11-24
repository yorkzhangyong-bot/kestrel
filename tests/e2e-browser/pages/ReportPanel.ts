import { type Locator, type Page, expect } from '@playwright/test';

/**
 * The Report tab (feature 005, extended by feature 013): generating the OWASP report and reading its rendered
 * Markdown preview. The report is fetched through the API and rendered with `st.markdown`, so the preview carries
 * real headings, list items, tables and `<pre><code>` blocks; the coverage table (FR-045) is read row by row and
 * the Not-tested list by its class-prefixed items.
 */
export class ReportPanel {
  readonly reportTab: Locator;
  readonly generateButton: Locator;
  readonly downloadButton: Locator;
  readonly panel: Locator;
  readonly headings: Locator;
  readonly listItems: Locator;
  readonly rows: Locator;
  readonly codeBlocks: Locator;

  constructor(readonly page: Page) {
    this.reportTab = page.getByRole('tab', { name: 'Report', exact: true });
    this.generateButton = page.getByRole('button', { name: 'Generate report', exact: true });
    this.downloadButton = page.getByRole('button', { name: 'Download Markdown', exact: true });
    this.panel = page.getByRole('tabpanel', { name: 'Report', exact: true });
    this.headings = this.panel.getByRole('heading');
    this.listItems = this.panel.getByRole('listitem');
    this.rows = this.panel.getByRole('row');
    this.codeBlocks = this.panel.locator('pre code');
  }

  async open(): Promise<void> {
    await this.reportTab.click();
    await expect(this.generateButton).toBeVisible();
  }

  /** Generate the report and wait for the rendered preview (the download buttons render with it). */
  async generate(): Promise<void> {
    await this.generateButton.click();
    await expect(this.downloadButton).toBeVisible({ timeout: 60_000 });
  }

  /** One finding's list item, matched by its exact evidence line. */
  evidenceItem(line: string): Locator {
    return this.listItems.filter({ hasText: line });
  }

  /** The code block whose exact text is `text` (winning message, an item's detail, or the verbatim reply). */
  codeBlock(text: string): Locator {
    return this.codeBlocks.filter({ hasText: text });
  }

  /** The OWASP coverage row whose Family cell names this detector (FR-045). */
  coverageRow(familyLabel: string): Locator {
    return this.rows.filter({ hasText: familyLabel }).first();
  }

  /** The Not-tested list's class-prefixed items (they start with an OWASP class name, e.g. `LLM02:`). */
  notTestedItems(): Locator {
    return this.listItems.filter({ hasText: /^LLM\d\d:/ });
  }
}
