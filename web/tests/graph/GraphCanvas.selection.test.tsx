import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import GraphCanvas, { HOVER_INTENT_MS } from '@/components/graph/GraphCanvas';
import { GraphAppearanceContext } from '@/components/graph/graph-appearance';
import {
  EDGE_ANIMATION,
  NODE_ANIMATION,
} from '@/components/graph/graph-motion';
import { createMockGraph } from '@/mocks/graph/response';
import type { GraphData } from '@antv/g6';
import {
  MemoryRouter,
  createMemoryRouter,
  RouterProvider,
} from 'react-router-dom';
import MapPage from '@/pages/map/MapPage';
import * as graphApi from '@/apis/graph/graph';
import * as mapDimming from '@/components/graph/graph-dimming';
import * as geometry from '@/components/graph/graph-geometry';
import { useAuthStore } from '@/stores/useAuthStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { toggleTheme, useColorTheme } from '@/util/theme-color';
import {
  emptyView,
  MAP_LAYOUT_REVISION,
  saveModeEntry,
} from '@/components/graph/graph-view';

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
  minimapRender: vi.fn(),
  off: vi.fn(),
  setZoomRange: vi.fn(),
  zoomTo: vi.fn(),
  translateTo: vi.fn(),
  translateBy: vi.fn(),
  translateElementTo: vi.fn<(...args: unknown[]) => Promise<void>>(
    async () => {},
  ),
  getZoom: vi.fn(() => 1),
  getZoomRange: vi.fn(() => [0.01, 2.5]),
  getPosition: vi.fn(() => [0, 0]),
  getViewportByCanvas: vi.fn((point: number[]) => point),
  setSize: vi.fn(),
  setNode: vi.fn(),
  setEdge: vi.fn(),
  resizeCallbacks: [] as (() => void)[],
  handlers: new Map<string, (event: { target: { id: string } }) => void>(),
}));
vi.mock('@antv/g6', () => ({
  Graph: class {
    destroyed = false;
    initial: { nodes?: unknown[] } | undefined;
    constructor(options?: { data?: { nodes?: unknown[] } }) {
      canvas.created(options);
      this.initial = options?.data;
    }
    on(name: string, handler: (event: { target: { id: string } }) => void) {
      canvas.handlers.set(name, handler);
    }
    async render() {}
    setLayout = canvas.setLayout;
    layout = canvas.layout;
    fitView = canvas.fitView;
    setPlugins = canvas.setPlugins;
    getPluginInstance() {
      return { onDraw: canvas.minimapRender, onRender: canvas.minimapRender };
    }
    off = canvas.off;
    setZoomRange = canvas.setZoomRange;
    getZoom = canvas.getZoom;
    getZoomRange = canvas.getZoomRange;
    getPosition = canvas.getPosition;
    zoomTo = canvas.zoomTo;
    translateTo = canvas.translateTo;
    translateBy = canvas.translateBy;
    translateElementTo = canvas.translateElementTo;
    getViewportByCanvas = canvas.getViewportByCanvas;
    getNodeData() {
      return (
        canvas.setData.mock.lastCall?.[0]?.nodes ?? this.initial?.nodes ?? []
      );
    }
    setSize = canvas.setSize;
    setNode = canvas.setNode;
    setEdge = canvas.setEdge;
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

/** GraphCanvas sends only changed element states; merge the calls to read what is applied now. */
const appliedStates = () =>
  Object.assign(
    {},
    ...canvas.setElementState.mock.calls.map(([states]) => states),
  ) as Record<string, string[]>;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  canvas.getZoom.mockReturnValue(1);
  canvas.getPosition.mockReturnValue([0, 0]);
  canvas.getViewportByCanvas.mockImplementation((point) => point);
  canvas.translateBy.mockResolvedValue(undefined);
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
  it.each(['rgb(223, 223, 220)', 'rgb(51, 51, 51)'])(
    'D-GRP-01 selection dims elements without changing the %s map background',
    async (background) => {
      const dimming = vi.spyOn(mapDimming, 'applyMapDimming');
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      const view = render(<GraphCanvas data={data} />);
      await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
      const host = view.container.querySelector<HTMLElement>(
        '.relationship-canvas',
      )!;
      host.style.backgroundColor = background;
      view.rerender(<GraphCanvas data={data} selectedId="KRX:005930" />);
      await waitFor(() =>
        expect(dimming).toHaveBeenLastCalledWith(
          expect.anything(),
          true,
          expect.any(Map),
          background,
        ),
      );
    },
  );
  it('keeps the renderer when a parent supplies equivalent appearance values', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const page = (selectedId?: string) => (
      <GraphAppearanceContext
        value={{ variant: 'improved', theme: 'light', preview: true }}
      >
        <GraphCanvas data={data} selectedId={selectedId} />
      </GraphAppearanceContext>
    );
    const view = render(page());
    await waitFor(() => expect(canvas.created).toHaveBeenCalledTimes(1));
    view.rerender(page('KRX:005930'));
    await waitFor(() =>
      expect(
        canvas.setData.mock.lastCall?.[0].nodes.some(
          (n: { id: string }) => n.id === 'KRX:005930',
        ),
      ).toBe(true),
    );
    expect(canvas.created).toHaveBeenCalledTimes(1);
    expect(canvas.destroyed).not.toHaveBeenCalled();
  });

  it('D-GRP-01 82번 화면 모드를 바꾸면 그래프·카메라는 그대로 두고 색만 다시 읽어 그린다', async () => {
    document.documentElement.dataset.theme = 'light';
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    // 지도 화면처럼 화면 모드를 그래프 모양(GraphAppearanceContext)으로도 내려준다.
    function Themed() {
      const theme = useColorTheme();
      return (
        <GraphAppearanceContext value={{ variant: 'improved', theme }}>
          <GraphCanvas data={data} />
        </GraphAppearanceContext>
      );
    }
    render(<Themed />);
    await waitFor(() => expect(canvas.created).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const draws = canvas.setData.mock.calls.length;
    canvas.zoomTo.mockClear();
    canvas.translateTo.mockClear();
    canvas.fitView.mockClear();

    document.documentElement.style.setProperty('--color-zoop-ink', '#fafafa');
    act(() => {
      toggleTheme();
    });

    await waitFor(() =>
      expect(canvas.setData.mock.calls.length).toBeGreaterThan(draws),
    );
    expect(canvas.created).toHaveBeenCalledTimes(1);
    expect(canvas.destroyed).not.toHaveBeenCalled();
    expect(canvas.setNode.mock.lastCall?.[0].state.hovered.haloStroke).toBe(
      '#fafafa',
    );
    expect(canvas.setEdge).toHaveBeenCalled();
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(canvas.translateTo).not.toHaveBeenCalled();
    expect(canvas.fitView).not.toHaveBeenCalled();
    document.documentElement.style.removeProperty('--color-zoop-ink');
    act(() => {
      toggleTheme();
    });
  });

  it('D-GRP-01 does not move nodes by dragging; only the map camera moves', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.created).toHaveBeenCalled());
    const behaviors = canvas.created.mock.lastCall![0].behaviors as (
      string | { type?: string }
    )[];
    expect(
      behaviors.some(
        (b) =>
          b === 'drag-element' ||
          (typeof b === 'object' && b.type === 'drag-element'),
      ),
    ).toBe(false);
    expect(canvas.handlers.has('node:dragend')).toBe(false);
  });

  it('D-GRP-01 hides the source and snapshot timestamp from the map canvas', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);

    expect(screen.queryByText(/SOURCE ·/)).toBeNull();
    expect(screen.queryByText(/AS OF/)).toBeNull();
  });

  it('D-GRP-01 double click fits the visible neighborhood and the tutorial blocks double click', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const view = render(<GraphCanvas data={data} />);
    const host = screen.getByRole('img');
    Object.defineProperty(host, 'clientWidth', {
      configurable: true,
      value: 1200,
    });
    Object.defineProperty(host, 'clientHeight', {
      configurable: true,
      value: 700,
    });
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    canvas.zoomTo.mockClear();
    await act(async () =>
      canvas.handlers.get('node:dblclick')!({ target: { id: 'KRX:005930' } }),
    );
    await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
    expect(canvas.zoomTo.mock.lastCall![0]).toBeLessThanOrEqual(1.8);
    canvas.zoomTo.mockClear();
    fireEvent.keyDown(screen.getByRole('button', { name: '기업: 삼성전자' }), {
      key: 'Enter',
      shiftKey: true,
    });
    await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
    view.rerender(
      <GraphCanvas data={data} tutorialLocked tutorialTargetId="KRX:005930" />,
    );
    await act(async () => {});
    canvas.zoomTo.mockClear();
    await act(async () => {
      canvas.handlers.get('node:dblclick')!({ target: { id: 'KRX:005930' } });
    });
    expect(canvas.zoomTo).not.toHaveBeenCalled();
  });

  it('D-GRP-01 Shift+Enter on a single-company event fits its visible neighborhood', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    render(<GraphCanvas data={data} onSelect={onSelect} />);
    const host = screen.getByRole('img');
    Object.defineProperty(host, 'clientWidth', {
      configurable: true,
      value: 1200,
    });
    Object.defineProperty(host, 'clientHeight', {
      configurable: true,
      value: 700,
    });
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const drawnIds = () =>
      (
        canvas.setData.mock.lastCall![0] as { nodes: { id: string }[] }
      ).nodes.map((node) => node.id);
    expect(drawnIds()).toContain('mock-issue-20');
    canvas.zoomTo.mockClear();
    fireEvent.keyDown(
      screen.getByRole('button', { name: '사건: 삼성전자 개별 공시 (예시)' }),
      { key: 'Enter', shiftKey: true },
    );
    await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
    expect(onSelect).not.toHaveBeenCalled();
    expect(canvas.zoomTo.mock.lastCall![0]).toBeLessThanOrEqual(1.8);
  });

  it('M-GRP-01 folds path details into a compact bar and reopens the sheet without losing the path', async () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    useAuthStore.setState({ status: 'ready', session: null, member: null });
    useGraphUiStore.getState().reset();
    vi.spyOn(graphApi, 'getGraph').mockResolvedValue(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
    );
    const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
      initialEntries: ['/?mode=all&path=KRX:005930,NASDAQ:NVDA'],
    });
    render(<RouterProvider router={router} />);
    await screen.findByRole('dialog', { name: '지도 상세' });
    await userEvent.click(screen.getByRole('button', { name: '지도로 접기' }));
    expect(screen.queryByRole('dialog', { name: '지도 상세' })).toBeNull();
    const bar = screen.getByRole('group', { name: '지도 경로' });
    expect(bar.textContent).toContain('삼성전자 ⇆ NVIDIA');
    expect(router.state.location.search).toContain('path=');
    await userEvent.click(
      within(bar).getByRole('button', { name: '경로 단계 보기' }),
    );
    expect(screen.getByRole('dialog', { name: '지도 상세' })).toBeTruthy();
  });
  it('모바일의 기존 상세/경로를 닫고 실제 캔버스에서 재시작·이동·확대·기업 선택을 수행한다', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('max-width: 767px'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    useAuthStore.setState({ status: 'ready', session: null, member: null });
    useGraphUiStore.getState().reset();
    vi.spyOn(graphApi, 'getGraph').mockResolvedValue(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
    );
    const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
      initialEntries: [
        '/?mode=all&path=KRX:005930,NASDAQ:NVDA&select=node:KRX:005930',
      ],
    });
    const view = render(<RouterProvider router={router} />);
    await screen.findByRole('dialog', { name: '지도 상세' });
    await act(async () => {
      await router.navigate(
        '/?mode=all&tour=1&path=KRX:005930,NASDAQ:NVDA&select=node:KRX:005930&impact=KRX:005930,old&round=old&asOf=2020-01-01T00:00:00Z&graphVersion=old',
      );
    });
    const pad = await screen.findByRole('button', {
      name: '강조된 지도 이동 영역',
    });
    expect(screen.queryByRole('dialog', { name: '지도 상세' })).toBeNull();
    for (
      let parent: HTMLElement | null = pad;
      parent;
      parent = parent.parentElement
    )
      expect(parent.inert).not.toBe(true);
    expect(router.state.location.search).toBe('?mode=all&tour=1');
    fireEvent.keyDown(pad, { key: 'ArrowRight' });
    const zoom = screen.getByRole('button', { name: '확대' });
    await waitFor(() =>
      expect((zoom as HTMLButtonElement).disabled).toBe(false),
    );
    await userEvent.click(zoom);
    const target = await screen.findByRole('button', {
      name: '강조된 삼성전자 노드 선택',
    });
    await userEvent.click(target);
    await screen.findByRole('dialog', { name: '지도 상세' });
    expect(useGraphUiStore.getState().tutorialStep).toBe(3);
    view.unmount();
  });
  it('기업 하나에만 연결된 목표 사건도 실제 G6 데이터와 클릭 강조 영역에 표시한다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const company = data.nodes.find((node) => node.id === 'KRX:005930')!;
    const issue = data.nodes.find((node) => node.kind === 'issue')!;
    const edge = data.edges.find(
      (edge) => edge.source === issue.id && edge.target === company.id,
    )!;
    const small = { ...data, nodes: [company, issue], edges: [edge] };
    const select = vi.fn();
    render(
      <GraphCanvas
        data={small}
        tutorialLocked
        tutorialTargetId={issue.id}
        onSelect={select}
      />,
    );
    const marker = await screen.findByRole('button', {
      name: `강조된 ${issue.label} 노드 선택`,
    });
    await waitFor(() => {
      const rendered = canvas.setData.mock.lastCall![0] as GraphData;
      expect(
        rendered.nodes?.some(
          (node) => node.id === issue.id && node.style?.visibility !== 'hidden',
        ),
      ).toBe(true);
    });
    await userEvent.click(marker);
    expect(select).toHaveBeenCalledWith(issue.id);
    const draws = canvas.draw.mock.calls.length;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(canvas.draw).toHaveBeenCalledTimes(draws);
  });
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
        expect(direct?.style?.lineWidth).toBe(2.2);
        expect(direct?.style?.stroke).toBe(
          theme === 'dark' ? '#a5a9b1' : '#71757c',
        );
        const label = rendered.nodes?.find(
          (node) => node.id === 'NASDAQ:NVDA',
        )?.style;
        expect(Number(label?.labelFontSize)).toBeGreaterThan(17.2);
        expect(
          screen.getByRole('button', { name: 'AI 채팅' }).querySelector('img'),
        ).toBeNull();
        const filters = screen.getByRole('group', { name: '그래프 표시 필터' });
        expect(filters.closest('.relationship-toolbar')).toBeTruthy();
        expect(screen.queryByLabelText('그래프 범례')).toBeNull();
      } finally {
        unmount();
        delete document.documentElement.dataset.theme;
      }
    },
  );
  it('튜토리얼은 프로그램 맞춤으로 완료되지 않고 실제 이동·확대 동작을 보고한다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const action = vi.fn();
    canvas.translateBy.mockResolvedValue(undefined);
    const view = render(
      <GraphCanvas data={data} tutorialPhase="pan" onTutorialAction={action} />,
    );
    await waitFor(() =>
      expect(canvas.handlers.has('aftertransform')).toBe(true),
    );
    await waitFor(() =>
      expect(canvas.zoomTo).toHaveBeenCalledWith(0.53, false),
    );
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByLabelText('지도 확대 조절').style.left).toBe('');
    expect(screen.getByLabelText('지도 확대 조절').style.right).toBe('');
    screen.getByRole('button', { name: '강조된 지도 이동 영역' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    await waitFor(() => expect(action).toHaveBeenCalledWith('pan'));
    view.rerender(
      <GraphCanvas
        data={data}
        tutorialPhase="zoom"
        onTutorialAction={action}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /^확대$/ }));
    expect(action).toHaveBeenCalledWith('zoom');
    action.mockClear();
    fireEvent.wheel(screen.getByRole('img', { name: /관계 지도:/ }), {
      deltaY: -100,
    });
    canvas.getZoom.mockReturnValue(1.25);
    act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
    expect(action).toHaveBeenCalledWith('zoom');
    expect(canvas.created).toHaveBeenCalledTimes(1);
  });

  it('1단계는 그래프를 반투명·입력 차단하고 바깥 이동 영역의 드래그만 실습으로 처리한다', async () => {
    vi.stubGlobal('PointerEvent', MouseEvent);
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const action = vi.fn();
    const select = vi.fn();
    const edge = vi.fn();
    render(
      <GraphCanvas
        data={data}
        tutorialPhase="pan"
        onTutorialAction={action}
        onSelect={select}
        onSelectEdge={edge}
      />,
    );
    await waitFor(() => expect(canvas.handlers.has('node:click')).toBe(true));
    const surface = screen.getByRole('img', { name: /관계 지도:/ });
    expect(surface.className).toContain('pointer-events-none');
    expect(surface.className).toContain('opacity-35');
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: data.nodes[0].id } }),
    );
    act(() =>
      canvas.handlers.get('edge:click')!({ target: { id: data.edges[0].id } }),
    );
    expect(select).not.toHaveBeenCalled();
    expect(edge).not.toHaveBeenCalled();
    const pad = screen.getByRole('button', { name: '강조된 지도 이동 영역' });
    pad.setPointerCapture = vi.fn();
    fireEvent.pointerDown(pad, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(pad, { clientX: 70, clientY: 40 });
    fireEvent.pointerUp(pad, { button: 0, clientX: 70, clientY: 40 });
    await waitFor(() =>
      expect(canvas.translateBy).toHaveBeenCalledWith([60, 30], false),
    );
    await waitFor(() => expect(action).toHaveBeenCalledWith('pan'));
  });

  it('튜토리얼 목표만 밝게 유지하고 다른 노드·연결은 선택하지 않는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const issue = data.nodes.find((node) => node.kind === 'issue')!;
    const select = vi.fn();
    const edge = vi.fn();
    render(
      <GraphCanvas
        data={data}
        tutorialLocked
        tutorialTargetId={issue.id}
        onSelect={select}
        onSelectEdge={edge}
      />,
    );
    const hit = await screen.findByRole('button', {
      name: `강조된 ${issue.label} 노드 선택`,
    });
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenCalledWith(
        expect.objectContaining({
          [issue.id]: ['tutorial'],
        }),
      ),
    );
    // Everything but the target sits under the dimming cover.
    expect(appliedStates()[data.nodes[0].id] ?? []).toEqual([]);
    expect(
      document
        .querySelector('[data-map-dimmed]')
        ?.getAttribute('data-map-dimmed'),
    ).toBe('true');
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: data.nodes[0].id } }),
    );
    act(() =>
      canvas.handlers.get('edge:click')!({ target: { id: data.edges[0].id } }),
    );
    expect(select).not.toHaveBeenCalled();
    expect(edge).not.toHaveBeenCalled();
    expect(parseFloat(hit.style.width)).toBeGreaterThan(20 * 1.15);
    await userEvent.click(hit);
    expect(select).toHaveBeenCalledWith(issue.id);
  });

  it('2단계는 카메라 조작을 허용하면서 다른 노드와 배경 선택은 막는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const company = data.nodes.find((node) => node.id === 'KRX:005930')!;
    const select = vi.fn();
    const { container } = render(
      <GraphCanvas
        data={data}
        tutorialLocked
        tutorialCameraEnabled
        tutorialTargetId={company.id}
        onSelect={select}
      />,
    );
    await screen.findByRole('button', {
      name: `강조된 ${company.label} 노드 선택`,
    });
    const host = container.querySelector('.relationship-g6')!;
    expect(host.classList.contains('pointer-events-none')).toBe(false);
    expect(host.getAttribute('data-tutorial-action')).toBe('move');
    act(() => canvas.handlers.get('canvas:click')!({ target: { id: '' } }));
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: data.nodes[0].id } }),
    );
    expect(select).not.toHaveBeenCalled();
    canvas.zoomTo.mockClear();
    await userEvent.click(screen.getByRole('button', { name: '확대' }));
    expect(canvas.zoomTo).toHaveBeenCalled();
  });

  it('3단계에서 선택 기업의 이웃은 밝기를 유지하되 목표 사건 외 선택은 막는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const company = data.nodes.find((node) => node.id === 'KRX:005930')!;
    const relation = data.edges.find(
      (edge) =>
        (edge.source === company.id || edge.target === company.id) &&
        data.nodes.some(
          (node) =>
            node.kind === 'issue' &&
            node.id ===
              (edge.source === company.id ? edge.target : edge.source),
        ),
    )!;
    const issueId =
      relation.source === company.id ? relation.target : relation.source;
    const select = vi.fn();
    const { container } = render(
      <GraphCanvas
        data={data}
        selectedId={company.id}
        tutorialLocked
        tutorialShowNeighborhood
        tutorialTargetId={issueId}
        onSelect={select}
      />,
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenCalledWith(
        expect.objectContaining({
          [company.id]: ['related', 'selected'],
          [issueId]: ['related', 'tutorial'],
          [relation.id]: ['related'],
        }),
      ),
    );
    expect(
      container
        .querySelector('.relationship-g6')
        ?.classList.contains('pointer-events-none'),
    ).toBe(true);
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: company.id } }),
    );
    expect(select).not.toHaveBeenCalled();
  });

  it('shows the full API issue title on hover and clears it on leave', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const issue = data.nodes.find((node) => node.kind === 'issue')!;
    issue.label = 'API 사건의 긴 제목 전체가 호버 안내에 표시되어야 합니다';
    render(<GraphCanvas data={data} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    // D-GRP-01: brushing past the node (leaving before HOVER_INTENT_MS) shows nothing.
    act(() =>
      canvas.handlers.get('node:pointerenter')!({ target: { id: issue.id } }),
    );
    act(() =>
      canvas.handlers.get('node:pointerleave')!({ target: { id: issue.id } }),
    );
    await new Promise((resolve) => setTimeout(resolve, HOVER_INTENT_MS + 50));
    expect(screen.queryByRole('tooltip')).toBeNull();
    act(() =>
      canvas.handlers.get('node:pointerenter')!({ target: { id: issue.id } }),
    );
    expect(screen.queryByRole('tooltip')).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole('tooltip').textContent).toBe(issue.label),
    );
    act(() =>
      canvas.handlers.get('node:pointerleave')!({ target: { id: issue.id } }),
    );
    expect(screen.queryByRole('tooltip')).toBeNull();
    // Coming back before the delayed hover clear shows the title again.
    act(() =>
      canvas.handlers.get('node:pointerenter')!({ target: { id: issue.id } }),
    );
    expect(screen.getByRole('tooltip').textContent).toBe(issue.label);
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

      // An explicit fit can still use the full, newly expanded graph surface. Since
      // 2026-11-04 it moves only the camera: the map keeps its first-drawn node positions.
      await userEvent.click(
        screen.getByRole('button', { name: '전체 그래프 맞춤' }),
      );
      await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
      expect(positions()).toEqual(before);
    },
  );
  it('D-GRP-01 keeps every drawn node in place when selecting a company unfolds its issues', async () => {
    // 2026-11-04 decision: only focus and flow arrangements move nodes on the map.
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const company = graph.nodes.find((node) => node.kind === 'company')!;
    const template = graph.nodes.find((node) => node.kind === 'issue')!;
    const extra = Array.from({ length: 8 }, (_, index) => ({
      ...template,
      id: `issue-busy-${index}`,
      isFocus: false,
      evidenceCount: index,
    }));
    const data = {
      ...graph,
      nodes: [...graph.nodes, ...extra],
      edges: [
        ...graph.edges,
        ...extra.map((issue, index) => ({
          ...graph.edges[0],
          id: `busy-${index}`,
          source: issue.id,
          target: company.id,
          relationType: 'INVOLVES' as const,
        })),
      ],
    };
    const { rerender } = render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const positions = () =>
      new Map(
        (canvas.setData.mock.lastCall![0] as GraphData).nodes!.map((node) => [
          String(node.id),
          [node.style!.x, node.style!.y],
        ]),
      );
    const before = positions();
    expect(before.has('issue-busy-0')).toBe(false);
    const host = screen.getByRole('img');
    // The detail rail narrows the canvas as the company opens.
    Object.defineProperty(host, 'clientWidth', {
      value: 700,
      configurable: true,
    });
    rerender(<GraphCanvas data={data} selectedId={company.id} />);
    await waitFor(() => expect(positions().has('issue-busy-0')).toBe(true));
    const after = positions();
    for (const [id, position] of before)
      expect([id, after.get(id)]).toEqual([id, position]);
  });
  it('D-GRP-03 lights only the spotlit companies, their shared issues and the lines between them', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const shared = data.edges.find(
      (edge) => edge.relationType === 'SHARES_ISSUE',
    )!;
    const spotlight = [shared.source, shared.target, ...shared.via];
    render(
      <GraphCanvas
        data={data}
        selectedId={shared.source}
        spotlight={spotlight}
      />,
    );
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    const rendered = canvas.setData.mock.lastCall![0] as GraphData;
    await waitFor(() =>
      expect(
        screen
          .getByTestId('graph-canvas')
          .querySelector('[data-map-dimmed]')
          ?.getAttribute('data-map-dimmed'),
      ).toBe('true'),
    );
    const lit = new Set(spotlight);
    const other = rendered.nodes!.find((node) => !lit.has(String(node.id)))!;
    const states = appliedStates();
    expect(states[shared.target]).toContain('related');
    expect(states[shared.via[0]]).toContain('related');
    expect(states[String(other.id)] ?? []).not.toContain('related');
    const between = rendered.edges!.find(
      (edge) => lit.has(String(edge.source)) && lit.has(String(edge.target)),
    )!;
    expect(states[String(between.id)]).toContain('related');
  });
  it('keeps a user-placed view centered when a sidebar narrows the map', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    sessionStorage.setItem(
      'zoop.graph.view:member-a:all',
      JSON.stringify({
        url: '/?mode=all',
        view: {
          hidden: [],
          camera: { zoom: 1, position: [0, 0], size: [0, 0], layout: 2 },
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
    const direct = await screen.findByRole('button', { name: /^직접 관련/ });
    expect(direct.getAttribute('title')).toContain(
      '기업이 사건의 당사자입니다',
    );
    // 2026-11-04: shared-issue lines are not drawn, so the legend has no chip for them.
    expect(screen.queryByRole('button', { name: /^사건 공유/ })).toBeNull();
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
      const button = screen.getByRole('button', { name: /^직접 관련 \d/ });
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
                'INVOLVES',
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
  it('ports legend filters without moving nodes and never hides companies or issues', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const before = (canvas.setData.mock.lastCall![0] as GraphData).nodes?.find(
      (node) => node.id === 'NASDAQ:NVDA',
    )?.style;
    // 2026-11-04 decision: company and issue counts are labels, not toggles.
    const filters = screen.getByRole('group', { name: '그래프 표시 필터' });
    expect(
      within(filters).queryByRole('button', { name: /^기업 \d/ }),
    ).toBeNull();
    expect(
      within(filters).queryByRole('button', { name: /^사건 \d/ }),
    ).toBeNull();
    expect(filters.textContent).toMatch(/기업 \d+/);
    expect(filters.textContent).toMatch(/사건 \d+/);
    await userEvent.click(
      screen.getByRole('button', { name: /^직접 관련 \d/ }),
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: /^직접 관련 \d/ })
          .getAttribute('aria-pressed'),
      ).toBe('false'),
    );
    const after = (canvas.setData.mock.lastCall![0] as GraphData).nodes?.find(
      (node) => node.id === 'NASDAQ:NVDA',
    )?.style;
    expect(after?.visibility).toBe('visible');
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
    // G6 returns world-space pan; convert the delta to pixels at restored zoom 1.8.
    expect(canvas.translateBy).toHaveBeenCalledWith([63, 90], false);
  });
  it('D-GRP-01 mobile reload converts saved world pan to pixels at the saved zoom', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { unmount } = render(
      <GraphCanvas data={data} memoryOwner="mobile-reload" />,
    );
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    canvas.getZoom.mockReturnValue(0.2);
    canvas.getPosition.mockReturnValue([500, -200]);
    act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
    unmount();
    canvas.getPosition.mockReturnValue([0, 0]);
    canvas.translateBy.mockClear();
    render(<GraphCanvas data={data} memoryOwner="mobile-reload" />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(2));
    expect(canvas.zoomTo).toHaveBeenCalledWith(0.2, false);
    // G6 getPosition is world-space; translateBy consumes screen pixels.
    expect(canvas.translateBy).toHaveBeenCalledWith([100, -40], false);
  });
  it('opens the default layout instead of a saved camera taken at another map size', async () => {
    const all = createMockGraph({ mode: 'all', personalFilter: 'all' });
    sessionStorage.setItem(
      'zoop.graph.view:member-a:all',
      JSON.stringify({
        url: '/?mode=all',
        view: {
          hidden: [],
          camera: {
            zoom: 1.8,
            position: [40, 60],
            size: [1600, 900],
            layout: 2,
          },
        },
      }),
    );
    render(<GraphCanvas data={all} memoryOwner="member-a" />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    await waitFor(() =>
      expect(canvas.zoomTo).toHaveBeenCalledWith(0.53, false),
    );
    expect(canvas.translateTo).not.toHaveBeenCalled();
    expect(canvas.translateBy).not.toHaveBeenCalled();
  });
  it('D-GRP-01 flow order neither reuses nor overwrites the remembered map camera', async () => {
    const all = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const saved = JSON.stringify({
      url: '/?mode=all',
      view: {
        hidden: [],
        camera: { zoom: 1.8, position: [40, 60], size: [0, 0], layout: 2 },
      },
    });
    sessionStorage.setItem('zoop.graph.view:member-a:all', saved);
    const { unmount } = render(
      <GraphCanvas data={all} memoryOwner="member-a" flow />,
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    expect(canvas.zoomTo).not.toHaveBeenCalledWith(1.8, false);
    canvas.getZoom.mockReturnValue(0.4);
    canvas.getPosition.mockReturnValue([900, 900]);
    unmount();
    expect(
      JSON.parse(sessionStorage.getItem('zoop.graph.view:member-a:all')!).view
        .camera,
    ).toEqual({ zoom: 1.8, position: [40, 60], size: [0, 0], layout: 2 });
  });

  it('D-GRP-01 keeps one minimap on small/narrow graphs, selection, focus, flow and resize', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const smallIds = new Set(data.nodes.slice(0, 50).map((node) => node.id));
    const small = {
      ...data,
      nodes: data.nodes.filter((node) => smallIds.has(node.id)),
      edges: data.edges.filter(
        (edge) => smallIds.has(edge.source) && smallIds.has(edge.target),
      ),
    };
    const { rerender } = render(<GraphCanvas data={small} />);
    const host = screen.getByRole('img');
    Object.defineProperty(host, 'clientWidth', {
      configurable: true,
      value: 1200,
    });
    Object.defineProperty(host, 'clientHeight', {
      configurable: true,
      value: 800,
    });
    await waitFor(() =>
      expect(canvas.setPlugins).toHaveBeenLastCalledWith([
        expect.objectContaining({
          type: 'minimap',
          size: [192, 128],
          padding: 10,
        }),
      ]),
    );
    expect(canvas.setPlugins).toHaveBeenCalledTimes(1);
    const drawn = canvas.minimapRender.mock.calls.length;
    Object.defineProperty(host, 'clientWidth', {
      configurable: true,
      value: 375,
    });
    act(() => canvas.resizeCallbacks.at(-1)?.());
    await waitFor(() =>
      expect(canvas.minimapRender.mock.calls.length).toBeGreaterThan(drawn),
    );
    for (const props of [
      { selectedId: 'KRX:005930' },
      { focusId: 'KRX:005930', focusLayout: true },
      { flow: true },
    ]) {
      const before = canvas.setData.mock.calls.length;
      rerender(<GraphCanvas data={small} {...props} />);
      await waitFor(() =>
        expect(canvas.setData.mock.calls.length).toBeGreaterThan(before),
      );
      expect(canvas.setPlugins).toHaveBeenCalledTimes(1);
    }
  });

  it.each(['none', 'delayed route', 'wheel', 'drag', 'zoom'])(
    'D-GRP-01 returns the preselection camera after switches and resize unless the user intervenes: %s',
    async (interaction) => {
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      const { rerender } = render(<GraphCanvas data={data} />);
      await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
      const host = screen.getByRole('img');
      Object.defineProperties(host, {
        clientWidth: { configurable: true, value: 900 },
        clientHeight: { configurable: true, value: 700 },
      });
      canvas.getPosition.mockReturnValue([40, 60]);
      canvas.getViewportByCanvas.mockImplementation((point) => [
        point[0] + canvas.getPosition()[0],
        point[1] + canvas.getPosition()[1],
      ]);
      canvas.getZoom.mockReturnValue(1.2);
      canvas.translateBy.mockClear();
      if (interaction === 'delayed route') {
        // An uncommitted click must wait for the router before moving the camera.
        act(() =>
          canvas.handlers.get('node:click')!({ target: { id: 'KRX:005930' } }),
        );
        await act(async () => {});
        expect(canvas.translateBy).not.toHaveBeenCalled();
      }
      rerender(<GraphCanvas data={data} selectedId="KRX:005930" />);
      await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
      const positions = () =>
        new Map(
          (canvas.setData.mock.lastCall![0] as GraphData).nodes!.map((n) => [
            n.id,
            [n.style!.x, n.style!.y],
          ]),
        );
      const before = positions();
      canvas.getPosition.mockReturnValue([120, 80]);
      canvas.getZoom.mockReturnValue(1.5);
      const count = canvas.setData.mock.calls.length;
      rerender(<GraphCanvas data={data} selectedId="KRX:000660" />);
      await waitFor(() =>
        expect(canvas.setData.mock.calls.length).toBeGreaterThan(count),
      );
      if (interaction === 'wheel') fireEvent.wheel(host, { deltaY: 20 });
      if (interaction === 'drag') {
        fireEvent.pointerDown(host, {
          button: 0,
          pointerId: 1,
          clientX: 10,
          clientY: 10,
        });
        fireEvent.pointerMove(host, { pointerId: 1, clientX: 40, clientY: 30 });
        fireEvent.pointerUp(window, { button: 0, pointerId: 1 });
      }
      if (interaction === 'zoom') {
        await userEvent.click(
          screen.getByRole('button', {
            name: '확대',
          }),
        );
        await act(async () => {});
      }
      canvas.translateTo.mockClear();
      canvas.translateBy.mockClear();
      canvas.zoomTo.mockClear();
      const drawCount = canvas.setData.mock.calls.length;
      rerender(<GraphCanvas data={data} />);
      await waitFor(() =>
        expect(canvas.setData.mock.calls.length).toBeGreaterThan(drawCount),
      );
      await act(async () => {});
      Object.defineProperty(host, 'clientWidth', {
        configurable: true,
        value: 1200,
      });
      act(() => canvas.resizeCallbacks[0]());
      await waitFor(() =>
        expect(canvas.setSize).toHaveBeenLastCalledWith(1200, 700),
      );
      await act(async () => {});
      if (interaction === 'none' || interaction === 'delayed route') {
        expect(canvas.translateBy).toHaveBeenLastCalledWith([-80, -20], false);
        expect(canvas.translateTo).not.toHaveBeenCalled();
        expect(canvas.zoomTo).toHaveBeenLastCalledWith(1.2, false);
      } else {
        expect(canvas.translateTo).not.toHaveBeenCalled();
        expect(canvas.translateBy).not.toHaveBeenCalled();
        expect(canvas.zoomTo).not.toHaveBeenCalled();
      }
      expect(positions()).toEqual(before);
    },
  );

  /** A camera whose translateBy/zoomTo calls move what getViewportByCanvas reports. */
  function liveCamera(position: [number, number], zoom: number) {
    const camera = { position, zoom };
    canvas.getPosition.mockImplementation(() => camera.position);
    canvas.getViewportByCanvas.mockImplementation((point) => [
      point[0] + camera.position[0],
      point[1] + camera.position[1],
    ]);
    canvas.getZoom.mockImplementation(() => camera.zoom);
    canvas.translateBy.mockImplementation(async ([dx, dy]: number[]) => {
      camera.position = [camera.position[0] + dx, camera.position[1] + dy];
    });
    canvas.zoomTo.mockImplementation(async (next: number) => {
      camera.zoom = next;
    });
    return camera;
  }
  it('D-GRP-01 Shift+Enter on a collapsed node keeps its neighborhood fit after closing', async () => {
    const base = createMockGraph({ mode: 'all', personalFilter: 'all' });
    // Extra single-company issues fold behind 삼성전자's "+N" badge.
    const issue = base.nodes.find((node) => node.id === 'mock-issue-20')!;
    const link = base.edges.find(
      (edge) => edge.source === issue.id || edge.target === issue.id,
    )!;
    const extra = Array.from(
      { length: 8 },
      (_, index) => `fold-issue-${index}`,
    );
    const data = {
      ...base,
      nodes: [
        ...base.nodes,
        ...extra.map((id, index) => ({
          ...issue,
          id,
          label: `접힌 사건 ${index}`,
        })),
      ],
      edges: [
        ...base.edges,
        ...extra.map((id) => ({
          ...link,
          id: `edge-${id}`,
          source: link.source === issue.id ? id : link.source,
          target: link.target === issue.id ? id : link.target,
        })),
      ],
    };
    const onSelect = vi.fn();
    const { rerender } = render(
      <GraphCanvas data={data} onSelect={onSelect} />,
    );
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 700 },
    });
    await act(async () => {});
    const drawn = canvas.setData.mock.lastCall![0] as GraphData;
    const visible = new Set(
      drawn
        .nodes!.filter((node) => node.style?.visibility !== 'hidden')
        .map((node) => node.id),
    );
    const collapsed = data.nodes.find((node) => !visible.has(node.id))!;
    expect(collapsed).toBeDefined();
    const camera = liveCamera([40, 60], 1.2);
    fireEvent.keyDown(
      document.querySelector(`[data-node-id="${collapsed.id}"]`)!,
      {
        key: 'Enter',
        shiftKey: true,
      },
    );
    expect(onSelect).toHaveBeenCalledWith(collapsed.id);
    canvas.zoomTo.mockClear();
    rerender(
      <GraphCanvas data={data} onSelect={onSelect} selectedId={collapsed.id} />,
    );
    await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
    await act(async () => {});
    // The neighborhood fit moved the camera on purpose.
    camera.position = [300, 200];
    camera.zoom = 1.6;
    canvas.translateBy.mockClear();
    canvas.zoomTo.mockClear();
    const count = canvas.setData.mock.calls.length;
    rerender(<GraphCanvas data={data} onSelect={onSelect} />);
    await waitFor(() =>
      expect(canvas.setData.mock.calls.length).toBeGreaterThan(count),
    );
    await act(async () => {});
    expect(canvas.zoomTo).not.toHaveBeenCalledWith(1.2, false);
    expect(camera.position).toEqual([300, 200]);
  });

  /** Select, move the camera for the selection, then deselect: the camera returns to [40, 60] @ 1.2. */
  async function selectAndReturn(
    props: Partial<Parameters<typeof GraphCanvas>[0]> = {},
    duringSelection?: (camera: ReturnType<typeof liveCamera>) => void,
  ) {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { rerender } = render(<GraphCanvas data={data} {...props} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 700 },
    });
    await act(async () => {});
    const camera = liveCamera([40, 60], 1.2);
    let count = canvas.setData.mock.calls.length;
    rerender(<GraphCanvas data={data} {...props} selectedId="KRX:005930" />);
    await waitFor(() =>
      expect(canvas.setData.mock.calls.length).toBeGreaterThan(count),
    );
    await act(async () => {});
    camera.position = [120, 80];
    camera.zoom = 1.5;
    duringSelection?.(camera);
    count = canvas.setData.mock.calls.length;
    const redraw = async (next = props) => {
      const before = canvas.setData.mock.calls.length;
      rerender(<GraphCanvas data={data} {...next} />);
      await waitFor(() =>
        expect(canvas.setData.mock.calls.length).toBeGreaterThan(before),
      );
      await act(async () => {});
    };
    const resize = async (width: number) => {
      Object.defineProperty(host, 'clientWidth', {
        configurable: true,
        value: width,
      });
      act(() => canvas.resizeCallbacks[0]());
      await waitFor(() =>
        expect(canvas.setSize).toHaveBeenLastCalledWith(width, 700),
      );
      await act(async () => {});
    };
    return { camera, host, redraw, resize };
  }
  function dragMinimap(host: HTMLElement) {
    const minimap = document.createElement('div');
    minimap.className = 'graph-overview';
    host.parentElement!.append(minimap);
    fireEvent.pointerDown(minimap, { button: 0, pointerId: 7 });
  }

  it('D-GRP-01 consumes the return before a direct camera move and the first closing resize', async () => {
    const { camera, redraw, resize } = await selectAndReturn();
    await redraw();
    expect(camera).toEqual({ position: [40, 60], zoom: 1.2 });
    camera.position = [300, 200];
    canvas.translateBy.mockClear();
    canvas.zoomTo.mockClear();
    await resize(1200);
    expect(canvas.translateBy).not.toHaveBeenCalled();
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(camera.position).toEqual([300, 200]);
  });

  it('D-GRP-01 edge-only changes retain sidebar centering and a queued fit', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const view = render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 700 },
    });
    liveCamera([40, 60], 1.2);
    const props = {
      data,
      selectedId: 'KRX:005930',
      centerRequest: { id: 'KRX:005930', seq: 1 },
    };
    view.rerender(<GraphCanvas {...props} />);
    await act(async () => {});
    view.rerender(<GraphCanvas {...props} selectedEdgeId="mock-follows-1" />);
    await act(async () => {});
    canvas.translateBy.mockClear();
    act(() => canvas.resizeCallbacks[0]());
    await waitFor(() => expect(canvas.translateBy).toHaveBeenCalled());
    canvas.zoomTo.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '전체 그래프 맞춤' }));
      view.rerender(<GraphCanvas {...props} selectedEdgeId="mock-follows-2" />);
    });
    expect(canvas.zoomTo).toHaveBeenCalled();
  });

  it('D-GRP-01 whole fit follows panel closure and subsequent resize until manual movement', async () => {
    const { host, redraw, resize } = await selectAndReturn();
    await userEvent.click(
      screen.getByRole('button', { name: '전체 그래프 맞춤' }),
    );
    await act(async () => {});
    canvas.zoomTo.mockClear();
    await redraw();
    await resize(1200);
    expect(canvas.zoomTo).toHaveBeenCalled();
    canvas.zoomTo.mockClear();
    await resize(1280);
    expect(canvas.zoomTo).toHaveBeenCalled();
    // 휠 확대는 이제 G6 behavior가 아니라 graph-wheel-zoom.ts가 실제로 zoomTo를 부른다.
    // 축소하면 맞춤 배율로 정한 하한 아래로 내려가(mock은 setZoomRange를 따르지 않는다) 다시 그릴 때 하한으로 올리므로,
    // 하한과 관계없는 확대로 '직접 움직임'만 만든다.
    fireEvent.wheel(host, { deltaY: -20 });
    canvas.zoomTo.mockClear();
    await resize(1300);
    expect(canvas.zoomTo).not.toHaveBeenCalled();
  });

  it.each(['width', 'height'])(
    'D-GRP-01 discards the return when browser %s changes',
    async (axis) => {
      const width = vi
        .spyOn(document.documentElement, 'clientWidth', 'get')
        .mockReturnValue(1920);
      const height = vi
        .spyOn(document.documentElement, 'clientHeight', 'get')
        .mockReturnValue(900);
      const { camera, redraw } = await selectAndReturn();
      if (axis === 'width') width.mockReturnValue(1280);
      else height.mockReturnValue(812);
      canvas.zoomTo.mockClear();
      canvas.translateBy.mockClear();
      await redraw();
      expect(canvas.zoomTo).not.toHaveBeenCalled();
      expect(canvas.translateBy).not.toHaveBeenCalled();
      expect(camera).toEqual({ position: [120, 80], zoom: 1.5 });
      width.mockReturnValue(1920);
      height.mockReturnValue(900);
      await redraw({ selectedId: null, evidenceMode: true });
      expect(canvas.translateBy).not.toHaveBeenCalled();
    },
  );

  it.each([
    { connectionPath: true },
    { tutorialLocked: true },
    { tutorialCenterId: 'KRX:005930' },
    { tutorialPhase: 'pan' as const },
  ])(
    'D-GRP-01 effect selection in a special camera mode does not record a return: %j',
    async (props) => {
      const { redraw, camera } = await selectAndReturn(props);
      canvas.zoomTo.mockClear();
      canvas.translateBy.mockClear();
      await redraw({});
      expect(canvas.zoomTo).not.toHaveBeenCalled();
      expect(canvas.translateBy).not.toHaveBeenCalled();
      expect(camera).toEqual({ position: [120, 80], zoom: 1.5 });
    },
  );

  it.each([false, true])(
    'D-GRP-01 mobile fit reserves only one minimap obstacle (measured=%s)',
    async (measured) => {
      let mobile = true;
      vi.stubGlobal('matchMedia', () => ({
        matches: mobile,
        addEventListener() {},
        removeEventListener() {},
      }));
      const free = vi.spyOn(geometry, 'freeViewport');
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      render(<GraphCanvas data={data} />);
      const host = screen.getByRole('img');
      Object.defineProperties(host, {
        clientWidth: { configurable: true, value: 375 },
        clientHeight: { configurable: true, value: 700 },
      });
      host.getBoundingClientRect = () =>
        ({
          left: 0,
          top: 0,
          right: 375,
          bottom: 700,
          width: 375,
          height: 700,
        }) as DOMRect;
      if (measured) {
        const overview = document.createElement('div');
        overview.className = 'graph-overview';
        overview.getClientRects = () =>
          [{ width: 144, height: 96 }] as unknown as DOMRectList;
        overview.getBoundingClientRect = () =>
          ({ left: 12, top: 540, width: 144, height: 96 }) as DOMRect;
        host.parentElement!.append(overview);
      }
      await waitFor(() =>
        expect(canvas.setPlugins).toHaveBeenLastCalledWith([
          expect.objectContaining({ size: [144, 96] }),
        ]),
      );
      await userEvent.click(
        screen.getByRole('button', { name: '전체 그래프 맞춤' }),
      );
      await act(async () => {});
      const obstacles = free.mock.lastCall![2];
      expect(obstacles).toEqual([
        { x: measured ? 12 : 8, y: 540, width: 144, height: 96 },
      ]);
      mobile = false;
      canvas.setPlugins.mockClear();
      act(() => canvas.resizeCallbacks[0]());
      await waitFor(() =>
        expect(canvas.setPlugins).toHaveBeenLastCalledWith([
          expect.objectContaining({ size: [192, 128] }),
        ]),
      );
      expect(canvas.setPlugins).toHaveBeenNthCalledWith(1, []);
      mobile = true;
      act(() => canvas.resizeCallbacks[0]());
      await waitFor(() =>
        expect(canvas.setPlugins).toHaveBeenLastCalledWith([
          expect.objectContaining({ size: [144, 96] }),
        ]),
      );
    },
  );

  it('D-GRP-01 a pending user fit survives deselection in the same update', async () => {
    const { redraw } = await selectAndReturn();
    canvas.zoomTo.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '전체 그래프 맞춤' }));
      await redraw();
    });
    await act(async () => {});
    expect(canvas.zoomTo).toHaveBeenCalled();
  });

  it('D-GRP-01 selecting an edge does not restore the previous company camera', async () => {
    const onSelectEdge = vi.fn();
    const { camera, redraw } = await selectAndReturn({ onSelectEdge });
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const edge = data.edges.find((item) => item.relationType === 'FOLLOWS')!;
    await act(async () =>
      canvas.handlers.get('edge:click')!({ target: { id: edge.id } }),
    );
    expect(onSelectEdge).toHaveBeenCalledWith(edge.id);
    await redraw({ onSelectEdge, selectedEdgeId: edge.id });
    expect(camera).toEqual({ position: [120, 80], zoom: 1.5 });
  });

  it.each(['focus', 'flow'])(
    'D-GRP-01 fits the map when %s and selection are cleared together',
    async (layout) => {
      const props =
        layout === 'focus'
          ? { focusLayout: true, focusId: 'KRX:005930' }
          : { flow: true };
      const { redraw } = await selectAndReturn(props);
      canvas.zoomTo.mockClear();
      await redraw({});
      expect(canvas.zoomTo).toHaveBeenCalled();
    },
  );

  it('D-GRP-01 a center request without selection does not supply the next selection return', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const view = render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
    const host = screen.getByRole('img');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 700 },
    });
    const camera = liveCamera([40, 60], 1.2);
    view.rerender(
      <GraphCanvas data={data} centerRequest={{ id: 'KRX:005930', seq: 1 }} />,
    );
    await act(async () => {});
    camera.position = [300, 200];
    view.rerender(<GraphCanvas data={data} selectedId="KRX:005930" />);
    await act(async () => {});
    camera.position = [120, 80];
    view.rerender(<GraphCanvas data={data} />);
    await act(async () => {});
    expect(camera.position).toEqual([300, 200]);
  });

  it.each(['path', 'tutorial'])(
    'D-GRP-01 an uncommitted %s click does not supply a later selection return',
    async (mode) => {
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      const onSelect = vi.fn();
      const view = render(
        <GraphCanvas
          data={data}
          onSelect={onSelect}
          connectionPath={mode === 'path'}
          tutorialLocked={mode === 'tutorial'}
          tutorialTargetId="KRX:005930"
        />,
      );
      await waitFor(() => expect(canvas.resizeCallbacks).toHaveLength(1));
      const host = screen.getByRole('img');
      Object.defineProperties(host, {
        clientWidth: { configurable: true, value: 900 },
        clientHeight: { configurable: true, value: 700 },
      });
      const camera = liveCamera([40, 60], 1.2);
      await act(async () =>
        canvas.handlers.get('node:click')!({ target: { id: 'KRX:005930' } }),
      );
      camera.position = [300, 200];
      view.rerender(<GraphCanvas data={data} selectedId="KRX:000660" />);
      await act(async () => {});
      camera.position = [120, 80];
      view.rerender(<GraphCanvas data={data} />);
      await act(async () => {});
      expect(camera.position).toEqual([300, 200]);
    },
  );

  it('D-GRP-01 drops the return target once the restored camera settles', async () => {
    const { camera, redraw, resize } = await selectAndReturn();
    await redraw();
    expect(camera).toEqual({ position: [40, 60], zoom: 1.2 });
    // The detail rail closes: the camera stays where the restore left it.
    await resize(1200);
    // Later the map moves by any path, and the holdings sidebar resizes the canvas.
    camera.position = [300, 200];
    canvas.translateBy.mockClear();
    canvas.zoomTo.mockClear();
    await resize(1000);
    expect(canvas.translateBy).not.toHaveBeenCalled();
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(camera.position).toEqual([300, 200]);
  });

  it.each([
    ['minimap', 'during selection'],
    ['minimap', 'after return'],
    ['arrow key', 'during selection'],
    ['arrow key', 'after return'],
  ])(
    'D-GRP-01 a %s move %s cancels the selection camera return',
    async (path, timing) => {
      const props =
        path === 'arrow key' ? { tutorialPhase: 'pan' as const } : {};
      const move = (host: HTMLElement) => {
        if (path === 'minimap') {
          dragMinimap(host);
          canvas.translateBy([30, 0], false);
        } else {
          fireEvent.keyDown(
            screen.getByRole('button', { name: '강조된 지도 이동 영역' }),
            { key: 'ArrowRight' },
          );
        }
      };
      const { camera, host, redraw, resize } = await selectAndReturn(
        timing === 'after return' ? {} : props,
        timing === 'during selection'
          ? () => move(screen.getByRole('img'))
          : undefined,
      );
      await act(async () => {});
      let moved = camera.position;
      await redraw(props);
      if (timing === 'after return') {
        expect(camera).toEqual({ position: [40, 60], zoom: 1.2 });
        move(host);
        await act(async () => {});
        moved = camera.position;
      }
      expect(camera.position).toEqual(moved);
      canvas.translateBy.mockClear();
      canvas.zoomTo.mockClear();
      await resize(1200);
      expect(canvas.translateBy).not.toHaveBeenCalled();
      expect(canvas.zoomTo).not.toHaveBeenCalled();
      expect(camera.position).toEqual(moved);
    },
  );

  it('D-GRP-01 does not undo a focus move drawn together with the deselection', async () => {
    const { camera, redraw } = await selectAndReturn();
    canvas.translateBy.mockClear();
    canvas.zoomTo.mockClear();
    await redraw({ focusId: 'KRX:000660' });
    expect(canvas.focusElement).toHaveBeenLastCalledWith('KRX:000660', false);
    expect(canvas.translateBy).not.toHaveBeenCalled();
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(camera).toEqual({ position: [120, 80], zoom: 1.5 });
  });

  it('D-GRP-01 does not undo a center request drawn together with the deselection', async () => {
    const { camera, redraw } = await selectAndReturn();
    canvas.zoomTo.mockClear();
    await redraw({ centerRequest: { id: 'KRX:000660', seq: 1 } });
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    expect(camera.zoom).toBe(1.5);
  });

  it('D-GRP-01 moves the mobile minimap left of the round zoom buttons', async () => {
    render(
      <GraphCanvas
        data={createMockGraph({ mode: 'all', personalFilter: 'all' })}
      />,
    );
    const root = await screen.findByTestId('graph-canvas');
    expect(root.className).toContain('[&_.graph-overview]:right-0!');
    expect(root.className).toContain('max-md:[&_.graph-overview]:right-auto!');
    expect(root.className).toContain('max-md:[&_.graph-overview]:left-2!');
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
  it('D-GRP-01 hover emphasizes incident nodes/edges without dimming, selecting or redrawing the viewport', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    render(<GraphCanvas data={data} onSelect={onSelect} />);
    // Nothing is emphasized yet, so no element state needs to be sent.
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
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
      expect(appliedStates()).toMatchObject({
        'NASDAQ:NVDA': ['hovered'],
        'mock-issue-1': ['related'],
        [edge.id]: ['related'],
      }),
    );
    // Only a click selection dims the rest; hover leaves unrelated nodes as they were.
    expect(appliedStates()['KRX:005380'] ?? []).toEqual([]);
    expect(onSelect).not.toHaveBeenCalled();
    expect(canvas.draw).toHaveBeenCalledTimes(draws);
    expect(canvas.setData).toHaveBeenCalledTimes(layouts);
    expect(canvas.focusElement).not.toHaveBeenCalled();
    expect(canvas.created).toHaveBeenCalledOnce();
  });

  it('D-GRP-01 moving between nodes ignores stale leave and keeps the clicked node emphasized on exit', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const shared = data.edges.find((edge) => edge.relationType === 'FOLLOWS')!;
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
      expect(appliedStates()).toMatchObject({
        'mock-issue-1': ['hovered'],
        'KRX:005930': ['related', 'selected'],
      }),
    );
    await act(async () =>
      canvas.handlers.get('canvas:pointerleave')!({ target: { id: 'canvas' } }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({
        // Without hover, the clicked node keeps its connections emphasized.
        'mock-issue-1': ['related'],
        'KRX:005930': ['related', 'selected'],
        [shared.id]: expect.arrayContaining(['selected']),
      }),
    );
    expect(canvas.created).toHaveBeenCalledOnce();
  });

  it('D-GRP-01 hover cannot brighten nodes outside an explicit focus scope', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} focusId="NASDAQ:NVDA" focusHops={1} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'KRX:005380' },
      }),
    );
    expect(appliedStates()['KRX:005380'] ?? []).toEqual([]);
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
    // Dimming is one cover over the map (graph-dimming.ts), not a G6 state.
    expect(
      Object.values(states).some((list) => list.includes('inactive')),
    ).toBe(false);
    expect(
      document
        .querySelector('[data-map-dimmed]')
        ?.getAttribute('data-map-dimmed'),
    ).toBe('false');
  });

  it('D-GRP-01 outside focus mode a selected company still dims unrelated nodes', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} selectedId="NASDAQ:NVDA" />);
    await waitFor(() => expect(canvas.setElementState).toHaveBeenCalled());
    const states = canvas.setElementState.mock.calls.at(-1)![0] as Record<
      string,
      string[]
    >;
    // Dimming is one cover over the map (graph-dimming.ts), not a G6 state.
    expect(
      Object.values(states).some((list) => list.includes('inactive')),
    ).toBe(false);
    expect(
      document
        .querySelector('[data-map-dimmed]')
        ?.getAttribute('data-map-dimmed'),
    ).toBe('true');
  });

  it('D-GRP-01 shows each zoom control name on hover and lets the tutorial camera step use fit', () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    const zoom = screen.getByLabelText('지도 확대 조절');
    for (const name of ['확대', '축소', '전체 그래프 맞춤']) {
      const button = within(zoom).getByRole('button', { name });
      expect(button.textContent).toContain(name);
      expect(button.getAttribute('data-tutorial-action')).toBe('zoom');
    }
  });

  it('D-GRP-01 shows the flow order toggle in the always-visible zoom controls', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onFlowChange = vi.fn();
    const { rerender } = render(
      <GraphCanvas data={data} onFlowChange={onFlowChange} />,
    );
    const zoom = screen.getByLabelText('지도 확대 조절');
    const toggle = within(zoom).getByRole('button', {
      name: '흐름 순으로 정렬',
    });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    await act(async () => toggle.click());
    expect(onFlowChange).toHaveBeenCalledWith(true);
    rerender(
      <GraphCanvas
        data={data}
        onFlowChange={onFlowChange}
        focusId="NASDAQ:NVDA"
        focusLayout
      />,
    );
    expect(
      (
        within(screen.getByLabelText('지도 확대 조절')).getByRole('button', {
          name: '흐름 순으로 정렬',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it('D-GRP-04 selects eligible edges via canvas/keyboard and never recreates the viewport', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelectEdge = vi.fn();
    const shared = data.edges.find(
      (edge) => edge.relationType === 'SHARES_ISSUE',
    )!;
    const follows = data.edges.find((edge) => edge.relationType === 'FOLLOWS')!;
    const involves = data.edges.find(
      (edge) => edge.relationType === 'INVOLVES',
    )!;
    const { rerender } = render(
      <GraphCanvas data={data} onSelectEdge={onSelectEdge} />,
    );
    await waitFor(() => expect(canvas.handlers.has('edge:click')).toBe(true));
    // 2026-11-04: shared-issue lines are not drawn, so they cannot be selected either.
    for (const edge of [involves, shared])
      await act(async () =>
        canvas.handlers.get('edge:click')!({ target: { id: edge.id } }),
      );
    expect(onSelectEdge).not.toHaveBeenCalled();
    expect(
      (canvas.setData.mock.lastCall![0] as GraphData).edges?.some(
        (edge) => edge.id === shared.id,
      ),
    ).toBe(false);
    expect(screen.queryByRole('button', { name: /사건 공유/ })).toBeNull();
    await act(async () =>
      canvas.handlers.get('edge:click')!({ target: { id: follows.id } }),
    );
    expect(onSelectEdge).toHaveBeenCalledWith(follows.id);
    rerender(
      <GraphCanvas
        data={data}
        onSelectEdge={onSelectEdge}
        selectedEdgeId={follows.id}
      />,
    );
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ [follows.id]: ['selected'] }),
      ),
    );
    onSelectEdge.mockClear();
    await userEvent.click(
      screen.getByRole('button', {
        name: /연결선: HBM3E 12단 경쟁 – HBM4 공급 계약/,
      }),
    );
    expect(onSelectEdge).toHaveBeenLastCalledWith('mock-follows-1');
    rerender(<GraphCanvas data={data} onSelectEdge={onSelectEdge} />);
    await waitFor(() =>
      expect(canvas.setElementState).toHaveBeenLastCalledWith(
        expect.objectContaining({ [follows.id]: [] }),
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
  it('opens a single-company event from the keyboard and retains it when it is the focus target', async () => {
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

  it('D-GRP-01 노드 위에서 끌어도 지도를 옮기고, 끈 뒤 손을 뗄 때의 클릭으로 노드를 고르지 않는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    render(<GraphCanvas data={data} onSelect={onSelect} />);
    await waitFor(() => expect(canvas.handlers.has('node:click')).toBe(true));
    const options = canvas.created.mock.lastCall?.[0] as {
      behaviors: unknown[];
      node: {
        state: Record<string, Record<string, unknown>>;
      };
    };
    expect(options.behaviors[0]).toEqual({
      type: 'drag-canvas',
      enable: true,
      animation: false,
    });
    const surface = screen.getByRole('img', { name: /관계 지도:/ });

    fireEvent.pointerDown(surface, { button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(surface, { clientX: 140, clientY: 125 });
    fireEvent.pointerUp(window, { clientX: 140, clientY: 125 });
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: data.nodes[0].id } }),
    );
    act(() => canvas.handlers.get('canvas:click')!({ target: { id: '' } }));
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.pointerDown(surface, { button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerUp(window, { clientX: 101, clientY: 100 });
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: data.nodes[0].id } }),
    );
    expect(onSelect).toHaveBeenCalledWith(data.nodes[0].id);
  });

  it('D-GRP-01 끌고 있는 동안 지나친 hover는 그리지 않고, 손을 뗄 때 마지막으로 가리킨 노드만 한 번 반영한다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const draws = canvas.draw.mock.calls.length;
    const surface = screen.getByRole('img', { name: /관계 지도:/ });
    const issue = data.nodes.find((node) => node.kind === 'issue')!;

    fireEvent.pointerDown(surface, { button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(surface, { clientX: 140, clientY: 125 });
    await act(async () => {
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      });
      canvas.handlers.get('edge:pointerenter')!({
        target: { id: data.edges[0].id },
      });
      canvas.handlers.get('node:pointerleave')!({
        target: { id: 'NASDAQ:NVDA' },
      });
      canvas.handlers.get('edge:pointerleave')!({ target: { id: '' } });
      canvas.handlers.get('node:pointerenter')!({ target: { id: issue.id } });
    });
    expect(canvas.setElementState).not.toHaveBeenCalled();
    expect(canvas.draw).toHaveBeenCalledTimes(draws);
    expect(screen.queryByRole('tooltip')).toBeNull();

    await act(async () =>
      fireEvent.pointerUp(window, { clientX: 140, clientY: 125 }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ [issue.id]: ['hovered'] }),
    );
    expect(canvas.setElementState).toHaveBeenCalledOnce();
    // 끌기 중 지나친 NVDA는 hover되지 않는다(사건과 연결돼 related만 붙는다).
    expect(appliedStates()['NASDAQ:NVDA'] ?? []).not.toContain('hovered');
    expect(screen.getByRole('tooltip').textContent).toBe(issue.label);
  });

  it('D-GRP-01 끌기 전에 올려 둔 hover는 지도 밖에서 손을 떼면 풀리고, 바뀐 것이 없으면 다시 그리지 않는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const surface = screen.getByRole('img', { name: /관계 지도:/ });
    const issue = data.nodes.find((node) => node.kind === 'issue')!;
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({ target: { id: issue.id } }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ [issue.id]: ['hovered'] }),
    );
    expect(screen.getByRole('tooltip').textContent).toBe(issue.label);

    // 같은 노드 위에서 끌기만 하고 떼면 hover는 그대로이고 상태를 다시 보내지 않는다.
    const sent = canvas.setElementState.mock.calls.length;
    fireEvent.pointerDown(surface, { button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(surface, { clientX: 140, clientY: 125 });
    await act(async () =>
      fireEvent.pointerUp(window, { clientX: 140, clientY: 125 }),
    );
    expect(canvas.setElementState).toHaveBeenCalledTimes(sent);
    expect(screen.getByRole('tooltip').textContent).toBe(issue.label);

    // 끌다가 지도 밖으로 나가 손을 떼면 그때 hover를 푼다.
    fireEvent.pointerDown(surface, { button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(surface, { clientX: 140, clientY: 125 });
    await act(async () => fireEvent.pointerLeave(surface));
    expect(screen.getByRole('tooltip').textContent).toBe(issue.label);
    expect(canvas.setElementState).toHaveBeenCalledTimes(sent);
    await act(async () =>
      fireEvent.pointerUp(window, { clientX: 900, clientY: 900 }),
    );
    await waitFor(() => expect(appliedStates()[issue.id]).toEqual([]));
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('D-GRP-01 다른 버튼·손가락을 떼는 것은 끌기를 끝내지 않고, pointercancel은 끝낸다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const surface = screen.getByRole('img', { name: /관계 지도:/ });

    fireEvent.pointerDown(surface, {
      button: 0,
      pointerId: 1,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(surface, {
      pointerId: 1,
      clientX: 140,
      clientY: 125,
    });
    await act(async () => {
      fireEvent.pointerUp(window, { button: 2, pointerId: 1 });
      fireEvent.pointerUp(window, { button: 0, pointerId: 2 });
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      });
    });
    expect(canvas.setElementState).not.toHaveBeenCalled();

    await act(async () => fireEvent.pointerCancel(window, { pointerId: 1 }));
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ 'NASDAQ:NVDA': ['hovered'] }),
    );
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'KRX:005380' },
      }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ 'KRX:005380': ['hovered'] }),
    );
  });

  it('D-GRP-01 브라우저 밖에서 버튼을 놓아 pointerup을 놓쳐도, 버튼 없이 돌아온 움직임에서 끌기를 끝내고 hover를 되살린다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const surface = screen.getByRole('img', { name: /관계 지도:/ });

    fireEvent.pointerDown(surface, {
      button: 0,
      pointerId: 1,
      pointerType: 'mouse',
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(surface, {
      pointerId: 1,
      pointerType: 'mouse',
      buttons: 1,
      clientX: 140,
      clientY: 125,
    });
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    expect(canvas.setElementState).not.toHaveBeenCalled();

    // pointerup 없이 버튼이 떼어진 채 지도 안으로 돌아온다.
    await act(async () =>
      fireEvent.pointerMove(surface, {
        pointerId: 1,
        pointerType: 'mouse',
        buttons: 0,
        clientX: 150,
        clientY: 130,
      }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ 'NASDAQ:NVDA': ['hovered'] }),
    );
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'KRX:005380' },
      }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ 'KRX:005380': ['hovered'] }),
    );
  });

  it('D-GRP-01 마우스로 끌던 중 화면을 터치해도(다른 종류의 주 포인터) 마우스 끌기를 유지한다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    render(<GraphCanvas data={data} onSelect={onSelect} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const surface = screen.getByRole('img', { name: /관계 지도:/ });

    fireEvent.pointerDown(surface, {
      button: 0,
      pointerId: 1,
      pointerType: 'mouse',
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(surface, {
      pointerId: 1,
      pointerType: 'mouse',
      buttons: 1,
      clientX: 140,
      clientY: 125,
    });
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    // 첫 터치는 터치 종류의 주 포인터(isPrimary)지만 마우스 끌기를 끝내지 않는다.
    await act(async () => {
      fireEvent.pointerDown(surface, {
        button: 0,
        pointerId: 2,
        pointerType: 'touch',
        isPrimary: true,
        clientX: 300,
        clientY: 300,
      });
      fireEvent.pointerMove(surface, {
        pointerId: 2,
        pointerType: 'touch',
        buttons: 1,
        clientX: 310,
        clientY: 305,
      });
      fireEvent.pointerUp(window, { button: 0, pointerId: 2 });
    });
    expect(canvas.setElementState).not.toHaveBeenCalled();

    // 마우스는 계속 추적된다: 버튼을 든 채 움직이면 그대로 끌기이고, 떼면 그때 반영한다.
    fireEvent.pointerMove(surface, {
      pointerId: 1,
      pointerType: 'mouse',
      buttons: 1,
      clientX: 160,
      clientY: 140,
    });
    expect(canvas.setElementState).not.toHaveBeenCalled();
    await act(async () =>
      fireEvent.pointerUp(window, { button: 0, pointerId: 1 }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ 'NASDAQ:NVDA': ['hovered'] }),
    );
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: 'NASDAQ:NVDA' } }),
    );
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('D-GRP-01 끌던 중 두 번째 손가락이 닿아도 첫 손가락의 끌기를 유지하고, 첫 손가락을 뗄 때 반영한다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    render(<GraphCanvas data={data} onSelect={onSelect} />);
    await waitFor(() =>
      expect(canvas.handlers.has('node:pointerenter')).toBe(true),
    );
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const surface = screen.getByRole('img', { name: /관계 지도:/ });

    fireEvent.pointerDown(surface, {
      button: 0,
      pointerId: 1,
      pointerType: 'touch',
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent.pointerMove(surface, {
      pointerId: 1,
      pointerType: 'touch',
      buttons: 1,
      clientX: 140,
      clientY: 125,
    });
    await act(async () =>
      canvas.handlers.get('node:pointerenter')!({
        target: { id: 'NASDAQ:NVDA' },
      }),
    );
    // 두 번째 손가락: 누름·움직임·뗌 모두 첫 손가락의 끌기를 건드리지 않는다.
    await act(async () => {
      fireEvent.pointerDown(surface, {
        button: 0,
        pointerId: 2,
        pointerType: 'touch',
        isPrimary: false,
        clientX: 300,
        clientY: 300,
      });
      fireEvent.pointerMove(surface, {
        pointerId: 2,
        pointerType: 'touch',
        buttons: 1,
        clientX: 302,
        clientY: 301,
      });
      fireEvent.pointerUp(window, { button: 0, pointerId: 2 });
    });
    expect(canvas.setElementState).not.toHaveBeenCalled();

    await act(async () =>
      fireEvent.pointerUp(window, { button: 0, pointerId: 1 }),
    );
    await waitFor(() =>
      expect(appliedStates()).toMatchObject({ 'NASDAQ:NVDA': ['hovered'] }),
    );
    // 첫 손가락은 끌기였으므로 뗄 때의 클릭으로 노드를 고르지 않는다.
    act(() =>
      canvas.handlers.get('node:click')!({ target: { id: 'NASDAQ:NVDA' } }),
    );
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('D-GRP-03 선택 상태가 G6 기본 12px로 이름표를 줄이지 않는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.created).toHaveBeenCalled());
    const { state } = (
      canvas.created.mock.lastCall?.[0] as {
        node: {
          state: Record<string, Record<string, (datum: unknown) => unknown>>;
        };
      }
    ).node;
    const datum = {
      id: 'n',
      style: { labelFontSize: 26, labelFontWeight: 800 },
    };
    expect(state.selected.labelFontSize(datum)).toBe(26);
    expect(state.selected.labelFontWeight(datum)).toBe(800);
  });
});

describe('D-GRP-01 지도 배율 표시', () => {
  it('확대·축소와 맞춤 버튼 사이에 지금 배율을 퍼센트로 보이고, 배율이 바뀌면 따라 바뀐다', async () => {
    render(
      <GraphCanvas
        data={createMockGraph({ mode: 'all', personalFilter: 'all' })}
      />,
    );
    await waitFor(() =>
      expect(canvas.handlers.has('aftertransform')).toBe(true),
    );
    canvas.getZoom.mockReturnValue(0.534);
    act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
    const zoom = await screen.findByRole('status', { name: '현재 배율 53%' });
    expect(zoom.textContent).toBe('53%');
    const controls = within(screen.getByLabelText('지도 확대 조절'));
    const order = [
      controls.getByRole('button', { name: '축소' }),
      zoom,
      controls.getByRole('button', { name: '전체 그래프 맞춤' }),
    ];
    expect(
      order[0].compareDocumentPosition(order[1]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      order[1].compareDocumentPosition(order[2]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    canvas.getZoom.mockReturnValue(1.2);
    act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
    expect(
      screen.getByRole('status', { name: '현재 배율 120%' }).textContent,
    ).toBe('120%');
  });
});

describe('D-GRP-01 지도 카메라 움직임', () => {
  function stubMotion(reduce: boolean) {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion') ? reduce : false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
  }

  it('G6는 카메라만 움직이고 노드·연결선·휠 확대·끌기는 바로 반응하게 둔다', async () => {
    render(
      <GraphCanvas
        data={createMockGraph({ mode: 'all', personalFilter: 'all' })}
      />,
    );
    await waitFor(() => expect(canvas.created).toHaveBeenCalledTimes(1));
    const options = canvas.created.mock.lastCall![0] as {
      animation: unknown;
      node: { animation: unknown };
      edge: { animation: unknown };
      behaviors: (string | { type: string; animation?: unknown })[];
    };
    // G6 5는 그래프 animation이 false면 화면 이동 애니메이션도 모두 끈다.
    expect(options.animation).toBe(true);
    // 노드·연결선은 배치를 바꿀 때 부르는 이동(translate)만 움직인다.
    expect(options.node.animation).toEqual(NODE_ANIMATION);
    expect(options.edge.animation).toEqual(EDGE_ANIMATION);
    for (const stage of ['enter', 'exit', 'show', 'hide', 'update'] as const) {
      expect(NODE_ANIMATION[stage]).toBe(false);
      expect(EDGE_ANIMATION[stage]).toBe(false);
    }
    for (const behavior of options.behaviors) {
      expect(typeof behavior).toBe('object');
      expect((behavior as { animation?: unknown }).animation).toBe(false);
    }
  });

  it('확대·축소 버튼은 250ms로 움직이고, 동작 줄이기면 바로 옮긴다', async () => {
    stubMotion(false);
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const view = render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.created).toHaveBeenCalledTimes(1));
    canvas.zoomTo.mockClear();
    await userEvent.click(screen.getByRole('button', { name: /^확대$/ }));
    expect(canvas.zoomTo).toHaveBeenLastCalledWith(1.2, {
      duration: 250,
      easing: 'cubic-bezier(0.35, 0, 0.35, 1)',
    });

    stubMotion(true);
    canvas.zoomTo.mockClear();
    await userEvent.click(screen.getByRole('button', { name: /^축소$/ }));
    expect(canvas.zoomTo).toHaveBeenLastCalledWith(1 / 1.2, false);
    view.unmount();
    vi.unstubAllGlobals();
  });
  it('포커스에 들어가면 이웃을 가운데 기업의 이전 자리에 그린 뒤 링으로 펴고, 동작 줄이기면 바로 놓는다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const focusId = data.nodes.find((node) => node.kind === 'company')!.id;
    const lastNodes = () =>
      new Map(
        (
          canvas.setData.mock.lastCall![0] as {
            nodes: { id: string; style: { x: number; y: number } }[];
          }
        ).nodes.map((node) => [node.id, [node.style.x, node.style.y]]),
      );

    stubMotion(false);
    const view = render(<GraphCanvas data={data} focusLayout />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const before = lastNodes();
    canvas.setData.mockClear();
    view.rerender(<GraphCanvas data={data} focusId={focusId} focusLayout />);
    await waitFor(() => expect(canvas.translateElementTo).toHaveBeenCalled());
    const [targets, animated] = canvas.translateElementTo.mock.lastCall! as [
      Record<string, [number, number]>,
      boolean,
    ];
    expect(animated).toBe(true);
    expect(Object.keys(targets).length).toBeGreaterThan(1);
    const drawn = lastNodes();
    // 가운데 기업은 제자리에서, 이웃은 모두 가운데 기업의 이전 자리에서 출발한다.
    expect(drawn.get(focusId)).toEqual(before.get(focusId));
    for (const id of Object.keys(targets)) {
      expect(drawn.get(id)).toEqual(before.get(focusId));
      expect(targets[id]).not.toEqual(before.get(focusId));
    }

    // 같은 포커스에서 단계만 바꾸면 이미 보이던 이웃은 지금 자리에서 옮기고, 새 이웃만 가운데에서 펴진다.
    // 1단계가 끝난 자리: 그린 자리에서 옮겨 간 목표 자리로 바뀐다.
    const oneHop = new Map([...lastNodes(), ...Object.entries(targets)]);
    const firstRing = Object.keys(targets).filter((id) => id !== focusId);
    canvas.translateElementTo.mockClear();
    canvas.setData.mockClear();
    view.rerender(
      <GraphCanvas data={data} focusId={focusId} focusHops={2} focusLayout />,
    );
    await waitFor(() => expect(canvas.translateElementTo).toHaveBeenCalled());
    const [twoHopTargets] = canvas.translateElementTo.mock.lastCall! as [
      Record<string, [number, number]>,
      boolean,
    ];
    const twoHop = lastNodes();
    const center = oneHop.get(focusId);
    for (const id of Object.keys(twoHopTargets)) {
      if (id === focusId) continue;
      expect(twoHop.get(id)).toEqual(
        firstRing.includes(id) ? oneHop.get(id) : center,
      );
    }
    expect(
      Object.keys(twoHopTargets).some((id) => !firstRing.includes(id)),
    ).toBe(true);
    view.unmount();

    stubMotion(true);
    canvas.translateElementTo.mockClear();
    const reduced = render(<GraphCanvas data={data} focusLayout />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    const layouts = canvas.setData.mock.calls.length;
    reduced.rerender(<GraphCanvas data={data} focusId={focusId} focusLayout />);
    await waitFor(() =>
      expect(canvas.setData.mock.calls.length).toBeGreaterThan(layouts),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(canvas.translateElementTo).not.toHaveBeenCalled();
    reduced.unmount();
    vi.unstubAllGlobals();
  });
  it('흐름 순으로 정렬을 켜고 끌 때도 노드를 이전 자리에서 새 자리로 옮긴다', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    stubMotion(false);
    const view = render(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.setData).toHaveBeenCalled());
    canvas.translateElementTo.mockClear();
    view.rerender(<GraphCanvas data={data} flow />);
    await waitFor(() => expect(canvas.translateElementTo).toHaveBeenCalled());
    expect(canvas.translateElementTo.mock.lastCall![1]).toBe(true);
    canvas.translateElementTo.mockClear();
    view.rerender(<GraphCanvas data={data} />);
    await waitFor(() => expect(canvas.translateElementTo).toHaveBeenCalled());
    view.unmount();
    vi.unstubAllGlobals();
  });
});

describe('D-GRP-01 지도 이동 범위', () => {
  /** jsdom has no layout; give the map host a real size for the bounds math. */
  const sized = () => {
    const width = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientWidth',
    );
    const height = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientHeight',
    );
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get: () => 1200,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get: () => 700,
    });
    return () => {
      if (width)
        Object.defineProperty(HTMLElement.prototype, 'clientWidth', width);
      if (height)
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', height);
    };
  };
  const remember = (zoom: number) =>
    saveModeEntry('public', 'all', {
      url: '/?mode=all',
      view: {
        ...emptyView(),
        camera: {
          zoom,
          position: [0, 0],
          size: [1200, 700],
          layout: MAP_LAYOUT_REVISION,
        },
      },
    });

  it('기억한 카메라에 노드가 하나도 보이지 않으면 전체 맞춤으로 연다', async () => {
    const restore = sized();
    try {
      remember(0.13);
      // Every circle lands far outside the 1200x700 map.
      canvas.getViewportByCanvas.mockImplementation((point) => [
        point[0] + 50000,
        point[1] + 50000,
      ]);
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      render(<GraphCanvas data={data} />);
      await waitFor(() =>
        expect(canvas.handlers.has('aftertransform')).toBe(true),
      );
      await waitFor(() =>
        expect(canvas.zoomTo).toHaveBeenCalledWith(0.13, false),
      );
      // After the empty camera, the whole fit applies its own zoom too.
      await waitFor(() =>
        expect(canvas.zoomTo.mock.calls.some(([zoom]) => zoom !== 0.13)).toBe(
          true,
        ),
      );
    } finally {
      restore();
    }
  });

  it('기억한 카메라에 노드가 보이면 그 카메라를 그대로 쓴다', async () => {
    const restore = sized();
    try {
      remember(0.5);
      canvas.getViewportByCanvas.mockImplementation((point) => [
        point[0] * 0.001 + 600,
        point[1] * 0.001 + 350,
      ]);
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      render(<GraphCanvas data={data} />);
      await waitFor(() =>
        expect(canvas.zoomTo).toHaveBeenCalledWith(0.5, false),
      );
      await act(async () => {});
      // Only the remembered zoom is applied: no fallback fit.
      expect(canvas.zoomTo.mock.calls.every(([zoom]) => zoom === 0.5)).toBe(
        true,
      );
    } finally {
      restore();
    }
  });

  it('휴대폰 상세 시트에 가려진 부분은 이동 범위에서 뺀다', async () => {
    const restore = sized();
    // M-GRP-01 sheet covering the lower half of the 1200x700 map.
    const sheet = document.createElement('div');
    sheet.dataset.screenId = 'M-GRP-01';
    const rect = DOMRect.fromRect({ x: 0, y: 350, width: 1200, height: 350 });
    sheet.getBoundingClientRect = () => rect;
    sheet.getClientRects = () =>
      [rect] as unknown as ReturnType<HTMLElement['getClientRects']>;
    document.body.append(sheet);
    try {
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      render(<GraphCanvas data={data} />);
      await waitFor(() =>
        expect(canvas.handlers.has('aftertransform')).toBe(true),
      );
      await act(async () => {});
      canvas.translateBy.mockClear();
      // The graph sits at y=510: inside the band of the whole map (175-525),
      // but behind the sheet. The free area above it is 0-350 (band 87.5-262.5).
      canvas.getViewportByCanvas.mockImplementation(() => [600, 510]);
      act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
      // Without the sheet this would not move at all. freeViewport keeps a small gap.
      expect(canvas.translateBy).toHaveBeenCalledTimes(1);
      const [[dx, dy]] = canvas.translateBy.mock.calls[0] as [[number, number]];
      expect(dx).toBe(0);
      expect(dy).toBeLessThan(-240);
      expect(dy).toBeGreaterThan(-260);
    } finally {
      sheet.remove();
      restore();
    }
  });

  it('지도를 빈 캔버스로 끌어내면 그래프가 화면 가운데 띠에 닿도록 되돌린다', async () => {
    const restore = sized();
    try {
      const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
      render(<GraphCanvas data={data} />);
      await waitFor(() =>
        expect(canvas.handlers.has('aftertransform')).toBe(true),
      );
      await act(async () => {});
      canvas.translateBy.mockClear();
      // The whole graph now sits 50000px right of and below the map.
      canvas.getViewportByCanvas.mockImplementation((point) => [
        point[0] + 50000,
        point[1] + 50000,
      ]);
      act(() => canvas.handlers.get('aftertransform')!({ target: { id: '' } }));
      expect(canvas.translateBy).toHaveBeenCalledTimes(1);
      const [[dx, dy]] = canvas.translateBy.mock.calls[0] as [[number, number]];
      expect(dx).toBeLessThan(-40000);
      expect(dy).toBeLessThan(-40000);
    } finally {
      restore();
    }
  });
});
