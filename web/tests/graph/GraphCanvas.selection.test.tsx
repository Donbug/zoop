import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import GraphCanvas from '@/components/graph/GraphCanvas';
import { createMockGraph } from '@/mocks/graph/response';
import type { GraphData } from '@antv/g6';

const canvas = vi.hoisted(() => ({
  created: vi.fn(),
  destroyed: vi.fn(),
  setData: vi.fn(),
  draw: vi.fn(),
  setElementState: vi.fn(),
  focusElement: vi.fn(),
  handlers: new Map<string, (event: { target: { id: string } }) => void>(),
}));
vi.mock('@antv/g6', () => ({
  Graph: class {
    destroyed = false;
    constructor() {
      canvas.created();
    }
    on(name: string, handler: (event: { target: { id: string } }) => void) {
      canvas.handlers.set(name, handler);
    }
    async render() {}
    setSize() {}
    setData = canvas.setData;
    draw = canvas.draw;
    setElementState = canvas.setElementState;
    focusElement = canvas.focusElement;
    destroy() {
      this.destroyed = true;
      canvas.destroyed();
    }
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  canvas.handlers.clear();
  Object.defineProperty(document, 'fonts', {
    configurable: true,
    value: { ready: Promise.resolve() },
  });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
});
describe('D-GRP-02 · canvas selection bridge', () => {
  it('D-GRP-01 hover emphasizes incident nodes/edges without selecting or redrawing the viewport', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    render(<GraphCanvas data={data} onSelect={onSelect} />);
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    const draws = canvas.draw.mock.calls.length;
    const layouts = canvas.setData.mock.calls.length;
    const edge = data.edges.find(
      (item) => item.source === 'mock-issue-1' && item.target === 'NASDAQ:NVDA',
    )!;
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({
          'NASDAQ:NVDA': ['hovered'],
          'mock-issue-1': ['related'],
          [edge.id]: ['related'],
          'KRX:005380': ['inactive'],
        }),
      ),
    );
    expect(onSelect).not.toHaveBeenCalled();
    expect(canvas.draw).toHaveBeenCalledTimes(draws);
    expect(canvas.setData).toHaveBeenCalledTimes(layouts);
    expect(canvas.focusElement).not.toHaveBeenCalled();
    expect(canvas.created).toHaveBeenCalledOnce();
  });

  it('D-GRP-01 moving between nodes ignores stale leave and restores the clicked selection on exit', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const shared = data.edges.find(
      (edge) => edge.relationType === 'SHARES_ISSUE',
    )!;
    render(
      <GraphCanvas
        data={data}
        selectedId="KRX:005930"
        selectedEdgeId={shared.id}
      />,
    );
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'mock-issue-1' },
      }),
    );
    await act(async () =>
      canvas.handlers.get('node:pointerleave')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({
          'mock-issue-1': ['hovered'],
          'KRX:005930': ['related', 'selected'],
        }),
      ),
    );
    await act(async () =>
      canvas.handlers.get('canvas:pointerleave')!({ target: { id: 'canvas' } }),
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({
          'mock-issue-1': [],
          'KRX:005930': ['selected'],
          [shared.id]: ['selected'],
        }),
      ),
    );
    expect(canvas.created).toHaveBeenCalledOnce();
  });

  it('D-GRP-01 hover cannot brighten nodes outside an explicit focus scope', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} focusId="NASDAQ:NVDA" focusHops={1} />);
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'KRX:005380' },
      }),
    );
    expect(canvas.setElementState).toHaveBeenLastCalledWith(
      expect.objectContaining({ 'KRX:005380': [] }),
    );
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ 'NASDAQ:NVDA': ['hovered'] }),
      ),
    );
  });

  it('D-GRP-04 selects eligible edges via canvas/keyboard and never recreates the viewport', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelectEdge = vi.fn();
    const shared = data.edges.find(
      (edge) => edge.relationType === 'SHARES_ISSUE',
    )!;
    const involves = data.edges.find(
      (edge) => edge.relationType === 'INVOLVES',
    )!;
    const { rerender } = render(
      <GraphCanvas data={data} onSelectEdge={onSelectEdge} />,
    );
    await waitFor(() => expect(canvas.handlers.has('edge:click')).toBe(true));
    await act(async () =>
      canvas.handlers.get('edge:click')!({ target: { id: involves.id } }),
    );
    expect(onSelectEdge).not.toHaveBeenCalled();
    await act(async () =>
      canvas.handlers.get('edge:click')!({ target: { id: shared.id } }),
    );
    expect(onSelectEdge).toHaveBeenCalledWith(shared.id);
    rerender(
      <GraphCanvas
        data={data}
        onSelectEdge={onSelectEdge}
        selectedEdgeId={shared.id}
      />,
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ [shared.id]: ['selected'] }),
      ),
    );
    await userEvent.click(
      screen.getByRole('button', {
        name: /연결선: HBM3E 12단 경쟁 – HBM4 공급 계약/,
      }),
    );
    expect(onSelectEdge).toHaveBeenLastCalledWith('mock-follows-1');
    rerender(<GraphCanvas data={data} onSelectEdge={onSelectEdge} />);
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ [shared.id]: [] }),
      ),
    );
    expect(canvas.created).toHaveBeenCalledOnce();
  });
  it('keeps the graph instance across selection/close and clears visual selection', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    const props = {
      data,
      selectedId: null as string | null,
      focusId: null as string | null,
      onSelect,
    };
    const { rerender } = render(<GraphCanvas {...props} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    await act(async () =>
      canvas.handlers.get('node:click')!({ target: { id: 'mock-issue-1' } }),
    );
    expect(onSelect).toHaveBeenCalledWith('mock-issue-1');
    rerender(<GraphCanvas {...props} selectedId="mock-issue-1" />);
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ 'mock-issue-1': ['selected'] }),
      ),
    );
    rerender(<GraphCanvas {...props} />);
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ 'mock-issue-1': [] }),
      ),
    );
    expect(canvas.created).toHaveBeenCalledOnce();
    expect(canvas.destroyed).not.toHaveBeenCalled();
  });
  it('opens a folded event from the keyboard and retains it when it is the focus target', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    const props = {
      data,
      selectedId: null as string | null,
      focusId: null as string | null,
      onSelect,
    };
    const { rerender } = render(<GraphCanvas {...props} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    await userEvent.click(
      screen.getByRole('button', { name: '사건: NVIDIA 개별 공시 (예시)' }),
    );
    expect(onSelect).toHaveBeenCalledWith('mock-issue-19');
    rerender(
      <GraphCanvas
        {...props}
        selectedId="mock-issue-19"
        focusId="mock-issue-19"
      />,
    );
    await waitFor(() =>
      expect(canvas.focusElement).toHaveBeenCalledWith('mock-issue-19', false),
    );
    rerender(<GraphCanvas {...props} focusId="mock-issue-19" />);
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ 'mock-issue-19': [] }),
      ),
    );
    const rendered = canvas.setData.mock.lastCall![0] as GraphData;
    expect(rendered.nodes?.some((node) => node.id === 'mock-issue-19')).toBe(
      true,
    );
    expect(canvas.focusElement).toHaveBeenCalledTimes(1);
    const ids = new Set(rendered.nodes?.map((node) => node.id));
    expect(
      rendered.edges?.every(
        (edge) => ids.has(edge.source) && ids.has(edge.target),
      ),
    ).toBe(true);
  });
});
