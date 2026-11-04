// A-ADM-03 그래프 정기 회차 (#55, docs/api/openapi.yaml listGraphRounds·getGraphRound·retryGraphRound·startGraphRound)
// 회차 행에는 코드·id·digest만 있고 경로·본문·비밀은 없다.

export const GRAPH_ROUND_STAGES = [
  'scheduled',
  'run_requested',
  'plan_ready',
  'analysis_queued',
  'analysis_done',
  'freeze_requested',
  'handoff_ready',
  'imported',
  'skipped',
  'failed',
] as const;

/** 회차 단계. scheduled → … → imported 순으로 전진하고 skipped·failed로 끝날 수 있다. */
export type GraphRoundStage = (typeof GRAPH_ROUND_STAGES)[number];

/** 아직 끝나지 않은 회차. 끝난 단계는 imported·skipped·failed이고, failed는 재시도로 다시 열 수 있다. */
export const isOpenRound = (stage: GraphRoundStage) =>
  stage !== 'imported' && stage !== 'skipped' && stage !== 'failed';

export type GraphRound = {
  roundId: string;
  slotAt: string;
  stage: GraphRoundStage;
  /** system:scheduler 또는 admin:<id>(수동 시작). 재시도는 이벤트로 남고 이 값은 바뀌지 않는다. */
  startedBy: string;
  attempts: number;
  nextAttemptAt: string | null;
  plan: { planId: string | null; planDigest: string | null } | null;
  analysisJobId: string | null;
  handoff: {
    handoffId: string | null;
    manifestDigest: string | null;
    bundleDigest: string | null;
  } | null;
  /** 이 회차가 수입한 비활성 버전. 공개는 별도 활성화다. */
  graphVersionId: string | null;
  activatedVersionId: string | null;
  activationNote: string | null;
  /** failed일 때만 */
  failureCode: string | null;
  /** 지금 이 회차를 처리 중인 writer와 그 lease 만료 시각 */
  lease: { owner: string; until: string } | null;
  createdAt: string;
  updatedAt: string;
};

export type GraphRoundEventOutcome =
  'advanced' | 'waiting' | 'failed' | 'retried' | 'skipped';

export type GraphRoundEvent = {
  id: number;
  at: string;
  stage: GraphRoundStage;
  outcome: GraphRoundEventOutcome;
  code: string | null;
  requestId: string | null;
  /** 외부 응답의 코드·digest만 */
  detail: Record<string, unknown> | null;
};

export type GraphRoundList = {
  items: GraphRound[];
  nextCursor: string | null;
};

export type GraphRoundDetail = {
  round: GraphRound;
  /** 오래된 것부터 */
  events: GraphRoundEvent[];
};

/** 개요(getPipelineOverview)의 rounds. 공개 Web에서는 살아 있는 writer의 상태다. */
export type GraphRoundsSection = {
  /** 회차 실행기(writer scheduler)가 동작 중인지 */
  enabled: boolean;
  nextSlotAt: string | null;
  lastTickAt: string | null;
  /** 끝나지 않은 회차 수 */
  openRounds: number;
  /** 최근 회차 10개(최신 슬롯부터) */
  recent: GraphRound[];
};
