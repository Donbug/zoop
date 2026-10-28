import { render, screen, within, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { BriefingResponse } from '@/types/briefing';
import { briefingIssueViews } from '@/util/briefingIssueView';
import IssueCentricBriefing from '@/components/briefing/IssueCentricBriefing';
const cutoff = '2026-10-22T00:20:00Z';
const s = (id = 'e1', text = '합성 실행 조건을 확인한다.') => ({
  text,
  evidenceIds: [id],
});
function fixture(): BriefingResponse {
  const company = {
    id: 'NASDAQ:AAA',
    name: '합성기업A',
    role: null,
    roleUnconfirmed: true,
    relationType: 'INVOLVES',
  };
  const item = (n: number) => ({
    eventId: 'issue-' + n,
    rank: n,
    title: '서로 다른 사건 ' + n,
    companies: [company],
    evidenceIds: ['e' + n],
    evidenceCount: 1,
    reason: '합성 선정 이유',
    summary: { status: 'unavailable', reason: '합성 사건 설명 ' + n },
    timePrecision: 'unknown',
    eventTime: null,
  });
  const business = {
    companyId: company.id,
    companyName: company.name,
    role: 'selected',
    stance: 'watch',
    sourceIds: ['e1', 'e2', 'e3'],
    previous: null,
    title: s(),
    takeaway: s(),
    newInformation: s(),
    judgment: s(),
    watch: [
      s('e1', '첫 사건 확인'),
      s('e2', '두 번째 사건 확인'),
      s('e3', '세 번째 사건 확인'),
    ],
    positive: s(),
    negative: s(),
    checks: [],
    price: { companyId: company.id, cutoff, latest: null },
  };
  const review = {
    schemaVersion: 'zoop-edition-review-v1',
    status: 'REVIEWED',
    verificationMode: 'editorial_source_review',
    roundId: 'r',
    date: '2026-10-22',
    edition: 'morning',
    cutoff,
    resultVersion: 'review',
    analysisVersion: 'base',
    headline: '합성 총평',
    summary: s(),
    marketInterpretation: s(),
    comparison: s(),
    nextSession: s(),
    previousReview: null,
    companies: [business],
    sources: Object.fromEntries(
      [1, 2, 3].map((n) => [
        'e' + n,
        {
          title: '합성 출처 ' + n,
          url: 'https://example.test/' + n,
          publishedAt: '2026-10-21T23:00:00Z',
          quote: '합성 인용',
          fullBody: '합성 원문',
        },
      ]),
    ),
  };
  const price = {
    schemaVersion: 'zoop-company-price-context-v1',
    status: 'derived',
    authorship: 'deterministic_price_observation',
    roundId: 'r',
    date: '2026-10-22',
    edition: 'morning',
    cutoff,
    resultVersion: 'prices',
    reviewVersion: 'review',
    companies: [
      {
        companyId: company.id,
        currency: 'USD',
        provider: 'toss',
        cutoff,
        status: 'unavailable',
        reason: '합성 관측 없음',
      },
    ],
  };
  const ai = {
    schemaVersion: 'zoop-ai-price-outlooks-v1',
    model: 'gpt-6-luna',
    promptVersion: 'company-outlook-v5',
    verificationMode: 'independent_model',
    status: 'PASS',
    roundId: 'r',
    date: '2026-10-22',
    edition: 'morning',
    cutoff,
    resultVersion: 'ai',
    reviewVersion: 'review',
    priceContextVersion: 'prices',
    projectionSha256: 'a'.repeat(64),
    generationRequestDigest: 'b'.repeat(64),
    verificationRequestDigest: 'c'.repeat(64),
    companies: [
      {
        companyId: company.id,
        companyName: company.name,
        role: 'selected',
        assessment: 'positive',
        impact: s('e1', '첫 사건의 사업상 의미'),
        outlook: s('e1', '첫 사건의 조건부 전망'),
        conditions: [
          s('e1', '첫 사건 확인'),
          s('e2', '두 번째 사건 확인'),
          s('e3', '세 번째 사건 확인'),
        ],
        risks: [s()],
        previous: { status: 'unavailable' },
        comparison: {
          ...s(),
          status: 'unavailable',
          previousResultVersion: null,
        },
      },
    ],
  };
  return {
    id: 'r',
    date: '2026-10-22',
    edition: 'morning',
    status: 'published',
    dataAsOf: cutoff,
    graphVersion: null,
    items: [item(1), item(2), item(3)],
    companyOutlooks: { resultVersion: 'base' },
    editionReview: review,
    companyPriceContext: price,
    aiPriceOutlooks: ai,
    marketVariables: { status: 'unavailable', reason: '합성 시장 자료 없음' },
  } as unknown as BriefingResponse;
}
afterEach(cleanup);
describe('D-BRF-01/02 issue-centered reading', () => {
  it('keeps three distinct issues from the same company and never copies its judgment to unrelated issues', () => {
    const r = fixture(),
      original = structuredClone(r),
      views = briefingIssueViews(r);
    expect(views.map((v) => v.item.eventId)).toEqual([
      'issue-1',
      'issue-2',
      'issue-3',
    ]);
    expect(views.map((v) => v.companies[0].assessment)).toEqual([
      'positive',
      undefined,
      undefined,
    ]);
    expect(
      views.map((v) => v.companies[0].conditions.map((s) => s.text)),
    ).toEqual([['첫 사건 확인'], ['두 번째 사건 확인'], ['세 번째 사건 확인']]);
    expect(r).toEqual(original);
  });
  it('keeps multiple companies inside one issue with their own source-bound judgments', () => {
    const r = fixture();
    const second = {
      ...r.items[0].companies[0],
      id: 'NASDAQ:BBB',
      name: '합성기업B',
    };
    r.items[0].companies.push(second);
    const business = structuredClone(r.editionReview!.companies[0]);
    business.companyId = second.id;
    business.companyName = second.name;
    business.price.companyId = second.id;
    r.editionReview!.companies.push(business);
    r.companyPriceContext!.companies.push({
      ...structuredClone(r.companyPriceContext!.companies[0]),
      companyId: second.id,
    });
    r.aiPriceOutlooks!.companies.push({
      ...structuredClone(r.aiPriceOutlooks!.companies[0]),
      companyId: second.id,
      companyName: second.name,
      assessment: 'negative',
    });
    const views = briefingIssueViews(r);
    expect(views[0].companies.map((c) => [c.company.id, c.assessment])).toEqual(
      [
        ['NASDAQ:AAA', 'positive'],
        ['NASDAQ:BBB', 'negative'],
      ],
    );
    expect(views[1].companies.map((c) => c.company.id)).toEqual(['NASDAQ:AAA']);
  });
  it('keeps source-bound watch conditions but never invents an impact label when AI output is absent', () => {
    const r = fixture();
    r.aiPriceOutlooks = undefined;
    const views = briefingIssueViews(r);
    expect(views[1].companies[0].conditions[0].text).toBe('두 번째 사건 확인');
    expect(
      views.every((v) => v.companies.every((c) => c.assessment === undefined)),
    ).toBe(true);
  });
  it('does not treat a statement covering two separate issues or shared evidence as one-issue impact', () => {
    const r = fixture();
    r.aiPriceOutlooks!.companies[0].impact.evidenceIds = ['e1', 'e2'];
    expect(
      briefingIssueViews(r).every(
        (v) => v.companies[0].assessment === undefined,
      ),
    ).toBe(true);
    r.aiPriceOutlooks!.companies[0].impact.evidenceIds = ['e1'];
    r.items[1].evidenceIds = ['e1'];
    expect(
      briefingIssueViews(r).every(
        (v) => v.companies[0].assessment === undefined,
      ),
    ).toBe(true);
  });
  it('rejects stale model versions and future sources rather than substituting a document sentiment or company-wide rating', () => {
    const r = fixture();
    r.aiPriceOutlooks!.priceContextVersion = 'wrong';
    expect(briefingIssueViews(r).every((v) => !v.companies[0].assessment)).toBe(
      true,
    );
    const future = fixture();
    future.editionReview!.sources.e1.publishedAt = '2026-10-23T00:00:00Z';
    expect(
      briefingIssueViews(future).every((v) => !v.companies[0].assessment),
    ).toBe(true);
  });
  it('puts indicators before issue cards and loads no issue evidence while cards are closed', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <IssueCentricBriefing result={fixture()} />
      </MemoryRouter>,
    );
    const headings = screen.getAllByRole('heading').map((x) => x.textContent);
    expect(headings).toEqual(['주요 시장 지표', '핵심 이슈']);
    expect(screen.queryByText('첫 사건 확인')).toBeNull();
    expect(screen.queryByText('오늘 확인할 사건')).toBeNull();
    expect(screen.queryByText('첫 사건의 사업상 의미')).toBeNull();
    const first = screen.getByText('서로 다른 사건 1').closest('summary')!;
    await user.click(first);
    expect(screen.getByText('첫 사건의 사업상 의미')).toBeTruthy();
    expect(
      within(first.parentElement!).getByText('오늘 확인할 사건'),
    ).toBeTruthy();
    expect(
      within(first.parentElement!).getAllByText('첫 사건 확인').length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText('첫 사건의 조건부 전망')).toBeTruthy();
    expect(screen.getAllByText('사업 영향 · 긍정 요인')).toHaveLength(1);
    const second = screen.getByText('서로 다른 사건 2').closest('summary')!;
    await user.click(second);
    expect(
      within(second.parentElement!).queryByText('첫 사건의 사업상 의미'),
    ).toBeNull();
    expect(
      within(second.parentElement!).getByText(
        '이 이슈의 사업 영향은 아직 판단하기 어렵습니다.',
      ),
    ).toBeTruthy();
    await user.click(first);
    expect(screen.queryByText('첫 사건의 사업상 의미')).toBeNull();
    expect(screen.queryByText('첫 사건 확인')).toBeNull();
  });
});

describe('issue/company previous-judgment binding', () => {
  function pair() {
    const current = fixture(),
      prior = fixture();
    prior.id = 'prior';
    prior.date = '2026-10-21';
    prior.edition = 'evening';
    prior.dataAsOf = '2026-10-21T08:30:00Z';
    for (const source of Object.values(prior.editionReview!.sources))
      source.publishedAt = '2026-10-21T07:00:00Z';
    Object.assign(prior.editionReview!, {
      roundId: prior.id,
      date: prior.date,
      edition: prior.edition,
      cutoff: prior.dataAsOf,
      resultVersion: 'prior-review',
    });
    prior.editionReview!.companies[0].price.cutoff = prior.dataAsOf;
    prior.aiPriceOutlooks = undefined;
    current.editionReview!.previousReview = {
      roundId: prior.id,
      date: prior.date,
      edition: prior.edition,
      cutoff: prior.dataAsOf,
      resultVersion: 'prior-review',
      draft: { companies: prior.editionReview!.companies },
    };
    current.editionReview!.companies[0].previous = structuredClone(
      prior.editionReview!.companies[0],
    );
    current.editionReview!.companies[0].checks =
      prior.editionReview!.companies[0].watch.map((w) => ({
        condition: w.text,
        status: 'not_observed' as const,
        observation: s(),
      }));
    const c = current.aiPriceOutlooks!.companies[0];
    c.previous = {
      status: 'available',
      kind: 'preserved_editorial_review',
      roundId: prior.id,
      resultVersion: 'prior-review',
      judgment: { judgment: prior.editionReview!.companies[0].judgment },
    };
    c.comparison = {
      ...s('e1', '같은 사건의 새 근거로 판단 갱신'),
      status: 'updated',
      previousResultVersion: 'prior-review',
    };
    return { current, prior };
  }
  it('requires the historical publication, same event and same company', () => {
    const { current, prior } = pair();
    expect(
      briefingIssueViews(current)[0].companies[0].comparison,
    ).toBeUndefined();
    expect(
      briefingIssueViews(current, current.items, prior)[0].companies[0]
        .comparison?.text,
    ).toBe('같은 사건의 새 근거로 판단 갱신');
    prior.items[0].eventId = 'another-event';
    expect(
      briefingIssueViews(current, current.items, prior)[0].companies[0]
        .comparison,
    ).toBeUndefined();
  });
  it('rejects a changed historical revision and future response', () => {
    const { current, prior } = pair();
    prior.editionReview!.resultVersion = 'revised';
    expect(
      briefingIssueViews(current, current.items, prior)[0].companies[0]
        .previous,
    ).toBeUndefined();
    prior.editionReview!.resultVersion = 'prior-review';
    prior.dataAsOf = '2026-10-23T08:30:00Z';
    expect(
      briefingIssueViews(current, current.items, prior)[0].companies[0]
        .previous,
    ).toBeUndefined();
  });
});

describe('D-BRF-01/02 new issue/company AI revision', () => {
  function fresh() {
    const value = fixture();
    value.issueIntelligence = {
      schemaVersion: 'issue-intelligence-v1',
      policyVersion: 'issue-selection-policy-v2',
      verificationMode: 'separate_model_request',
      model: 'gpt-6-luna',
      roundId: value.id,
      date: value.date,
      edition: value.edition,
      cutoff: value.dataAsOf!,
      resultVersion: 'new-revision',
      generatedAt: '2026-10-28T00:00:00Z',
      issues: value.items.map((i) => {
        const id = i.evidenceIds[0];
        const text = s(id, i.title + '의 새 판단');
        return {
          issueId: i.eventId,
          status: 'PASS' as const,
          resultVersion: 'new-' + i.eventId,
          headline: s(id, i.title),
          sources: {
            [id]: {
              evidenceId: id,
              documentId: 'doc-' + id,
              bodySha256: 'a'.repeat(64),
              title: '합성 근거',
              url: 'https://example.test/' + id,
              publishedAt: '2026-10-21T23:00:00Z',
              quote: '합성 원문',
            },
          },
          companies: i.companies.map((c) => ({
            companyId: c.id,
            sourceIds: [id],
            assessment: 'positive' as const,
            takeaway: text,
            positive: text,
            negative: text,
            newInformation: text,
            impact: text,
            outlook: text,
            conditions: [text],
            risks: [text],
            comparison: {
              ...text,
              status: 'unavailable' as const,
              previousResultVersion: null,
            },
            previous: {
              status: 'unavailable' as const,
              reason: 'same_issue_missing',
            },
          })),
        };
      }),
    };
    return value;
  }
  it('keeps three distinct judgments for the same company instead of borrowing its old copy', () => {
    const value = fresh();
    const views = briefingIssueViews(value);
    expect(views.map((v) => v.companies[0].outlook?.text)).toEqual(
      value.items.map((i) => i.title + '의 새 판단'),
    );
    expect(views.map((v) => v.companies[0].refs[0].id)).toEqual([
      'e1',
      'e2',
      'e3',
    ]);
    expect(views[0].companies[0].price).toBeDefined();
  });
  it.each([
    'future_source',
    'foreign_evidence',
    'wrong_round',
    'wrong_issue_previous',
    'unverified',
  ])('rejects %s without falling back to old company copy', (kind) => {
    const value = fresh();
    const layer = value.issueIntelligence!;
    const issue = layer.issues[0];
    const c = issue.companies[0];
    if (kind === 'future_source')
      issue.sources.e1.publishedAt = '2026-11-01T00:00:00Z';
    if (kind === 'foreign_evidence')
      c.impact = { text: '다른 사건의 판단', evidenceIds: ['e2'] };
    if (kind === 'wrong_round') layer.roundId = 'elsewhere';
    if (kind === 'wrong_issue_previous') {
      c.previous = {
        status: 'available',
        issueId: 'different',
        companyId: c.companyId,
        roundId: 'old',
        date: '2026-10-21',
        edition: 'evening',
        cutoff: '2026-10-21T08:30:00Z',
        resultVersion: 'old',
        judgment: { outlook: s() },
      };
      c.comparison = {
        ...c.comparison,
        status: 'updated',
        previousResultVersion: 'old',
      };
    }
    if (kind === 'unverified') Object.assign(issue, { status: 'WITHHELD' });
    expect(
      briefingIssueViews(value).every((v) =>
        v.companies.every((c) => !c.outlook && !c.assessment),
      ),
    ).toBe(true);
  });
});
