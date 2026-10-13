import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useGraphData } from '@/hooks/useGraphData';
import { getGraph } from '@/apis/graph/graph';
import { createMockGraph } from '@/mocks/graph/response';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';

vi.mock('@/apis/graph/graph', () => ({ getGraph: vi.fn() }));
const mocked = vi.mocked(getGraph);
const all: GraphRequest = { mode: 'all', personalFilter: 'all' };
const personal: GraphRequest = {
  mode: 'personal',
  personalFilter: 'watchlist',
};
beforeEach(() => mocked.mockReset());
describe('D-GRP-01/01b async states', () => {
  it('discards a late response after a fast filter switch', async () => {
    let resolveFirst!: (value: GraphResponse) => void;
    mocked.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        }),
    );
    mocked.mockResolvedValueOnce(createMockGraph(personal));
    const { result, rerender } = renderHook(
      ({ request }) => useGraphData(request, 'test-member', 0),
      { initialProps: { request: all } },
    );
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    rerender({ request: personal });
    await waitFor(() =>
      expect(result.current.data?.metadata.mode).toBe('personal'),
    );
    await act(async () => resolveFirst(createMockGraph(all)));
    expect(result.current.data?.metadata.personalFilter).toBe('watchlist');
  });
  it('keeps the previous graph when a request fails and retries', async () => {
    mocked
      .mockResolvedValueOnce(createMockGraph(all))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(createMockGraph(personal));
    const { result, rerender } = renderHook(
      ({ request, retry }) => useGraphData(request, 'test-member', retry),
      { initialProps: { request: all, retry: 0 } },
    );
    await waitFor(() => expect(result.current.data).not.toBeNull());
    rerender({ request: personal, retry: 0 });
    await waitFor(() => expect(result.current.error).toBe('offline'));
    expect(result.current.data?.metadata.mode).toBe('all');
    rerender({ request: personal, retry: 1 });
    await waitFor(() =>
      expect(result.current.data?.metadata.mode).toBe('personal'),
    );
  });
  it('never retains personal data across logout or a new member session', async () => {
    mocked
      .mockResolvedValueOnce(createMockGraph(personal))
      .mockResolvedValue(createMockGraph(all));
    const { result, rerender } = renderHook(
      ({ request, token }) => useGraphData(request, token, 0),
      {
        initialProps: {
          request: personal as GraphRequest,
          token: 'member-a' as string | null,
        },
      },
    );
    await waitFor(() =>
      expect(result.current.data?.metadata.mode).toBe('personal'),
    );
    rerender({ request: all, token: null });
    expect(result.current.data).toBeNull();
    rerender({ request: personal, token: 'member-b' });
    expect(result.current.data).toBeNull();
  });
});
