import { beforeEach, describe, expect, it } from 'vitest';
import { issues } from '@/mocks/graph/fixture';
import {
  mockDecideCandidate,
  mockGetCandidate,
  mockListCandidates,
  resetCandidateMock,
} from '@/mocks/admin/candidates';

// A-ADM-03 후보 목업: 지도 목업 이슈로 만든 합성 후보(개발 서버 전용)

describe('A-ADM-03 candidate mock', () => {
  beforeEach(() => resetCandidateMock());

  it('lists map issues as published candidates plus hold and reject examples', () => {
    const first = mockListCandidates({});
    expect(first.counts).toEqual({
      ALLOW: 18,
      HOLD: 4,
      REJECT: 1,
      inactive: 1,
    });
    expect(first.items).toHaveLength(20);
    expect(first.items[0].title).toBe(issues[0].label);
    expect(first.items[0].companies.map((c) => c.name)).toEqual([
      '삼성전자',
      'NVIDIA',
      'SK하이닉스',
    ]);
    const second = mockListCandidates({}, first.nextCursor ?? undefined);
    expect(second.items).toHaveLength(4);
    expect(second.nextCursor).toBeNull();
  });

  it('filters by status, search text and rule like the API', () => {
    expect(mockListCandidates({ status: 'HOLD' }).items).toHaveLength(4);
    expect(
      mockListCandidates({ q: '하이닉스' }).items.every((row) =>
        row.companies.some((c) => c.name === 'SK하이닉스'),
      ),
    ).toBe(true);
    expect(mockListCandidates({ rule: true }).items).toHaveLength(0);
  });

  it('records a relation decision and rejects a stale revision', () => {
    const hold = mockListCandidates({ status: 'HOLD' }).items[0];
    const relation = mockGetCandidate(hold.candidateId).relations[0];
    const request = {
      decision: 'allow' as const,
      reason: '원문 확인',
      relationId: relation.relationId,
      expectedRevision: relation.revision,
      expectedSourceVersion: relation.sourceVersion,
      expectedSourceRevision: relation.sourceRevision,
    };
    expect(mockDecideCandidate(hold.candidateId, request)).toMatchObject({
      decision: 'approved',
      publicChanged: false,
    });
    const after = mockGetCandidate(hold.candidateId);
    expect(after.relations[0].decision?.reason).toBe('원문 확인');
    expect(after.history).toHaveLength(1);
    expect(() => mockDecideCandidate(hold.candidateId, request)).toThrow(
      expect.objectContaining({ code: 'REVISION_CONFLICT' }),
    );
  });
});
