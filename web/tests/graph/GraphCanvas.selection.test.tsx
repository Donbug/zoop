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
  setSize: vi.fn(),
  resizeCallbacks: [] as (() => void)[],
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
    setSize = canvas.setSize;
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
  canvas.resizeCallbacks.length = 0;
  Object.defineProperty(document, 'fonts', {
    configurable: true,
    value: { ready: Promise.resolve() },
  });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        canvas.resizeCallbacks.push(callback);
      }
      observe() {}
      disconnect() {}
    },
  );
});
describe('D-GRP-02 · canvas selection bridge', () => {
  it('D-GRP-01 redraws at the current container size after resize and ignores a disposed observer', async () => {
    const all = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const personal = createMockGraph({
      mode: 'personal',
      personalFilter: 'all',
    });
    const { rerender } = render(<GraphCanvas data={all} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 1200 },
      clientHeight: { configurable: true, value: 800 },
    });
    const draws = canvas.draw.mock.calls.length;
    act(() => canvas.resizeCallbacks[0]());
    await waitFor(() =>
      expect(canvas.setSize).toHaveBeenLastCalledWith(1200, 800),
    );
    await waitFor(() =>
      expect(canvas.draw.mock.calls.length).toBeGreaterThan(draws),
    );
    const oldObserver = canvas.resizeCallbacks[0];
    rerender(<GraphCanvas data={personal} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(2));
    canvas.setSize.mockClear();
    act(() => oldObserver());
    await act(async () => {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
    });
    expect(canvas.setSize).not.toHaveBeenCalled();
  });
  it('D-GRP-01 keeps the graph host pinned to the map surface across mode switches and an opaque legend', async () => {
    const all = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const personal = createMockGraph({
      mode: 'personal',
      personalFilter: 'all',
    });
    const { rerender } = render(<GraphCanvas data={all} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    // G6 sets an inline position: relative on its container; the important utilities must win.
    const host = screen.getByRole('img');
    expect(host.className).toContain('absolute!');
    expect(host.className).toContain('inset-0');
    expect(screen.getByLabelText('그래프 범례').className).toContain(
      'bg-zoop-map',
    );
    rerender(<GraphCanvas data={personal} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(2));
    rerender(<GraphCanvas data={all} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(3));
    expect(screen.getByRole('img').className).toContain('absolute!');
    expect(canvas.destroyed).toHaveBeenCalledTimes(2);
  });
  it('D-GRP-01 keeps the market title when a company is selected and omits the frame number', () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { rerender } = render(
      <GraphCanvas data={data} selectedId="KRX:005930" />,
    );
    expect(
      screen.getByRole('heading', { name: '시장 전체 지도' }),
    ).toBeTruthy();
    expect(screen.queryByText('(01)')).toBeNull();
    rerender(<GraphCanvas data={data} selectedId="NASDAQ:NVDA" />);
    expect(
      screen.getByRole('heading', { name: '시장 전체 지도' }),
    ).toBeTruthy();
  });
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
