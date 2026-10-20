import { adminCall } from '@/apis/admin/auth';
import type {
  DislikePage,
  FeedbackPeriod,
  FeedbackSummary,
  InsightCompanyDetail,
  InsightCompanyRanking,
  InsightsOverview,
  StatsSummary,
  StatsWindow,
  TranscriptDetail,
  TranscriptFilter,
  TranscriptPage,
} from '@/types/admin/insights';

// A-ADM-01·02·02b 관리자 통계·선호도·대화록 조회. 모두 관리자 세션 GET이다.

function query(values: Record<string, string | null | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : '';
}

const period = ({ window, start, end }: FeedbackPeriod) =>
  start || end ? { start, end } : { window };

/** getInsightsOverview: 대시보드의 이용·선호도(7일) 요약 */
export function getInsightsOverview() {
  return adminCall<InsightsOverview>('/api/v1/admin/insights/overview', 'GET');
}

/** getInsightsSummary: 지표·산식·일별 추이·회차별 조회 */
export function getInsightsSummary(window: StatsWindow) {
  return adminCall<StatsSummary>(
    `/api/v1/admin/insights/summary${query({ window })}`,
    'GET',
  );
}

/** listCompanyInsights: 종목 순위(불투명 커서) */
export function listCompanyInsights(window: StatsWindow, cursor?: string) {
  return adminCall<InsightCompanyRanking>(
    `/api/v1/admin/insights/companies${query({ window, cursor })}`,
    'GET',
  );
}

/** getCompanyInsights: 한 기업의 일별 활동 */
export function getCompanyInsights(companyId: string, window: StatsWindow) {
  return adminCall<InsightCompanyDetail>(
    `/api/v1/admin/insights/companies/${encodeURIComponent(companyId)}${query({ window })}`,
    'GET',
  );
}

/** getFeedbackSummary: AI 기능별 현재 유효한 좋아요·싫어요 */
export function getFeedbackSummary(value: FeedbackPeriod) {
  return adminCall<FeedbackSummary>(
    `/api/v1/admin/feedback/summary${query(period(value))}`,
    'GET',
  );
}

/** listDislikedResults: 현재 싫어요 평가와 사유(불투명 커서) */
export function listDislikedResults(value: FeedbackPeriod, cursor?: string) {
  return adminCall<DislikePage>(
    `/api/v1/admin/feedback/dislikes${query({ ...period(value), cursor })}`,
    'GET',
  );
}

/**
 * listMaskedTranscripts: 가린 대화록 목록. 일반 관리자 권한과 별개인 열람 권한과
 * 승인된 열람 목적(purpose)이 필요하고, 열람은 감사 기록에 남는다.
 */
export function listMaskedTranscripts(
  only: TranscriptFilter,
  purpose: string,
  cursor?: string,
) {
  return adminCall<TranscriptPage>(
    `/api/v1/admin/transcripts${query({ only, purpose, cursor })}`,
    'GET',
  );
}

/** getMaskedTranscript: 가린 대화록 한 건(열람 목적 필수) */
export function getMaskedTranscript(sessionId: string, purpose: string) {
  return adminCall<TranscriptDetail>(
    `/api/v1/admin/transcripts/${encodeURIComponent(sessionId)}${query({ purpose })}`,
    'GET',
  );
}
