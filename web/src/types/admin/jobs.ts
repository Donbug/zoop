// A-ADM-03 작업 탭 (FS058·FS067-01·FS067-03, docs/api/openapi.yaml listAnalysisJobs·getAnalysisJob·retryAnalysisJob·cancelAnalysisJob)

export type JobKind = 'ingest' | 'revalidate' | 'project';
export type JobStatus =
  'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export type RetryCode =
  | 'allowed'
  | 'succeeded'
  | 'in_progress'
  | 'superseded'
  | 'newer_attempt'
  | 'duplicate_running'
  | 'other_running'
  | 'dataset_missing'
  | 'outcome_unknown';

export type RetryState = {
  allowed: boolean;
  code: RetryCode;
  /** 서버가 적어 주는 판정 이유 */
  reason: string;
  /** 재시도를 막고 있는 작업 ID */
  blockedBy?: string | null;
};

export type IngestOutcome = {
  /** 대기·실행 중이면 null. empty는 새 기사가 없었던 정상 종료다. */
  outcome: 'collected' | 'empty' | 'failed' | 'cancelled' | null;
  newArticles: number | null;
  duplicateArticles: number | null;
  baselineBefore: string | null;
  baselineAfter: string | null;
  baselineAdvanced: boolean;
};

export type JobUsage = {
  calls: number;
  replayCalls: number;
  inputTokens: number;
  outputTokens: number;
  elapsedSeconds: number;
  estimatedCost: number | null;
};

export type RunReport = {
  runId: string | null;
  processed: number;
  skipped: number;
  approved: number;
  held: number;
  rejected: number;
  pending: number;
  errorCount: number;
  errors: Record<string, unknown>[];
  collectionErrorCount: number;
  collectionErrors: Record<string, unknown>[];
  elapsedSeconds: number;
  executionMode: string | null;
  usage: JobUsage;
};

export type AnalysisJob = {
  id: string;
  kind: JobKind;
  label: string;
  status: JobStatus;
  reason: string;
  requestedBy: string;
  requestedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  durationSeconds: number | null;
  retryOf: string | null;
  cancelRequested: boolean;
  /** 서버 재시작 뒤 복구된 작업 */
  recovered: boolean;
  retry: RetryState;
  ingest: IngestOutcome | null;
  report: RunReport | null;
  flush: { completedProjectionJobs: number } | null;
  error: { code: string; message: string } | null;
  ledgerBefore: unknown;
  ledgerAfter: unknown;
};

export type JobLock = {
  /** 관리자 작업이 실행 중일 때만 잠긴다. 대기 중인 작업은 잠그지 않는다. */
  locked: boolean;
  jobId: string | null;
  reason: string | null;
};

export type IngestBaseline = {
  at: string | null;
  jobId: string | null;
  outcome: 'collected' | 'empty' | null;
  newArticles: number | null;
  /** 가장 최근 처리가 실패·취소된 기사 파일 수. 기사별 처리 기록이 없으면 null */
  unresolvedFailures: number | null;
};

export type JobList = {
  items: AnalysisJob[];
  active: AnalysisJob | null;
  lock: JobLock;
  ingest: IngestBaseline;
  retryRule: string;
  nextCursor: string | null;
};

export type JobCreated = {
  job: AnalysisJob;
  /** 같은 요청이 이미 처리돼 새 작업을 만들지 않았다. */
  deduplicated: boolean;
};
