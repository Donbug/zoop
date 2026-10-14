import { companies, directEdges, issues } from '@/mocks/graph/fixture';
import {
  evidenceIdsForIssue,
  mockEvidenceRecords,
} from '@/mocks/evidence/fixture';
import type { EventContext, EventDetail } from '@/types/map/event';

export type EventMockScenario =
  | 'success'
  | 'unknown-time'
  | 'no-companies'
  | 'no-evidence'
  | 'partial'
  | 'error';

// ERD v6: Neo4j Issue + INVOLVES; shared companies.id; PostgreSQL
// articles/article_versions/evidence/document_analyses. No SQL Issue FK.
// All titles, summaries and quotes below are synthetic, never news/model results.
export function createMockEvent(
  id: string,
  scenario: EventMockScenario = 'success',
  context: EventContext = {},
): EventDetail {
  if (scenario === 'error')
    throw new Error('사건 조회에 실패했습니다. 다시 시도해 주세요. (목업)');
  const issue = issues.find((node) => node.id === id);
  if (!issue) throw new Error('사건을 찾을 수 없습니다.');
  if (
    context.round ||
    (context.graphVersion && context.graphVersion !== 'mock-graph-v1') ||
    (context.asOf && context.asOf !== '2026-10-06T03:41:00Z')
  )
    throw new Error(
      '해당 시점·회차의 목업 데이터가 없습니다. 최신 데이터로 대체하지 않습니다.',
    );
  const edges =
    scenario === 'no-companies'
      ? []
      : directEdges.filter((edge) => edge.source === id);
  const evidenceIds =
    scenario === 'no-evidence' ? [] : evidenceIdsForIssue(issue.id);
  const articleId = `mock-article-${id}`;
  const event: EventDetail = {
    id,
    title: issue.label,
    eventTime: scenario === 'unknown-time' ? null : issue.eventTime,
    timePrecision:
      scenario === 'unknown-time'
        ? 'unknown'
        : (issue.timePrecision ?? 'unknown'),
    period: null,
    companies: edges.map((edge) => ({
      id: edge.target,
      name: companies.find((c) => c.id === edge.target)!.label,
      role: edge.role,
      roleUnconfirmed: false,
      relationType: 'INVOLVES',
    })),
    articles: [
      {
        id: articleId,
        title: `[가상 기사] ${issue.label} 관련 소식`,
        publisher: '줍 가상 뉴스룸',
        url: null,
        publishedAt: '2026-10-06T00:00:00Z',
        relationType: 'REPORTS',
      },
      {
        id: `${articleId}-detail`,
        title: `[가상 공시] ${issue.label} 참고 자료`,
        publisher: '줍 가상 공시 저장소',
        url: null,
        publishedAt: null,
        relationType: 'PROVIDES_BACKGROUND',
      },
    ],
    evidenceIds,
    summary: evidenceIds.length
      ? {
          text: `${issue.label}에 관한 가상 사건입니다. 참여 기업과 관련 자료를 살펴볼 수 있습니다. 계약 규모와 향후 성과는 확인되지 않았습니다.`,
          evidenceIds,
          generatedAt: '2026-10-06T03:00:00Z',
          resultVersion: 'mock-summary-v1',
        }
      : {
          status: 'unavailable',
          reason: '확인된 근거가 없어 요약을 제공하지 않습니다.',
        },
    mentions: [],
    relations: edges.map((edge) => ({
      id: edge.id,
      edgeId: edge.id,
      relationType: edge.relationType,
      source: edge.source,
      target: edge.target,
      role: edge.role,
      roleUnconfirmed: false,
      assertionStatus: edge.assertionStatus,
      evidenceIds,
    })),
    sourceSupport: {
      articleCount: 2,
      knownLineageCount: null,
      unknownLineageArticles: [articleId, `${articleId}-detail`],
      independentSourceCount: null,
      duplicateGroups: [],
    },
    fieldDecisions: [],
    follows: { previous: [], next: [] },
    approval: null,
    metadata: {
      source: 'MOCK · ERD v6 기반 가상 데이터',
      asOf: '2026-10-06T03:41:00Z',
      graphVersion: 'mock-graph-v1',
      requestId: `mock-event-${id}`,
      partial: scenario === 'partial',
      failures: [],
    },
  };
  if (scenario === 'partial') {
    event.articles = [];
    event.metadata.failures = [
      {
        section: 'articles',
        code: 'SOURCE_UNAVAILABLE',
        message: '관련 문서를 일시적으로 조회하지 못했습니다.',
        retryable: true,
        asOf: null,
      },
    ];
  }
  return event;
}

// Shared evidence IDs point to versioned article text, just as in ERD v6.
export const mockEventEvidence = mockEvidenceRecords;
