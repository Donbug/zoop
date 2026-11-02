import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ExplicitPersonalBriefing from '@/components/briefing/ExplicitPersonalBriefing';
import { useAuthStore } from '@/stores/useAuthStore';
import { call } from '@/apis/auth/ApiService';
import type { BriefingResponse } from '@/types/briefing';
vi.mock('@/apis/auth/ApiService', () => ({ call: vi.fn() }));
const api = vi.mocked(call);
const round = {
  id: 'r',
  date: '2026-10-22',
  edition: 'morning',
  dataAsOf: '2026-10-22T00:20:00Z',
} as BriefingResponse;
beforeEach(() => {
  api.mockReset();
  useAuthStore.getState().clearSession();
});
function member() {
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
}
it('logged-out users see only the login requirement and no account/selection request', () => {
  render(
    <MemoryRouter>
      <ExplicitPersonalBriefing round={round} compact />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole('link', { name: '로그인 후 개인화 브리핑 만들기' }),
  ).toBeTruthy();
  expect(api).not.toHaveBeenCalled();
});
it('a member starts with no selected companies; import is explicit and POST uses only checked ids', async () => {
  member();
  api.mockResolvedValueOnce({
    companies: [
      { id: 'A', name: '합성 A' },
      { id: 'B', name: '합성 B' },
    ],
    selectedIds: [],
  });
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <ExplicitPersonalBriefing round={round} compact />
    </MemoryRouter>,
  );
  await screen.findByLabelText('합성 A A');
  expect(api).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole('button', { name: '2. 선택 종목으로 브리핑 만들기' }),
  ).toHaveProperty('disabled', true);
  await user.click(screen.getByLabelText('합성 B B'));
  api.mockRejectedValueOnce(new Error('synthetic stop after request'));
  await user.click(
    screen.getByRole('button', { name: '2. 선택 종목으로 브리핑 만들기' }),
  );
  expect(api).toHaveBeenLastCalledWith(
    '/api/v1/briefings/r/personalized/selection',
    'POST',
    { companyIds: ['B'], maxIssues: 3, minIssues: 0, perCompanyLimit: 3 },
  );
  await screen.findByRole('alert');
});
it('logout immediately hides previously chosen private inputs', async () => {
  member();
  api.mockResolvedValueOnce({
    companies: [{ id: 'A', name: '합성 A' }],
    selectedIds: [],
  });
  render(
    <MemoryRouter>
      <ExplicitPersonalBriefing round={round} compact />
    </MemoryRouter>,
  );
  await screen.findByLabelText('합성 A A');
  await act(async () => useAuthStore.getState().clearSession());
  await waitFor(() =>
    expect(
      screen.getByRole('link', { name: '로그인 후 개인화 브리핑 만들기' }),
    ).toBeTruthy(),
  );
  expect(screen.queryByRole('checkbox')).toBeNull();
});
