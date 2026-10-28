import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import AppLayout from '@/components/common/AppLayout';

vi.mock('@/components/common/ServiceHeader', () => ({
  default: () => <header>메뉴</header>,
}));
vi.mock('@/components/common/BottomNav', () => ({ default: () => null }));
function Page() {
  const location = useLocation();
  return (
    <p>
      {location.pathname}
      {location.hash}
    </p>
  );
}
it('moves focus to the main content without changing the URL', async () => {
  render(
    <MemoryRouter initialEntries={['/stocks']}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/stocks" element={<Page />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(
    screen.getByRole('link', { name: '본문으로 건너뛰기' }),
  );
  expect(document.activeElement?.id).toBe('service-main');
  expect(screen.getByText('/stocks')).toBeTruthy();
});

function Company() {
  const location = useLocation();
  const [mountedAt] = useState(location.pathname);
  return (
    <>
      <p>처음 {mountedAt}</p>
      <Link to="/companies/b">다음 기업</Link>
    </>
  );
}
it('keeps the page mounted while moving inside the same menu', async () => {
  render(
    <MemoryRouter initialEntries={['/companies/a']}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/companies/:id" element={<Company />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole('link', { name: '다음 기업' }));
  expect(screen.getByText('처음 /companies/a')).toBeTruthy();
});
