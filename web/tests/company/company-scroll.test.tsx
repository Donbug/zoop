import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import { useCompanyScroll } from '@/hooks/useCompanyScroll';
function Page({ ready = true }: { ready?: boolean }) {
  useCompanyScroll('member:A', ready);
  const nav = useNavigate();
  return <button onClick={() => nav('/other')}>이동</button>;
}
function Back() {
  const nav = useNavigate();
  return <button onClick={() => nav(-1)}>복귀</button>;
}
const key = 'zoop.company.scroll:member:A:entry';
function Harness({ ready = true }: { ready?: boolean }) {
  return (
    <MemoryRouter initialEntries={[{ pathname: '/companies/A', key: 'entry' }]}>
      <Routes>
        <Route path="/companies/A" element={<Page ready={ready} />} />
        <Route path="/other" element={<Back />} />
      </Routes>
    </MemoryRouter>
  );
}
test('D-COM-01 D8 saves a history entry and restores it on Back', async () => {
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  vi.stubGlobal('scrollY', 280);
  render(<Harness />);
  expect(scroll).toHaveBeenCalledWith(0, 0);
  fireEvent.scroll(window);
  await userEvent.click(screen.getByRole('button', { name: '이동' }));
  expect(JSON.parse(sessionStorage.getItem(key)!).y).toBe(280);
  scroll.mockClear();
  await userEvent.click(screen.getByRole('button', { name: '복귀' }));
  await waitFor(() =>
    expect(scroll).toHaveBeenCalledWith({ top: 280, behavior: 'instant' }),
  );
});
test('D-COM-01 D8 waits for resources before restoring and starts fresh history at the top', async () => {
  sessionStorage.setItem(key, JSON.stringify({ url: '/companies/A', y: 340 }));
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  const { rerender } = render(<Harness ready={false} />);
  expect(scroll).not.toHaveBeenCalled();
  rerender(<Harness ready />);
  await waitFor(() =>
    expect(scroll).toHaveBeenCalledWith({ top: 340, behavior: 'instant' }),
  );
});
test.each([-1, 'bad', null])(
  'D-COM-01 D8 ignores invalid saved offsets %s',
  (y) => {
    sessionStorage.setItem(key, JSON.stringify({ url: '/companies/A', y }));
    const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    render(<Harness />);
    expect(scroll).toHaveBeenCalledWith(0, 0);
  },
);
