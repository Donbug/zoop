import { ApiError } from '@/apis/auth/ApiService';
import { createMockGraph } from '@/mocks/graph/response';
import { createMockEvent } from '@/mocks/events/fixture';
import {
  isSelectableRelation,
  type RelationDetail,
} from '@/types/map/relation';
import type { EventContext } from '@/types/map/event';

export type RelationMockScenario =
  'success' | 'empty' | 'no-evidence' | 'error' | 'forbidden';

// ERD v6: SHARES_ISSUE is derived from common approved Issue IDs, not
// a persisted company-company edge or a claim of trade/causality.
export function createMockRelation(
  id: string,
  context: EventContext = {},
  scenario: RelationMockScenario = 'success',
): RelationDetail {
  if (scenario === 'error')
    throw new ApiError(
      503,
      'SOURCE_UNAVAILABLE',
      '연결선 정보를 일시적으로 불러오지 못했습니다. (목업)',
    );
  if (scenario === 'forbidden')
    throw new ApiError(403, 'ACCESS_DENIED', '이 연결선을 볼 권한이 없습니다.');
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  if (
    context.round ||
    (context.graphVersion &&
      context.graphVersion !== graph.metadata.graphVersion) ||
    (context.asOf && context.asOf !== graph.metadata.asOf)
  )
    throw new ApiError(
      404,
      'RESOURCE_NOT_FOUND',
      '해당 시점·회차의 목업 데이터가 없습니다. 최신 데이터로 대체하지 않습니다.',
    );
  const edge = graph.edges.find((candidate) => candidate.id === id);
  if (!edge || !isSelectableRelation(edge))
    throw new ApiError(
      404,
      'RESOURCE_NOT_FOUND',
      '선택 가능한 연결선을 찾을 수 없습니다.',
    );
  const source = graph.nodes.find((node) => node.id === edge.source)!;
  const target = graph.nodes.find((node) => node.id === edge.target)!;
  const shared = edge.relationType === 'SHARES_ISSUE';
  const structural = edge.relationType === 'STRUCTURALLY_RELATED_TO';
  const via = (
    scenario === 'empty' || structural
      ? []
      : shared
        ? edge.via
        : [edge.source, edge.target]
  ).map((issueId) => {
    const event = createMockEvent(
      issueId,
      scenario === 'no-evidence' ? 'no-evidence' : 'success',
      context,
    );
    return {
      id: event.id,
      title: event.title,
      eventTime: event.eventTime,
      timePrecision: event.timePrecision,
      evidenceIds: event.evidenceIds,
    };
  });
  const evidenceIds = [
    ...new Set(
      shared
        ? via.flatMap((issue) => issue.evidenceIds)
        : scenario === 'empty' || scenario === 'no-evidence'
          ? []
          : edge.evidenceIds,
    ),
  ];
  const basisEdges = shared
    ? graph.edges.filter(
        (candidate) =>
          via.some((issue) => issue.id === candidate.source) &&
          [source.id, target.id].includes(candidate.target) &&
          !candidate.derived,
      )
    : [edge];
  return {
    id,
    relationType: edge.relationType,
    derived: edge.derived,
    directed: !shared,
    source: { id: source.id, kind: source.kind, label: source.label },
    target: { id: target.id, kind: target.kind, label: target.label },
    role: edge.role,
    summary: shared
      ? `같은 사건 ${via.length}건`
      : structural
        ? '구조적 관계'
        : '후속 사건',
    roles: [],
    assertionStatus: edge.assertionStatus,
    evidenceIds,
    validity: structural ? 'unknown' : null,
    structuralDetails: structural
      ? { status: 'unavailable', reason: 'not_recorded', paths: [] }
      : { status: 'not_applicable', reason: null, paths: [] },
    basis: basisEdges.map((item) => ({
      edgeId: item.id,
      relationType: item.relationType,
      sourceUrl: null,
      verifiedAt: null,
      validFrom: null,
      validUntil: null,
      countries: [],
      validity: 'unknown',
    })),
    relationIds: basisEdges.map((item) => item.id),
    verification: {
      status: 'not_applicable',
      note: '합성 데이터이며 실제 관계 검증 결과가 아닙니다.',
    },
    via,
    explanation: shared
      ? '두 기업이 같은 사건에 함께 등장했다는 뜻입니다. 직접 거래나 영향 관계는 아닙니다.'
      : structural
        ? '사업 관계로 이 사건과 연결됩니다. 합성 목업에는 공급 경로가 기록되어 있지 않습니다.'
        : '출발 사건에서 도착 사건으로 이어지는 후속 관계입니다. 주가 영향이나 인과관계를 의미하지 않습니다.',
    metadata: {
      source: graph.metadata.source,
      asOf: graph.metadata.asOf,
      graphVersion: graph.metadata.graphVersion,
      requestId: `mock-relation-${id}`,
      partial: structural,
      failures: structural
        ? [
            {
              section: 'structuralDetails',
              code: 'STRUCTURAL_DETAIL_UNAVAILABLE',
              message: '사업 관계 상세 정보가 기록되어 있지 않습니다.',
              retryable: false,
              asOf: graph.metadata.asOf,
            },
          ]
        : [],
    },
  };
}
