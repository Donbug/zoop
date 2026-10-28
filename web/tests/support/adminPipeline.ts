import type {
  CandidateDetail,
  CandidateRow,
  PipelineOverview,
} from '@/types/admin/pipeline';
import { json, type FakeServer } from './fakeServer';

// A-ADM-03 이슈 관제 계약 픽스처. 실제 원장 값이 아니다.

export const OVERVIEW = '/api/v1/admin/pipeline/overview';
export const CANDIDATES = '/api/v1/admin/pipeline/candidates';
export const CANDIDATE = `${CANDIDATES}/:candidateId`;

export const overview = (
  patch: Partial<PipelineOverview> = {},
): PipelineOverview => ({
  asOf: '2026-10-28T01:00:00Z',
  ledger: { database: 'zoop-ai', checkedAt: '2026-10-28T00:59:00Z' },
  policy: {
    version: null,
    decisionPolicy: {},
    webVerification: false,
    validationModel: null,
  },
  candidates: {
    total: 14,
    active: 12,
    inactive: 2,
    allow: 7,
    hold: 3,
    reject: 2,
  },
  issues: { approved: 7, relations: 21, articles: 40 },
  review: {
    revision: 4,
    decisions: 5,
    allowed: 3,
    rejected: 2,
    holdPendingReview: 3,
    ruleCandidates: 0,
    ruleEvents: 0,
  },
  projection: {
    status: 'reflected',
    pendingJobs: null,
    oldestPendingAt: null,
    lastCompletedAt: null,
    neo4j: null,
    checkedAt: '2026-10-28T01:00:00Z',
  },
  publication: {
    activeVersionId: 'v-20261028',
    ledgerMatchesActive: true,
    issuesOnlyInLedger: [],
    issuesOnlyInActive: [],
  },
  jobs: {
    running: 1,
    queued: 0,
    failed24h: 1,
    lastFailure: {
      jobId: 'job-failed',
      label: '기사 분석',
      finishedAt: '2026-10-27T23:00:00Z',
      code: 'SOURCE_UNAVAILABLE',
      message: null,
    },
    ingest: {
      at: '2026-10-28T00:00:00Z',
      jobId: 'job-ingest',
      outcome: 'succeeded',
      newArticles: 4,
      unresolvedFailures: 2,
    },
  },
  runs: [],
  ...patch,
});

export const RULES = '/api/v1/admin/pipeline/rules';

/**
 * 이슈 관제 화면을 여는 테스트가 늘 보이는 영역의 요청을 처리하도록 등록한다.
 * 개요·자동 검수 규칙(탭 위)과 기본 탭인 후보 목록이다. 규칙·후보는 빈 응답이며, 테스트가 나중에 등록하면 덮인다.
 */
export function onOverview(server: FakeServer, body = overview()) {
  server.on('GET', OVERVIEW, () => json(body));
  server.on('GET', RULES, () =>
    json({ items: [], asOf: '2026-10-28T01:00:00Z', nextCursor: null }),
  );
  server.on('GET', CANDIDATES, () =>
    json({
      items: [],
      nextCursor: null,
      counts: {},
      asOf: '2026-10-28T01:00:00Z',
    }),
  );
}

export const candidate = (
  id = 'cand-1',
  patch: Partial<CandidateRow> = {},
): CandidateRow => ({
  title: '삼성전자, 미국 공장 증설',
  candidateId: id,
  issueId: 'issue-1',
  status: 'HOLD',
  active: true,
  policyVersion: null,
  action: '증설',
  target: '미국 공장',
  eventTime: '2026-10-27T03:00:00Z',
  companies: [{ companyId: 'c-005930', name: '삼성전자', role: 'subject' }],
  relationTypes: ['INVOLVES'],
  evidenceCount: 2,
  reasons: ['출처가 하나뿐이에요'],
  onUserGraph: false,
  decision: null,
  rule: null,
  ...patch,
});

export const candidateDetail = (
  id = 'cand-1',
  patch: Partial<CandidateDetail> = {},
): CandidateDetail => ({
  ...candidate(id),
  sourceVersion: 'src-v3',
  articles: [
    {
      title: '삼성전자 美 공장 증설',
      articleId: 'art-1',
      publisher: '연합뉴스',
      url: 'https://news.example.test/art-1',
      publishedAt: '2026-10-27T02:00:00Z',
    },
  ],
  evidence: [
    {
      articleId: 'art-1',
      articleVersion: 'v1',
      start: 0,
      end: 12,
      quote: '삼성전자가 미국 공장을 증설한다',
      articleTitle: '삼성전자 美 공장 증설',
      url: 'https://news.example.test/art-1',
    },
  ],
  relations: [
    {
      relationId: 'rel-1',
      sourceVersion: 'src-v3',
      sourceRevision: 'r1',
      revision: 1,
      relationType: 'INVOLVES',
      source: '삼성전자',
      target: '미국 공장 증설',
      role: null,
      assertionStatus: null,
      evidenceCount: 2,
      onUserGraph: false,
      decision: null,
    },
  ],
  verification: {
    provider: 'openai',
    model: 'gpt-test',
    verifierVersion: null,
    verdicts: [{ target: 'event', decision: 'HOLD', reason: '출처 부족' }],
  },
  invalidationReason: null,
  history: [],
  graphDb: 'not_stored',
  ...patch,
});
