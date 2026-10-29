import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import JudgmentUpdate from '@/components/briefing/JudgmentUpdate';
import { validJudgment } from '@/util/judgmentUpdate';
import type { BriefingResponse } from '@/types/briefing';
import type { JudgmentUpdate as Update } from '@/types/briefing/judgmentUpdate';
const s = (text: string, id = 'a') => ({ text, evidenceIds: [id] });
function fixture() {
  const update: Update = {
    schemaVersion: 'zoop-judgment-update-v1',
    status: 'PASS',
    roundId: 'r',
    edition: 'morning',
    cutoff: '2026-10-23T09:20:00+09:00',
    previousRoundId: 'p',
    previousCutoff: '2026-10-22T17:30:00+09:00',
    companyResultVersion: 'current',
    previousResultVersion: 'previous',
    resultVersion: 'new',
    scopeNote: '합성 시험',
    conclusion: s('계약과 공급 일정 실행력을 확인합니다.'),
    industryChange: s('이전 투자 계획에 제품별 수요 계획이 추가됐습니다.'),
    limits: s('직접 공급관계는 입증하지 않습니다.'),
    sources: Object.fromEntries(
      ['a', 'b'].map((id) => [
        id,
        {
          evidenceId: id,
          title: `합성 원문 ${id}`,
          url: `https://example.com/${id}`,
          fullBody: '1단계 도입 예정. 2단계는 최종 계약 조건.',
          publishedAt: '2026-10-22T10:00:00+09:00',
        },
      ]),
    ),
    companies: ['a', 'b'].map((id, i) => ({
      companyId: id,
      companyName: i ? '이전 기업' : '새 기업',
      role: i ? 'watch' : 'selected',
      decision: i ? 'maintained' : 'initial',
      sourceIds: [id],
      previousJudgment: i
        ? {
            outlook: s('기존 계획의 실행을 관찰합니다.', id),
            conditions: [s('장비 적용을 확인합니다.', id)],
          }
        : null,
      previousResultVersion: i ? 'previous' : null,
      newEvidence: s(
        i ? '새 확인 자료가 없습니다.' : '단계별 수요 계획입니다.',
        id,
      ),
      reason: s('실행 가능성을 확인합니다.', id),
      strengthenIf: s('도입이 확인되면 강화합니다.', id),
      weakenIf: s('취소가 확인되면 낮춥니다.', id),
      topic: s('계획 확인', id),
      title: s(i ? '기존 계획 추적' : '수요 구체화', id),
      description: s('후속 계약 확인', id),
    })),
  };
  return {
    id: 'r',
    edition: 'morning',
    dataAsOf: update.cutoff,
    items: [{ companies: [{ id: 'a' }] }],
    companyOutlooks: { resultVersion: 'current', companies: [] },
    judgmentUpdate: update,
  } as unknown as BriefingResponse;
}
describe('D-BRF-01/02 judgment update', () => {
  it('keeps original links without empty body disclosures in a finished-only projection', () => {
    const r = fixture();
    for (const source of Object.values(r.judgmentUpdate!.sources!))
      delete source.fullBody;
    render(<JudgmentUpdate result={r} compact={false} />);
    expect(screen.queryByText('보존 원문 보기')).toBeNull();
    expect(
      screen.getAllByRole('link', { name: /원문 ↗/ }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        '전체 본문은 포함되지 않았습니다. 원문 링크에서 확인해 주세요.',
      ).length,
    ).toBeGreaterThan(0);
  });
  it('keeps the prior company in a distinct watch section and exposes actual prior judgment and conditions', async () => {
    const r = fixture();
    render(<JudgmentUpdate result={r} compact />);
    expect(screen.getByText('이번 핵심 기업 한눈에')).toBeTruthy();
    expect(screen.getByText('이전 기업의 미해결 조건 추적')).toBeTruthy();
    expect(screen.getByText('기존 판단 유지 · 펼치기')).toBeTruthy();
    const card = screen.getByLabelText('이전 기업 판단 갱신');
    expect(card.hasAttribute('open')).toBe(false);
    await userEvent.click(card.querySelector('summary')!);
    expect(card.hasAttribute('open')).toBe(true);
    expect(
      within(card).getByText('기존 계획의 실행을 관찰합니다.'),
    ).toBeTruthy();
    expect(
      within(card).getByText('무엇이 확인되면 강화하나요?', { exact: true }),
    ).toBeTruthy();
  });
  it('rejects another round, missing completeness fields, foreign company evidence and invented same-company change', () => {
    for (const kind of ['round', 'missing', 'foreign', 'previous']) {
      const r = fixture();
      const u = r.judgmentUpdate!;
      if (kind === 'round') u.roundId = 'other';
      if (kind === 'missing') delete u.industryChange;
      if (kind === 'foreign') u.companies![0].reason.evidenceIds = ['b'];
      if (kind === 'previous') u.companies![0].decision = 'strengthened';
      expect(validJudgment(r)).toBeNull();
    }
  });
  it('exposes preserved full-source context and labels editorial verification scope', async () => {
    const r = fixture();
    r.judgmentUpdate!.editorialReview = {
      reviewer: 'codex',
      reviewedAt: '2026-10-24T02:00:00Z',
      modelVerificationAppliesTo: 'pre_edit_draft',
      reason: '원문 대조',
    };
    render(<JudgmentUpdate result={r} compact={false} />);
    expect(
      screen.getAllByText('1단계 도입 예정. 2단계는 최종 계약 조건.').length,
    ).toBeGreaterThan(0);
    await userEvent.click(screen.getByText('해석·검토 범위'));
    expect(
      screen.getByText('원문 대조 후 편집한 검토본입니다.', { exact: false }),
    ).toBeTruthy();
  });
});
