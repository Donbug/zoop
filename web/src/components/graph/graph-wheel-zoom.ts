import type { Graph } from '@antv/g6';
import { MAX_GRAPH_ZOOM, MIN_GRAPH_ZOOM } from './graph-zoom-range';

/**
 * D-GRP-01 휠 확대. G6 zoom-canvas는 휠 한 칸(deltaY 100)마다 배율을 1.5배·0.5배로 한 번에 바꾸고,
 * 휠 입력에는 animation 설정을 쓰지 않아서 확대가 뚝뚝 끊겨 보였다.
 * 여기서는 휠 입력을 목표 배율에 쌓고, 프레임마다 현재 배율을 목표 쪽으로 일정 비율씩 옮긴다.
 * 연달아 굴리면 목표만 바뀌므로 움직임이 끊기지 않고 이어진다.
 */

type Point = [number, number];
type WheelInput = Pick<WheelEvent, 'deltaY' | 'deltaMode' | 'ctrlKey'>;

/** 휠 한 칸(deltaY 100)에 약 1.22배. */
const WHEEL_RATE = 0.002;
/** 트랙패드 핀치는 브라우저가 ctrl+휠로 작은 delta를 보내므로 더 크게 반영한다. */
const PINCH_RATE = 0.01;
/** 이벤트 하나가 바꾸는 양의 상한. 빠르게 굴려도 한 번에 튀지 않는다. */
const MAX_DELTA = 300;
/** 남은 차이의 63%를 따라잡는 시간(ms). 휠 한 칸이 약 200ms 안에 끝난다. */
const TIME_CONSTANT = 60;
/** 로그 배율 차이가 이보다 작으면 목표에 닿은 것으로 본다. */
const SETTLE = 0.002;
const LINE_HEIGHT = 16;

/** 휠 이벤트 하나가 바꾸는 로그 배율. 양수면 확대한다. */
export function wheelZoomStep(event: WheelInput, pageHeight: number): number {
  const scale =
    event.deltaMode === 1
      ? LINE_HEIGHT
      : event.deltaMode === 2
        ? pageHeight
        : 1;
  const delta = Math.max(-MAX_DELTA, Math.min(MAX_DELTA, event.deltaY * scale));
  return -delta * (event.ctrlKey ? PINCH_RATE : WHEEL_RATE);
}

/** 프레임 사이 dt(ms) 동안 현재 로그 배율이 목표 쪽으로 옮겨 갈 비율. 프레임 속도와 관계없이 같은 시간에 닿는다. */
export function wheelZoomFollow(dt: number): number {
  return 1 - Math.exp(-dt / TIME_CONSTANT);
}

export interface WheelZoomOptions {
  graph: () => Graph | null;
  /**
   * 휠 확대가 멈췄을 때(목표에 닿았거나 다른 카메라 이동이 끼어들었을 때) 한 번 부른다.
   * 움직이는 동안 미룬 배율 표시·이름표 다시 읽기·카메라 저장을 여기서 한다.
   */
  onSettle: () => void;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (id: number) => void;
  reducedMotion?: () => boolean;
}

export interface WheelZoom {
  wheel(event: WheelInput, origin: Point, pageHeight: number): void;
  /** 휠 확대가 아닌 카메라 이동이 시작되면 부른다. 그 이동과 다투지 않도록 여기서 멈춘다. */
  interrupt(): void;
  /** 정리할 때 부른다. onSettle은 부르지 않는다. */
  cancel(): void;
  /** 휠 확대가 움직이는 중인지. */
  running(): boolean;
  /** 지금 일어나는 transform이 휠 확대 자신의 것인지. */
  owns(): boolean;
}

function prefersReducedMotion() {
  return (
    typeof window.matchMedia !== 'function' ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

export function createWheelZoom({
  graph: getGraph,
  onSettle,
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (id) => cancelAnimationFrame(id),
  reducedMotion = prefersReducedMotion,
}: WheelZoomOptions): WheelZoom {
  let target = 0;
  let origin: Point = [0, 0];
  let frame: number | null = null;
  let lastTime: number | null = null;
  let active = false;
  let owning = false;

  const range = (graph: Graph): [number, number] => {
    const [min, max] = graph.getZoomRange() ?? [MIN_GRAPH_ZOOM, MAX_GRAPH_ZOOM];
    return [Math.log(min), Math.log(max)];
  };
  const zoomTo = (graph: Graph, zoom: number) => {
    owning = true;
    try {
      // 기준점이 있고 애니메이션이 없는 확대는 G6가 같은 호출 안에서 바로 적용한다(viewport.transform).
      void graph.zoomTo(zoom, false, origin);
    } finally {
      owning = false;
    }
  };
  const stop = () => {
    if (frame !== null) cancelFrame(frame);
    frame = null;
    lastTime = null;
    active = false;
  };
  const step = (time: number) => {
    frame = null;
    const graph = getGraph();
    if (!graph || graph.destroyed) {
      stop();
      return;
    }
    const dt = lastTime === null ? 16 : Math.min(64, time - lastTime);
    lastTime = time;
    const current = Math.log(graph.getZoom());
    const diff = target - current;
    const done = Math.abs(diff) < SETTLE;
    zoomTo(
      graph,
      Math.exp(done ? target : current + diff * wheelZoomFollow(dt)),
    );
    if (done) {
      stop();
      onSettle();
      return;
    }
    frame = requestFrame(step);
  };

  return {
    wheel(event, point, pageHeight) {
      const graph = getGraph();
      if (!graph || graph.destroyed) return;
      const change = wheelZoomStep(event, pageHeight);
      if (change === 0) return;
      const [min, max] = range(graph);
      if (!active) target = Math.log(graph.getZoom());
      target = Math.max(min, Math.min(max, target + change));
      origin = point;
      if (reducedMotion()) {
        // 동작 줄이기에서는 예전처럼 바로 옮긴다. 이름표 읽기는 aftertransform이 평소대로 맡는다.
        zoomTo(graph, Math.exp(target));
        return;
      }
      active = true;
      if (frame === null) frame = requestFrame(step);
    },
    interrupt() {
      if (!active || owning) return;
      stop();
      onSettle();
    },
    cancel: stop,
    running: () => active,
    owns: () => owning,
  };
}
