import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
  useParams,
} from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import { useCompanyScroll } from '@/hooks/useCompanyScroll';
function Page({ ready = true }: { ready?: boolean }) {
  const { id } = useParams();
  useCompanyScroll(`member:${id}`, ready);
  const nav = useNavigate();
  return (
    <>
      <button onClick={() => nav('/other')}>이동</button>
      <button onClick={() => nav('/companies/B')}>다른 기업</button>
      <button onClick={() => nav(-1)}>이력 복귀</button>
      {['?event=e1', '?tab=documents', '?period=1w'].flatMap((query) =>
        [false, true].map((replace) => (
          <button
            key={`${query}:${replace}`}
            onClick={() => nav(query, { replace })}
          >{`${query}:${replace ? 'replace' : 'push'}`}</button>
        )),
      )}
    </>
  );
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
        <Route path="/companies/:id" element={<Page ready={ready} />} />
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

test.each(
  ['?event=e1', '?tab=documents', '?period=1w'].flatMap((query) =>
    [false, true].map((replace) => ({ query, replace })),
  ),
)(
  'D-COM-01 D8 keeps scroll on query-only $query replace=$replace',
  async ({ query, replace }) => {
    const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    render(<Harness />);
    vi.stubGlobal('scrollY', 375);
    fireEvent.scroll(window);
    scroll.mockClear();
    await userEvent.click(
      screen.getByRole('button', {
        name: `${query}:${replace ? 'replace' : 'push'}`,
      }),
    );
    expect(scroll).not.toHaveBeenCalled();
    expect(JSON.parse(sessionStorage.getItem(key)!).y).toBe(375);
  },
);

test('D-COM-01 D8 restores the previous query history entry on Back', async () => {
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  render(<Harness />);
  vi.stubGlobal('scrollY', 375);
  fireEvent.scroll(window);
  await userEvent.click(screen.getByRole('button', { name: '?event=e1:push' }));
  vi.stubGlobal('scrollY', 650);
  fireEvent.scroll(window);
  scroll.mockClear();
  await userEvent.click(screen.getByRole('button', { name: '이력 복귀' }));
  await waitFor(() =>
    expect(scroll).toHaveBeenCalledWith({ top: 375, behavior: 'instant' }),
  );
});

test('D-COM-01 D8 starts another company at the top', async () => {
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  render(<Harness />);
  vi.stubGlobal('scrollY', 375);
  fireEvent.scroll(window);
  scroll.mockClear();
  await userEvent.click(screen.getByRole('button', { name: '다른 기업' }));
  expect(scroll).toHaveBeenCalledWith(0, 0);
});

test('D-COM-01 D8 saves the current query position even without another scroll event', async () => {
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  render(<Harness />);
  vi.stubGlobal('scrollY', 375);
  fireEvent.scroll(window);
  await userEvent.click(screen.getByRole('button', { name: '?event=e1:push' }));
  await userEvent.click(
    screen.getByRole('button', { name: '?tab=documents:push' }),
  );
  scroll.mockClear();
  await userEvent.click(screen.getByRole('button', { name: '이력 복귀' }));
  await waitFor(() =>
    expect(scroll).toHaveBeenCalledWith({ top: 375, behavior: 'instant' }),
  );
});

test.each(['wheel', 'touchstart'])(
  'D-COM-01 D8 cancels pending restoration after %s input',
  async (event) => {
    sessionStorage.setItem(
      key,
      JSON.stringify({ url: '/companies/A', y: 340 }),
    );
    const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    const view = render(<Harness ready={false} />);
    fireEvent(window, new Event(event));
    view.rerender(<Harness ready />);
    expect(scroll).not.toHaveBeenCalled();
  },
);

test('D-COM-01 D8 waits for resources to restore a saved zero position too', async () => {
  sessionStorage.setItem(key, JSON.stringify({ url: '/companies/A', y: 0 }));
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  const view = render(<Harness ready={false} />);
  expect(scroll).not.toHaveBeenCalled();
  view.rerender(<Harness ready />);
  await waitFor(() =>
    expect(scroll).toHaveBeenCalledWith({ top: 0, behavior: 'instant' }),
  );
});
