import { beforeEach, expect, it } from 'vitest';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';

// #381 리뷰: 같은 회원의 세션 복원은 필터를 남기고, 로그아웃·회원 교체는 지운다.
const STOCKS = 'zoop.stocks.personal-filter';
const GRAPH = 'zoop.graph.personal-filter';
const OWNER = 'zoop.private.owner';

const member = (id: string): Session => ({
  authenticated: true,
  kind: 'member',
  user: { id, email: `${id}@zoop.test`, displayName: id },
  setup: { completed: true, tutorialCompleted: true },
  csrfToken: 'csrf-test',
  expiresAt: null,
});

beforeEach(() => {
  sessionStorage.clear();
  useAuthStore.setState({
    status: 'checking',
    session: null,
    member: null,
    onboardingCompleted: null,
  });
});

it('새로 고침 뒤 같은 회원의 세션을 복원하면 고른 필터를 남긴다', () => {
  sessionStorage.setItem(OWNER, 'mem-1');
  sessionStorage.setItem(STOCKS, 'watch');
  sessionStorage.setItem(GRAPH, 'holdings');

  useAuthStore.getState().setSession(member('mem-1'));

  expect(sessionStorage.getItem(STOCKS)).toBe('watch');
  expect(sessionStorage.getItem(GRAPH)).toBe('holdings');
});

it('다른 회원의 세션이 복원되면 이전 회원의 필터를 지운다', () => {
  sessionStorage.setItem(OWNER, 'mem-1');
  sessionStorage.setItem(STOCKS, 'watch');

  useAuthStore.getState().setSession(member('mem-2'));

  expect(sessionStorage.getItem(STOCKS)).toBeNull();
  expect(sessionStorage.getItem(OWNER)).toBe('mem-2');
});

it('주인을 모르는 필터는 복원해도 남기지 않는다', () => {
  sessionStorage.setItem(STOCKS, 'watch');

  useAuthStore.getState().setSession(member('mem-1'));

  expect(sessionStorage.getItem(STOCKS)).toBeNull();
});

it('로그인 중 회원이 바뀌거나 로그아웃하면 필터를 지운다', () => {
  useAuthStore.getState().setSession(member('mem-1'));
  sessionStorage.setItem(STOCKS, 'watch');
  useAuthStore.getState().setSession(member('mem-2'));
  expect(sessionStorage.getItem(STOCKS)).toBeNull();

  sessionStorage.setItem(GRAPH, 'holdings');
  useAuthStore.getState().clearSession();
  expect(sessionStorage.getItem(GRAPH)).toBeNull();
  expect(sessionStorage.getItem(OWNER)).toBeNull();
});
