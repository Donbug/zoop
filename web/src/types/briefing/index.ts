export type BriefingEdition = 'morning' | 'evening';

import type { EventDetail } from '@/types/map/event';
import type { DocumentSentiment, SentimentLabel } from '@/types/evidence';
import type { MarketOutlookAnalysis } from './marketOutlook';
export type { MarketOutlookAnalysis } from './marketOutlook';
/** 전망 분석은 발행 당시 검증한 구조화 결과가 있는 회차에만 존재한다. */
export type BriefingMarketSummary =
  | (Extract<EventDetail['summary'], { text: string }> & {
      analysis?: MarketOutlookAnalysis;
    })
  | Extract<EventDetail['summary'], { status: 'unavailable' }>;
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
  /** getBriefing SourceSupportOut. 과거 저장 응답에는 없을 수 있다. */
  sourceSupport?: { articleCount: number };
  /** 문서×기업 판정(DocumentSentimentRef). 이슈 단위로 합치지 않는다. */
  documentSentiments?: BriefingDocumentSentiment[];
};

export type BriefingDocumentSentiment = {
  articleId: string;
  sentiment: DocumentSentiment;
};

/** 발행 회차 판정(BriefingOutlook). 주가 전망이 아니며 문서별 판정과 구분한다. */
export type BriefingOutlook = {
  label: SentimentLabel;
  rationale: string;
  issueIds: string[];
  judgedAt: string;
  model: string;
  promptVersion: string;
};

/** D-BRF-01·02: 선택한 발행 회차에 고정된 문안·근거. 최신 사건/문서 조회로 대체하지 않는다. */
export type BriefingItemDetail = {
  roundId: string;
  eventId: string;
  title: string;
  summary: EventDetail['summary'];
  selectionReason: string;
  claims: {
    text: string;
    type: 'fact' | 'plan' | 'outlook';
    evidenceIds: string[];
  }[];
  companies: EventDetail['companies'];
  evidence: BriefingItemEvidence[];
  limitations: string[];
  metadata: EventDetail['metadata'];
};

export type BriefingItemEvidence = {
  id: string;
  quote: string;
  documentId: string;
  documentVersion: string;
  title: string;
  publisher: string;
  url: string | null;
  publishedAt: string | null;
  quoteVerified: true;
  sourceKind: 'news' | 'disclosure';
  bodySha256: string;
  /** 원문 전체 기준 Unicode code point 구간. end/quoteEnd는 끝 글자를 포함하지 않는다. */
  bodyContext: {
    text: string;
    start: number;
    end: number;
    quoteStart: number;
    quoteEnd: number;
    offsetUnit: 'unicode_code_point';
  } | null;
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
  source: {
    name: string;
    official: boolean;
    delayNote: string | null;
    /** getBriefing QuoteSourceOut.url; older saved responses may omit it. */
    url?: string | null;
  } | null;
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

/** 출근 회차와 직전 발행 퇴근 회차의 고정 선정 목록 비교. 성과 평가는 별도다. */
export type PreviousBriefingComparisonItem = Omit<
  SinceMorningItem,
  'morningRank' | 'morningEvidenceCount'
> & {
  previousRank: number | null;
  previousEvidenceCount: number | null;
};
export type PreviousBriefingComparison =
  | {
      status: 'available';
      previousRoundId: string;
      previousDate?: string;
      previousEdition?: BriefingEdition;
      previousPublishedAt: string | null;
      previousDataAsOf: string;
      comparisonBasis: 'event_identity';
      forecastEvaluation: { status: 'unavailable'; reason: string };
      items: PreviousBriefingComparisonItem[];
    }
  | { status: 'unavailable'; reason: string };
export type BriefingContinuity = {
  schemaVersion: 'importance-continuity-v1' | 'importance-continuity-v2';
  roundId: string;
  cutoff: string;
  mode:
    'core' | 'reference' | 'recap' | 'coverage_limited' | 'validation_failed';
  importanceFloor: 2 | 1 | null;
  message: string;
  coverage: {
    status: 'registered_scope' | 'limited' | 'insufficient';
    confirmedDocuments: number;
    message: string;
  };
  references: {
    issueId: string;
    title: string;
    importance: 1;
    label: string;
    companies: { id: string; name: string }[];
    sources: {
      evidenceId: string;
      documentId: string;
      documentVersion: string;
      quote: string;
      url: string | null;
      dateContext: { publishedAt: string };
    }[];
  }[];
  recap: {
    status: 'available' | 'unavailable';
    previousRoundId: string | null;
    date?: string;
    edition?: BriefingEdition;
    dataAsOf: string | null;
    message: string;
    items: BriefingItem[];
  };
  watchConditions: {
    text: string;
    kind: 'verification_check' | 'previous_condition';
    companyName?: string;
    previousRoundId?: string;
  }[];
  forecast: { status: 'unavailable' | 'not_updated'; message: string };
};

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
  continuity?: BriefingContinuity;
  editionReview?: import('./editionReview').EditionReview;
  companyPriceContext?: import('./priceContext').BriefingPriceContext;
  /** Fixed original review used only to authenticate reused price observations in an explicit selection. */
  companyPriceBasis?: import('./editionReview').EditionReview;
  aiPriceOutlooks?: import('./aiPriceOutlook').AiPriceOutlooks;
  preservedPublication?: {
    sha256: string;
    response: Omit<BriefingResponse, 'preservedPublication'>;
  };
  issueIntelligence?: import('./issueIntelligence').IssueIntelligence;
  issueReading?: import('./issueReading').IssueReading;
  judgmentUpdate?: import('./judgmentUpdate').JudgmentUpdate;
  companyOutlooks?: import('./companyOutlook').CompanyOutlooks;
  marketSummary: BriefingMarketSummary;
  marketVariables:
    | {
        status: 'available';
        /** Stored collection time only; never infer it from the observation time. */
        collectedAt?: string | null;
        indicators: MarketIndicator[];
      }
    | { status: 'unavailable'; reason: string };
  /** 퇴근 회차만 값이 있다. 출근 회차는 null */
  sinceMorning: SinceMorning | null;
  /** 출근 회차의 직전 퇴근 대비. 과거 응답에는 없을 수 있다. */
  previousComparison?: PreviousBriefingComparison | null;
  emptyReason: 'no_issues_in_window' | null;
  notice: {
    kind: string;
    message: string;
    reason: string | null;
    at: string | null;
  } | null;
  corrections: {
    id: number;
    /** 이 정정이 속한 핵심 이슈. 회차 전체 정정이면 null. 과거 응답에는 없을 수 있다. */
    eventId?: string | null;
    original: string | null;
    corrected: string;
    reason: string;
    createdAt: string;
  }[];
  metadata: EventDetail['metadata'];
  /** 과거 응답에는 없을 수 있다. */
  outlook?: BriefingOutlook | null;
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
  /** 원래 발행 스냅샷과 나중에 만든 재구성을 구분한다. 발행본 자체의 graphVersion은 바꾸지 않는다. */
  graphOrigin?: 'publication_snapshot' | 'reconstructed' | null;
  reconstructedAt?: string | null;
  /** 저장본 부재와 일시 조회 불가를 구분한다. 기존 서버와 호환하기 위해 선택 필드다. */
  unavailableReason?:
    | 'snapshot_not_recorded'
    | 'snapshot_unavailable'
    | 'briefing_targets_unavailable'
    | null;
  /** 회차 데이터 창의 끝(KST). 보여 주는 관계·근거의 기준 시각 */
  dataAsOf: string | null;
  graphVersion: string | null;
  keyIssueIds: string[];
  companyIds: string[];
  correctionCount: number;
};

/** 새 핵심 이슈가 없는 정상 회차에서만 제공하는, 고정된 이전 발행본의 읽기 뷰. */
export type BriefingRecap = {
  roundId: string;
  graphVersion: string | null;
  dataAsOf: string | null;
  status: 'available' | 'unavailable' | 'not_applicable';
  reason: string | null;
  message: string;
  previous: BriefingResponse | null;
};
