import { beforeEach, expect, test, vi } from 'vitest';
import { loadSession, logout } from '@/apis/auth/auth';
import { call, ApiError } from '@/apis/auth/ApiService';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { getGraph } from '@/apis/graph/graph';
import { memberDestination } from '@/apis/auth/member-session';
import type { Session } from '@/types/auth';
import {
  createFakeServer,
  deferred,
  json,
  apiError,
  noContent,
} from '../support/fakeServer';

const anonymous: Session = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};
const member = (id = 'synthetic-a'): Session => ({
  authenticated: true,
  kind: 'member',
  user: { id, email: 'synthetic@example.test', displayName: '합성' },
  setup: { completed: true, tutorialCompleted: false },
  csrfToken: 'synthetic-csrf',
  expiresAt: null,
});
const guest: Session = {
  ...anonymous,
  authenticated: true,
  kind: 'guest',
  csrfToken: 'synthetic-guest-csrf',
};
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  useAuthStore.getState().clearSession();
  useAuthStore.setState({ status: 'checking' });
  server = createFakeServer();
});

test('late anonymous session response cannot replace a newer successful login', async () => {
  const response = deferred<Response>();
  server.on('GET', '/api/v1/auth/session', () => response.promise);
  const request = loadSession(true).catch(() => null);
  useAuthStore.getState().setSession(member());
  response.resolve(json(anonymous));
  await request;
  expect(useAuthStore.getState().member?.id).toBe('synthetic-a');
});
test('late member response cannot resurrect logout', async () => {
  const response = deferred<Response>();
  server.on('GET', '/api/v1/auth/session', () => response.promise);
  const request = loadSession(true).catch(() => null);
  useAuthStore.getState().clearSession();
  response.resolve(json(member()));
  await request;
  expect(useAuthStore.getState().member).toBeNull();
});
test('stale API 401 does not erase another member session', async () => {
  useAuthStore.getState().setSession(member());
  const response = deferred<Response>();
  server.on('GET', '/api/v1/portfolio', () => response.promise);
  const request = call('/api/v1/portfolio', 'GET').catch(() => null);
  useAuthStore.getState().setSession(member('synthetic-b'));
  response.resolve(apiError(401, 'SESSION_EXPIRED'));
  await request;
  expect(useAuthStore.getState().member?.id).toBe('synthetic-b');
});
test('member transition and current 401 clear private onboarding draft', async () => {
  useAuthStore.getState().setSession(member());
  useOnboardingStore.getState().toggleWatchlist('private-a');
  useAiChatStore.getState().setDraft('private-a');
  useAuthStore.getState().setSession(member('synthetic-b'));
  expect(useOnboardingStore.getState().watchlistIds).toEqual([]);
  expect(useAiChatStore.getState().draft).toBe('');
  useOnboardingStore.getState().toggleWatchlist('private-b');
  server.on('GET', '/api/v1/portfolio', () => apiError(401, 'SESSION_EXPIRED'));
  await call('/api/v1/portfolio', 'GET').catch(() => null);
  expect(useOnboardingStore.getState().watchlistIds).toEqual([]);
  expect(useAiChatStore.getState().draft).toBe('');
  expect(useAuthStore.getState().member).toBeNull();
});
test('guest mutations include CSRF and cookies but no Authorization or refresh', async () => {
  useAuthStore.getState().setSession(guest);
  const fetchMock = vi.fn<typeof fetch>(async () => noContent());
  vi.stubGlobal('fetch', fetchMock);
  await call('/api/v1/auth/tutorial', 'POST', {});
  const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
  expect(init?.credentials).toBe('include');
  expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(
    'synthetic-guest-csrf',
  );
  expect(new Headers(init?.headers).has('Authorization')).toBe(false);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
test('common failures retain HTTP status and business code', async () => {
  server.on('PUT', '/api/v1/me/settings', () =>
    apiError(409, 'VERSION_CONFLICT'),
  );
  await expect(call('/api/v1/me/settings', 'PUT', {})).rejects.toMatchObject({
    status: 409,
    code: 'VERSION_CONFLICT',
  });
  await expect(call('/api/v1/me/settings', 'PUT', {})).rejects.toBeInstanceOf(
    ApiError,
  );
});
test('local forged tokens cannot permit a personalized graph', async () => {
  localStorage.setItem('accessToken', 'synthetic-forged');
  useAuthStore.getState().clearSession();
  await expect(
    getGraph({ mode: 'personal', personalFilter: 'all' }),
  ).rejects.toThrow(/로그인/);
  localStorage.removeItem('accessToken');
});
test('logout posts to server with CSRF and clears client state', async () => {
  useAuthStore.getState().setSession(member());
  useOnboardingStore.getState().toggleWatchlist('private');
  const fetchMock = vi.fn<typeof fetch>(async () => noContent());
  vi.stubGlobal('fetch', fetchMock);
  await logout();
  expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/auth/logout');
  const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
  expect(init?.method).toBe('POST');
  expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('synthetic-csrf');
  expect(useAuthStore.getState().member).toBeNull();
  expect(useOnboardingStore.getState().watchlistIds).toEqual([]);
  expect(useAiChatStore.getState().draft).toBe('');
});
test('known zero portfolio and interests select market mode', async () => {
  useAuthStore.getState().setSession(member());
  server.on('GET', '/api/v1/me/settings', () => json({ watchlistIds: [] }));
  server.on('GET', '/api/v1/portfolio', () => json({ holdings: [] }));
  expect(await memberDestination(member())).toBe('/?mode=all');
});
