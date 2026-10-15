import { describe, expect, it } from 'vitest';
import { createMockRelation } from '@/mocks/relations/fixture';
import { createMockGraph } from '@/mocks/graph/response';
import { createMockEvidence } from '@/mocks/evidence/fixture';

const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
const shared = graph.edges.find(
  (edge) => edge.relationType === 'SHARES_ISSUE',
)!;

describe('D-GRP-04 · ERD v6 mock relations', () => {
  it('derives common issues and resolves all their evidence without inventing a direct relationship', () => {
    const detail = createMockRelation(shared.id);
    expect(detail.derived).toBe(true);
    expect(detail.directed).toBe(false);
    expect(detail.via.map((issue) => issue.id)).toEqual(shared.via);
    expect(detail.evidenceIds).toEqual([
      ...new Set(detail.via.flatMap((issue) => issue.evidenceIds)),
    ]);
    expect(detail.evidenceIds.length).toBeGreaterThan(0);
    for (const id of detail.evidenceIds)
      expect(
        createMockEvidence(id).eventIds.some((eventId) =>
          shared.via.includes(eventId),
        ),
      ).toBe(true);
    expect(detail.basis.every((item) => item.verifiedAt === null)).toBe(true);
    expect(detail.explanation).toContain('직접 거래나 영향 관계는 아닙니다');
  });
  it('keeps FOLLOWS direction and relation evidence separate from endpoint evidence', () => {
    const edge = graph.edges.find((item) => item.relationType === 'FOLLOWS')!;
    const detail = createMockRelation(edge.id);
    expect(detail.directed).toBe(true);
    expect(detail.source.id).toBe(edge.source);
    expect(detail.target.id).toBe(edge.target);
    expect(detail.evidenceIds).toEqual(edge.evidenceIds);
    expect(detail.evidenceIds).not.toEqual(
      detail.via.flatMap((issue) => issue.evidenceIds),
    );
    detail.evidenceIds.forEach((id) =>
      expect(createMockEvidence(id).quote).toContain('후속 관계'),
    );
  });
  it('does not substitute a current snapshot or permit issue-company detail', () => {
    for (const context of [
      { round: 'old-round' },
      { graphVersion: 'old-version' },
      { asOf: '2000-01-01' },
    ])
      expect(() => createMockRelation(shared.id, context)).toThrow(
        '최신 데이터로 대체하지 않습니다',
      );
    expect(() =>
      createMockRelation(
        graph.edges.find((item) => item.relationType === 'INVOLVES')!.id,
      ),
    ).toThrow('선택 가능한 연결선');
    expect(() => createMockRelation('missing')).toThrow('선택 가능한 연결선');
  });
  it('distinguishes empty common issues, no evidence, permission and service failures', () => {
    expect(createMockRelation(shared.id, {}, 'empty').via).toEqual([]);
    const noEvidence = createMockRelation(shared.id, {}, 'no-evidence');
    expect(noEvidence.via.length).toBeGreaterThan(0);
    expect(noEvidence.evidenceIds).toEqual([]);
    expect(noEvidence.via.every((issue) => !issue.evidenceIds.length)).toBe(
      true,
    );
    expect(() => createMockRelation(shared.id, {}, 'forbidden')).toThrow(
      '권한',
    );
    expect(() => createMockRelation(shared.id, {}, 'error')).toThrow(
      '일시적으로',
    );
  });
});
