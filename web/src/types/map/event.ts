// D-GRP-02 · getEvent consumer DTOs from docs/api/openapi.yaml.
// Geography belongs to GraphNode, not EventDetail. Never infer it from companies.
export type TimePrecision = 'year' | 'month' | 'day' | 'datetime' | 'unknown';
export interface EventContext {
  round?: string;
  graphVersion?: string;
  asOf?: string;
}
export interface EventCompany {
  id: string;
  name: string;
  role: string | null;
  roleUnconfirmed: boolean;
  relationType: 'INVOLVES' | 'STRUCTURALLY_RELATED_TO';
}
export interface EventArticle {
  id: string;
  title: string | null;
  publisher: string | null;
  url: string | null;
  publishedAt: string | null;
  relationType: 'REPORTS' | 'PROVIDES_BACKGROUND' | null;
}
export interface EventDetail {
  id: string;
  title: string;
  eventTime: string | null;
  timePrecision: TimePrecision;
  period: string | null;
  companies: EventCompany[];
  articles: EventArticle[];
  evidenceIds: string[];
  summary:
    | {
        text: string;
        evidenceIds: string[];
        generatedAt: string;
        resultVersion: string;
      }
    | { status: 'unavailable'; reason: string };
  mentions: {
    title: string;
    mentionId: string;
    articleId: string;
    action: string;
    target: string | null;
    eventTime: string | null;
    timePrecision: TimePrecision;
    period: string | null;
    assertionStatus: string;
    participants: {
      companyId: string | null;
      name: string;
      role: string | null;
      roleUnconfirmed: boolean;
    }[];
    evidenceIds: string[];
    background: boolean;
  }[];
  relations: {
    id: string;
    edgeId: string | null;
    relationType: string;
    source: string;
    target: string;
    role: string | null;
    roleUnconfirmed: boolean;
    assertionStatus: string | null;
    evidenceIds: string[];
  }[];
  sourceSupport: {
    articleCount: number;
    knownLineageCount: number | null;
    unknownLineageArticles: string[];
    independentSourceCount: number | null;
    duplicateGroups: string[][];
  };
  fieldDecisions: {
    candidateId: string | null;
    mentionId: string | null;
    outcomes: { field: string; decision: string; reason: string | null }[];
  }[];
  follows: { previous: FollowRef[]; next: FollowRef[] };
  /** 관리자 최종 승인이 있는 사건만 채워진다. 사용자 화면에는 보이지 않는다(FE 전달 3-1). */
  approval: {
    source: 'admin-review';
    label: string;
    scope: string;
  } | null;
  metadata: {
    source: string;
    asOf: string;
    graphVersion: string | null;
    requestId: string;
    partial: boolean;
    failures: {
      section: string;
      code: string;
      message: string;
      retryable: boolean;
      asOf: string | null;
    }[];
  };
}
interface FollowRef {
  id: string;
  title: string;
  eventTime: string | null;
  timePrecision: TimePrecision;
}
