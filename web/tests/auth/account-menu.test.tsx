import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import AccountMenu from '@/components/common/AccountMenu';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  noContent,
} from '../support/fakeServer';

const member = (id = 'menu-member'): Session => ({
  authenticated: true,
  kind: 'member',
  user: { id, displayName: `회원 ${id}`, email: `${id}@example.test` },
  setup: { completed: true, tutorialCompleted: true },
  csrfToken: 'synthetic-menu-csrf',
  expiresAt: null,
});
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  useAuthStore.getState().setSession(member());
  server = createFakeServer();
  server.on('POST', '/api/v1/auth/logout', () => noContent());
});
function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}
function open() {
  render(
    <MemoryRouter initialEntries={['/stocks']}>
      <AccountMenu />
      <button>바깥 영역</button>
      <Location />
    </MemoryRouter>,
  );
  return userEvent.setup();
}
it('opens an account summary with just logout without navigating to stocks', async () => {
  const user = open();
  const trigger = screen.getByRole('button', { name: '계정 메뉴 열기' });
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
  const tooltip = document.getElementById(
    trigger.getAttribute('aria-describedby')!,
  );
  expect(tooltip?.textContent).toBe('계정 메뉴 열기');
  await user.click(trigger);
  expect(trigger.getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByText('menu-member@example.test')).toBeTruthy();
  const menu = screen.getByRole('menu', { name: '계정 메뉴' });
  expect(trigger.getAttribute('aria-controls')).toBe(menu.id);
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(1);
  expect(document.activeElement).toBe(
    within(menu).getByRole('menuitem', { name: '로그아웃' }),
  );
  expect(screen.getByTestId('location').textContent).toBe('/stocks');
  await user.click(trigger);
  expect(screen.queryByRole('menu')).toBeNull();
});
it('supports Enter, Space, arrow keys, Escape focus return and Tab dismissal', async () => {
  const user = open();
  await user.tab();
  const trigger = screen.getByRole('button', { name: '계정 메뉴 열기' });
  expect(document.activeElement).toBe(trigger);
  await user.keyboard('{Enter}{ArrowDown}{Home}{End}');
  expect(document.activeElement).toBe(screen.getByRole('menuitem'));
  await user.keyboard('{Escape}');
  expect(document.activeElement).toBe(trigger);
  expect(screen.queryByRole('menu')).toBeNull();
  await user.keyboard(' ');
  expect(screen.getByRole('menu')).toBeTruthy();
  await user.tab();
  expect(screen.queryByRole('menu')).toBeNull();
});
it('opens on a touch tap and closes on an outside tap', async () => {
  const user = open();
  await user.pointer({
    keys: '[TouchA]',
    target: screen.getByRole('button', { name: '계정 메뉴 열기' }),
  });
  expect(screen.getByRole('menu')).toBeTruthy();
  await user.pointer({
    keys: '[TouchA]',
    target: screen.getByRole('button', { name: '바깥 영역' }),
  });
  expect(screen.queryByRole('menu')).toBeNull();
});
it('keeps the confirmed account on logout failure and retries with cookies and CSRF', async () => {
  const user = open();
  const response = deferred<Response>();
  server.on('POST', '/api/v1/auth/logout', () => response.promise);
  await user.click(screen.getByRole('button', { name: '계정 메뉴 열기' }));
  await user.click(screen.getByRole('menuitem', { name: '로그아웃' }));
  const pending = screen.getByRole('menuitem', {
    name: '로그아웃하고 있어요',
  }) as HTMLButtonElement;
  expect(pending.disabled).toBe(true);
  // Native browsers can blur a focused button when disabled (jsdom does not).
  fireEvent.blur(pending, { relatedTarget: null });
  expect(screen.getByRole('menu')).toBeTruthy();
  await user.click(pending);
  expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(1);
  await act(async () => response.resolve(apiError(503, 'SOURCE_UNAVAILABLE')));
  await screen.findByRole('alert');
  expect(document.activeElement).toBe(
    screen.getByRole('menuitem', { name: '로그아웃 다시 시도' }),
  );
  expect(useAuthStore.getState().member?.id).toBe('menu-member');
  expect(screen.getByTestId('location').textContent).toBe('/stocks');
  server.on('POST', '/api/v1/auth/logout', () => noContent());
  await user.click(
    screen.getByRole('menuitem', { name: '로그아웃 다시 시도' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('location').textContent).toBe('/login'),
  );
  expect(useAuthStore.getState().member).toBeNull();
  expect(screen.queryByRole('menu')).toBeNull();
  const request = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => String(url).endsWith('/auth/logout'))
    .at(-1)?.[1];
  expect(request?.credentials).toBe('include');
  expect(new Headers(request?.headers).get('X-CSRF-Token')).toBe(
    'synthetic-menu-csrf',
  );
  expect(new Headers(request?.headers).has('Authorization')).toBe(false);
});
it.each(['success', 'failure'])(
  'ignores an old logout %s after a member switch',
  async (result) => {
    const user = open();
    const response = deferred<Response>();
    server.on('POST', '/api/v1/auth/logout', () => response.promise);
    await user.click(screen.getByRole('button', { name: '계정 메뉴 열기' }));
    await user.click(screen.getByRole('menuitem', { name: '로그아웃' }));
    await act(async () =>
      useAuthStore.getState().setSession(member('next-member')),
    );
    expect(screen.queryByRole('menu')).toBeNull();
    await act(async () =>
      response.resolve(
        result === 'success'
          ? noContent()
          : apiError(503, 'SOURCE_UNAVAILABLE'),
      ),
    );
    expect(useAuthStore.getState().member?.id).toBe('next-member');
    expect(screen.getByTestId('location').textContent).toBe('/stocks');
    await user.click(screen.getByRole('button', { name: '계정 메뉴 열기' }));
    expect(screen.getByText('next-member@example.test')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect((screen.getByRole('menuitem') as HTMLButtonElement).disabled).toBe(
      false,
    );
  },
);
it('shows login instead of account details for nonmembers', () => {
  useAuthStore.getState().clearSession();
  open();
  expect(
    screen.getByRole('link', { name: '로그인' }).getAttribute('href'),
  ).toBe('/login');
  expect(screen.queryByRole('button', { name: '계정 메뉴 열기' })).toBeNull();
  expect(screen.queryByText('menu-member@example.test')).toBeNull();
});
