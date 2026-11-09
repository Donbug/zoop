import { ApiError } from '@/apis/auth/ApiService';
import { companies, directEdges, issues } from '@/mocks/graph/fixture';
import type {
  CandidateDecisionRequest,
  CandidateDecisionResponse,
  CandidateDetail,
  CandidateFilters,
  CandidateList,
  CandidateRow,
  CandidateStatus,
  PipelineOverview,
  ReviewDecision,
} from '@/types/admin/pipeline';

// A-ADM-03 후보 목업. 지도 목업(mocks/graph/fixture.ts)의 이슈·기업으로 만든 합성 후보이며 실제 검수 기록이 아니다.
// - 지도에 보이는 다기업 이슈는 통과(ALLOW)·사용자에게 보임으로 둔다.
// - 보류·폐기 화면을 확인할 수 있게, 같은 기업으로 만든 "(예시)" 후보를 보류 4건·폐기 2건 더 둔다.
// - 결정은 이 탭을 연 동안만 메모리에 남는다(새로고침하면 처음 상태).

const AS_OF = '2026-10-06T03:41:00Z';
const SOURCE_VERSION = 'mock-ai-source-v1';
const POLICY_VERSION = 'mock-policy-v1';
const PAGE_SIZE = 20;

const companyName = new Map(
  companies.map((company) => [company.id, String(company.label)]),
);

type Seed = {
  title: string;
  companyIds: string[];
  status: CandidateStatus;
  active: boolean;
  issueId: string | null;
  reasons: string[];
};

// 지도 이슈 중 기업이 둘 이상인 것(개별 공시·미연결 예시는 후보 검수 대상이 아니라 뺀다).
const mapSeeds: Seed[] = issues.slice(0, 18).map((issue) => ({
  title: String(issue.label),
  companyIds: issueCompanies(issue.id),
  status: 'ALLOW' as const,
  active: true,
  issueId: issue.id,
  reasons: ['원문 인용이 관계를 직접 뒷받침해요.'],
}));

const extraSeeds: Seed[] = [
  {
    title: 'HBM4 추가 물량 협상 (예시)',
    companyIds: ['KRX:000660', 'NASDAQ:NVDA'],
    status: 'HOLD',
    active: true,
    issueId: null,
    reasons: ['기사 하나에서만 확인돼 운영자 확인이 필요해요.'],
  },
  {
    title: '2나노 고객사 확보 (예시)',
    companyIds: ['NYSE:TSM', 'NASDAQ:QCOM'],
    status: 'HOLD',
    active: true,
    issueId: null,
    reasons: ['관계 방향이 원문에서 분명하지 않아요.'],
  },
  {
    title: '전고체 배터리 공동 개발 (예시)',
    companyIds: ['KRX:006400', 'KRX:005380'],
    status: 'HOLD',
    active: true,
    issueId: null,
    reasons: ['발표 시점과 사건 시점이 달라 확인이 필요해요.'],
  },
  {
    title: 'AI 검색 제휴 검토 (예시)',
    companyIds: ['KRX:035420', 'NASDAQ:MSFT'],
    status: 'HOLD',
    active: true,
    issueId: null,
    reasons: ['"검토 중"이라는 표현만 있어 확정된 관계인지 알 수 없어요.'],
  },
  {
    title: '스마트폰 판매 순위 (예시)',
    companyIds: ['NASDAQ:AAPL', 'KRX:005930'],
    status: 'REJECT',
    active: true,
    issueId: null,
    reasons: ['순위 비교라 두 기업 사이의 관계가 아니에요.'],
  },
  {
    title: '주가 동반 상승 (예시)',
    companyIds: ['NASDAQ:NVDA', 'NASDAQ:AMD'],
    status: 'REJECT',
    active: false,
    issueId: null,
    reasons: ['시세 움직임만 있고 사건 근거가 없어요.'],
  },
];

function issueCompanies(issueId: string) {
  return directEdges
    .filter((edge) => edge.source === issueId)
    .map((edge) => edge.target);
}

function quoteLength(value: string) {
  return [...value].length;
}

function build(seed: Seed, index: number): CandidateDetail {
  const n = index + 1;
  const candidateId = `mock-candidate-${n}`;
  const articleId = `mock-candidate-article-${n}`;
  const quote = `${seed.title}과 관련 기업의 연결을 확인하기 위한 합성 인용문입니다.`;
  const issueNode = seed.issueId
    ? `issue:${seed.issueId}`
    : `issue:${candidateId}`;
  const shown = seed.status === 'ALLOW' && seed.active;
  return {
    title: seed.title,
    candidateId,
    issueId: seed.issueId,
    status: seed.status,
    active: seed.active,
    policyVersion: POLICY_VERSION,
    action: 'mock',
    target: seed.title,
    eventTime: '2026-10-06T00:00:00Z',
    companies: seed.companyIds.map((id) => ({
      companyId: id,
      name: companyName.get(id) ?? id,
      role: 'participant',
    })),
    relationTypes: ['INVOLVES'],
    evidenceCount: 1,
    reasons: seed.reasons,
    onUserGraph: shown,
    decision: null,
    rule: null,
    sourceVersion: SOURCE_VERSION,
    articles: [
      {
        title: `[가상 기사] ${seed.title} 관련 소식`,
        articleId,
        publisher: '줍 가상 뉴스룸',
        url: null,
        publishedAt: '2026-10-06T00:00:00Z',
      },
    ],
    evidence: [
      {
        articleId,
        articleVersion: 'mock-article-v1',
        start: 0,
        end: quoteLength(quote),
        quote,
        articleTitle: `[가상 기사] ${seed.title} 관련 소식`,
        url: null,
      },
    ],
    relations: seed.companyIds.map((id, j) => ({
      relationId: `mock-candidate-relation-${n}-${j + 1}`,
      sourceVersion: SOURCE_VERSION,
      sourceRevision: 'r1',
      revision: 1,
      relationType: 'INVOLVES',
      source: issueNode,
      target: id,
      role: 'participant',
      assertionStatus: seed.status === 'ALLOW' ? 'approved' : 'pending',
      evidenceCount: 1,
      onUserGraph: shown,
      decision: null,
    })),
    verification: {
      provider: 'mock',
      model: 'mock-verifier',
      verifierVersion: 'mock-v1',
      verdicts: [
        { target: candidateId, decision: seed.status, reason: seed.reasons[0] },
      ],
    },
    invalidationReason: seed.active
      ? null
      : '같은 사건의 새 후보로 바뀌었어요.',
    history: [],
    // 보류·폐기는 승인 전이라 공개 대상이 아니다. 보류를 승인하면 pending(다음 공개 버전 대기)이 된다.
    graphDb: shown ? 'reflected' : 'not_stored',
  };
}

function initial() {
  return [...mapSeeds, ...extraSeeds].map(build);
}

let records = initial();

/** 테스트에서 처음 상태로 되돌린다. */
export function resetCandidateMock() {
  records = initial();
}

const ROW_KEYS = [
  'title',
  'candidateId',
  'issueId',
  'status',
  'active',
  'policyVersion',
  'action',
  'target',
  'eventTime',
  'companies',
  'relationTypes',
  'evidenceCount',
  'reasons',
  'onUserGraph',
  'decision',
  'rule',
] as const satisfies readonly (keyof CandidateRow)[];

function toRow(detail: CandidateDetail): CandidateRow {
  return Object.fromEntries(
    ROW_KEYS.map((key) => [key, structuredClone(detail[key])]),
  ) as CandidateRow;
}

function matches(detail: CandidateDetail, filters: CandidateFilters) {
  if (filters.status && detail.status !== filters.status) return false;
  if (filters.active !== undefined && detail.active !== filters.active)
    return false;
  if (
    filters.published !== undefined &&
    detail.onUserGraph !== filters.published
  )
    return false;
  // 규칙 평가는 아직 없다(rule=null). 실제 API처럼 규칙 대상만 고르면 빈 목록이다.
  if (filters.rule) return false;
  if (filters.decision === 'none' && detail.decision) return false;
  if (
    (filters.decision === 'allow' || filters.decision === 'reject') &&
    detail.decision?.decision !== filters.decision
  )
    return false;
  if (filters.q) {
    const q = filters.q.toLowerCase();
    const text = [detail.title, ...detail.companies.map((c) => c.name)]
      .join(' ')
      .toLowerCase();
    if (!text.includes(q)) return false;
  }
  return true;
}

function counts() {
  const active = records.filter((r) => r.active);
  return {
    ALLOW: active.filter((r) => r.status === 'ALLOW').length,
    HOLD: active.filter((r) => r.status === 'HOLD').length,
    REJECT: active.filter((r) => r.status === 'REJECT').length,
    inactive: records.length - active.length,
  };
}

export function mockListCandidates(
  filters: CandidateFilters,
  cursor?: string,
): CandidateList {
  const start = cursor ? Number(cursor) || 0 : 0;
  const found = records.filter((r) => matches(r, filters));
  const page = found.slice(start, start + PAGE_SIZE);
  const next = start + PAGE_SIZE;
  return {
    items: page.map(toRow),
    nextCursor: next < found.length ? String(next) : null,
    counts: counts(),
    asOf: AS_OF,
  };
}

export function mockGetCandidate(candidateId: string): CandidateDetail {
  const found = records.find((r) => r.candidateId === candidateId);
  if (!found)
    throw new ApiError(404, 'RESOURCE_NOT_FOUND', '후보를 찾을 수 없습니다.');
  return structuredClone(found);
}

export function mockDecideCandidate(
  candidateId: string,
  request: CandidateDecisionRequest,
): CandidateDecisionResponse {
  const found = records.find((r) => r.candidateId === candidateId);
  const relation = found?.relations.find(
    (r) => r.relationId === request.relationId,
  );
  if (!found || !relation)
    throw new ApiError(404, 'RESOURCE_NOT_FOUND', '후보를 찾을 수 없습니다.');
  if (
    relation.decision ||
    relation.revision !== request.expectedRevision ||
    relation.sourceVersion !== request.expectedSourceVersion ||
    relation.sourceRevision !== request.expectedSourceRevision
  )
    throw new ApiError(409, 'REVISION_CONFLICT', '관계 상태가 바뀌었습니다.');
  const revision = relation.revision + 1;
  const decision: ReviewDecision = {
    id: found.history.length + 1,
    targetType: 'relation',
    targetId: relation.relationId,
    decision: request.decision,
    reason: request.reason,
    adminEmail: 'mock-admin@zoop.test',
    decidedAt: new Date().toISOString(),
    revision,
    origin: 'admin',
  };
  relation.decision = decision;
  relation.revision = revision;
  found.history = [decision, ...found.history];
  found.decision = decision;
  if (request.decision === 'allow' && found.status === 'HOLD')
    found.graphDb = 'pending';
  return {
    candidateId,
    decision: request.decision === 'allow' ? 'approved' : 'rejected',
    revision,
    publicChanged: false,
  };
}

/** 개요의 후보 판정 수를 목업 후보와 맞춘다. 나머지 개요 값은 실제 API 그대로다. */
export function withMockCandidateCounts(
  overview: PipelineOverview,
): PipelineOverview {
  const c = counts();
  const active = c.ALLOW + c.HOLD + c.REJECT;
  return {
    ...overview,
    candidates: {
      total: records.length,
      active,
      inactive: c.inactive,
      allow: c.ALLOW,
      hold: c.HOLD,
      reject: c.REJECT,
    },
  };
}
