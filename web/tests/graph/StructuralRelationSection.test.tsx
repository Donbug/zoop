import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StructuralRelationSection from '@/components/graph/StructuralRelationSection';
import type { StructuralDetails } from '@/types/map/relation';
import { isSelectableRelation } from '@/types/map/relation';
import { createMockRelation } from '@/mocks/relations/fixture';
import { createMockGraph } from '@/mocks/graph/response';

const details: StructuralDetails = {
  status: 'available',
  reason: null,
  paths: [
    {
      relationId: 'source-1',
      companies: [
        { id: 'a', label: '기업 A' },
        { id: 'b', label: '기업 B' },
      ],
      links: [
        {
          basisId: 'basis-1',
          relationType: 'SUPPLIES',
          supplierCompanyId: 'b',
          customerCompanyId: 'a',
          businessScope: '<b>서버 부품</b>',
          productScope: null,
          validFrom: '2026-01-01',
          validUntil: null,
          validity: 'active',
          verifiedAt: '2026-10-20T03:00:00Z',
          countries: [],
          evidenceIds: ['basis-evidence'],
        },
      ],
    },
  ],
};
afterEach(cleanup);

describe('D-GRP-04 structural supply details', () => {
  it('uses the supplier direction, renders scope as text and opens only this basis', async () => {
    const open = vi.fn();
    render(<StructuralRelationSection details={details} onEvidence={open} />);
    expect(screen.getByText('기업 B → 기업 A')).toBeTruthy();
    expect(screen.getByText('<b>서버 부품</b>').querySelector('b')).toBeNull();
    expect(screen.getByText('범위 정보 미상')).toBeTruthy();
    expect(screen.getByText(/종료일 미상/)).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: '공급 관계 근거 1건 보기' }),
    );
    expect(open).toHaveBeenCalledWith(details.paths[0].links[0]);
  });
  it('does not manufacture relationships from absent, withheld or inapplicable data', () => {
    const { rerender } = render(
      <StructuralRelationSection onEvidence={vi.fn()} />,
    );
    expect(
      screen.getByText('사업 관계 상세 정보가 아직 제공되지 않습니다.'),
    ).toBeTruthy();
    rerender(
      <StructuralRelationSection
        details={{
          status: 'unavailable',
          reason: 'details_not_available',
          paths: [],
        }}
        onEvidence={vi.fn()}
      />,
    );
    expect(
      screen.getByText('현재 표시할 수 있는 사업 관계 상세 정보가 없습니다.'),
    ).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
    rerender(
      <StructuralRelationSection
        details={{ status: 'not_applicable', reason: null, paths: [] }}
        onEvidence={vi.fn()}
      />,
    );
    expect(screen.queryByRole('region')).toBeNull();
  });
  it('keeps separate source paths and never collapses two steps into a direct supply', () => {
    const two = structuredClone(details);
    const path = two.paths[0];
    path.companies.push({ id: 'c', label: '기업 C' });
    path.links.push({
      ...path.links[0],
      basisId: 'basis-2',
      supplierCompanyId: 'c',
      customerCompanyId: 'b',
    });
    two.paths.push({ ...structuredClone(path), relationId: 'source-2' });
    render(<StructuralRelationSection details={two} onEvidence={vi.fn()} />);
    expect(screen.getAllByText('기업 C → 기업 B')).toHaveLength(2);
    expect(screen.queryByText('기업 C → 기업 A')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });
  it('allows structural selection without making issue links selectable', () => {
    expect(
      isSelectableRelation({ relationType: 'STRUCTURALLY_RELATED_TO' }),
    ).toBe(true);
    expect(isSelectableRelation({ relationType: 'INVOLVES' })).toBe(false);
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const shared = graph.edges.find((e) => e.relationType === 'SHARES_ISSUE')!;
    expect(createMockRelation(shared.id).structuralDetails?.status).toBe(
      'not_applicable',
    );
  });
});
