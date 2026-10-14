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
