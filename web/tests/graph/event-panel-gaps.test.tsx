import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import EventDetailPanel from '@/components/graph/EventDetailPanel';
import IsolatedIssuesPanel from '@/components/graph/IsolatedIssuesPanel';
import { createMockEvent } from '@/mocks/events/fixture';
import { createMockGraph } from '@/mocks/graph/response';
import {
  createFakeServer,
  deferred,
  json,
  apiError,
} from '../support/fakeServer';

let server: ReturnType<typeof createFakeServer>;
const event = createMockEvent('mock-issue-1');
beforeEach(() => {
  server = createFakeServer();
  vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api');
});
afterEach(() => vi.unstubAllEnvs());

it('D-GRP-02 M9/M10/M11 hides unavailable focus and selects only nodes on the current map', async () => {
  const follow = {
    id: 'follow',
    title: '이어진 합성 사건',
    eventTime: null,
    timePrecision: 'unknown' as const,
  };
  server.on('GET', '/api/v1/events/:id', () =>
    json({
      ...event,
      follows: {
        previous: [],
        next: [follow, { ...follow, id: 'outside', title: '지도 밖 사건' }],
      },
    }),
  );
  const select = vi.fn();
  const company = event.companies[0];
  render(
    <MemoryRouter>
      <EventDetailPanel
        id={event.id}
        context={{}}
        geography={null}
        onClose={vi.fn()}
        onAction={vi.fn()}
        canFocus={false}
        nodeIds={new Set([company.id, 'follow'])}
        onSelectNode={select}
      />
    </MemoryRouter>,
  );
  await screen.findByRole('heading', { name: event.title });
  expect(screen.queryByRole('button', { name: '이슈 중심 그래프' })).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: company.name }));
  expect(select).toHaveBeenCalledWith(company.id);
  const outside = event.companies.find((c) => c.id !== company.id)!;
  expect(
    screen.getByRole('link', { name: outside.name }).getAttribute('href'),
  ).toContain('/companies/');
  await userEvent.click(screen.getByRole('button', { name: follow.title }));
  expect(select).toHaveBeenCalledWith('follow');
  expect(screen.queryByRole('button', { name: '지도 밖 사건' })).toBeNull();
});

const base = createMockGraph({ mode: 'all', personalFilter: 'all' }).nodes.find(
  (n) => n.kind === 'issue',
)!;
const issues = [
  {
    ...base,
    id: 'unknown',
    label: '시각 미상 사건',
    eventTime: '2099-01-01',
    timePrecision: 'unknown' as const,
  },
  {
    ...base,
    id: 'known',
    label: '날짜 사건',
    eventTime: '2026-10-02',
    timePrecision: 'day' as const,
  },
];
it('D-GRP-01 M15 sorts unknown precision last, formats dates and opens requested evidence only', async () => {
  const response = deferred<Response>();
  server.on('GET', '/api/v1/events/:id', () => response.promise);
  const evidence = vi.fn();
  const { container } = render(
    <IsolatedIssuesPanel
      issues={issues}
      onSelect={vi.fn()}
      onClose={vi.fn()}
      onEvidence={evidence}
    />,
  );
  expect(container.querySelector('li')?.textContent).toContain('날짜 사건');
  expect(screen.getByText('2026-10-02')).toBeTruthy();
  expect(screen.getByText('발생 시각 미상')).toBeTruthy();
  expect(server.calls('GET', '/api/v1/events/:id')).toHaveLength(0);
  await userEvent.click(
    screen.getByRole('button', { name: '날짜 사건 근거 보기' }),
  );
  await act(async () => response.resolve(json({ ...event, id: 'known' })));
  await waitFor(() =>
    expect(evidence).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'known', evidenceIds: event.evidenceIds }),
    ),
  );
});
it('D-GRP-01 M15 preserves the panel on permission failure and ignores an unmounted late response', async () => {
  server.on('GET', '/api/v1/events/:id', () => apiError(403, 'ACCESS_DENIED'));
  const evidence = vi.fn();
  const view = render(
    <IsolatedIssuesPanel
      issues={issues}
      onSelect={vi.fn()}
      onClose={vi.fn()}
      onEvidence={evidence}
    />,
  );
  await userEvent.click(
    screen.getByRole('button', { name: '날짜 사건 근거 보기' }),
  );
  expect(await screen.findByRole('alert')).toBeTruthy();
  const response = deferred<Response>();
  server.on('GET', '/api/v1/events/:id', () => response.promise);
  await userEvent.click(
    screen.getByRole('button', { name: '날짜 사건 근거 보기' }),
  );
  view.unmount();
  await act(async () => response.resolve(json({ ...event, id: 'known' })));
  expect(evidence).not.toHaveBeenCalled();
});
