import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { BriefingResponse } from '@/types/briefing';
import PriorIssueFollowUps from '@/components/briefing/PriorIssueFollowUps';
import { validIssueFollowUps } from '@/util/issueFollowUps';

function fixture(): BriefingResponse {
  return {
    id: 'now',
    status: 'published',
    scheduledAt: '2026-10-23T09:20:00+09:00',
    publishedAt: null,
    generatedAt: null,
    graphVersion: null,
    marketSummary: { status: 'unavailable', reason: 'Synthetic fixture' },
    marketVariables: { status: 'unavailable', reason: 'Synthetic fixture' },
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'synthetic',
      asOf: '2026-10-23T09:20:00+09:00',
      graphVersion: null,
      requestId: 'test',
      partial: false,
      failures: [],
    },
    date: '2026-10-23',
    edition: 'morning',
    dataAsOf: '2026-10-23T09:20:00+09:00',
    items: [],
    issueIntelligence: {
      schemaVersion: 'issue-intelligence-v1',
      policyVersion: 'issue-selection-policy-v2',
      verificationMode: 'separate_model_request',
      model: 'gpt-6-luna',
      roundId: 'now',
      date: '2026-10-23',
      edition: 'morning',
      cutoff: '2026-10-23T09:20:00+09:00',
      resultVersion: 'now-v1',
      generatedAt: '2026-10-23T09:20:00+09:00',
      issues: [],
    },
    issueFollowUps: {
      schemaVersion: 'issue-followups-v1',
      roundId: 'now',
      baseResultVersion: 'now-v1',
      cutoff: '2026-10-23T09:20:00+09:00',
      scope: 'provided_verified_rounds',
      reviewedRounds: [
        {
          roundId: 'old',
          date: '2026-10-22',
          edition: 'evening',
          cutoff: '2026-10-22T17:30:00+09:00',
          resultVersion: 'old-v1',
        },
      ],
      entries: [1, 2].map((n) => ({
        issueId: 'old-event-' + n,
        companyId: 'C',
        companyName: '합성 기업',
        title: '서로 다른 사건 ' + n,
        status: 'outcome_unverified',
        origin: {
          roundId: 'old',
          date: '2026-10-22',
          edition: 'evening',
          cutoff: '2026-10-22T17:30:00+09:00',
          resultVersion: 'old-v1',
        },
        condition: { text: '확인 조건 ' + n, evidenceIds: ['e' + n] },
        sources: [
          {
            evidenceId: 'e' + n,
            documentId: 'doc' + n,
            bodySha256: 'a'.repeat(64),
            title: '합성 출처 ' + n,
            url: 'https://example.test/' + n,
            quote: '합성 인용 ' + n,
            publishedAt: '2026-10-22T08:00:00+09:00',
          },
        ],
      })),
    },
  };
}
afterEach(cleanup);
describe('previous issue follow-ups', () => {
  it('accepts equal cutoffs expressed in UTC and KST', () => {
    const result = fixture();
    result.issueFollowUps!.cutoff = '2026-10-23T00:20:00Z';
    expect(validIssueFollowUps(result)?.entries).toHaveLength(2);
  });
  it('keeps distinct events of one company collapsed, with original condition and source', async () => {
    const result = fixture();
    const before = JSON.stringify(result);
    render(
      <MemoryRouter>
        <PriorIssueFollowUps result={result} />
      </MemoryRouter>,
    );
    expect(screen.queryByText('확인 조건 1')).toBeNull();
    await userEvent.click(
      screen.getByText('이전 이슈에서 이어 볼 확인사항 · 2건'),
    );
    expect(screen.getByText('확인 조건 1')).toBeTruthy();
    expect(screen.getByText('확인 조건 2')).toBeTruthy();
    expect(screen.getAllByText('합성 기업 · 결과 미확인')).toHaveLength(2);
    const first = screen.getByRole('region', {
      name: '서로 다른 사건 1 · 합성 기업',
    });
    await userEvent.click(within(first).getByText('당시 근거 1건'));
    expect(within(first).getByText('합성 인용 1')).toBeTruthy();
    expect(
      within(first)
        .getByRole('link', { name: /합성 출처/ })
        .getAttribute('href'),
    ).toBe('https://example.test/1');
    expect(
      within(first)
        .getByRole('link', { name: '이전 브리핑' })
        .getAttribute('href'),
    ).toBe('/briefing?date=2026-10-22&edition=evening&reading=compact');
    expect(JSON.stringify(result)).toBe(before);
  });
  it('does not add empty sections to legacy or first rounds', () => {
    const result = fixture();
    delete result.issueFollowUps;
    const { rerender, container } = render(
      <PriorIssueFollowUps result={result} />,
    );
    expect(container.innerHTML).toBe('');
    result.issueFollowUps = {
      ...fixture().issueFollowUps!,
      entries: [],
      reviewedRounds: [],
    };
    rerender(<PriorIssueFollowUps result={result} />);
    expect(container.innerHTML).toBe('');
  });
  it.each([
    'version',
    'future',
    'duplicate',
    'foreign-source',
    'future-source',
    'status',
    'origin',
    'current-pair',
  ])('rejects %s binding rather than claiming an outcome', (kind) => {
    const result = fixture();
    const value = result.issueFollowUps!;
    if (kind === 'version') value.baseResultVersion = 'other';
    if (kind === 'future')
      value.reviewedRounds[0].cutoff = '2026-11-01T09:00:00Z';
    if (kind === 'duplicate')
      value.entries.push(structuredClone(value.entries[0]));
    if (kind === 'foreign-source')
      value.entries[0].condition.evidenceIds = ['foreign'];
    if (kind === 'future-source')
      value.entries[0].sources[0].publishedAt = '2026-11-01T09:00:00Z';
    if (kind === 'status')
      Object.assign(value.entries[0], { status: 'completed' });
    if (kind === 'origin') value.entries[0].origin.resultVersion = 'different';
    if (kind === 'current-pair') value.reviewedRounds[0].roundId = result.id;
    expect(validIssueFollowUps(result)).toBeNull();
    render(<PriorIssueFollowUps result={result} />);
    expect(screen.getByRole('alert').textContent).toContain(
      '이전 확인사항의 회차·근거 연결',
    );
  });
  it('does not activate unsafe source URLs', async () => {
    const result = fixture();
    result.issueFollowUps!.entries[0].sources[0].url = 'javascript:alert(1)';
    render(
      <MemoryRouter>
        <PriorIssueFollowUps result={result} />
      </MemoryRouter>,
    );
    await userEvent.click(
      screen.getByText('이전 이슈에서 이어 볼 확인사항 · 2건'),
    );
    expect(screen.queryByRole('link', { name: /합성 출처 1/ })).toBeNull();
  });
});

function reviewedFixture() {
  const result = fixture();
  result.issueFollowUpReview = {
    schemaVersion: 'issue-followup-review-v1',
    method: 'recorded_editorial_review',
    roundId: result.id,
    baseResultVersion: 'now-v1',
    cutoff: result.dataAsOf!,
    reviewedAt: '2026-10-29T09:00:00+09:00',
    entries: result.issueFollowUps!.entries.map((e, n) => ({
      ref: {
        issueId: e.issueId,
        companyId: e.companyId,
        origin: e.origin,
        condition: e.condition,
      },
      status: n === 0 ? 'fulfilled' : 'insufficient_evidence',
      summary: '검토 결론 ' + n,
      facts: [{ text: '확인된 사실 ' + n, sourceIds: ['s'] }],
      requirements: [
        {
          text: '필요한 실행 증거 ' + n,
          observation: n === 0 ? 'completed' : 'unverified',
          sourceIds: n === 0 ? ['s'] : [],
        },
      ],
      sources: [
        {
          id: 's',
          documentId: 'saved-doc',
          bodySha256: 'b'.repeat(64),
          title: '후속 출처',
          url: 'https://example.test/followup',
          publishedAt: '2026-10-22T23:00:00+09:00',
          quote: '합성 실행 근거',
          start: 0,
          end: 8,
          relation: 'same_event',
          kind: n === 0 ? 'completed_action' : 'plan',
          period: 'after_condition',
        },
      ],
    })),
  };
  return result;
}

describe('saved evidence follow-up outcomes', () => {
  it('separates completion from missing data and keeps original conditions', async () => {
    const result = reviewedFixture();
    const before = JSON.stringify(result);
    render(
      <MemoryRouter>
        <PriorIssueFollowUps result={result} />
      </MemoryRouter>,
    );
    await userEvent.click(
      screen.getByText('이전 이슈에서 이어 볼 확인사항 · 2건'),
    );
    expect(screen.getByText(/조건 충족 확인 1건 · 자료 부족 1건/)).toBeTruthy();
    expect(screen.getByText('✓ 조건 충족 확인')).toBeTruthy();
    expect(screen.getByText('○ 자료 부족 · 판단 보류')).toBeTruthy();
    expect(screen.getAllByText('확인된 사실 1')).toHaveLength(2);
    expect(screen.getByText('필요한 실행 증거 1')).toBeTruthy();
    expect(screen.getByText('확인 조건 1')).toBeTruthy();
    expect(screen.getAllByText('당시 근거 1건')).toHaveLength(2);
    await userEvent.click(screen.getAllByText('대조한 근거 1건')[0]);
    expect(
      screen
        .getAllByRole('link', { name: '후속 출처 ↗' })[0]
        .getAttribute('href'),
    ).toBe('https://example.test/followup');
    expect(JSON.stringify(result)).toBe(before);
  });
  it.each([
    'future',
    'condition',
    'origin',
    'version',
    'plan',
    'other-event',
    'old-source',
    'foreign-fact',
    'missing',
    'false-completion',
    'invalid-status',
  ])('rejects %s without losing original conditions', async (kind) => {
    const result = reviewedFixture();
    const review = result.issueFollowUpReview!;
    // Avoid mutating original condition through test fixture reference aliases.
    review.entries = structuredClone(review.entries);
    const e = review.entries[0];
    const s = e.sources[0];
    if (kind === 'future') s.publishedAt = '2026-11-01T00:00:00Z';
    if (kind === 'condition') e.ref.condition.text = 'other condition';
    if (kind === 'origin') e.ref.origin.cutoff = '2026-10-21T00:00:00Z';
    if (kind === 'version') review.baseResultVersion = 'other';
    if (kind === 'plan') s.kind = 'plan';
    if (kind === 'other-event') s.relation = 'related_event';
    if (kind === 'old-source') {
      s.publishedAt = '2026-10-22T01:00:00Z';
      s.period = 'prior_background';
    }
    if (kind === 'foreign-fact') e.facts[0].sourceIds = ['foreign'];
    if (kind === 'missing') review.entries.pop();
    if (kind === 'false-completion') review.entries[1].status = 'fulfilled';
    if (kind === 'invalid-status') Object.assign(e, { status: 'failed' });
    render(
      <MemoryRouter>
        <PriorIssueFollowUps result={result} />
      </MemoryRouter>,
    );
    await userEvent.click(
      screen.getByText('이전 이슈에서 이어 볼 확인사항 · 2건'),
    );
    expect(screen.getByRole('alert').textContent).toContain(
      '후속 검토의 회차·근거 연결',
    );
    expect(screen.queryByText('✓ 조건 충족 확인')).toBeNull();
    expect(screen.getByText('확인 조건 1')).toBeTruthy();
  });
});
