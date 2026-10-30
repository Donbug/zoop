import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ScheduledPersonalBriefing from '@/components/briefing/ScheduledPersonalBriefing';
import { call } from '@/apis/auth/ApiService';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BriefingResponse } from '@/types/briefing';
vi.mock('@/apis/auth/ApiService', () => ({ call: vi.fn() }));
vi.mock('@/components/briefing/IssueCentricBriefing', () => ({
  default: ({ result }: { result: { marker?: string } }) => (
    <div>{result.marker}</div>
  ),
}));
const api = vi.mocked(call),
  settingsPath = '/api/v1/briefings/personalization/settings';
const round = {
  id: 'r',
  date: '2026-10-22',
  edition: 'morning',
  dataAsOf: '2026-10-22T00:20:00Z',
} as BriefingResponse;
const choice = {
  companyIds: ['A'],
  maxIssues: 3,
  minIssues: 0,
  perCompanyLimit: 3,
};
const saved = {
  demoEnabled: false,
  nextScheduledAt: '2026-10-30T08:30:00Z',
  preference: {
    revisionId: 'p1',
    choice,
    effectiveFrom: '2026-10-30T08:30:00Z',
  },
};
const options = {
  companies: [
    { id: 'A', name: 'Apple', logoUrl: '/graph-assets/apple.svg' },
    { id: 'B', name: '삼성전자', logoUrl: null },
  ],
  selectedIds: [],
};
const delivered = {
  status: 'ready',
  mode: 'scheduled',
  roundId: 'r',
  selection: {
    roundId: 'r',
    choice,
    minimumShortfall: 0,
    presentation: { marker: 'already published result', items: [] },
    details: {},
    tracking: [],
  },
};
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
    csrfToken: 'test',
    expiresAt: null,
  });
}
function renderPage() {
  return render(
    <MemoryRouter>
      <ScheduledPersonalBriefing round={round} compact />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  api.mockReset();
  useAuthStore.getState().clearSession();
});
it('requires login and never requests private settings for guests', () => {
  renderPage();
  expect(
    screen.getByRole('link', { name: '로그인 후 개인화 브리핑 설정' }),
  ).toBeTruthy();
  expect(api).not.toHaveBeenCalled();
});
it('opens the logo-bearing chooser only on search focus and saves a prospective setting without generation', async () => {
  member();
  api.mockImplementation(async (path, method) => {
    if (path === settingsPath && method === 'PUT') return saved;
    if (path.startsWith(settingsPath)) return { ...saved, preference: null };
    if (path.includes('/options')) return options;
    return { status: 'not_published', roundId: 'r' };
  });
  const user = userEvent.setup();
  renderPage();
  await user.click(await screen.findByRole('button', { name: '종목 설정' }));
  expect(screen.queryByRole('checkbox')).toBeNull();
  await user.click(screen.getByLabelText('기준 종목 검색'));
  await user.click(screen.getByLabelText('Apple A'));
  expect(
    document.querySelector('img[src="/graph-assets/apple.svg"]'),
  ).toBeTruthy();
  await user.click(screen.getByRole('button', { name: '목록 닫기' }));
  expect(screen.queryByRole('checkbox')).toBeNull();
  await user.click(screen.getByRole('button', { name: '브리핑 설정 저장' }));
  await screen.findByText(/이미 나온 브리핑은 유지됩니다/);
  expect(api).toHaveBeenCalledWith(settingsPath, 'PUT', {
    choice,
    expectedRevision: null,
  });
  expect(
    api.mock.calls.filter(
      (c) => c[1] === 'POST' && !c[0].endsWith('/initialize'),
    ),
  ).toHaveLength(0);
  expect(screen.queryByText('현재 설정으로 데모 보기')).toBeNull();
});
it('loads an immutable published result automatically and leaves it unchanged after saving a new preference', async () => {
  member();
  api.mockImplementation(async (path, method) => {
    if (path === settingsPath && method === 'PUT')
      return {
        ...saved,
        preference: {
          ...saved.preference,
          revisionId: 'p2',
          choice: { ...choice, companyIds: ['B'] },
        },
      };
    if (path.startsWith(settingsPath)) return saved;
    if (path.includes('/options')) return options;
    return delivered;
  });
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('already published result');
  await user.click(screen.getByRole('button', { name: '설정 변경' }));
  await user.click(screen.getByLabelText('기준 종목 검색'));
  await user.click(screen.getByLabelText('Apple A'));
  await user.click(screen.getByLabelText('삼성전자 B'));
  await user.click(screen.getByRole('button', { name: '브리핑 설정 저장' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(settingsPath, 'PUT', {
      choice: { ...choice, companyIds: ['B'] },
      expectedRevision: 'p1',
    }),
  );
  expect(screen.getByText('already published result')).toBeTruthy();
  expect(
    api.mock.calls.filter(
      (c) => c[1] === 'POST' && !c[0].endsWith('/initialize'),
    ),
  ).toHaveLength(0);
});
it('a demo is explicitly operator-enabled, separately labelled and never created from a page read', async () => {
  member();
  api.mockImplementation(async (path, method) => {
    if (path.startsWith(settingsPath)) return { ...saved, demoEnabled: true };
    if (path.includes('/options')) return options;
    if (method === 'POST') return { ...delivered, mode: 'demo' };
    return { status: 'not_published', roundId: 'r' };
  });
  const user = userEvent.setup();
  renderPage();
  await screen.findByText('데모 미리보기');
  expect(
    api.mock.calls.filter(
      (c) => c[1] === 'POST' && !c[0].endsWith('/initialize'),
    ),
  ).toHaveLength(0);
  await user.click(screen.getByText('데모 미리보기'));
  await user.click(
    screen.getByRole('button', { name: '현재 설정으로 데모 보기' }),
  );
  await screen.findByText('already published result');
  expect(api).toHaveBeenCalledWith(
    '/api/v1/briefings/r/personalized/demo',
    'POST',
    { preferenceRevision: 'p1' },
  );
  expect(screen.getByText(/별도 데모 기록/)).toBeTruthy();
});
it('logout hides the member result immediately', async () => {
  member();
  api.mockImplementation(async (path) =>
    path === settingsPath
      ? saved
      : path.includes('/options')
        ? options
        : delivered,
  );
  renderPage();
  await screen.findByText('already published result');
  await act(async () => useAuthStore.getState().clearSession());
  expect(screen.queryByText('already published result')).toBeNull();
  expect(
    screen.getByRole('link', { name: '로그인 후 개인화 브리핑 설정' }),
  ).toBeTruthy();
});

it('keeps settings editable when a published round is temporarily unavailable', async () => {
  member();
  api.mockImplementation(async (path) => {
    if (path.startsWith(settingsPath)) return saved;
    if (path.includes('/options')) return options;
    throw new Error('source unavailable');
  });
  const user = userEvent.setup();
  renderPage();
  await user.click(await screen.findByRole('button', { name: '설정 변경' }));
  expect(screen.getByLabelText('기준 종목 검색')).toBeTruthy();
  expect(screen.getByText(/발행 기록을 불러오지 못했어요/)).toBeTruthy();
});

it('initializes from holdings/watchlist without opening the chooser or generating an issue', async () => {
  member();
  api.mockImplementation(async (path) =>
    path.startsWith(settingsPath)
      ? { ...saved, initializationStatus: 'initialized' }
      : path.includes('/options')
        ? options
        : { status: 'not_published', roundId: 'r' },
  );
  renderPage();
  await screen.findByText(/보유·관심 종목으로 기본 설정했습니다/);
  expect(api).toHaveBeenCalledWith(settingsPath + '/initialize', 'POST');
  expect(screen.queryByRole('combobox')).toBeNull();
  expect(screen.queryByText('추가 설정 · 이슈 수')).toBeNull();
  expect(
    api.mock.calls.filter(
      (c) => c[1] === 'POST' && !c[0].endsWith('/initialize'),
    ),
  ).toHaveLength(0);
});
it('no holdings and no watchlist means no default profile and no automatic briefing', async () => {
  member();
  api.mockImplementation(async (path) =>
    path.startsWith(settingsPath)
      ? { ...saved, preference: null, initializationStatus: 'no_companies' }
      : path.includes('/options')
        ? options
        : { status: 'not_published', roundId: 'r' },
  );
  renderPage();
  await screen.findByText(
    /보유·관심 종목이 없어 개인화 브리핑을 제공하지 않습니다/,
  );
  expect(screen.queryByRole('combobox')).toBeNull();
  expect(screen.queryByText('추가 설정 · 이슈 수')).toBeNull();
  expect(screen.getByRole('link', { name: '내 종목 설정' })).toBeTruthy();
  expect(
    api.mock.calls.filter(
      (c) => c[1] === 'POST' && !c[0].endsWith('/initialize'),
    ),
  ).toHaveLength(0);
});
