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
import GraphCanvas from '@/components/graph/GraphCanvas';
import { GraphAppearanceContext } from '@/components/graph/graph-appearance';
import { createMockGraph } from '@/mocks/graph/response';
import type { GraphData } from '@antv/g6';
import {
  MemoryRouter,
  createMemoryRouter,
  RouterProvider,
} from 'react-router-dom';
import MapPage from '@/pages/map/MapPage';
import * as graphApi from '@/apis/graph/graph';
import { useAuthStore } from '@/stores/useAuthStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';

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
    constructor(options: unknown) {
      canvas.created(options);
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

  it('D-GRP-01 Shift+Enter on a folded event expands it first and fits its neighborhood after that draw', async () => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const onSelect = vi.fn();
    const view = render(<GraphCanvas data={data} onSelect={onSelect} />);
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
    expect(drawnIds()).not.toContain('mock-issue-20');
    canvas.zoomTo.mockClear();
    fireEvent.keyDown(
      screen.getByRole('button', { name: '사건: 삼성전자 개별 공시 (예시)' }),
      { key: 'Enter', shiftKey: true },
    );
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('mock-issue-20'));
    expect(canvas.zoomTo).not.toHaveBeenCalled();
    view.rerender(
      <GraphCanvas
        data={data}
        onSelect={onSelect}
        selectedId="mock-issue-20"
      />,
    );
    await waitFor(() => expect(drawnIds()).toContain('mock-issue-20'));
    await waitFor(() => expect(canvas.zoomTo).toHaveBeenCalled());
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
        expect(direct?.style?.lineWidth).toBe(1.5);
        expect(direct?.style?.stroke).toBe(
          theme === 'dark' ? '#a3a3a3' : '#777773',
        );
        const label = rendered.nodes?.find(
          (node) => node.id === 'NASDAQ:NVDA',
        )?.style;
        expect(Number(label?.labelFontSize)).toBeGreaterThan(17.2);
        const aiFeature = screen.getByRole('button', { name: 'AI 기능' });
        expect(aiFeature.querySelector('img')?.getAttribute('src')).toBe(
          '/graph-assets/ai.svg',
        );
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
          [data.nodes[0].id]: ['inactive'],
        }),
      ),
    );
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
    // 저장한 화면 위치(40, 60)와 지금 위치(5, 10)의 차이만큼 옮긴다.
    expect(canvas.translateBy).toHaveBeenCalledWith([35, 50], false);
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
        camera: { zoom: 1.8, position: [40, 60], size: [0, 0] },
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
    ).toEqual({ zoom: 1.8, position: [40, 60], size: [0, 0] });
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
