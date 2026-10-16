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
> & { eventId: string; rank: number; reason: string; evidenceCount: number };
export type MarketIndicator = {
  id: 'kospi' | 'kosdaq' | 'usdkrw';
  label: string;
  unit: 'pt' | 'KRW';
  status: 'ok' | 'delayed' | 'unavailable' | 'failed';
  value: number | null;
  valueKind: 'close' | 'latest' | null;
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
