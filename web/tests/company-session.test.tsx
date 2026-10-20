import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import PriceChart from '@/components/company/PriceChart';
import { timeRange } from '@/components/company/detail-model';
import type { Events } from '@/types/company/detail';

test('D-COM-05: 1d leaves session selection to BE; longer periods keep from', () => {
  expect(timeRange('2026-10-20T12:00:00+09:00', '1d')).toEqual({
    to: '2026-10-20T03:00:00.000Z',
  });
  expect(timeRange('2026-10-20T03:00:00Z', '1w').from).toBe(
    '2026-10-13T03:00:00.000Z',
  );
});

test.each([
  ['2026-10-20T00:00:00Z', '2026-10-20T03:00:00Z', '2026-10-20'],
  // Previous US session: exchange date must not shift to the Korean date.
  ['2026-10-16T13:30:00Z', '2026-10-16T20:00:00Z', '2026-10-16'],
])(
  'D-COM-05: server session controls axis and excludes outside markers (%s)',
  (from, to, sessionDate) => {
    const event = (eventTime: string): Events['items'] => [
      {
        id: eventTime,
        title: '세션 테스트 사건',
        eventTime,
        timePrecision: 'datetime',
        reportedAt: eventTime,
        relationTypes: [],
        companyIds: [],
        articleCount: 1,
      },
    ];
    const before = new Date(Date.parse(from) - 300000).toISOString();
    const after = new Date(Date.parse(to) + 300000).toISOString();
    const { container } = render(
      <PriceChart
        points={[
          { time: from, close: 100 },
          { time: to, close: 120 },
        ]}
        asOf="2026-10-20T03:00:00Z"
        period="1d"
        range={{ from, to, sessionDate }}
        groups={
          new Map([
            ['before', event(before)],
            ['inside', event(from)],
            ['after', event(after)],
          ])
        }
        selectedBucket={null}
        selectedEvent={null}
        onBucket={() => {}}
      />,
    );
    expect(container.querySelector('polyline')?.getAttribute('points')).toBe(
      '10,160 530,20',
    );
    expect(
      screen.getByText(
        `${sessionDate} 장 · 거래소 현지 거래일 · 시간 표시는 KST`,
      ),
    ).toBeTruthy();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(
      screen.getByRole('button', { name: '차트 사건 inside · 사건 1건' }),
    ).toBeTruthy();
  },
);

test('D-COM-05: older API without range retains the 24h axis', () => {
  const { container } = render(
    <PriceChart
      points={[
        { time: '2026-10-19T03:00:00Z', close: 100 },
        { time: '2026-10-20T03:00:00Z', close: 120 },
      ]}
      asOf="2026-10-20T03:00:00Z"
      period="1d"
      groups={new Map()}
      selectedBucket={null}
      selectedEvent={null}
      onBucket={() => {}}
    />,
  );
  expect(container.querySelector('polyline')?.getAttribute('points')).toBe(
    '10,160 530,20',
  );
  expect(screen.queryByText(/거래소 현지 거래일/)).toBeNull();
});
