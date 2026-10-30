// A-ADM-04 브리핑 운영 · A-ADM-04b AI 사용량 (docs/api/openapi.yaml admin-briefings·admin-ai)
// 응답은 래퍼 없는 본문이다. 발행 원문은 바뀌지 않고, 정정은 원문 옆에 따로 쌓인다.

import type { DashboardRoundStatus } from './dashboard';

export type StageStatus =
  'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'unknown';

export type Stage = { status: StageStatus; at: string | null };

export type Suspension = { reason: string; at: string; adminEmail: string };

/** RoundOut */
export type AdminRound = {
  id: string;
  date: string;
  edition: 'morning' | 'evening';
  scheduledAt: string;
  dataWindow: { start: string | null; end: string; openStart: boolean };
  status: DashboardRoundStatus;
  stages: { generate: Stage; verify: Stage; publish: Stage };
  failureReason: string | null;
  generatedAt: string | null;
  publishedAt: string | null;
  graphVersion: string | null;
  reviewRevision: number | null;
  itemCount: number | null;
  trigger: 'scheduler' | 'admin' | null;
  attempts: number;
  delayed: boolean;
  correctionCount: number;
  suspension: Suspension | null;
  reprocessable: boolean;
  /** 재처리할 수 없는 이유 */
  blockedReason: string | null;
};

export type RoundList = {
  items: AdminRound[];
  schedule: { morning: string; evening: string; timezone: string };
  nextCursor: string | null;
};

export type Correction = {
  id: number;
  seq: number;
  eventId: string | null;
  original: string | null;
  corrected: string;
  reason: string;
  createdAt: string;
  adminEmail: string;
};

/** BriefingPayload 중 운영 화면이 쓰는 필드(발행 원문) */
export type PublishedBriefing = {
  id: string;
  items: { eventId: string; rank: number; title: string; reason: string }[];
};

export type RoundDetail = AdminRound & {
  published: PublishedBriefing | null;
  corrections: Correction[];
  attemptsLog: {
    n: number;
    trigger: 'scheduler' | 'admin';
    startedAt: string;
    finishedAt: string | null;
    status: string;
    failureReason: string | null;
    adminEmail: string | null;
  }[];
};

export type CorrectionRequest = {
  /** null이면 회차 전체 정정 */
  eventId: string | null;
  correctedText: string;
  reason: string;
};

export type SuspensionAction = 'suspend' | 'resume';

export type AiUsageWindow = '24h' | '7d' | '30d' | 'all';
export type AiUsageAvailability = 'complete' | 'partial' | 'unavailable';
export type AiFeature =
  | 'chatbot'
  | 'news-analysis'
  | 'briefing'
  | 'document-sentiment'
  | 'briefing-outlook';

/** 실제 청구 비용과 추정 비용을 따로 둔다. 모르면 null이고 0으로 채우지 않는다. */
export type FeatureCost = {
  status: 'unavailable' | 'estimated';
  actual: number | null;
  estimated: number | null;
  currency: string | null;
  reason: string;
};

export type AiFeatureUsage = {
  feature: AiFeature;
  availability: AiUsageAvailability;
  unavailableMetrics: string[];
  label: string;
  /** 처리 방식 설명 */
  engine: string;
  modelBacked: boolean;
  requests: number | null;
  succeeded: number | null;
  failed: number | null;
  latencyMs: { avg: number; p95: number; max: number } | null;
  usage: {
    modelCalls: number | null;
    inputTokens: number | null;
    outputTokens: number | null;
    replayCalls: number | null;
    retries: number | null;
  };
  cost: FeatureCost;
  source: 'measured' | 'job-runner' | 'ledger-db' | 'document';
  recentErrors:
    { at: string; code: string | null; message: string | null }[] | null;
  note: string;
};

export type PastRun = {
  runId: string | null;
  label: string;
  policyGroup: 'strict-web' | 'relaxed-no-web' | 'admin-job';
  source: 'ledger-db' | 'document' | 'job-runner';
  processed: number | null;
  approved: number | null;
  held: number | null;
  rejected: number | null;
  pending: number | null;
  errorCount: number | null;
  /** 앱에 사용량 기록이 없는 실행(analyze_plan 등)은 null: 0이 아니라 미측정이다. */
  usage: {
    calls: number;
    replayCalls: number;
    inputTokens: number;
    outputTokens: number;
    elapsedSeconds: number;
    estimatedCost: number | null;
  } | null;
};

/**
 * 하루(KST) 동안 한 기능이 쓴 모델 사용량. 계약 제안(#134 요청) 필드이며, 모르는 값은 0이 아니라 null이다.
 * 비용은 실제 청구액과 추정액을 따로 둔다.
 */
export type AiUsageDayFeature = {
  feature: AiFeature;
  availability: AiUsageAvailability;
  unavailableMetrics: string[];
  modelCalls: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  actualCost: number | null;
  estimatedCost: number | null;
};

export type AiUsageDay = {
  /** KST 날짜 YYYY-MM-DD */
  date: string;
  features: AiUsageDayFeature[];
};

/**
 * 집계 기간에 AI를 쓴 회원 수(계약 제안). totalMembers는 기간 끝 기준 가입 회원(탈퇴 제외)이다.
 * 기능별 회원 수는 측정하지 않으면 null이다.
 */
export type AiUsageMembers = {
  availability: AiUsageAvailability;
  unavailableMetrics: string[];
  totalMembers: number | null;
  aiMembers: number | null;
  chatbotMembers: number | null;
  briefingMembers: number | null;
  note: string | null;
};

export type AiUsage = {
  availability: 'complete' | 'partial';
  unavailableMetrics: string[];
  asOf: string;
  window: AiUsageWindow;
  /** 기능별 원천을 하나라도 못 읽어도 정해진 5개 기능 행을 유지한다. */
  features: AiFeatureUsage[];
  pastRuns: PastRun[];
  cost: FeatureCost;
  /** 날짜별·기능별 사용량(계약 제안). 서버가 아직 주지 않으면 없다. */
  daily?: AiUsageDay[] | null;
  /** AI 사용 회원 수(계약 제안). 서버가 아직 주지 않으면 없다. */
  members?: AiUsageMembers | null;
};
