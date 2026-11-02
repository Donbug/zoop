import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, test } from 'vitest';
import { useCompanyShortPrices } from '@/hooks/useCompanyShortPrices';
import { createFakeServer, deferred, json } from '../support/fakeServer';
test('D-COM-01 D12 checks exactly two periods per company/cutoff and reuses them on rerender', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id/prices', (r) =>
    json({
      status: 'unavailable',
      reason: `${r.params.id}:${r.query.get('period')}`,
    }),
  );
  const props = { id: 'A', asOf: '2026-10-06T03:00:00Z', enabled: true };
  const { result, rerender } = renderHook(
    (p) => useCompanyShortPrices(p.id, p.asOf, p.enabled),
    { initialProps: props },
  );
  await waitFor(() =>
    expect(result.current['1w'].data?.status).toBe('unavailable'),
  );
  expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(2);
  rerender({ ...props });
  expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(2);
  rerender({ ...props, asOf: '2026-10-07T03:00:00Z' });
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(4),
  );
  rerender({ ...props, id: 'B' });
  await waitFor(() =>
    expect(result.current['1d'].data).toMatchObject({ reason: 'B:1d' }),
  );
  expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(6);
});
test('D-COM-01 D12 ignores late prices after a company change and does not fetch before enabled', async () => {
  const server = createFakeServer(),
    pending = deferred<Response>();
  server.on('GET', '/api/v1/companies/:id/prices', (r) =>
    r.params.id === 'A'
      ? pending.promise
      : json({ status: 'unavailable', reason: 'B 시세 없음' }),
  );
  const props = { id: 'A', asOf: '2026-10-06T03:00:00Z', enabled: false };
  const { result, rerender } = renderHook(
    (p) => useCompanyShortPrices(p.id, p.asOf, p.enabled),
    { initialProps: props },
  );
  expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(0);
  rerender({ ...props, enabled: true });
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(2),
  );
  rerender({ ...props, enabled: true, id: 'B' });
  await waitFor(() =>
    expect(result.current['1d'].data).toMatchObject({ reason: 'B 시세 없음' }),
  );
  await act(async () =>
    pending.resolve(json({ status: 'unavailable', reason: 'A 늦은 응답' })),
  );
  expect(result.current['1d'].data).toMatchObject({ reason: 'B 시세 없음' });
});
