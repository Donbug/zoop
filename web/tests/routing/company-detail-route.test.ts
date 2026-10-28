import { expect, test } from 'vitest';
import { companyDetailRouteFromMap } from '@/util/company-detail-route';

test('FS044 · D-GRP-03 / M-COM-01 returns to the original company with its selected issue', () => {
  const original =
    '/companies/KRX%3A000660?period=1m&tab=events&asOf=2026-10-08T23%3A59%3A59Z&graphVersion=fixture-2026-10-08&event=issue-a&bucket=2026-09-22';
  const map = new URLSearchParams({
    companyId: 'KRX:000660',
    period: '1m',
    tab: 'events',
    asOf: '2026-10-08T23:59:59Z',
    graphVersion: 'fixture-2026-10-08',
    event: 'issue-a',
    returnTo: original,
  });
  expect(companyDetailRouteFromMap('KRX:000660', map.toString())).toBe(
    original,
  );
});

test('FS044 · D-COM-03 / M-COM-02 changes company but retains period, tab, snapshot and depth 2', () => {
  const map = new URLSearchParams({
    companyId: 'KRX:000660',
    period: '1m',
    tab: 'documents',
    asOf: '2026-10-08T23:59:59Z',
    graphVersion: 'fixture-2026-10-08',
    depth: '2',
    event: 'issue-a',
    bucket: '2026-09-22',
    returnTo: '/companies/KRX%3A000660?event=issue-a',
  });
  expect(companyDetailRouteFromMap('NASDAQ:NVDA', map.toString())).toBe(
    '/companies/NASDAQ%3ANVDA?period=1m&tab=documents&asOf=2026-10-08T23%3A59%3A59Z&graphVersion=fixture-2026-10-08&depth=2',
  );
  expect(companyDetailRouteFromMap('NASDAQ:NVDA', '')).toBe(
    '/companies/NASDAQ%3ANVDA',
  );
});
