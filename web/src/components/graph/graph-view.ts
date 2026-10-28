import type { GraphResponse } from '@/types/map/graph';
import type { MapMode } from '@/types/map';

export type LegendKey =
  'company' | 'issue' | GraphResponse['edges'][number]['relationType'];
/**
 * 지도 기본 배치(graph-model의 좌표계) 버전. 노드 좌표 계산 방식이 바뀌면 올린다.
 * 3: 관계 묶음 사이 여백 압축(#321 후속).
 * 4: 확대된 노드·라벨의 점유 면적 반영(#330).
 * 5: 기본 간격 50% 확대·저연결 노드 여유 확대. 이전 좌표의 카메라는 복원하지 않는다.
 * 6: 연결 없는 묶음 사이 여백을 최종 확대 후 180으로 줄인다.
 */
export const MAP_LAYOUT_REVISION = 6;
export type GraphView = {
  hidden: LegendKey[];
  /**
   * size: 저장할 때의 지도 크기. 크기가 달라지면 위치를 복원하지 않고 기본 배치로 연다.
   * layout: 저장할 때의 배치 버전(MAP_LAYOUT_REVISION). 다르면 위치를 복원하지 않는다.
   */
  camera?: {
    zoom: number;
    position: [number, number];
    size: [number, number];
    layout: number;
  };
};
export type ModeEntry = { url: string; view: GraphView };
export const emptyView = (): GraphView => ({ hidden: [] });
const keys: LegendKey[] = [
  'company',
  'issue',
  'INVOLVES',
  'STRUCTURALLY_RELATED_TO',
  'FOLLOWS',
  'SHARES_ISSUE',
];
export function readModeEntry(owner: string, mode: MapMode): ModeEntry | null {
  try {
    const entry = JSON.parse(
      sessionStorage.getItem(`zoop.graph.view:${owner}:${mode}`) ?? 'null',
    );
    if (
      !entry ||
      typeof entry.url !== 'string' ||
      !entry.url.startsWith('/?') ||
      !entry.view ||
      !Array.isArray(entry.view.hidden)
    )
      return null;
    const camera = entry.view.camera;
    return {
      url: entry.url,
      view: {
        hidden: entry.view.hidden.filter((key: LegendKey) =>
          keys.includes(key),
        ),
        ...(camera &&
        Number.isFinite(camera.zoom) &&
        camera.zoom >= 0.01 &&
        camera.zoom <= 4 &&
        Array.isArray(camera.position) &&
        camera.position.length === 2 &&
        camera.position.every(Number.isFinite) &&
        Array.isArray(camera.size) &&
        camera.size.length === 2 &&
        camera.size.every(Number.isFinite) &&
        camera.layout === MAP_LAYOUT_REVISION
          ? { camera }
          : {}),
      },
    };
  } catch {
    return null;
  }
}
/** 저장한 화면 위치를 지금 지도 크기에 그대로 쓸 수 있는지(1px 오차 허용) */
export function sameViewport(
  saved: [number, number],
  width: number,
  height: number,
) {
  return Math.abs(saved[0] - width) <= 1 && Math.abs(saved[1] - height) <= 1;
}
export function saveModeEntry(owner: string, mode: MapMode, entry: ModeEntry) {
  try {
    sessionStorage.setItem(
      `zoop.graph.view:${owner}:${mode}`,
      JSON.stringify(entry),
    );
  } catch {
    /* Private storage can be disabled. */
  }
}
export function isolatedIssues(graph: GraphResponse) {
  const connected = new Set(
    graph.edges.flatMap((edge) => [edge.source, edge.target]),
  );
  return graph.nodes.filter(
    (node) => node.kind === 'issue' && !connected.has(node.id),
  );
}
export function restoreTargets(entry: ModeEntry | null, graph: GraphResponse) {
  const result: Record<string, string | null> = {
    select: null,
    focus: null,
    hops: null,
    path: null,
    impact: null,
  };
  if (!entry) return { changes: result, dropped: false };
  const params = new URL(entry.url, 'http://localhost').searchParams;
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const edges = new Set(graph.edges.map((edge) => edge.id));
  for (const key of ['select', 'focus', 'path', 'impact'] as const) {
    const value = params.get(key);
    if (!value) continue;
    const pair = value.split(',');
    const valid =
      key === 'select'
        ? value === 'bundle:isolated'
          ? isolatedIssues(graph).length > 0
          : value.startsWith('node:')
            ? nodes.has(value.slice(5))
            : value.startsWith('edge:') && edges.has(value.slice(5))
        : key === 'focus'
          ? nodes.has(value)
          : key === 'path'
            ? pair.length <= 2 &&
              pair.every((id) => nodes.get(id)?.kind === 'company')
            : pair.length === 2 &&
              nodes.get(pair[0])?.kind === 'company' &&
              nodes.get(pair[1])?.kind === 'issue';
    if (valid) result[key] = value;
  }
  if (result.focus) result.hops = params.get('hops') === '2' ? '2' : '1';
  return {
    changes: result,
    dropped: ['select', 'focus', 'path', 'impact'].some(
      (key) => params.has(key) && !result[key],
    ),
  };
}
