import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import CompanyGraphPreview from '@/components/company/CompanyGraphPreview';
import { readCompanyResource } from '@/apis/company/company';
import { createMockGraph } from '@/mocks/graph/response';
import { createFakeServer, json } from './support/fakeServer';
import type { GraphResponse } from '@/types/map/graph';
import { getGraph } from '@/apis/graph/graph';
const full = createMockGraph({ mode: 'all', personalFilter: 'all' });
const focus = full.nodes.find((n) => n.kind === 'company')!;
const issue = full.nodes.find((n) => n.kind === 'issue')!;
const graph: GraphResponse = {
  ...full,
  nodes: [
    { ...focus, isFocus: true },
    { ...issue, isFocus: false },
  ],
  edges: [
    {
      id: 'fixture-edge',
      source: focus.id,
      target: issue.id,
      relationType: 'INVOLVES',
      role: null,
      summary: '합성 직접 관계',
      assertionStatus: 'confirmed',
      derived: false,
      via: [],
      evidenceIds: ['fixture-evidence'],
    },
  ],
  metadata: { ...full.metadata, focusCompanyIds: [focus.id], depth: 1 },
};
test('D-COM-04 zooms, resets view and keeps selected node keyboard accessible', async () => {
  const select = vi.fn();
  const user = userEvent.setup();
  render(
    <CompanyGraphPreview
      data={graph}
      selectedId={issue.id}
      onSelect={select}
    />,
  );
  const svg = screen.getByRole('img', { name: '기준 시점 기업 관계 그래프' });
  const original = svg.getAttribute('viewBox');
  await user.click(
    screen.getByRole('button', { name: '기업 관계 그래프 확대' }),
  );
  expect(svg.getAttribute('viewBox')).not.toBe(original);
  expect(screen.getByText(/확대 비율 125%/)).toBeTruthy();
  await user.click(
    screen.getByRole('button', { name: '기업 관계 그래프 전체 보기' }),
  );
  expect(svg.getAttribute('viewBox')).toBe(original);
  const node = screen.getByRole('button', { name: `사건 · ${issue.label}` });
  expect(node.getAttribute('aria-pressed')).toBe('true');
  node.focus();
  await user.keyboard('{Enter}');
  expect(select).toHaveBeenCalledWith(issue.id, 'issue');
});
test('zoom bounds disable controls without changing node selection', async () => {
  const user = userEvent.setup();
  render(<CompanyGraphPreview data={graph} />);
  for (let i = 0; i < 10; i++)
    await user.click(
      screen.getByRole('button', { name: '기업 관계 그래프 확대' }),
    );
  expect(
    screen
      .getByRole('button', { name: '기업 관계 그래프 확대' })
      .hasAttribute('disabled'),
  ).toBe(true);
});
test('focus-only response is relationship empty, while partial and truncated are distinct', () => {
  render(
    <CompanyGraphPreview
      data={{
        ...graph,
        nodes: [graph.nodes[0]],
        edges: [],
        metadata: {
          ...graph.metadata,
          emptyReason: 'no_relations',
          partial: true,
          truncated: true,
        },
      }}
    />,
  );
  expect(screen.getByText(/관계 없음/)).toBeTruthy();
  expect(screen.getByText(/전체 관계로 해석하지/)).toBeTruthy();
  expect(screen.getByText(/표시 상한/)).toBeTruthy();
});
test('derived edges are never styled as a confirmed highlighted path', () => {
  render(
    <CompanyGraphPreview
      data={{ ...graph, edges: [{ ...graph.edges[0], derived: true }] }}
      highlighted={['fixture-edge']}
    />,
  );
  const line = screen
    .getByRole('img', { name: '기준 시점 기업 관계 그래프' })
    .querySelector('line')!;
  expect(line.getAttribute('class')).not.toContain('b75b00');
  expect(line.getAttribute('stroke-dasharray')).toBe('4 4');
});
test.each(['focus', 'depth', 'version', 'time', 'missing-depth'] as const)(
  'a mismatched %s snapshot is rejected',
  async (field) => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/companies/:id/graph', () =>
      json({
        ...graph,
        metadata: {
          ...graph.metadata,
          asOf: '2026-10-01T00:00:00Z',
          graphVersion: 'fixture-v1',
          ...(field === 'focus'
            ? { focusCompanyIds: ['OTHER'] }
            : field === 'depth'
              ? { depth: 2 }
              : field === 'time'
                ? { asOf: '2026-10-02T00:00:00Z' }
                : field === 'missing-depth'
                  ? { depth: null }
                  : { graphVersion: 'OTHER' }),
        },
      }),
    );
    await expect(
      readCompanyResource(
        `/api/v1/companies/${encodeURIComponent(focus.id)}/graph?asOf=2026-10-01T00%3A00%3A00Z&depth=1&graphVersion=fixture-v1`,
      ),
    ).rejects.toThrow();
  },
);

test('an empty relationship result still identifies the requested focus company', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id/graph', () =>
    json({
      ...graph,
      nodes: [],
      edges: [],
      metadata: {
        ...graph.metadata,
        asOf: '2026-10-01T00:00:00Z',
        graphVersion: 'fixture-v1',
        focusCompanyIds: [],
      },
    }),
  );
  await expect(
    readCompanyResource(
      `/api/v1/companies/${encodeURIComponent(focus.id)}/graph?asOf=2026-10-01T00%3A00%3A00Z&depth=1&graphVersion=fixture-v1`,
    ),
  ).rejects.toThrow('기업·시점·관계 단계');
});

test('equivalent KST timestamp is accepted and historical map uses the same guard', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id/graph', () =>
    json({
      ...graph,
      metadata: {
        ...graph.metadata,
        asOf: '2026-10-01T09:00:00+09:00',
        graphVersion: 'fixture-v1',
      },
    }),
  );
  const request = {
    mode: 'all' as const,
    personalFilter: 'all' as const,
    companyId: focus.id,
    asOf: '2026-10-01T00:00:00Z',
    graphVersion: 'fixture-v1',
    depth: 1 as const,
  };
  expect((await getGraph(request)).nodes).toHaveLength(2);
  server.on('GET', '/api/v1/companies/:id/graph', () =>
    json({
      ...graph,
      metadata: {
        ...graph.metadata,
        asOf: '2026-10-02T00:00:00Z',
        graphVersion: 'fixture-v1',
      },
    }),
  );
  await expect(getGraph(request)).rejects.toThrow('시점');
});

test('an unconfirmed edge is not highlighted as a verified impact path', () => {
  render(
    <CompanyGraphPreview
      data={{
        ...graph,
        edges: [{ ...graph.edges[0], assertionStatus: 'unconfirmed' }],
      }}
      highlighted={['fixture-edge']}
    />,
  );
  expect(
    screen.getByRole('img').querySelector('line')!.getAttribute('class'),
  ).not.toContain('b75b00');
});

test('lost pointer capture stops panning until the next drag', () => {
  render(<CompanyGraphPreview data={graph} />);
  const svg = screen.getByRole('img');
  Object.defineProperty(svg, 'setPointerCapture', { value: vi.fn() });
  vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    width: 320,
    height: 300,
    top: 0,
    left: 0,
    right: 320,
    bottom: 300,
    toJSON: () => ({}),
  });
  fireEvent.pointerDown(svg, {
    button: 0,
    pointerId: 1,
    clientX: 10,
    clientY: 10,
  });
  fireEvent.pointerMove(svg, { pointerId: 1, clientX: 30, clientY: 30 });
  const panned = svg.getAttribute('viewBox');
  expect(panned).not.toBe('0 0 320 300');
  fireEvent.lostPointerCapture(svg, { pointerId: 1 });
  fireEvent.pointerMove(svg, { pointerId: 1, clientX: 100, clientY: 100 });
  expect(svg.getAttribute('viewBox')).toBe(panned);
});
