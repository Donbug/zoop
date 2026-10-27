import type { EventDetail, TimePrecision } from './event';
import type { GraphEdge } from './graph';

export type RelationValidity = 'scheduled' | 'active' | 'ended' | 'unknown';
export interface StructuralSupplyLink {
  basisId: string;
  relationType: 'SUPPLIES';
  supplierCompanyId: string;
  customerCompanyId: string;
  businessScope: string | null;
  productScope: string | null;
  validFrom: string | null;
  validUntil: string | null;
  validity: RelationValidity;
  verifiedAt: string;
  countries: string[];
  evidenceIds: string[];
}
export interface StructuralDetails {
  status: 'available' | 'unavailable' | 'not_applicable';
  reason: 'legacy_data' | 'not_recorded' | 'details_not_available' | null;
  paths: {
    relationId: string;
    companies: { id: string; label: string }[];
    links: StructuralSupplyLink[];
  }[];
}

// D-GRP-04 · EdgeDetail consumer contract from docs/api/openapi.yaml.
export interface RelationDetail {
  id: string;
  relationType: GraphEdge['relationType'];
  derived: boolean;
  directed: boolean;
  source: { id: string; kind: 'company' | 'issue'; label: string };
  target: { id: string; kind: 'company' | 'issue'; label: string };
  role: string | null;
  summary: string;
  roles: string[];
  assertionStatus: string | null;
  evidenceIds: string[];
  basis: {
    edgeId: string;
    relationType: string;
    sourceUrl: string | null;
    verifiedAt: string | null;
    validFrom: string | null;
    validUntil: string | null;
    countries: string[];
    validity: RelationValidity;
  }[];
  relationIds: string[];
  verification: { status: 'ALLOW' | 'not_applicable'; note: string | null };
  via: {
    id: string;
    title: string;
    eventTime: string | null;
    timePrecision: TimePrecision;
    evidenceIds: string[];
  }[];
  explanation: string | null;
  validity: RelationValidity | null;
  structuralDetails?: StructuralDetails;
  metadata: EventDetail['metadata'];
}

export function isSelectableRelation(edge: Pick<GraphEdge, 'relationType'>) {
  return (
    edge.relationType === 'SHARES_ISSUE' || edge.relationType === 'FOLLOWS'
  );
}
