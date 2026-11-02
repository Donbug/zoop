import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ExplicitPersonalBriefing from '@/components/briefing/ExplicitPersonalBriefing';
import { useAuthStore } from '@/stores/useAuthStore';
import { call } from '@/apis/auth/ApiService';
import type { BriefingResponse } from '@/types/briefing';
vi.mock('@/apis/auth/ApiService', () => ({ call: vi.fn() }));
vi.mock('@/components/briefing/IssueCentricBriefing', () => ({
  default: ({ result }: { result: { ready?: boolean } }) => (
    <p>
      {result.ready
        ? 'synthetic verified analysis'
        : 'synthetic pending analysis'}
    </p>
  ),
}));
const api = vi.mocked(call);
const cutoff = '2026-10-22T00:20:00Z';
const round = {
  id: 'r',
  date: '2026-10-22',
  edition: 'morning',
  dataAsOf: cutoff,
} as BriefingResponse;
const choice = {
  companyIds: ['A'],
  maxIssues: 3,
  minIssues: 0,
  perCompanyLimit: 3,
};
const result = (ready = false) => ({
  roundId: 'r',
  dataAsOf: cutoff,
  selectionVersion: 's',
  choice,
  eligibleCount: 3,
  matchingCount: 1,
  minimumShortfall: 0,
  pendingAnalysisCount: ready ? 0 : 1,
  analysisStatus: ready ? 'ready' : 'needs_generation',
  presentation: { ready, items: [] },
  details: {},
  tracking: [],
});
beforeEach(() => {
  api.mockReset();
  useAuthStore.getState().clearSession();
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: {
      id: 'm',
      email: 'synthetic@example.invalid',
      displayName: '합성',
    },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'synthetic',
    expiresAt: null,
  });
});
async function start() {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <ExplicitPersonalBriefing round={round} compact />
    </MemoryRouter>,
  );
  await user.click(await screen.findByLabelText('합성 A A'));
  await user.click(
    screen.getByRole('button', { name: '2. 선택 종목으로 브리핑 만들기' }),
  );
  return user;
}
it('submits the exact choice/version once then polls a saved job without starting AI from GET', async () => {
  api
    .mockResolvedValueOnce({
      companies: [{ id: 'A', name: '합성 A' }],
      selectedIds: [],
    })
    .mockResolvedValueOnce(result())
    .mockResolvedValueOnce({
      id: 'j',
      status: 'queued',
      selectionVersion: 's',
      selection: result(),
    })
    .mockResolvedValueOnce({
      id: 'j',
      status: 'ready',
      selectionVersion: 's',
      selection: result(true),
    });
  await start();
  await screen.findByText('synthetic verified analysis', {}, { timeout: 4000 });
  expect(api).toHaveBeenCalledWith(
    '/api/v1/briefings/r/personalized/generations',
    'POST',
    { choice, selectionVersion: 's' },
  );
  expect(api).toHaveBeenLastCalledWith(
    '/api/v1/briefings/r/personalized/generations/j',
    'GET',
  );
  expect(
    api.mock.calls.filter(
      (c) => c[1] === 'POST' && c[0].endsWith('/generations'),
    ),
  ).toHaveLength(1);
});
it('does not install a late generated response for another company even if its version string matches', async () => {
  const changed = { ...result(true), choice: { ...choice, companyIds: ['B'] } };
  api
    .mockResolvedValueOnce({
      companies: [{ id: 'A', name: '합성 A' }],
      selectedIds: [],
    })
    .mockResolvedValueOnce(result())
    .mockResolvedValueOnce({
      id: 'j',
      status: 'queued',
      selectionVersion: 's',
      selection: result(),
    })
    .mockResolvedValueOnce({
      id: 'j',
      status: 'ready',
      selectionVersion: 's',
      selection: changed,
    });
  await start();
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy(), {
    timeout: 4000,
  });
  expect(screen.queryByText('synthetic verified analysis')).toBeNull();
});
