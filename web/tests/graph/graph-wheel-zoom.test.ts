import type { Graph } from '@antv/g6';
import { describe, expect, it, vi } from 'vitest';
import {
  createWheelZoom,
  wheelZoomFollow,
  wheelZoomStep,
} from '@/components/graph/graph-wheel-zoom';

function fakeGraph(start = 1, range: [number, number] = [0.01, 2.5]) {
  let zoom = start;
  const calls: { zoom: number; origin: unknown }[] = [];
  const graph = {
    destroyed: false,
    getZoom: () => zoom,
    getZoomRange: () => range,
    zoomTo: (next: number, _animation: unknown, origin: unknown) => {
      zoom = Math.max(range[0], Math.min(range[1], next));
      calls.push({ zoom, origin });
      return Promise.resolve();
    },
  };
  return { graph: graph as unknown as Graph, calls, zoom: () => zoom };
}

function frames() {
  const queue = new Map<number, FrameRequestCallback>();
  let id = 0;
  let time = 0;
  return {
    requestFrame: (callback: FrameRequestCallback) => {
      queue.set(++id, callback);
      return id;
    },
    cancelFrame: (frame: number) => queue.delete(frame),
    pending: () => queue.size,
    /** 한 프레임(16ms)을 돌린다. */
    tick() {
      time += 16;
      const callbacks = [...queue.values()];
      queue.clear();
      callbacks.forEach((callback) => callback(time));
    },
    runAll(limit = 200) {
      for (let i = 0; i < limit && queue.size > 0; i++) this.tick();
    },
  };
}

const notch = (deltaY: number) => ({ deltaY, deltaMode: 0, ctrlKey: false });

describe('D-GRP-01 wheelZoomStep', () => {
  it('마우스 휠 한 칸은 약 1.22배로 확대·축소하고, 위아래가 대칭이다', () => {
    expect(Math.exp(wheelZoomStep(notch(-100), 800))).toBeCloseTo(1.2214, 3);
    expect(Math.exp(wheelZoomStep(notch(100), 800))).toBeCloseTo(1 / 1.2214, 3);
  });

  it('줄·페이지 단위 delta를 픽셀로 바꾸고, 한 이벤트의 양을 제한한다', () => {
    expect(
      wheelZoomStep({ deltaY: 3, deltaMode: 1, ctrlKey: false }, 800),
    ).toBe(wheelZoomStep(notch(48), 800));
    expect(
      wheelZoomStep({ deltaY: 1, deltaMode: 2, ctrlKey: false }, 800),
    ).toBe(wheelZoomStep(notch(300), 800));
    expect(wheelZoomStep(notch(5000), 800)).toBe(
      wheelZoomStep(notch(300), 800),
    );
  });

  it('트랙패드 핀치(ctrl+휠)는 작은 delta를 더 크게 반영한다', () => {
    expect(
      wheelZoomStep({ deltaY: -10, deltaMode: 0, ctrlKey: true }, 800),
    ).toBe(0.1);
  });

  it('프레임 속도와 관계없이 같은 시간 동안 같은 만큼 따라간다', () => {
    const once = wheelZoomFollow(32);
    const twice = 1 - (1 - wheelZoomFollow(16)) ** 2;
    expect(once).toBeCloseTo(twice, 10);
  });
});

describe('D-GRP-01 createWheelZoom', () => {
  it('휠 한 칸을 여러 프레임에 나눠 목표 배율로 옮기고, 끝날 때 한 번만 알린다', () => {
    const { graph, calls, zoom } = fakeGraph();
    const clock = frames();
    const onSettle = vi.fn();
    const wheel = createWheelZoom({
      graph: () => graph,
      onSettle,
      reducedMotion: () => false,
      ...clock,
    });
    wheel.wheel(notch(-100), [120, 80], 800);
    expect(wheel.running()).toBe(true);
    expect(calls).toHaveLength(0);
    clock.tick();
    expect(zoom()).toBeGreaterThan(1);
    expect(zoom()).toBeLessThan(1.2214);
    clock.runAll();
    expect(zoom()).toBeCloseTo(1.2214, 3);
    expect(calls.length).toBeGreaterThan(3);
    expect(calls.every((call) => (call.origin as number[])[0] === 120)).toBe(
      true,
    );
    // 약 200ms(13프레임) 안에 끝난다.
    expect(calls.length).toBeLessThanOrEqual(20);
    expect(onSettle).toHaveBeenCalledTimes(1);
    expect(wheel.running()).toBe(false);
  });

  it('움직이는 중 다시 굴리면 목표에 쌓아 끊기지 않고 이어 간다', () => {
    const { graph, zoom } = fakeGraph();
    const clock = frames();
    const onSettle = vi.fn();
    const wheel = createWheelZoom({
      graph: () => graph,
      onSettle,
      reducedMotion: () => false,
      ...clock,
    });
    wheel.wheel(notch(-100), [0, 0], 800);
    clock.tick();
    clock.tick();
    wheel.wheel(notch(-100), [0, 0], 800);
    expect(clock.pending()).toBe(1);
    clock.runAll();
    expect(zoom()).toBeCloseTo(1.2214 ** 2, 3);
    expect(onSettle).toHaveBeenCalledTimes(1);
  });

  it('배율 범위 밖으로는 목표를 쌓지 않는다', () => {
    const { graph, zoom } = fakeGraph(2.4);
    const clock = frames();
    const wheel = createWheelZoom({
      graph: () => graph,
      onSettle: () => {},
      reducedMotion: () => false,
      ...clock,
    });
    for (let i = 0; i < 10; i++) wheel.wheel(notch(-100), [0, 0], 800);
    clock.runAll();
    expect(zoom()).toBe(2.5);
    wheel.wheel(notch(100), [0, 0], 800);
    clock.tick();
    expect(zoom()).toBeLessThan(2.5);
  });

  it('다른 카메라 이동이 끼어들면 멈추고 한 번만 알린다', () => {
    const { graph } = fakeGraph();
    const clock = frames();
    const onSettle = vi.fn();
    const wheel = createWheelZoom({
      graph: () => graph,
      onSettle,
      reducedMotion: () => false,
      ...clock,
    });
    wheel.wheel(notch(-100), [0, 0], 800);
    clock.tick();
    wheel.interrupt();
    expect(wheel.running()).toBe(false);
    expect(clock.pending()).toBe(0);
    expect(onSettle).toHaveBeenCalledTimes(1);
    wheel.interrupt();
    expect(onSettle).toHaveBeenCalledTimes(1);
  });

  it('동작 줄이기에서는 프레임 없이 바로 옮긴다', () => {
    const { graph, zoom } = fakeGraph();
    const clock = frames();
    const onSettle = vi.fn();
    const wheel = createWheelZoom({
      graph: () => graph,
      onSettle,
      reducedMotion: () => true,
      ...clock,
    });
    wheel.wheel(notch(-100), [0, 0], 800);
    expect(zoom()).toBeCloseTo(1.2214, 3);
    expect(clock.pending()).toBe(0);
    expect(wheel.running()).toBe(false);
    expect(onSettle).not.toHaveBeenCalled();
  });

  it('정리하면 남은 프레임을 취소하고 알리지 않는다', () => {
    const { graph } = fakeGraph();
    const clock = frames();
    const onSettle = vi.fn();
    const wheel = createWheelZoom({
      graph: () => graph,
      onSettle,
      reducedMotion: () => false,
      ...clock,
    });
    wheel.wheel(notch(-100), [0, 0], 800);
    wheel.cancel();
    expect(clock.pending()).toBe(0);
    expect(onSettle).not.toHaveBeenCalled();
  });
});
