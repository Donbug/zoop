import { ApiError } from '@/apis/auth/ApiService';
import { issues, follows } from '@/mocks/graph/fixture';
import type { EvidenceResponse } from '@/types/evidence';

export type EvidenceMockScenario =
  'success' | 'no-link' | 'unavailable' | 'forbidden' | 'error';

function quoteLength(value: string) {
  // ERD v6 stores exclusive Unicode code-point offsets, not UTF-16 offsets.
  return [...value].length;
}

export function evidenceIdsForIssue(issueId: string) {
  const index = issues.findIndex((issue) => issue.id === issueId);
  if (index < 0) return [];
  const number = index + 1;
  return [`mock-evidence-${number}`, `mock-evidence-${number}-detail`];
}

const records = new Map<string, EvidenceResponse>();
for (const [index, issue] of issues.entries()) {
  const articleId = `mock-article-${issue.id}`;
  const shared = {
    articleId,
    articleVersion: 'mock-article-v1',
    eventIds: [issue.id],
    metadata: {
      source: 'MOCK · ERD v6 기반 합성 데이터',
      asOf: '2026-10-06T03:41:00Z',
      graphVersion: 'mock-graph-v1',
      requestId: `mock-evidence-${index + 1}`,
      partial: false,
      failures: [],
    },
    sentiment: null,
    documentVersion: 'mock-article-v1',
    documentSummary: null,
    analysisStatus: {
      summary: { status: 'not_requested' as const, reason: null },
      sentiment: { status: 'not_requested' as const, reason: null },
    },
    analysisProvenance: {
      sourceKind: 'synthetic' as const,
      executionMode: 'replay' as const,
      recordingKind: 'authored-test' as const,
    },
    resultVersion: 'mock-result-v1',
  };
  const firstQuote = `${issue.label}과 관련 기업의 연결을 확인하기 위한 합성 인용문입니다.`;
  const secondQuote = `등록된 문서 버전에서 ${issue.label} 관련 표현을 추가로 확인했습니다.`;
  const [firstId, secondId] = evidenceIdsForIssue(issue.id);
  records.set(firstId, {
    ...shared,
    id: firstId,
    quote: firstQuote,
    start: 0,
    end: quoteLength(firstQuote),
    article: {
      title: `[가상 기사] ${issue.label} 관련 소식`,
      publisher: '줍 가상 뉴스룸',
      url: `https://example.com/zoop/${encodeURIComponent(issue.id)}`,
      publishedAt: '2026-10-06T00:00:00Z',
    },
    quoteVerified: true,
  });
  records.set(secondId, {
    ...shared,
    articleId: `${articleId}-detail`,
    id: secondId,
    quote: secondQuote,
    start: 12,
    end: 12 + quoteLength(secondQuote),
    article: {
      title: `[가상 공시] ${issue.label} 참고 자료`,
      publisher: '줍 가상 공시 저장소',
      url: null,
      publishedAt: null,
    },
    quoteVerified: null,
  });
}

// A FOLLOWS edge has its own relation evidence, not the endpoints' evidence union.
for (const edge of follows) {
  const source = issues.find((issue) => issue.id === edge.source)!;
  const target = issues.find((issue) => issue.id === edge.target)!;
  const base = records.get(evidenceIdsForIssue(target.id)[0])!;
  const quote = `${source.label}에서 ${target.label}으로 이어지는 후속 관계를 설명하는 합성 인용문입니다.`;
  for (const id of edge.evidenceIds)
    records.set(id, {
      ...base,
      id,
      articleId: `mock-article-${edge.id}`,
      quote,
      start: 0,
      end: quoteLength(quote),
      eventIds: [target.id, source.id],
      article: {
        title: '[가상 기사] 후속 사건 연결 자료',
        publisher: '줍 가상 뉴스룸',
        url: null,
        publishedAt: null,
      },
    });
}

export function createMockEvidence(
  id: string,
  scenario: EvidenceMockScenario = 'success',
): EvidenceResponse {
  if (scenario === 'forbidden')
    throw new ApiError(403, 'ACCESS_DENIED', '이 근거를 볼 권한이 없습니다.');
  if (scenario === 'unavailable')
    throw new ApiError(
      404,
      'EVIDENCE_UNAVAILABLE',
      '삭제되었거나 비공개인 근거입니다.',
    );
  if (scenario === 'error')
    throw new ApiError(
      503,
      'SOURCE_UNAVAILABLE',
      '근거 자료를 일시적으로 불러오지 못했습니다.',
    );
  const record = records.get(id);
  if (!record)
    throw new ApiError(404, 'RESOURCE_NOT_FOUND', '근거를 찾을 수 없습니다.');
  if (scenario === 'no-link')
    return {
      ...record,
      article: record.article && { ...record.article, url: null },
    };
  return structuredClone(record);
}

export const mockEvidenceRecords = [...records.values()].map((record) =>
  structuredClone(record),
);
