import type { GraphEdge, GraphNode, GraphResponse } from '@/types/map/graph';

// D-GRP-01: 공개 그래프는 한 기사에서 뽑은 서로 다른 사건에 같은 제목(label)을 붙인다.
// 지도에는 같은 제목의 사건을 노드 하나로 묶어 그리고, 누르면 묶인 사건 목록을 보여 준다.
// 사건 ID·근거·영향 조회는 원래 사건 그대로 쓰고, 그리기용 그래프만 바꾼다.

export const GROUP_PREFIX = 'group:';

export interface IssueGroups {
  /** 같은 제목 사건을 묶음 노드로 바꾼 그리기용 그래프 */
  graph: GraphResponse;
  /** 묶음 노드 ID → 묶인 원래 사건(시각 최신순) */
  members: Map<string, GraphNode[]>;
  /** 원래 사건 ID → 묶음 노드 ID */
  groupOf: Map<string, string>;
  /** 원래 선 ID → 그리기용 선 ID(합쳐진 선은 남은 선 ID) */
  edgeOf: Map<string, string>;
}

const titleKey = (label: string) => label.normalize('NFC').trim();

function newestFirst(a: GraphNode, b: GraphNode) {
  if (a.eventTime && b.eventTime && a.eventTime !== b.eventTime)
    return a.eventTime < b.eventTime ? 1 : -1;
  if (a.eventTime !== b.eventTime) return a.eventTime ? -1 : 1;
  return a.id < b.id ? -1 : 1;
}

export function groupIssues(data: GraphResponse): IssueGroups {
  const byTitle = new Map<string, GraphNode[]>();
  for (const node of data.nodes) {
    if (node.kind !== 'issue') continue;
    const key = titleKey(node.label);
    byTitle.set(key, [...(byTitle.get(key) ?? []), node]);
  }
  const members = new Map<string, GraphNode[]>();
  const groupOf = new Map<string, string>();
  const groupNodes = new Map<string, GraphNode>();
  for (const list of byTitle.values()) {
    if (list.length < 2) continue;
    const sorted = [...list].sort(newestFirst);
    // 묶음 ID는 가장 작은 사건 ID로 정해 새로 고침·공유 주소에서도 같은 묶음을 가리킨다.
    const id = `${GROUP_PREFIX}${[...list].map((node) => node.id).sort()[0]}`;
    members.set(id, sorted);
    for (const node of list) groupOf.set(node.id, id);
    const first = sorted[0];
    groupNodes.set(id, {
      ...first,
      id,
      action: null,
      target: null,
      isFocus: list.some((node) => node.isFocus),
      holding: list.some((node) => node.holding),
      watch: list.some((node) => node.watch),
      evidenceCount: list.reduce(
        (sum, node) => sum + (node.evidenceCount ?? 0),
        0,
      ),
      geography: list.every((node) => node.geography === first.geography)
        ? first.geography
        : null,
    });
  }
  const edgeOf = new Map<string, string>();
  if (!members.size)
    return {
      graph: data,
      members,
      groupOf,
      edgeOf: new Map(data.edges.map((edge) => [edge.id, edge.id])),
    };

  const view = (id: string) => groupOf.get(id) ?? id;
  const nodes: GraphNode[] = [];
  for (const node of data.nodes) {
    const group = groupOf.get(node.id);
    if (!group) nodes.push(node);
    else if (groupNodes.has(group)) {
      nodes.push(groupNodes.get(group)!);
      groupNodes.delete(group);
    }
  }
  const merged = new Map<string, GraphEdge>();
  for (const edge of data.edges) {
    const source = view(edge.source);
    const target = view(edge.target);
    const via = [...new Set(edge.via.map(view))];
    const key = `${edge.relationType}|${source}|${target}|${edge.role ?? ''}`;
    const kept = merged.get(key);
    if (kept) {
      kept.evidenceIds = [
        ...new Set([...kept.evidenceIds, ...edge.evidenceIds]),
      ];
      kept.via = [...new Set([...kept.via, ...via])];
      edgeOf.set(edge.id, kept.id);
      continue;
    }
    merged.set(key, { ...edge, source, target, via });
    edgeOf.set(edge.id, edge.id);
  }
  return {
    graph: { ...data, nodes, edges: [...merged.values()] },
    members,
    groupOf,
    edgeOf,
  };
}

type CenterRequest = { id: string; seq: number };
const viewRequests = new WeakMap<CenterRequest, CenterRequest>();

/** 묶인 사건으로 지도 이동을 요청하면 묶음 노드로 옮긴다. 같은 요청에는 같은 객체를 돌려준다. */
export function viewRequest(
  request: CenterRequest | null,
  groups: IssueGroups | null,
): CenterRequest | null {
  const group = request && groups?.groupOf.get(request.id);
  if (!request || !group) return request;
  const cached = viewRequests.get(request);
  if (cached?.id === group) return cached;
  const next = { ...request, id: group };
  viewRequests.set(request, next);
  return next;
}
