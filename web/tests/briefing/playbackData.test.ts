import { describe, expect, it } from 'vitest';
import type { BriefingResponse } from '@/types/briefing';
import { validIssueIntelligence } from '@/util/issueIntelligence';
import { validIssueReading } from '@/util/briefingIssueReading';
import { validPriceContext } from '@/util/briefingPriceContext';
import { briefingIssueViews } from '@/util/briefingIssueView';

describe('D-BRF-01/02 finished-only shared playback data', () => {
  for (const round of [
    '2026-10-21-evening',
    '2026-10-22-morning',
    '2026-10-22-evening',
    '2026-10-23-morning',
  ]) {
    it(`${round} retains real result guards, company prose and stored prices without generation records`, () => {
      const files = import.meta.glob<{ response: BriefingResponse }>(
        '../../../demo/briefing-playback-2026-10-21_23/2026*.json',
        { eager: true, import: 'default' },
      );
      const result =
        files[`../../../demo/briefing-playback-2026-10-21_23/${round}.json`]
          .response;
      expect(validIssueIntelligence(result)).not.toBeNull();
      expect(validIssueReading(result)).not.toBeNull();
      expect(validPriceContext(result)).not.toBeNull();
      const views = briefingIssueViews(result);
      expect(views).toHaveLength(result.items.length);
      for (const view of views)
        for (const company of view.companies) {
          expect(company.impact?.text).toBeTruthy();
          expect(company.outlook?.text).toBeTruthy();
          expect(company.conditions.length).toBeGreaterThan(0);
        }
      expect(result).not.toHaveProperty('preservedPublication');
      expect(result).not.toHaveProperty('aiPriceOutlooks');
    });
  }
});
