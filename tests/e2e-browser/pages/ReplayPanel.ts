import { type Locator, type Page, expect } from '@playwright/test';

/** The three replay outcome values as the API names them, and the label the page shows (FR-016). */
export const OUTCOME_LABELS: Record<string, string> = {
  fixed: 'fixed',
  still_vulnerable: 'still vulnerable',
  inconclusive: 'inconclusive',
};

/** The pinned FR-041 caption, shown only for a multi-message source. */
export const MULTI_TURN_CAPTION = 'A multi-turn replay re-tests the recorded messages, not an adaptive attack.';

/**
 * The replay controls of a run's result card (feature 012): the Replay button and its blocked reason, the
 * outcome line, the "Replay of run #N" source link and the side-by-side comparison. The comparison table is
 * `st.dataframe`, drawn on a canvas, so only its accessible name is asserted here (the cells are covered by
 * tests/integration/test_ui_replay.py).
 */
export class ReplayPanel {
  readonly openRunSelect: Locator;
  readonly replayButton: Locator;
  readonly outcome: Locator;
  readonly comparison: Locator;
  readonly captions: Locator;
  readonly multiTurnCaption: Locator;

  constructor(readonly page: Page) {
    this.openRunSelect = page.getByRole('combobox', { name: 'Open a run', exact: true });
    this.replayButton = page.getByRole('button', { name: 'Replay', exact: true });
    this.outcome = page.getByText(/^Outcome: /);
    this.comparison = page.getByRole('region', { name: 'This replay compared with its source, side by side' });
    this.captions = page.getByTestId('stCaptionContainer');
    // The multi-turn caption is rendered with st.write (a paragraph), not st.caption.
    this.multiTurnCaption = page.getByText(MULTI_TURN_CAPTION, { exact: true });
  }

  /** The outcome line with its exact label, e.g. "Outcome: still vulnerable". */
  outcomeLine(label: string): Locator {
    return this.page.getByText(`Outcome: ${label}`, { exact: true });
  }

  /** The button that opens the replay's source run (FR-041). */
  replayOfRun(sourceRunId: number): Locator {
    return this.page.getByRole('button', { name: `Replay of run #${sourceRunId}`, exact: true });
  }

  /** The Replay button's disabled caption, the API's `replay_blocked_reason` shown verbatim. */
  blockedReason(reason: string): Locator {
    return this.captions.filter({ hasText: reason });
  }

  async clickReplay(): Promise<void> {
    await this.replayButton.click();
  }

  /**
   * Open a run by its label. A source and its replay can share one label when they started in the same second;
   * the picker lists runs newest first, so `newest` opens the replay and `oldest` the source.
   */
  async selectRunByAge(label: string, age: 'newest' | 'oldest'): Promise<void> {
    await this.openRunSelect.click();
    await this.openRunSelect.press('ArrowDown');
    await expect(this.page.getByRole('option').first()).toBeVisible();
    const option = this.page.getByRole('option', { name: label, exact: true });
    await (age === 'newest' ? option.first() : option.last()).click();
    await expect(this.openRunSelect).toHaveValue(label);
    await expect(this.page.getByTestId('stAlert').first()).toBeVisible();
  }
}
