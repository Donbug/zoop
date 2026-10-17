import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import PriceChart from '@/components/company/PriceChart';
import type { Event } from '@/types/company/detail';
import { readCompanyResource } from '@/apis/company/company';
import { createFakeServer, json } from './support/fakeServer';

const event: Event = {
  id: 'fixture-event',
  title: '합성 사건',
  eventTime: '2026-10-05T03:00:00Z',
  timePrecision: 'datetime',
  reportedAt: null,
  relationTypes: [],
  companyIds: ['fixture-company'],
  articleCount: 1,
};
const props = {
  asOf: '2026-10-06T03:00:00Z',
  period: '1m' as const,
  selectedBucket: null,
  selectedEvent: null,
  onSelect: vi.fn(),
  onBucket: vi.fn(),
};

test('a bucket without a price bar still has one keyboard accessible marker', async () => {
  const onBucket = vi.fn();
  render(
    <PriceChart
      {...props}
      onBucket={onBucket}
      points={[{ time: props.asOf, close: 120 }]}
      groups={
        new Map([['2026-10-05', [event, { ...event, id: 'fixture-other' }]]])
      }
    />,
  );
  const marker = screen.getByRole('button', {
    name: '차트 사건 2026-10-05 · 사건 2건',
  });
  marker.focus();
  await userEvent.keyboard('{Enter}');
  expect(onBucket).toHaveBeenCalledWith('2026-10-05');
  expect(screen.getAllByRole('button', { name: /^차트 사건/ })).toHaveLength(1);
});

test('multiple price bars in one event bucket do not duplicate its marker', () => {
  render(
    <PriceChart
      {...props}
      points={[
        { time: '2026-10-05T01:00:00Z', close: 100 },
        { time: '2026-10-05T03:00:00Z', close: 110 },
      ]}
      groups={new Map([['2026-10-05', [event]]])}
    />,
  );
  expect(screen.getAllByRole('button', { name: /^차트 사건/ })).toHaveLength(1);
});

test('the chart positions prices by elapsed time instead of index', () => {
  render(
    <PriceChart
      {...props}
      points={[
        { time: '2026-09-06T03:00:00Z', close: 100 },
        { time: '2026-09-07T03:00:00Z', close: 110 },
        { time: props.asOf, close: 120 },
      ]}
      groups={new Map()}
    />,
  );
  const line = screen
    .getByRole('group', { name: '공급된 종가 차트' })
    .querySelector('polyline')!;
  const positions = line
    .getAttribute('points')!
    .split(' ')
    .map((pair) => Number(pair.split(',')[0]));
  expect(positions[1] - positions[0]).toBeLessThan(
    (positions[2] - positions[1]) / 20,
  );
});

test('an event response for another cutoff is rejected despite matching version', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/events/:id', () =>
    json({
      ...event,
      metadata: { asOf: '2026-10-07T03:00:00Z', graphVersion: 'fixture-v1' },
    }),
  );
  await expect(
    readCompanyResource(
      `/api/v1/events/${event.id}?asOf=${props.asOf}&graphVersion=fixture-v1`,
    ),
  ).rejects.toThrow('기준 시점');
});

test('prices outside the requested range are rejected', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id/prices', () =>
    json({
      status: 'available',
      companyId: 'fixture-company',
      period: '1m',
      points: [{ time: '2026-10-07T03:00:00Z', close: 130 }],
    }),
  );
  await expect(
    readCompanyResource(
      `/api/v1/companies/fixture-company/prices?period=1m&from=2026-09-06T03:00:00Z&to=${props.asOf}`,
    ),
  ).rejects.toThrow('조회 범위 밖');
});

test('a bucket-start bar before from is kept; only bars after the cutoff are rejected', async () => {
  const server = createFakeServer();
  const points = [
    // 일봉은 구간 시작 시각(한국 자정)으로 찍혀 from(15:30)보다 앞선다.
    { time: '2026-09-15T15:00:00Z', close: 100 },
    { time: props.asOf, close: 120 },
  ];
  server.on('GET', '/api/v1/companies/:id/prices', () =>
    json({
      status: 'available',
      companyId: 'fixture-company',
      period: '1m',
      points,
    }),
  );
  const prices = await readCompanyResource<{ points: unknown[] }>(
    `/api/v1/companies/fixture-company/prices?period=1m&from=2026-09-16T06:30:00Z&to=${props.asOf}`,
  );
  expect(prices.points).toEqual(points);
});

test('a day-precision event gets a marker on the same KST day in the 1w chart', () => {
  const dayEvent: Event = {
    ...event,
    eventTime: '2026-10-05',
    timePrecision: 'day',
  };
  render(
    <PriceChart
      {...props}
      period="1w"
      points={[
        { time: '2026-10-04T23:00:00Z', close: 100 },
        { time: props.asOf, close: 120 },
      ]}
      groups={new Map([['2026-10-05 · 일 정밀도', [dayEvent]]])}
    />,
  );
  expect(
    screen.getByRole('button', {
      name: '차트 사건 2026-10-05 · 일 정밀도 · 사건 1건',
    }),
  ).toBeTruthy();
});
