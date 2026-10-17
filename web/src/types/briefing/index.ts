export type BriefingEdition = 'morning' | 'evening';

import type { EventDetail } from '@/types/map/event';
export type BriefingItem = Pick<
  EventDetail,
  | 'title'
  | 'eventTime'
  | 'timePrecision'
  | 'companies'
  | 'evidenceIds'
  | 'summary'
> & {
  eventId: string;
  rank: number;
  reason: string;
  evidenceCount: number;
  matchedCompanyIds?: string[];
};
export type MarketIndicator = {
  id: 'kospi' | 'kosdaq' | 'usdkrw';
  label: string;
  unit: 'pt' | 'KRW';
  status: 'ok' | 'delayed' | 'unavailable' | 'failed';
  value: number | null;
  /** reference는 은행 고시 기준환율이며 시장 종가와 구분한다. */
  valueKind: 'close' | 'latest' | 'reference' | null;
  observedDate: string | null;
  observedAt: string | null;
  baseline: { value: number; date: string; at: string | null } | null;
  change: number | null;
  changeRate: number | null;
  source: { name: string; official: boolean; delayNote: string | null } | null;
  reason: string | null;
};
/** 퇴근 회차의 같은 날 출근 회차 대비 핵심 이슈 변화(SinceMorningItem) */
export type SinceMorningItem = {
  title: string;
  eventId: string;
  eventTime: string | null;
  timePrecision: EventDetail['timePrecision'];
  /** KST 보도 시각. 시각이 없으면 날짜만, 저장 안 됐으면 null */
  reportedAt: string | null;
  companyNames: string[];
  change: 'new' | 'continuing' | 'dropped';
  rank: number | null;
  morningRank: number | null;
  evidenceCount: number | null;
  morningEvidenceCount: number | null;
};
export type SinceMorning =
  | {
      status: 'available';
      morningRoundId: string;
      morningPublishedAt: string | null;
      morningDataAsOf: string;
      items: SinceMorningItem[];
    }
  | { status: 'unavailable'; reason: string };
/** Consumer fields of getBriefing; publication snapshots are never recalculated. */
export type BriefingResponse = {
  id: string;
  date: string;
  edition: BriefingEdition;
  status: 'published' | 'not_ready' | 'generating' | 'failed' | 'suspended';
  scheduledAt: string;
  publishedAt: string | null;
  generatedAt: string | null;
  dataAsOf: string | null;
  graphVersion: string | null;
  items: BriefingItem[];
  marketSummary: EventDetail['summary'];
  marketVariables:
    | { status: 'available'; indicators: MarketIndicator[] }
    | { status: 'unavailable'; reason: string };
  /** 퇴근 회차만 값이 있다. 출근 회차는 null */
  sinceMorning: SinceMorning | null;
  emptyReason: 'no_issues_in_window' | null;
  notice: {
    kind: string;
    message: string;
    reason: string | null;
    at: string | null;
  } | null;
  corrections: {
    id: number;
    original: string | null;
    corrected: string;
    reason: string;
    createdAt: string;
  }[];
  metadata: EventDetail['metadata'];
};

/** listBriefingRounds 한 줄(BriefingRoundRef). 공개 이력은 발행·제공 중단 회차만 담는다. */
export type BriefingRoundRef = {
  id: string;
  date: string;
  edition: BriefingEdition;
  status: 'published' | 'suspended';
  publishedAt: string | null;
};

export type BriefingRoundsResponse = {
  items: BriefingRoundRef[];
  nextCursor: string | null;
};

/** getBriefingGraphBasis: 회차가 발행될 때의 그래프 기준(FS032). available이 아니면 읽을 그래프가 없다. */
export type BriefingGraphBasis = {
  roundId: string;
  date: string;
  edition: BriefingEdition;
  status: 'available' | 'suspended' | 'unavailable' | 'not_published';
  /** available이 아닐 때 사용자에게 보일 안내 */
  message: string | null;
  /** 제공 중단 회차에 관리자가 적은 사유 */
  reason: string | null;
  publishedAt: string | null;
  /** 회차 데이터 창의 끝(KST). 보여 주는 관계·근거의 기준 시각 */
  dataAsOf: string | null;
  graphVersion: string | null;
  keyIssueIds: string[];
  companyIds: string[];
  correctionCount: number;
};
