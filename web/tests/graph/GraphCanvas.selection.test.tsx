import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import GraphCanvas from '@/components/graph/GraphCanvas';
import { createMockGraph } from '@/mocks/graph/response';
import type { GraphData } from '@antv/g6';
import { MemoryRouter } from 'react-router-dom';
import MapPage from '@/pages/map/MapPage';
import * as graphApi from '@/apis/graph/graph';
import { useAuthStore } from '@/stores/useAuthStore';

const canvas = vi.hoisted(() => ({
  created: vi.fn(),
  destroyed: vi.fn(),
  setData: vi.fn(),
  draw: vi.fn(),
  setElementState: vi.fn(),
  focusElement: vi.fn(),
  setLayout: vi.fn(),
  layout: vi.fn(),
  fitView: vi.fn(),
  setPlugins: vi.fn(),
  zoomTo: vi.fn(),
  translateTo: vi.fn(),
  translateBy: vi.fn(),
  getZoom: vi.fn(() => 1),
  getPosition: vi.fn(() => [0, 0]),
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
    setLayout = canvas.setLayout;
    layout = canvas.layout;
    fitView = canvas.fitView;
    setPlugins = canvas.setPlugins;
    getZoom = canvas.getZoom;
    getPosition = canvas.getPosition;
    zoomTo = canvas.zoomTo;
    translateTo = canvas.translateTo;
    translateBy = canvas.translateBy;
    getViewportByCanvas(point: number[]) {
      return point;
    }
    getNodeData() {
      return canvas.setData.mock.lastCall?.[0]?.nodes ?? [];
    }
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
  sessionStorage.clear();
  canvas.getZoom.mockReturnValue(1);
  canvas.getPosition.mockReturnValue([0, 0]);
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
  it.each(['light', 'dark'] as const)(
    'D-GRP-01 uses the approved appearance on the normal %s map route',
    async (theme) => {
      document.documentElement.dataset.theme = theme;
      useAuthStore.setState({ status: 'ready', member: null, session: null });
      vi.spyOn(graphApi, 'getGraph').mockResolvedValue(
        createMockGraph({ mode: 'all', personalFilter: 'all' }),
      );
      const { unmount } = render(
        <MemoryRouter initialEntries={['/?mode=all']}>
          <MapPage />
        </MemoryRouter>,
      );
      try {
        await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
        const rendered = canvas.setData.mock.lastCall![0] as GraphData;
        const direct = rendered.edges?.find(
          (edge) => !edge.style?.lineDash && !edge.style?.endArrow,
        );
        expect(direct?.style?.lineWidth).toBe(1.5);
        expect(direct?.style?.stroke).toBe(
          theme === 'dark' ? '#c4c9d1' : '#606a76',
        );
        const label = rendered.nodes?.find(
          (node) => node.id === 'NASDAQ:NVDA',
        )?.style;
        expect(Number(label?.labelFontSize)).toBeGreaterThan(17.2);
        const filters = screen.getByRole('group', { name: '그래프 표시 필터' });
        expect(filters.closest('.relationship-toolbar')).toBeTruthy();
        expect(screen.queryByLabelText('그래프 범례')).toBeNull();
      } finally {
        unmount();
        delete document.documentElement.dataset.theme;
      }
    },
  );
  it('shows the full API issue title on hover and clears it on leave', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const issue = data.nodes.find((node) => node.kind === 'issue')!;
    issue.label = 'API 사건의 긴 제목 전체가 호버 안내에 표시되어야 합니다';
    render(<GraphCanvas data={data} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    act(() =>
      canvas.handlers.get('node:pointerenter')!({ target: { id: issue.id } }),
    );
    expect(screen.getByRole('tooltip').textContent).toBe(issue.label);
    act(() =>
      canvas.handlers.get('node:pointerleave')!({ target: { id: issue.id } }),
    );
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
  it('fits the graph around remaining overlays without recreating it', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { value: 1200, configurable: true },
      clientHeight: { value: 800, configurable: true },
    });
    const legend = screen.getByLabelText('지도 확대 조절');
    const box = {
      x: 20,
      y: 16,
      left: 20,
      top: 16,
      right: 260,
      bottom: 400,
      width: 240,
      height: 384,
    };
    vi.spyOn(legend, 'getClientRects').mockReturnValue([
      box,
    ] as unknown as DOMRectList);
    vi.spyOn(legend, 'getBoundingClientRect').mockReturnValue({
      ...box,
      toJSON() {},
    });
    canvas.zoomTo.mockClear();
    await userEvent.click(
      screen.getByRole('button', { name: '전체 그래프 맞춤' }),
    );
    await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
    expect(canvas.zoomTo.mock.lastCall?.[0]).toBeGreaterThan(0);
    expect(canvas.created).toHaveBeenCalledOnce();
    expect(screen.queryByRole('alert')).toBeNull();
  });
  it('centers the map on a company picked from the my-stocks sidebar', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { rerender } = render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { value: 900, configurable: true },
      clientHeight: { value: 600, configurable: true },
    });
    canvas.translateBy.mockClear();
    rerender(
      <GraphCanvas data={data} centerRequest={{ id: 'KRX:005930', seq: 1 }} />,
    );
    await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
    const node = (canvas.setData.mock.lastCall![0] as GraphData).nodes!.find(
      (node) => node.id === 'KRX:005930',
    )!;
    expect(canvas.translateBy).toHaveBeenLastCalledWith(
      [450 - Number(node.style!.x), 300 - Number(node.style!.y)],
      false,
    );
  });
  it('D-GRP-01/03 centers the clicked node after the detail rail resizes and redraws the map, preserving zoom', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    const { rerender } = render(
      <GraphCanvas data={data} onSelect={onSelect} />,
    );
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { value: 1200, configurable: true },
      clientHeight: { value: 700, configurable: true },
    });
    act(() => canvas.resizeCallbacks[0]());
    await waitFor(() => expect(canvas.setSize).toHaveBeenCalledWith(1200, 700));
    await act(async () => {});
    canvas.zoomTo.mockClear();
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: 'KRX:005930' } }),
    );
    expect(onSelect).toHaveBeenCalledWith('KRX:005930');
    rerender(
      <GraphCanvas data={data} onSelect={onSelect} selectedId="KRX:005930" />,
    );
    await act(async () => {});
    // The rail opens after selection, changing the responsive node positions.
    Object.defineProperty(host, 'clientWidth', {
      value: 868,
      configurable: true,
    });
    canvas.translateBy.mockClear();
    act(() => canvas.resizeCallbacks[0]());
    await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
    const node = (canvas.setData.mock.lastCall![0] as GraphData).nodes!.find(
      (node) => node.id === 'KRX:005930',
    )!;
    expect(canvas.translateBy).toHaveBeenLastCalledWith(
      [434 - Number(node.style!.x), 350 - Number(node.style!.y)],
      false,
    );
    expect(canvas.translateBy.mock.invocationCallOrder.at(-1)).toBeGreaterThan(
      canvas.draw.mock.invocationCallOrder.at(-1)!,
    );
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(canvas.created).toHaveBeenCalledOnce();

    // A deliberate pan/zoom releases the selected-node anchor on later resize.
    fireEvent.wheel(host);
    Object.defineProperty(host, 'clientWidth', {
      value: 800,
      configurable: true,
    });
    canvas.translateBy.mockClear();
    act(() => canvas.resizeCallbacks[0]());
    await waitFor(() =>
      expect(canvas.translateBy).toHaveBeenCalledWith([-34, 0], false),
    );
    await act(async () => {});
    expect(canvas.translateBy).toHaveBeenCalledTimes(1);

    // Clicking the same node again centers it, even though the URL is unchanged.
    canvas.translateBy.mockClear();
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: 'KRX:005930' } }),
    );
    await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
    const latest = (canvas.setData.mock.lastCall![0] as GraphData).nodes!.find(
      (node) => node.id === 'KRX:005930',
    )!;
    expect(canvas.translateBy).toHaveBeenLastCalledWith(
      [400 - Number(latest.style!.x), 350 - Number(latest.style!.y)],
      false,
    );
  });
  it('M-GRP-01 centers selection above an overlapping mobile detail sheet', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const sheet = document.createElement('aside');
    sheet.dataset.screenId = 'M-GRP-01';
    document.body.append(sheet);
    const rect = {
      left: 0,
      top: 400,
      right: 390,
      bottom: 700,
      width: 390,
      height: 300,
    } as DOMRect;
    vi.spyOn(sheet, 'getClientRects').mockReturnValue([
      rect,
    ] as unknown as DOMRectList);
    vi.spyOn(sheet, 'getBoundingClientRect').mockReturnValue(rect);
    const { rerender, unmount } = render(<GraphCanvas data={data} />);
    try {
      await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
      const host = screen.getByRole('img');
      Object.defineProperties(host, {
        clientWidth: { value: 390, configurable: true },
        clientHeight: { value: 700, configurable: true },
      });
      rerender(<GraphCanvas data={data} selectedId="KRX:005930" />);
      await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
      const node = (canvas.setData.mock.lastCall![0] as GraphData).nodes!.find(
        (node) => node.id === 'KRX:005930',
      )!;
      expect(canvas.translateBy).toHaveBeenLastCalledWith(
        // freeViewport reserves 20px at the canvas edge and 12px above the sheet.
        [195 - Number(node.style!.x), 204 - Number(node.style!.y)],
        false,
      );
    } finally {
      unmount();
      sheet.remove();
    }
  });
  it.each(['canvas click', 'external selection clear'])(
    'D-GRP-01/03 keeps every node and the camera in place after %s closes the rail',
    async (method) => {
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      const onSelect = vi.fn();
      const { rerender } = render(
        <GraphCanvas data={data} onSelect={onSelect} />,
      );
      await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
      const host = screen.getByRole('img');
      Object.defineProperties(host, {
        clientWidth: { value: 868, configurable: true },
        clientHeight: { value: 700, configurable: true },
      });
      rerender(
        <GraphCanvas data={data} onSelect={onSelect} selectedId="KRX:005930" />,
      );
      await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
      act(() => canvas.resizeCallbacks[0]());
      await waitFor(() =>
        expect(canvas.setSize).toHaveBeenCalledWith(868, 700),
      );
      await act(async () => {});
      const positions = () =>
        new Map(
          (canvas.setData.mock.lastCall![0] as GraphData).nodes!.map((node) => [
            node.id,
            [node.style!.x, node.style!.y],
          ]),
        );
      const before = positions();
      canvas.translateBy.mockClear();
      canvas.zoomTo.mockClear();
      canvas.focusElement.mockClear();
      if (method === 'canvas click') {
        act(() => canvas.handlers.get('canvas:click')!({ target: { id: '' } }));
        expect(onSelect).toHaveBeenLastCalledWith(null);
      }
      // Esc and the close button clear selectedId through MapPage, bypassing
      // the canvas click handler. Both must preserve the same screen position.
      rerender(<GraphCanvas data={data} onSelect={onSelect} />);
      Object.defineProperty(host, 'clientWidth', {
        value: 1200,
        configurable: true,
      });
      act(() => canvas.resizeCallbacks[0]());
      await waitFor(() =>
        expect(canvas.setSize).toHaveBeenLastCalledWith(1200, 700),
      );
      await act(async () => {});
      expect(positions()).toEqual(before);
      expect(canvas.translateBy).not.toHaveBeenCalled();
      expect(canvas.zoomTo).not.toHaveBeenCalled();
      expect(canvas.focusElement).not.toHaveBeenCalled();
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ 'KRX:005930': [] }),
      );
      expect(canvas.created).toHaveBeenCalledOnce();

      // An explicit fit can still use the full, newly expanded graph surface.
      await userEvent.click(
        screen.getByRole('button', { name: '전체 그래프 맞춤' }),
      );
      await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
      expect(positions()).not.toEqual(before);
    },
  );
  it('keeps a user-placed view centered when a sidebar narrows the map', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    sessionStorage.setItem(
      'zoop.graph.view:member-a:all',
      JSON.stringify({
        url: '/?mode=all',
        view: {
          hidden: [],
          camera: { zoom: 1, position: [0, 0], size: [0, 0] },
        },
      }),
    );
    render(<GraphCanvas data={data} memoryOwner="member-a" />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 600 },
    });
    canvas.translateBy.mockClear();
    act(() => canvas.resizeCallbacks[0]());
    await waitFor(() =>
      expect(canvas.translateBy).toHaveBeenCalledWith([450, 300], false),
    );
  });
  it('explains each legend item in its tooltip', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    const shared = await screen.findByRole('button', { name: /^사건 공유/ });
    expect(shared.getAttribute('title')).toContain(
      '같은 사건에 각각 직접 또는 구조적으로 연결',
    );
    expect(
      screen.getByRole('button', { name: /^후속 사건/ }).getAttribute('title'),
    ).toContain('앞 사건 다음에');
  });
  it('D-GRP-01 moves the only filter group to the toolbar and toggles actual edges without moving the camera', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const toolbar = document.createElement('header');
    document.body.append(toolbar);
    const { unmount } = render(
      <GraphCanvas data={data} filterHost={toolbar} />,
    );
    try {
      await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
      expect(
        screen.getAllByRole('group', { name: '그래프 표시 필터' }),
      ).toHaveLength(1);
      const button = screen.getByRole('button', { name: /^사건 공유 \d/ });
      expect(toolbar.contains(button)).toBe(true);
      expect(
        screen.getByTestId('graph-canvas').querySelector('aside'),
      ).toBeNull();
      canvas.zoomTo.mockClear();
      canvas.translateBy.mockClear();
      await userEvent.click(button);
      await waitFor(() =>
        expect(button.getAttribute('aria-pressed')).toBe('false'),
      );
      await waitFor(() =>
        expect(
          (canvas.setData.mock.lastCall![0] as GraphData).edges
            ?.filter(
              (edge) =>
                data.edges.find((item) => item.id === edge.id)?.relationType ===
                'SHARES_ISSUE',
            )
            .every((edge) => edge.style?.visibility === 'hidden'),
        ).toBe(true),
      );
      expect(canvas.created).toHaveBeenCalledOnce();
      expect(canvas.zoomTo).not.toHaveBeenCalled();
      expect(canvas.translateBy).not.toHaveBeenCalled();
      await userEvent.click(button);
      await waitFor(() =>
        expect(button.getAttribute('aria-pressed')).toBe('true'),
      );
    } finally {
      unmount();
      toolbar.remove();
    }
  });
  it('ports legend filters without moving nodes and keeps at least one node kind visible', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const before = (canvas.setData.mock.lastCall![0] as GraphData).nodes?.find(
      (node) => node.id === 'NASDAQ:NVDA',
    )?.style;
    await userEvent.click(screen.getByRole('button', { name: /기업 \d/ }));
    await waitFor(() =>
      expect(
        (canvas.setData.mock.lastCall![0] as GraphData).nodes?.find(
          (node) => node.id === 'NASDAQ:NVDA',
        )?.style?.visibility,
      ).toBe('hidden'),
    );
    expect(
      (screen.getByRole('button', { name: /^사건 \d+$/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    const after = (canvas.setData.mock.lastCall![0] as GraphData).nodes?.find(
      (node) => node.id === 'NASDAQ:NVDA',
    )?.style;
    expect([after?.x, after?.y]).toEqual([before?.x, before?.y]);
    expect(
      screen.queryByRole('button', { name: '흐름 순으로 정렬' }),
    ).toBeNull();
  });
  it('restores zoom and pan separately for each mode', async () => {
    const all = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const personal = createMockGraph({
      mode: 'personal',
      personalFilter: 'all',
    });
    const { rerender } = render(
      <GraphCanvas data={all} memoryOwner="member-a" />,
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    canvas.getZoom.mockReturnValue(1.8);
    canvas.getPosition.mockReturnValue([40, 60]);
    act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
    rerender(<GraphCanvas data={personal} memoryOwner="member-a" />);
    await waitFor(() => expect(canvas.created).toHaveBeenCalledTimes(2));
    canvas.getZoom.mockReturnValue(1.2);
    canvas.getPosition.mockReturnValue([5, 10]);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(2));
    act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
    rerender(<GraphCanvas data={all} memoryOwner="member-a" />);
    await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalledWith(1.8, false));
    expect(canvas.translateTo).toHaveBeenCalledWith([40, 60], false);
  });
  it('opens the default layout instead of a saved camera taken at another map size', async () => {
    const all = createMockGraph({ mode: 'all', personalFilter: 'all' });
    sessionStorage.setItem(
      'zoop.graph.view:member-a:all',
      JSON.stringify({
        url: '/?mode=all',
        view: {
          hidden: [],
          camera: { zoom: 1.8, position: [40, 60], size: [1600, 900] },
        },
      }),
    );
    render(<GraphCanvas data={all} memoryOwner="member-a" />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(canvas.translateTo).not.toHaveBeenCalled();
  });
  it('enables the desktop minimap only above sixty visible nodes', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { rerender } = render(<GraphCanvas data={data} />);
    const host = screen.getByRole('img');
    Object.defineProperty(host, 'clientWidth', {
      configurable: true,
      value: 1200,
    });
    await waitFor(() => expect(canvas.setPlugins).toHaveBeenCalledWith([]));
    const company = data.nodes.find((node) => node.kind === 'company')!;
    const large = {
      ...data,
      nodes: [
        ...data.nodes,
        ...Array.from({ length: 70 }, (_, index) => ({
          ...company,
          id: `more-${index}`,
        })),
      ],
    };
    rerender(<GraphCanvas data={large} />);
    await waitFor(() =>
      expect(canvas.setPlugins).toHaveBeenLastCalledWith([
        expect.objectContaining({ type: 'minimap', size: [192, 128] }),
      ]),
    );
  });

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
  it('D-GRP-01 keeps the graph host pinned to the map surface across mode switches without the old left legend', async () => {
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
    expect(screen.queryByLabelText('그래프 범례')).toBeNull();
    rerender(<GraphCanvas data={personal} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(2));
    rerender(<GraphCanvas data={all} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(3));
    expect(screen.getByRole('img').className).toContain('absolute!');
    expect(canvas.destroyed).toHaveBeenCalledTimes(2);
  });
  it('D-GRP-01 removes the duplicate left title and retains the map accessible name', () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { rerender } = render(
      <GraphCanvas data={data} selectedId="KRX:005930" />,
    );
    expect(
      screen.getByRole('img', { name: /시장 전체 관계 지도/ }),
    ).toBeTruthy();
    expect(screen.queryByText('(01)')).toBeNull();
    rerender(<GraphCanvas data={data} selectedId="NASDAQ:NVDA" />);
    expect(
      screen.getByRole('img', { name: /시장 전체 관계 지도/ }),
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

  it('D-GRP-01 moving between nodes ignores stale leave and keeps the clicked node emphasized on exit', async () => {
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
        // Without hover, the clicked node keeps its connections emphasized.
        expect.objectContaining({
          'mock-issue-1': ['related'],
          'KRX:005930': ['related', 'selected'],
          [shared.id]: expect.arrayContaining(['selected']),
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

  it('D-GRP-07b focus mode keeps 1·2-hop nodes and edges at full strength even while the focus company is selected', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(
      <GraphCanvas
        data={data}
        selectedId="NASDAQ:NVDA"
        focusId="NASDAQ:NVDA"
        focusHops={2}
        focusLayout
      />,
    );
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    const states = canvas.setElementState.mock.calls.at(-1)![0] as Record<
      string,
      string[]
    >;
    expect(states['NASDAQ:NVDA']).toEqual(expect.arrayContaining(['selected']));
    expect(
      Object.values(states).some((list) => list.includes('inactive')),
    ).toBe(false);
  });

  it('D-GRP-01 outside focus mode a selected company still dims unrelated nodes', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} selectedId="NASDAQ:NVDA" />);
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    const states = canvas.setElementState.mock.calls.at(-1)![0] as Record<
      string,
      string[]
    >;
    expect(
      Object.values(states).some((list) => list.includes('inactive')),
    ).toBe(true);
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
        expect.objectContaining({ 'mock-issue-1': ['related', 'selected'] }),
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
