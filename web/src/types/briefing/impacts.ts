export type ImpactLabel = 'positive' | 'negative' | 'mixed' | 'undetermined';
export type EffectSide = 'positive' | 'negative' | 'neutral' | 'uncertain';
export type S3Assessment = {
  id: string;
  relationId: string;
  status:
    | 'verified'
    | 'not-applicable'
    | 'not-proposed'
    | 'no-evidence'
    | 'technical-reject'
    | 'verifier-reject'
    | 'withheld';
  label: ImpactLabel | null;
  provenance: {
    sourceKind: 'collected' | 'synthetic';
    executionMode: 'live' | 'replay';
    recordingKind: 'provider' | 'authored-test';
  };
  evidence: {
    id: string;
    effect: EffectSide;
    quote: string;
    articleId: string;
    articleVersion: string;
    title: string | null;
    url: string | null;
    publishedAt: string | null;
    start: number;
    end: number;
  }[];
  evidencePlan?: ImpactEvidencePlan | null;
  supplementalReview?: SupplementalImpactReview | null;
  /** Exact source context, independent of whether a directional assessment passed. */
  facts?: {
    id: string;
    quote: string;
    articleId: string;
    articleVersion: string;
    title: string;
    url: string;
    publishedAt: string;
    start: number;
    end: number;
  }[];
};
export type SupplementalImpactReview = {
  mode: 'supplemental_historical_simulation';
  assessedAt: string;
  previousLabel: ImpactLabel;
  label: ImpactLabel;
  targetVerdict: 'supported' | 'insufficient';
  verifierModel: 'jev-1.14.0';
  summary: string;
  limitations: string;
  confirmedFacts: { text: string; evidenceIds: string[] }[];
  evidence: S3Assessment['evidence'];
  resultVersion: string;
  historicalVersionVerified: false;
};
export type ImpactEvidencePlan = {
  status: 'prepared_not_evaluated';
  preparedAt: string;
  reason: string;
  research?: {
    status: 'editorial_sources_not_ai_evaluated';
    linkedAt: string;
    sources: {
      id: string;
      companyId: string;
      title: string;
      url: string;
      publishedAt: string;
      timeBasis: 'issuer_html_jsonld' | 'SEC_index_accepted_America_New_York';
      summary: string;
      limitations: string;
      excerpt: string;
      transport: 'direct_http' | 'web_tool_extract';
      textSha256: string;
      historicalVersionVerified: false;
    }[];
    timeCheck: {
      status: 'publisher_time_disagreement';
      summary: string;
      limitation: string;
      storedPublishedAt: string;
      distributionPublishedAt: string;
      storedUrl: string;
      distributionUrl: string;
    } | null;
  } | null;
  existingEvidence: {
    scope: 'direct' | 'issuer_explanation' | 'conditional_risk' | 'background';
    note: string;
    source: NonNullable<S3Assessment['facts']>[number];
  }[];
  collectionNeeds: {
    kind: 'before_cutoff_gap' | 'future_followup';
    what: string;
    why: string;
    preferredSource: string;
  }[];
};
export type BriefingImpacts = {
  reviewContext?: {
    mode: 'historical_reassessment';
    assessedAt: string;
    inputScope: 'preserved_quote_context';
    generationModel: 'gpt-6-luna';
    verifierModel: 'jev-1.14.0';
    resultVersion: string;
    citationPolicy?: 'complete-source-paragraph-1' | null;
  } | null;
  roundId: string;
  eventId: string;
  graphVersion: string | null;
  dataAsOf: string;
  status: 'available' | 'unavailable';
  reason: string | null;
  companies: {
    companyId: string;
    companyName: string;
    status: 'available' | 'unavailable';
    reason: string | null;
    assessments: S3Assessment[];
  }[];
  metadata: {
    source: 's3_issue_impacts';
    asOf: string;
    graphVersion: string | null;
    requestId: string;
    partial: boolean;
    failures: unknown[];
  };
};
