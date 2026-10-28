// A-ADM-03 이슈 관제 개요·후보 (docs/api/openapi.yaml getPipelineOverview·listAnalysisCandidates·getAnalysisCandidate)
// 응답은 래퍼 없는 본문이다. AI 원천에 없는 값은 0이나 빈 문자열이 아니라 null로 온다.

import type { PastRun } from './briefings';

/** Overview.projection.status: 활성 버전에 기록된 그래프 상태. 앱이 GraphDB를 직접 읽지 않는다. */
export type ProjectionStatus =
  'reflected' | 'pending' | 'mismatch' | 'unavailable';

/** Overview */
export type PipelineOverview = {
  asOf: string;
  ledger: { database: string; checkedAt: string | null };
  policy: {
    version: string | null;
    decisionPolicy: Record<string, number>;
    webVerification: boolean;
    validationModel: string | null;
  };
  candidates: {
    total: number;
    active: number;
    inactive: number;
    allow: number;
    hold: number;
    reject: number;
  };
  issues: { approved: number; relations: number; articles: number };
  review: {
    revision: number;
    decisions: number;
    allowed: number;
    rejected: number;
    holdPendingReview: number;
    ruleCandidates: number;
    ruleEvents: number;
  };
  projection: {
    status: ProjectionStatus;
    pendingJobs: number | null;
    oldestPendingAt: string | null;
    lastCompletedAt: string | null;
    neo4j: null;
    checkedAt: string;
  };
  publication: {
    activeVersionId: string | null;
    /** 가장 최근 수입한 버전이 활성 버전인지 */
    ledgerMatchesActive: boolean;
    /** 아직 비교하지 않아 항상 빈 배열 */
    issuesOnlyInLedger: string[];
    issuesOnlyInActive: string[];
  };
  jobs: {
    running: number;
    queued: number;
    failed24h: number;
    lastFailure: {
      jobId: string;
      label: string | null;
      finishedAt: string | null;
      code: string | null;
      message: string | null;
    } | null;
    ingest: {
      at: string | null;
      jobId: string | null;
      outcome: string | null;
      newArticles: number | null;
      unresolvedFailures: number | null;
    } | null;
  };
  runs: PastRun[];
};

export type CandidateStatus = 'ALLOW' | 'HOLD' | 'REJECT';
export type CandidateDecisionFilter = 'none' | 'allow' | 'reject';

/** 앱 회사 ID에 아직 연결되지 않은 원천 기업이면 companyId가 null */
export type CandidateCompany = {
  companyId: string | null;
  name: string;
  role: string | null;
};

export type ReviewDecision = {
  id: number;
  targetType: string;
  targetId: string;
  decision: 'allow' | 'reject';
  reason: string;
  adminEmail: string;
  decidedAt: string;
  revision: number;
  origin: string;
};

/** CandidateRule. 앱이 아직 규칙을 평가하지 않아 지금은 항상 null로 온다. */
export type CandidateRule = {
  ruleId: string;
  applied: boolean;
  notAppliedReason: 'admin_decision' | 'rule_disabled' | null;
  hiddenRelations: string[];
};

/** CandidateRow */
export type CandidateRow = {
  /** 사건이 없는 관계 후보는 null */
  title: string | null;
  candidateId: string;
  issueId: string | null;
  status: CandidateStatus;
  active: boolean;
  policyVersion: string | null;
  action: string | null;
  target: string | null;
  eventTime: string | null;
  companies: CandidateCompany[];
  relationTypes: string[];
  evidenceCount: number;
  reasons: string[];
  onUserGraph: boolean;
  decision: ReviewDecision | null;
  rule: CandidateRule | null;
};

/** CandidateList. counts는 활성 후보의 판정별 수와 비활성 수(inactive) */
export type CandidateList = {
  items: CandidateRow[];
  nextCursor: string | null;
  counts: Partial<Record<CandidateStatus | 'inactive', number>>;
  asOf: string;
};

export type CandidateArticle = {
  title: string | null;
  articleId: string;
  publisher: string | null;
  url: string | null;
  publishedAt: string | null;
};

/** 접근이 철회된 기사이거나 인용 검증에 실패하면 quote가 null */
export type CandidateEvidence = {
  articleId: string;
  articleVersion: string;
  start: number;
  end: number;
  quote: string | null;
  articleTitle: string | null;
  url: string | null;
};

export type CandidateRelation = {
  relationId: string;
  sourceVersion: string;
  sourceRevision: string;
  revision: number;
  relationType: string;
  source: string;
  target: string;
  role: string | null;
  assertionStatus: string | null;
  evidenceCount: number;
  onUserGraph: boolean;
  decision: ReviewDecision | null;
};

export type CandidateVerification = {
  provider: string | null;
  model: string | null;
  verifierVersion: string | null;
  verdicts: { target: string; decision: string; reason: string | null }[];
};

/** 활성 공개 버전 기준으로 사용자가 지금 읽을 수 있는지 */
export type CandidateGraphState =
  'reflected' | 'excluded' | 'pending' | 'not_stored' | 'unknown';

/** CandidateDetail 중 화면이 쓰는 필드 */
export type CandidateDetail = CandidateRow & {
  sourceVersion: string;
  articles: CandidateArticle[];
  evidence: CandidateEvidence[];
  relations: CandidateRelation[];
  verification: CandidateVerification | null;
  invalidationReason: string | null;
  history: ReviewDecision[];
  graphDb: CandidateGraphState;
};

/** 목록 필터. 값이 없으면 그 조건을 걸지 않는다. */
export type CandidateFilters = {
  status?: CandidateStatus;
  decision?: CandidateDecisionFilter;
  active?: boolean;
  published?: boolean;
  q?: string;
};

/** DecisionRequest. 결정은 관계 단위이고, 상세에서 본 그 관계의 revision·AI 원천을 함께 보낸다. */
export type CandidateDecisionRequest = {
  decision: 'allow' | 'reject';
  reason: string;
  relationId: string;
  expectedRevision: number;
  expectedSourceVersion: string;
  expectedSourceRevision: string;
};

/** DecisionResponse. 승인은 공개가 아니라서 publicChanged는 항상 false다. */
export type CandidateDecisionResponse = {
  candidateId: string;
  decision: 'approved' | 'rejected';
  revision: number;
  publicChanged: false;
};
