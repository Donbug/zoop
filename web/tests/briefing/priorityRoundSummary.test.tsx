import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import PriorityRoundSummary from '@/components/briefing/PriorityRoundSummary';
import { commonPriorityOf } from '@/util/briefingCommonPriority';
import { personalPriorityOf } from '@/util/briefingPersonalPriority';
import type { BriefingResponse } from '@/types/briefing';
const result = {
  id: 'r',
  dataAsOf: '2026-11-02T00:20:00Z',
  edition: 'morning',
  references: { eventIds: [], companyIds: [], evidenceIds: ['e'] },
  marketSummary: { text: '기존 요약', resultVersion: 'old' },
  prioritySummary: {
    schemaVersion: 'briefing-priority-summary-v1',
    roundId: 'r',
    cutoff: '2026-11-02T00:20:00Z',
    resultVersion: 'new',
    evidenceIds: ['e'],
    text: '판단\n\n새 사실\n\n판단 변화\n\n조건부 전망\n\n다음 확인',
  },
} as unknown as BriefingResponse;
test('saved summary reveals next checks and preserves the old text', async () => {
  render(<PriorityRoundSummary result={result} compact />);
  expect(screen.getByRole('heading', { name: '오늘의 판단' })).toBeTruthy();
  const detail = screen
    .getByText('판단 변화·전망·다음 확인사항')
    .closest('details')!;
  expect(detail.open).toBe(false);
  await userEvent
    .setup()
    .click(screen.getByText('판단 변화·전망·다음 확인사항'));
  expect(detail.open).toBe(true);
  expect(screen.getByText('기존 요약')).toBeTruthy();
});
test('summary refuses another round or foreign evidence', () => {
  const { rerender } = render(
    <PriorityRoundSummary result={{ ...result, id: 'wrong' }} compact />,
  );
  expect(screen.getByRole('alert')).toBeTruthy();
  rerender(
    <PriorityRoundSummary
      result={{
        ...result,
        prioritySummary: {
          ...result.prioritySummary!,
          evidenceIds: ['foreign'],
        },
      }}
      compact
    />,
  );
  expect(screen.getByRole('alert')).toBeTruthy();
  expect(screen.queryByText('판단 변화·전망·다음 확인사항')).toBeNull();
});
test('malformed optional views fail closed without crashing legacy screens', () => {
  for (const invalid of [
    null,
    'invalid',
    [],
    { items: [null] },
    { companyIds: null },
  ]) {
    expect(() =>
      commonPriorityOf({
        ...result,
        commonPriority: invalid,
      } as unknown as BriefingResponse),
    ).not.toThrow();
    expect(() =>
      personalPriorityOf({
        ...result,
        personalPriority: invalid,
      } as unknown as BriefingResponse),
    ).not.toThrow();
  }
});
