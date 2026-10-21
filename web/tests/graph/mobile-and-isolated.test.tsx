import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import MapDetailSheet from '@/components/graph/MapDetailSheet';
import IsolatedIssuesPanel from '@/components/graph/IsolatedIssuesPanel';
import { isolatedIssues } from '@/components/graph/graph-view';
import { createMockGraph } from '@/mocks/graph/response';
it('M-GRP-01 supports half/full keyboard snaps, escape, focus return and viewport cleanup', async () => {
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const opener = document.createElement('button');
  opener.textContent = 'open';
  document.body.append(opener);
  opener.focus();
  const close = vi.fn();
  const { unmount } = render(
    <MapDetailSheet open onClose={close}>
      <aside>
        <button>panel action</button>
      </aside>
    </MapDetailSheet>,
  );
  const dialog = screen.getByRole('dialog', { name: '지도 상세' });
  await waitFor(() => expect(document.activeElement).toBe(dialog));
  expect(dialog.getAttribute('data-snap')).toBe('half');
  await userEvent.click(screen.getByRole('button', { name: '시트 크게 보기' }));
  expect(dialog.getAttribute('data-snap')).toBe('full');
  fireEvent.keyDown(screen.getByRole('button', { name: '시트 작게 보기' }), {
    key: 'ArrowDown',
  });
  expect(dialog.getAttribute('data-snap')).toBe('half');
  fireEvent.keyDown(dialog, { key: 'Escape' });
  expect(close).toHaveBeenCalledOnce();
  unmount();
  expect(document.activeElement).toBe(opener);
  expect(opener.inert).not.toBe(true);
  opener.remove();
});
it('isolated issue list opens only an actual selected issue and filters its list', async () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const issues = isolatedIssues(graph);
  const select = vi.fn();
  render(
    <IsolatedIssuesPanel issues={issues} onSelect={select} onClose={vi.fn()} />,
  );
  await userEvent.type(screen.getByLabelText('사건 검색'), 'no-such-title');
  expect(screen.getByRole('status').textContent).toBe(
    '해당하는 사건이 없습니다.',
  );
  await userEvent.clear(screen.getByLabelText('사건 검색'));
  await userEvent.click(screen.getByRole('button', { name: issues[0].label }));
  expect(select).toHaveBeenCalledWith(issues[0].id);
});
