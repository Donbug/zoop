import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import BottomNav from '@/components/common/BottomNav';
import SignupForm from '@/components/auth/SignupForm';
import { useAuthStore } from '@/stores/useAuthStore';
import { createFakeServer, json } from '../support/fakeServer';

beforeEach(() => {
  useAuthStore.getState().setSession({
    authenticated: false,
    kind: 'anonymous',
    user: null,
    setup: null,
    csrfToken: null,
    expiresAt: null,
  });
});

it('F1 common mobile navigation uses theme ink for the current destination', () => {
  render(
    <MemoryRouter initialEntries={['/my']}>
      <BottomNav />
    </MemoryRouter>,
  );
  const current = screen.getByRole('link', { name: '내 종목' });
  expect(current.getAttribute('aria-current')).toBe('page');
  expect(current.classList.contains('text-zoop-ink')).toBe(true);
  expect(current.classList.contains('text-black')).toBe(false);
  expect(
    screen
      .getByRole('link', { name: '종목' })
      .classList.contains('text-zoop-muted'),
  ).toBe(true);
});

it('D-AUT-02 F2 uses muted ink for password guidance and term disclosures', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/auth/terms', () =>
    json({
      items: [
        {
          id: 'fixture-terms',
          title: '합성 필수 약관',
          required: true,
          body: '합성 약관 본문',
          bodyAvailable: true,
          version: 'fixture-v1',
        },
      ],
      nextCursor: null,
    }),
  );
  render(
    <MemoryRouter>
      <SignupForm />
    </MemoryRouter>,
  );
  const required = await screen.findByText('(필수)');
  const rule = document.getElementById('signup-password-rule')!;
  const disclosure = screen
    .getByText('합성 필수 약관 본문 보기')
    .closest('details')!;
  for (const element of [rule, required, disclosure]) {
    expect(element.classList.contains('text-zoop-muted')).toBe(true);
    expect(element.classList.contains('text-gray-500')).toBe(false);
    expect(element.classList.contains('text-zoop-faint')).toBe(false);
  }
});
