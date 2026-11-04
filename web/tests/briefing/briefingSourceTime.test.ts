import { describe, expect, it } from 'vitest';
import {
  prioritySourceAvailable,
  prioritySourceTime,
} from '@/util/briefingSourceTime';

describe('D-BRF-01/02 source time precision', () => {
  it('keeps a publication day distinct from the first observation', () => {
    const source = {
      publishedAt: null,
      publishedDate: '2026-11-04',
      availableAt: '2026-11-04T00:02:00Z',
      eligibilityBasis: 'first_observed',
    };
    expect(prioritySourceAvailable(source)).toBe(
      Date.parse(source.availableAt),
    );
    expect(prioritySourceTime(source)).toContain(
      '게시일 2026-11-04 · 최초 수집',
    );
    expect(source.publishedAt).toBeNull();
  });
  it('rejects missing clocks, invalid dates and days after observation', () => {
    for (const source of [
      { publishedAt: null },
      {
        publishedAt: null,
        publishedDate: '2026-99-04',
        availableAt: '2026-11-04T00:02:00Z',
        eligibilityBasis: 'first_observed',
      },
      {
        publishedAt: null,
        publishedDate: '2026-11-05',
        availableAt: '2026-11-04T00:02:00Z',
        eligibilityBasis: 'first_observed',
      },
    ])
      expect(prioritySourceAvailable(source)).toBeNaN();
  });
});
