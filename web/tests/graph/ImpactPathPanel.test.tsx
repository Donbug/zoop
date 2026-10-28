import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ImpactPathPanel from '@/components/graph/ImpactPathPanel';
import { useRelationData } from '@/hooks/useRelationData';
import { createMockGraph } from '@/mocks/graph/response';
import { createMockRelation } from '@/mocks/relations/fixture';
import type { RelationDetail } from '@/types/map/relation';

vi.mock('@/hooks/useRelationData');

const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
const directEdge = graph.edges.find(
  (edge) => edge.relationType === 'INVOLVES',
)!;
const issue = graph.nodes.find((node) => node.id === directEdge.source)!;
const company = graph.nodes.find((node) => node.id === directEdge.target)!;
const structuralEdge = {
  ...directEdge,
  id: 'structural-issue-company',
  relationType: 'STRUCTURALLY_RELATED_TO' as const,
  summary: '구조적 관련',
};
const selectedGraph = {
  ...graph,
  edges: graph.edges.map((edge) =>
    edge.id === directEdge.id ? structuralEdge : edge,
  ),
};
const context = {
  graphVersion: graph.metadata.graphVersion ?? undefined,
  asOf: graph.metadata.asOf,
};

function structuralRelation(available: boolean): RelationDetail {
  const base = createMockRelation(
    graph.edges.find((edge) => edge.relationType === 'SHARES_ISSUE')!.id,
  );
  return {
    ...base,
    id: structuralEdge.id,
    relationType: 'STRUCTURALLY_RELATED_TO',
    source: { id: issue.id, kind: 'issue', label: issue.label },
    target: { id: company.id, kind: 'company', label: company.label },
    structuralDetails: available
      ? {
          status: 'available',
          reason: null,
          paths: [
            {
              relationId: 'supply-path',
              companies: [
                { id: company.id, label: company.label },
                { id: 'supplier', label: '공급 기업' },
              ],
              links: [
                {
                  basisId: 'basis-1',
                  relationType: 'SUPPLIES',
                  supplierCompanyId: 'supplier',
                  customerCompanyId: company.id,
                  businessScope: null,
                  productScope: null,
                  validFrom: null,
                  validUntil: null,
                  validity: 'active',
                  verifiedAt: graph.metadata.asOf,
                  countries: [],
                  evidenceIds: ['evidence-1'],
                },
              ],
            },
          ],
        }
      : { status: 'unavailable', reason: 'details_not_available', paths: [] },
    metadata: {
      ...base.metadata,
      partial: !available,
      failures: available
        ? []
        : [
            {
              section: 'structuralDetails',
              code: 'SOURCE_UNAVAILABLE',
              message: '구조 상세를 일시적으로 읽지 못했습니다.',
              retryable: true,
              asOf: graph.metadata.asOf,
            },
          ],
    },
  };
}

describe('ImpactPathPanel structural relation details', () => {
  beforeEach(() => {
    vi.mocked(useRelationData).mockImplementation((_id, _context, retry) => ({
      key: 'structural',
      data: structuralRelation(retry > 0),
      error: null,
      retryable: false,
      loading: false,
    }));
  });

  it('opens structural details through the company issue path and retries a partial response in context', async () => {
    render(
      <ImpactPathPanel
        companyId={company.id}
        issueId={issue.id}
        context={context}
        graph={selectedGraph}
        impact={{
          companyId: company.id,
          issueId: issue.id,
          pathStatus: 'available',
          pathType: 'structural',
          edgeId: structuralEdge.id,
          steps: [],
          businessPath: {
            status: 'unavailable',
            reason: 'not_recorded',
            companyIds: [],
            links: [],
          },
          impact: {
            status: 'unavailable',
            reason: 'issue_impact_not_produced',
            results: [],
          },
          metadata: {
            source: 'fixture',
            asOf: graph.metadata.asOf,
            graphVersion: graph.metadata.graphVersion,
          },
        }}
        loading={false}
        error={null}
        onRetry={vi.fn()}
        onClose={vi.fn()}
        onViewIssue={vi.fn()}
        onEvidence={vi.fn()}
        onAskAi={vi.fn()}
      />,
    );

    expect(
      await screen.findByText('구조 상세를 일시적으로 읽지 못했습니다.'),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(
      await screen.findByRole('button', { name: '공급 관계 근거 1건 보기' }),
    ).toBeTruthy();
    expect(useRelationData).toHaveBeenLastCalledWith(
      structuralEdge.id,
      context,
      1,
    );
  });
});
