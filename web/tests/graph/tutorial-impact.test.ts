import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getTutorialImpact } from '@/apis/graph/impact';
import { getRelation } from '@/apis/graph/relations';
import type { RelationDetail } from '@/types/map/relation';
vi.mock('@/apis/graph/relations', () => ({ getRelation: vi.fn() }));
const relation = {
  id: 'actual-edge',
  relationType: 'INVOLVES',
  derived: false,
  source: { id: 'issue', kind: 'issue', label: '실제 사건' },
  target: { id: 'company', kind: 'company', label: '실제 기업' },
  role: '공급',
  summary: '확인된 계약 당사자',
  evidenceIds: ['evidence-a'],
  verification: { status: 'ALLOW', note: null },
  metadata: {
    source: 'public_graph_snapshot',
    asOf: '2026-10-22T00:00:00Z',
    graphVersion: 'v1',
    partial: false,
  },
} as RelationDetail;
beforeEach(() => vi.mocked(getRelation).mockResolvedValue(relation));
describe('FS015 실제 지도 간선 기반 튜토리얼 경로', () => {
  it('서버에서 확인한 같은 간선의 두 끝점과 근거만 사용한다', async () => {
    const context = { asOf: relation.metadata.asOf, graphVersion: 'v1' };
    const impact = await getTutorialImpact(
      'company',
      'issue',
      'actual-edge',
      context,
    );
    expect(getRelation).toHaveBeenCalledWith('actual-edge', context);
    expect(impact.steps.map((step) => step.id)).toEqual(['company', 'issue']);
    expect(
      impact.steps.every((step) => step.evidenceIds[0] === 'evidence-a'),
    ).toBe(true);
  });
  it.each([
    { derived: true },
    { verification: { status: 'not_applicable', note: null } },
    { target: { id: 'different', kind: 'company', label: '다른 기업' } },
    { metadata: { ...relation.metadata, partial: true } },
  ])(
    '승인되지 않았거나 대상이 다른 연결은 완료하지 않는다: %j',
    async (change) => {
      vi.mocked(getRelation).mockResolvedValue({
        ...relation,
        ...change,
      } as RelationDetail);
      await expect(
        getTutorialImpact('company', 'issue', 'actual-edge'),
      ).rejects.toThrow('확인하지 못했어요');
    },
  );
});
