import { type Locator, type Page } from '@playwright/test';

/**
 * The run page's `Evidence` section (feature 013, FR-039): one `st.caption` per item carrying the API-composed line
 * `{label} · turn {N} · {location} · {OWASP class}`, then that item's detail as `st.text`. The screen derives
 * nothing (FR-043), so both texts are compared with the API's values verbatim.
 */
export class EvidencePanel {
  readonly headline: Locator;
  readonly heading: Locator;
  readonly evidenceItems: Locator;
  readonly details: Locator;

  constructor(readonly page: Page) {
    this.headline = page.getByTestId('stAlert').first();
    this.heading = page.getByRole('heading', { name: 'Evidence', exact: true });
    // A caption that is an evidence line always carries the "· turn N ·" segment; no other caption on the run
    // page does (the attacker source caption carries no turn number).
    this.evidenceItems = page.getByTestId('stCaptionContainer').filter({ hasText: /· turn \d+ ·/ });
    this.details = page.getByTestId('stText');
  }

  /** The evidence lines in the order they are shown (the API's detection order). */
  async lines(): Promise<string[]> {
    return this.evidenceItems.allInnerTexts();
  }

  /** The plain-text detail of one item, matched by its exact text. */
  detail(text: string): Locator {
    return this.details.filter({ hasText: text });
  }
}
