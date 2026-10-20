import type { MapMode, PersonalScope } from './index';

// D-GRP-01 / D-GRP-01b — docs/api/openapi.yaml GraphResponse.
export interface GraphNode {
  id: string;
  kind: 'company' | 'issue';
  label: string;
  isFocus: boolean;
  holding: boolean;
  watch: boolean;
  brandColor: string | null;
  logoUrl: string | null;
  eventTime: string | null;
  timePrecision: 'year' | 'month' | 'day' | 'datetime' | 'unknown' | null;
  action: string | null;
  target: string | null;
  evidenceCount: number | null;
  geography: 'domestic' | 'international' | null;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationType:
    'INVOLVES' | 'STRUCTURALLY_RELATED_TO' | 'FOLLOWS' | 'SHARES_ISSUE';
  role: string | null;
  summary: string;
  assertionStatus: string | null;
  derived: boolean;
  via: string[];
  evidenceIds: string[];
}
export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: {
    source: string;
    asOf: string;
    graphVersion: string | null;
    mode: MapMode;
    truncated: boolean;
    emptyReason: string | null;
    focusCompanyIds: string[];
    depth: number | null;
    limit: number;
    requestId: string;
    partial: boolean;
    failures: { section: string; code: string; message: string }[];
    personalFilter: PersonalScope | null;
  };
}
export interface GraphRequest {
  mode: MapMode;
  personalFilter: PersonalScope;
  companyId?: string;
  asOf?: string;
  graphVersion?: string;
  depth?: 1 | 2;
  /** D-BRF-04 브리핑 회차 id. 그 회차가 발행될 때의 그래프를 읽는다. */
  round?: string;
}
