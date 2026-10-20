// A-ADM-01 운영 대시보드 (docs/api/openapi.yaml Dashboard, getAdminDashboard)
// 응답은 래퍼 없는 Dashboard다. 화면이 쓰는 필드만 적고, 나머지 필드는 계약 정본을 따른다.

export type DashboardRoundStatus =
  | 'scheduled'
  | 'missing'
  | 'generating'
  | 'verifying'
  | 'published'
  | 'failed'
  | 'suspended';

export type DashboardJobStatus =
  'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export type DashboardGraphDbStatus =
  'reflected' | 'pending' | 'mismatch' | 'unavailable';

/** RoundOut 중 대시보드가 쓰는 필드 */
export type DashboardRound = {
  id: string;
  date: string;
  edition: 'morning' | 'evening';
  status: DashboardRoundStatus;
  dataWindow: { end: string | null };
};

/** JobOut 중 대시보드가 쓰는 필드 */
export type DashboardJob = {
  id: string;
  kind: string;
  label: string;
  status: DashboardJobStatus;
  requestedAt: string;
};

/** ReviewRuleOut 중 대시보드가 쓰는 필드 */
export type DashboardRule = {
  id: string;
  title: string;
  enabled: boolean;
  publishedEvents: number;
};

export type Dashboard = {
  generatedAt: string;
  metadata: {
    partial: boolean;
    failures: { source: string; code: string; message: string }[];
  };
  ledger: {
    status: 'connected' | 'unavailable';
    error: { code: string; message: string } | null;
  };
  graph: {
    activeVersionId: string | null;
    activatedAt: string | null;
    versionCount: number;
    activeVersion: {
      id: string;
      sequence: number;
      kind: string;
      sourceLabel: string;
      createdAt: string;
      activatedAt: string | null;
      issueCount: number;
      relationCount: number;
      articleCount: number;
    } | null;
    reviewRevision: number | null;
    reviewDecisions: number | null;
    rules: DashboardRule[] | null;
    graphDb: {
      status: DashboardGraphDbStatus;
      pendingJobs: number | null;
    } | null;
  } | null;
  /** 원장에 연결하지 못하면 null */
  candidates: {
    allow: number;
    hold: number;
    reject: number;
    inactive: number;
    holdPendingReview: number;
  } | null;
  jobs: {
    running: number;
    queued: number;
    failed24h: number;
    recent: DashboardJob[];
  } | null;
  ai: {
    window: string;
    requests: number;
    succeeded: number;
    failed: number;
    features: {
      feature: string;
      label: string;
      requests: number;
      failed: number;
    }[];
  } | null;
  briefings: { latest: DashboardRound[]; delayedOrFailed: number } | null;
  members: {
    registered: number;
    activeMemberSessions: number;
    activeGuestSessions: number;
    source: 'zoop-db';
  } | null;
  audit: { last24h: number } | null;
};
