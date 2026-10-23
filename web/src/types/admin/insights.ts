// A-ADM-02·02b 이용 통계·선호도·대화록 (docs/api/openapi.yaml admin-insights·admin-feedback)
// 응답은 래퍼 없는 본문이다. 사용자는 가명 id로만 오고, 사유·질문은 개인정보를 가린 사본이다.

export type StatsWindow = '7d' | '30d' | 'all';

export type StatsMetric = {
  key: string;
  group: 'usage' | 'interest' | 'ai';
  label: string;
  kind: 'count' | 'ratio';
  unit: string;
  /** 산식 설명. 값 옆에 그대로 보여 준다. */
  definition: string;
  /** 원천이 연결돼 읽을 수 있는지. unavailable이면 값은 null이다(0과 다름). */
  availability: 'available' | 'unavailable';
  unavailableReason:
    'not_integrated' | 'source_unavailable' | 'insufficient_history' | null;
  count: number | null;
  numerator: number | null;
  denominator: number | null;
  /** 0..1. 건수 지표와 표본이 작은 비율은 null */
  rate: number | null;
  /** 분모가 minSample 미만이라 비율을 숨겼다. */
  sampleHidden: boolean;
};

export type InsightsOverview = {
  window: string;
  asOf: string;
  minSample: number;
  metrics: StatsMetric[];
  feedback: {
    up: number | null;
    down: number | null;
    rate: number | null;
    sampleHidden: boolean;
    availability: 'available' | 'unavailable';
    unavailableReason: 'not_integrated' | 'source_unavailable' | null;
  };
  members: { registered: number; active: number; blocked: number };
};

export type DailyActivity = {
  date: string;
  activeUsers: number;
  nodeSelections: number;
  edgeSelections: number;
  briefingViews: number;
  aiQuestions: number | null;
};

export type RoundStat = {
  roundId: string;
  date: string;
  edition: 'morning' | 'evening';
  views: number;
  viewers: number;
  issueOpens: number;
  likes: number | null;
  dislikes: number | null;
};

export type StatsSummary = {
  window: StatsWindow;
  asOf: string;
  since: string | null;
  minSample: number;
  /** 온보딩 완료율이 어느 회원을 기준으로 하는지 */
  membersScope: string;
  metrics: StatsMetric[];
  trend: DailyActivity[];
  rounds: RoundStat[];
};

export type CompanyStatRow = {
  companyId: string;
  name: string;
  ticker: string | null;
  watchlistMembers: number;
  holdingMembers: number;
  nodeViews: number;
  edgeSelections: number | null;
  aiQuestions: number | null;
};

export type InsightCompanyRanking = {
  window: StatsWindow;
  asOf: string;
  totalCompanies: number;
  items: CompanyStatRow[];
  holdingsNote: string;
  nextCursor: string | null;
};

export type InsightCompanyDetail = {
  window: StatsWindow;
  asOf: string;
  companyId: string;
  name: string;
  ticker: string | null;
  inCatalog: boolean;
  watchlistMembers: number;
  holdingMembers: number;
  nodeViews: number;
  edgeSelections: number | null;
  issueSelections: number | null;
  aiQuestions: number | null;
  viewers: number;
  minSample: number;
  series: {
    date: string;
    nodeViews: number;
    edgeSelections: number | null;
    issueSelections: number | null;
    aiQuestions: number | null;
  }[];
  note: string;
};

export type FeedbackFeature =
  'chatbot_answer' | 'briefing_round' | 'briefing_issue';

/** 미리 정한 기간 또는 직접 고른 KST 날짜(start·end가 있으면 window보다 우선) */
export type FeedbackPeriod = {
  window: StatsWindow;
  start: string | null;
  end: string | null;
};

export type FeedbackSummary = {
  window: StatsWindow;
  start: string | null;
  end: string | null;
  asOf: string;
  minSample: number;
  features: {
    feature: FeedbackFeature;
    label: string;
    up: number;
    down: number;
    total: number;
    rate: number | null;
    sampleHidden: boolean;
    days: { date: string; up: number; down: number; rate: number | null }[];
  }[];
  unsupported: { feature: string; label: string; reason: string }[];
  /** 집계 기준 설명 */
  basis: string;
};

export type DislikeRow = {
  at: string;
  feature: FeedbackFeature;
  featureLabel: string;
  targetId: string;
  targetLabel: string;
  reason: string | null;
  /** 가명 id */
  voter: string;
  /** 챗봇 답변이면 대화록을 여는 세션 id */
  sessionId: string | null;
};

export type DislikePage = {
  items: DislikeRow[];
  nextCursor: string | null;
  total: number;
};

export type TranscriptFilter = 'all' | 'disliked';

export type TranscriptSummary = {
  id: string;
  user: string;
  userKind: 'member' | 'guest';
  startedAt: string;
  lastAt: string;
  messages: number;
  /** 가린 첫 질문 */
  preview: string;
  up: number;
  down: number;
};

export type TranscriptPage = {
  items: TranscriptSummary[];
  nextCursor: string | null;
  total: number;
};

export type TranscriptDetail = {
  id: string;
  user: string;
  userKind: 'member' | 'guest';
  startedAt: string;
  messages: {
    id: string;
    seq: number;
    at: string;
    question: string;
    answer: string;
    status: string;
    reason: string | null;
    contextLabels: string[];
    citationCount: number;
    feedback: { up: number; down: number; reasons: string[] };
  }[];
  masking: { rules: string[]; counts: Record<string, number> };
};
