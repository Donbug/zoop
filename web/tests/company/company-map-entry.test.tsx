import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { expect, test } from 'vitest';
import { useCompanyMapEntry } from '@/hooks/useCompanyMapEntry';
function View({ scope = 'company:member' }: { scope?: string }) {
  const url = useCompanyMapEntry(scope),
    nav = useNavigate(),
    location = useLocation();
  return (
    <>
      <output data-testid="entry">{url ?? 'none'}</output>
      <button onClick={() => nav(`${location.pathname}?tab=documents`)}>
        문서
      </button>
      <button onClick={() => nav(-1)}>뒤로</button>
    </>
  );
}
test.each([
  undefined,
  'https://evil.test',
  '//zoop.invalid/',
  '/\\zoop.invalid/',
  '/stocks',
  'javascript:alert(1)',
])('D-COM-01 D7 rejects a missing or non-map entry %s', (from) => {
  render(
    <MemoryRouter
      initialEntries={[{ pathname: '/companies/A', state: { from } }]}
    >
      <View />
    </MemoryRouter>,
  );
  expect(screen.getByTestId('entry').textContent).toBe('none');
});
test('D-COM-01 D7 keeps the entire map URL through query changes and history return', async () => {
  const map =
    '/?mode=personal&scope=watchlist&focus=KRX%3AA&hops=2&select=node%3Ae&legend=all#map';
  render(
    <MemoryRouter
      initialEntries={[{ pathname: '/companies/A', state: { from: map } }]}
    >
      <View />
    </MemoryRouter>,
  );
  expect(screen.getByTestId('entry').textContent).toBe(map);
  await userEvent.click(screen.getByRole('button', { name: '문서' }));
  expect(screen.getByTestId('entry').textContent).toBe(map);
  await userEvent.click(screen.getByRole('button', { name: '뒤로' }));
  expect(screen.getByTestId('entry').textContent).toBe(map);
});
test('D-COM-01 D7 does not reuse another member or company entry', async () => {
  const { rerender } = render(
    <MemoryRouter
      initialEntries={[
        { pathname: '/companies/A', state: { from: '/?mode=personal' } },
      ]}
    >
      <View />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole('button', { name: '문서' }));
  rerender(
    <MemoryRouter>
      <View scope="other:member" />
    </MemoryRouter>,
  );
  expect(screen.getByTestId('entry').textContent).toBe('none');
});
test('D-COM-01 D7 rejects the old navigation state when the member changes', () => {
  const { rerender } = render(
    <MemoryRouter
      initialEntries={[
        { pathname: '/companies/A', state: { from: '/?mode=personal' } },
      ]}
    >
      <View />
    </MemoryRouter>,
  );
  rerender(
    <MemoryRouter>
      <View scope="company:other-member" />
    </MemoryRouter>,
  );
  expect(screen.getByTestId('entry').textContent).toBe('none');
});
