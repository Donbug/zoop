import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BriefingS3Impacts, {
  BriefingS3Disclosure,
} from '@/components/briefing/BriefingS3Impacts';
import {
  getBriefingItemImpacts,
  validateBriefingImpacts,
} from '@/apis/briefing/impacts';
import type { BriefingResponse, BriefingItem } from '@/types/briefing';
import type { BriefingImpacts } from '@/types/briefing/impacts';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';
const round = {
  id: 'round-1',
  dataAsOf: '2026-10-22T08:30:00Z',
  graphVersion: 'graph-1',
} as BriefingResponse;
const item = {
  eventId: 'issue:1',
  companies: [{ id: 'company-1', name: '합성 기업' }],
} as BriefingItem;
const route = '/api/v1/briefings/:round/items/:issue/impacts';
function fixture(): BriefingImpacts {
  const assessment = (id: string, side: 'positive' | 'negative') => ({
    id,
    relationId: 'rel-1',
    status: 'verified' as const,
    label: side,
    provenance: {
      sourceKind: 'synthetic' as const,
      executionMode: 'replay' as const,
      recordingKind: 'authored-test' as const,
    },
    evidence: [
      {
        id: 'ev-' + id,
        effect: side,
        quote: '합성 ' + side + ' 원문 인용',
        articleId: 'article-1',
        articleVersion: 'v1',
        title: '합성 출처',
        url: 'https://example.test/source',
        publishedAt: '2026-10-22T08:00:00Z',
        start: 0,
        end: 20,
      },
    ],
  });
  return {
    roundId: round.id,
    eventId: item.eventId,
    graphVersion: round.graphVersion,
    dataAsOf: round.dataAsOf!,
    status: 'available',
    reason: null,
    companies: [
      {
        companyId: 'company-1',
        companyName: '합성 기업',
        status: 'available',
        reason: null,
        assessments: [assessment('a', 'positive'), assessment('b', 'negative')],
      },
    ],
    metadata: {
      source: 's3_issue_impacts',
      asOf: round.dataAsOf!,
      graphVersion: round.graphVersion,
      requestId: 'test',
      partial: false,
      failures: [],
    },
  };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe('version-bound S3 issue impacts', () => {
  it('calls the pinned public endpoint and preserves conflicting rows', async () => {
    const server = createFakeServer();
    server.on('GET', route, (req) => {
      expect(req.params.issue).toBe(item.eventId);
      expect(req.query.get('graphVersion')).toBe('graph-1');
      return json(fixture());
    });
    const v = await getBriefingItemImpacts(round, item);
    expect(v.companies[0].assessments.map((a) => a.label)).toEqual([
      'positive',
      'negative',
    ]);
  });
  it('rejects a different round, issue, graph, company or future evidence', () => {
    for (const change of [
      (v: BriefingImpacts) => {
        v.roundId = 'other';
      },
      (v: BriefingImpacts) => {
        v.eventId = 'other';
      },
      (v: BriefingImpacts) => {
        v.graphVersion = 'other';
      },
      (v: BriefingImpacts) => {
        v.companies[0].companyId = 'other';
      },
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].evidence[0].publishedAt =
          '2026-10-23T00:00:00Z';
      },
    ]) {
      const v = fixture();
      change(v);
      expect(() => validateBriefingImpacts(v, round, item)).toThrow();
    }
  });
  it('rejects a label or evidence on an unverified result', () => {
    const v = fixture();
    v.companies[0].assessments[0].status = 'withheld';
    expect(() => validateBriefingImpacts(v, round, item)).toThrow();
  });
  it('renders source verdicts, quotes, links and a synthetic replay label', async () => {
    const server = createFakeServer();
    server.on('GET', route, () => json(fixture()));
    render(<BriefingS3Impacts round={round} item={item} />);
    expect(
      await screen.findByText('평가 1 · 긍정 · 인용 근거 검증'),
    ).toBeTruthy();
    expect(screen.getByText('평가 2 · 부정 · 인용 근거 검증')).toBeTruthy();
    expect(screen.getByText('합성 positive 원문 인용')).toBeTruthy();
    expect(screen.getAllByText(/합성 재생 시험 결과/)).toHaveLength(2);
    expect(
      screen
        .getAllByRole('link')
        .every((a) => a.getAttribute('href') === 'https://example.test/source'),
    ).toBe(true);
  });
  it('distinguishes missing output from an actual undetermined verdict', async () => {
    const server = createFakeServer();
    const v = fixture();
    v.status = 'unavailable';
    v.reason = 'publication_snapshot_not_recorded';
    server.on(
      'GET',
      '/api/v1/briefings/:round/items/:issue/impact-reviews',
      () => json({ ...v, reason: 'historical_assessment_not_recorded' }),
    );
    v.companies = [];
    server.on('GET', route, () => json(v));
    render(<BriefingS3Impacts round={round} item={item} />);
    expect(
      await screen.findByText(
        /이 회차에는 연결된 S3 영향 평가가 저장돼 있지 않습니다/,
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/판단 유보/)).toBeNull();
  });
  it('distinguishes a transient failure and retries with GET only', async () => {
    const server = createFakeServer();
    server.on('GET', route, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const user = userEvent.setup();
    render(<BriefingS3Impacts round={round} item={item} />);
    await screen.findByText(/평가 미저장과는 다른 조회 오류/);
    server.on('GET', route, () => json(fixture()));
    await user.click(screen.getByRole('button', { name: 'S3 평가 다시 시도' }));
    expect(await screen.findByText('합성 positive 원문 인용')).toBeTruthy();
    expect(server.requests.every((r) => r.method === 'GET')).toBe(true);
  });
  it('keeps full-view S3 reads lazy until the disclosure is opened', async () => {
    const server = createFakeServer();
    server.on('GET', route, () => json(fixture()));
    const user = userEvent.setup();
    render(<BriefingS3Disclosure round={round} item={item} />);
    expect(server.requests).toHaveLength(0);
    await user.click(screen.getByText('S3 기업별 영향·근거 보기'));
    expect(await screen.findByText('합성 positive 원문 인용')).toBeTruthy();
    expect(server.requests).toHaveLength(1);
  });
  it('shows an actual undetermined verdict as an evaluated state', async () => {
    const server = createFakeServer();
    const v = fixture();
    v.companies[0].assessments = [v.companies[0].assessments[0]];
    v.companies[0].assessments[0].label = 'undetermined';
    server.on('GET', route, () => json(v));
    render(<BriefingS3Impacts round={round} item={item} />);
    expect(await screen.findByText('판단 유보 · 인용 근거 검증')).toBeTruthy();
    expect(screen.getByText(/평가는 수행했지만/)).toBeTruthy();
    expect(screen.queryByText(/영향 평가가 저장돼 있지 않습니다/)).toBeNull();
  });
  it('discards a late reply from another issue', async () => {
    const server = createFakeServer(),
      old = deferred<Response>();
    const second = { ...item, eventId: 'issue:2' };
    server.on('GET', route, (r) =>
      r.params.issue === item.eventId
        ? old.promise
        : json({ ...fixture(), eventId: second.eventId }),
    );
    const ui = render(
      <BriefingS3Impacts key="one" round={round} item={item} />,
    );
    await waitFor(() => expect(server.requests).toHaveLength(1));
    ui.rerender(<BriefingS3Impacts key="two" round={round} item={second} />);
    await screen.findByText('합성 positive 원문 인용');
    old.resolve(json({ ...fixture(), companies: [] }));
    await waitFor(() =>
      expect(screen.queryByText(/영향 평가가 저장돼 있지 않습니다/)).toBeNull(),
    );
  });
  it('reads a later review without turning it into the original publication assessment', async () => {
    const server = createFakeServer();
    const missing = {
      ...fixture(),
      status: 'unavailable' as const,
      reason: 'publication_snapshot_not_recorded',
      companies: [],
    };
    const review = fixture();
    review.reviewContext = {
      mode: 'historical_reassessment',
      assessedAt: '2026-10-27T00:00:00Z',
      inputScope: 'preserved_quote_context',
      generationModel: 'gpt-6-luna',
      verifierModel: 'jev-1.14.0',
      resultVersion: 'a'.repeat(64),
    };
    for (const c of review.companies)
      for (const a of c.assessments)
        a.provenance = {
          sourceKind: 'collected',
          executionMode: 'live',
          recordingKind: 'provider',
        };
    server.on('GET', route, () => json(missing));
    server.on(
      'GET',
      '/api/v1/briefings/:round/items/:issue/impact-reviews',
      () => json(review),
    );
    render(<BriefingS3Impacts round={round} item={item} />);
    expect(await screen.findByText(/사후 재평가/)).toBeTruthy();
    expect(screen.getByText('평가 1 · 긍정 · 인용 근거 검증')).toBeTruthy();
    expect(
      server.calls(
        'GET',
        '/api/v1/briefings/round-1/items/issue%3A1/impact-reviews',
      ),
    ).toHaveLength(1);
  });
  it('rejects synthetic or future results labelled as historical real-news reviews', () => {
    const v = fixture();
    v.reviewContext = {
      mode: 'historical_reassessment',
      assessedAt: '2026-10-27T00:00:00Z',
      inputScope: 'preserved_quote_context',
      generationModel: 'gpt-6-luna',
      verifierModel: 'jev-1.14.0',
      resultVersion: 'a'.repeat(64),
    };
    expect(() => validateBriefingImpacts(v, round, item)).toThrow();
    for (const c of v.companies)
      for (const a of c.assessments)
        a.provenance = {
          sourceKind: 'collected',
          executionMode: 'live',
          recordingKind: 'provider',
        };
    v.reviewContext.assessedAt = '2026-10-20T00:00:00Z';
    expect(() => validateBriefingImpacts(v, round, item)).toThrow();
  });
});

describe('D-BRF-01/02 confirmed facts are separate from impact direction', () => {
  function withFacts() {
    const v = fixture();
    const a = v.companies[0].assessments[0];
    v.companies[0].assessments = [a];
    const quote = a.evidence[0];
    a.facts = [
      {
        id: quote.id,
        quote: quote.quote,
        articleId: quote.articleId,
        articleVersion: quote.articleVersion,
        start: quote.start,
        title: '원문 사실 출처',
        url: 'https://example.test/fact',
        publishedAt: '2026-10-22T08:00:00Z',
        end: Array.from(quote.quote).length,
      },
    ];
    return v;
  }
  it('keeps fact evidence visible when there is no directional citation', async () => {
    const server = createFakeServer(),
      v = withFacts();
    const a = v.companies[0].assessments[0];
    a.status = 'no-evidence';
    a.label = null;
    a.evidence = [];
    v.companies[0].status = 'unavailable';
    v.status = 'unavailable';
    server.on('GET', route, () => json(v));
    render(<BriefingS3Impacts round={round} item={item} />);
    await screen.findByText('원문에서 확인된 내용');
    await userEvent.click(screen.getByText('사실 근거 · 원문 사실 출처'));
    expect(screen.getByText('합성 positive 원문 인용')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: /원문 보기/ }).getAttribute('href'),
    ).toBe('https://example.test/fact');
    expect(
      screen.getByText(/평가 생성 단계에서 근거 인용을 제시하지 않아/),
    ).toBeTruthy();
    expect(screen.queryByText('긍정 · 인용 근거 검증')).toBeNull();
  });
  it('rejects future, fabricated-offset and effect-bearing facts', () => {
    for (const change of [
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].facts![0].publishedAt =
          '2026-10-23T00:00:00Z';
      },
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].facts![0].end = 999;
      },
      (v: BriefingImpacts) => {
        Object.assign(v.companies[0].assessments[0].facts![0], {
          effect: 'positive',
        });
      },
    ]) {
      const v = withFacts();
      change(v);
      expect(() => validateBriefingImpacts(v, round, item)).toThrow();
    }
  });
});

describe('D-BRF-01/02 offline evidence preparation', () => {
  function withPlan(): BriefingImpacts {
    const v = fixture(),
      a = v.companies[0].assessments[0],
      q = a.evidence[0];
    a.label = 'undetermined';
    a.evidence[0].effect = 'uncertain';
    v.companies[0].assessments = [a];
    a.evidencePlan = {
      status: 'prepared_not_evaluated',
      preparedAt: '2026-10-23T00:00:00Z',
      reason: '단독 문장으로는 사업 효과를 알 수 없습니다.',
      existingEvidence: [
        {
          scope: 'issuer_explanation',
          note: '회사 측 활용 목적입니다. 실제 자금조달 완료가 아닙니다.',
          source: {
            id: 'supplement',
            quote: q.quote,
            articleId: q.articleId,
            articleVersion: q.articleVersion,
            title: '보강 출처',
            url: 'https://example.test/context',
            publishedAt: '2026-10-22T08:00:00Z',
            start: 0,
            end: Array.from(q.quote).length,
          },
        },
      ],
      collectionNeeds: [
        {
          kind: 'before_cutoff_gap',
          what: '계약 조건',
          why: '당시 공개된 조건을 확인합니다.',
          preferredSource: '공시',
        },
        {
          kind: 'future_followup',
          what: '실제 집행',
          why: '미래 성과를 과거에 소급하지 않습니다.',
          preferredSource: '후속 공시',
        },
      ],
    };
    return v;
  }
  it('shows existing context and missing data without replacing the held verdict', async () => {
    const server = createFakeServer();
    server.on('GET', route, () => json(withPlan()));
    render(<BriefingS3Impacts round={round} item={item} />);
    await screen.findByText('판단 유보 · 인용 근거 검증');
    await userEvent.click(screen.getByText('보강한 근거·추가로 확인할 자료'));
    expect(screen.getByText(/AI 재평가 전/)).toBeTruthy();
    expect(screen.getByText('당시 자료 추가 확인 · 계약 조건')).toBeTruthy();
    expect(screen.getByText('향후 추적 · 실제 집행')).toBeTruthy();
    expect(server.requests.every((r) => r.method === 'GET')).toBe(true);
  });
  it('rejects a future supplemental quote or an unsupported polarity claim', () => {
    const v = withPlan();
    v.companies[0].assessments[0].evidencePlan!.existingEvidence[0].source.publishedAt =
      '2026-10-23T01:00:00Z';
    expect(() => validateBriefingImpacts(v, round, item)).toThrow();
    const altered = withPlan();
    Object.assign(altered.companies[0].assessments[0].evidencePlan!, {
      label: 'positive',
    });
    expect(() => validateBriefingImpacts(altered, round, item)).toThrow();
  });
  function withLinkedSources(): BriefingImpacts {
    const v = withPlan();
    v.companies[0].assessments[0].evidencePlan!.research = {
      status: 'editorial_sources_not_ai_evaluated',
      linkedAt: '2026-10-28T00:00:00Z',
      timeCheck: null,
      sources: [
        {
          id: 'official',
          companyId: 'company-1',
          title: '공식 계약',
          url: 'https://www.sec.gov/fixture',
          publishedAt: '2026-10-21T20:03:35Z',
          timeBasis: 'SEC_index_accepted_America_New_York',
          summary: '계약 조건을 추가 확인했습니다.',
          limitations: '실제 집행 성과는 아닙니다.',
          excerpt: 'Authored exact source excerpt.',
          transport: 'web_tool_extract',
          textSha256: 'a'.repeat(64),
          historicalVersionVerified: false,
        },
      ],
    };
    return v;
  }
  function withRecheck(label: 'positive' | 'undetermined'): BriefingImpacts {
    const v = withLinkedSources(),
      a = v.companies[0].assessments[0],
      s = a.evidencePlan!.research!.sources[0];
    a.provenance = {
      sourceKind: 'collected',
      executionMode: 'live',
      recordingKind: 'provider',
    };
    v.reviewContext = {
      mode: 'historical_reassessment',
      assessedAt: '2026-10-28T00:00:00Z',
      inputScope: 'preserved_quote_context',
      generationModel: 'gpt-6-luna',
      verifierModel: 'jev-1.14.0',
      resultVersion: 'a'.repeat(64),
    };
    a.supplementalReview = {
      mode: 'supplemental_historical_simulation',
      assessedAt: '2026-10-28T01:00:00Z',
      previousLabel: 'undetermined',
      label,
      targetVerdict: 'supported',
      verifierModel: 'jev-1.14.0',
      summary:
        label === 'positive'
          ? '공식 발표의 효율 개선 기대를 추가 확인했습니다.'
          : '계약 조건은 확인됐지만 사업상 효과는 확정하지 못했습니다.',
      limitations: '계획과 계약 조건이며 실제 성과나 주가 예측은 아닙니다.',
      confirmedFacts: [
        {
          text: '회사의 조건부 계획을 확인했습니다.',
          evidenceIds: ['recheck-1'],
        },
      ],
      evidence: [
        {
          id: 'recheck-1',
          effect: label === 'positive' ? 'positive' : 'uncertain',
          quote: s.excerpt,
          articleId: 'supplement-' + s.id,
          articleVersion: 'sha256-' + s.textSha256,
          title: s.title,
          url: s.url,
          publishedAt: s.publishedAt,
          start: 0,
          end: Array.from(s.excerpt).length,
        },
      ],
      resultVersion: 'b'.repeat(64),
      historicalVersionVerified: false,
    };
    return v;
  }
  it.each(['positive', 'undetermined'] as const)(
    'shows latest %s reasons and citations without overwriting original review',
    async (label) => {
      const v = withRecheck(label);
      validateBriefingImpacts(v, round, item);
      const server = createFakeServer();
      server.on('GET', route, () => json(v));
      render(<BriefingS3Impacts round={round} item={item} />);
      await screen.findByText(
        label === 'positive'
          ? '긍정 · 공식 근거 보강 후 재검증'
          : '판단 유보 · 공식 근거 보강 후 재검증',
      );
      expect(
        screen.getByText('이전 검증 기록 · 판단 유보 · 인용 근거 검증'),
      ).toBeTruthy();
      expect(
        screen.getByText('회사의 조건부 계획을 확인했습니다.'),
      ).toBeTruthy();
      expect(
        screen.getByText(
          v.companies[0].assessments[0].supplementalReview!.summary,
        ),
      ).toBeTruthy();
      await userEvent.click(screen.getByText('재검증에 사용한 인용·출처 1건'));
      expect(
        screen
          .getAllByRole('link', { name: /공식 계약/ })
          .some(
            (a) => a.getAttribute('href') === 'https://www.sec.gov/fixture',
          ),
      ).toBe(true);
      expect(server.requests.every((r) => r.method === 'GET')).toBe(true);
    },
  );
  it('rejects forged updated labels, future quotes, missing receipts identity or unbound explanations', () => {
    for (const mutate of [
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].supplementalReview!.label = 'negative';
      },
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].supplementalReview!.evidence[0].publishedAt =
          '2026-10-23T00:00:00Z';
      },
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].supplementalReview!.resultVersion =
          'unknown';
      },
      (v: BriefingImpacts) => {
        v.companies[0].assessments[0].supplementalReview!.confirmedFacts[0].evidenceIds =
          ['foreign'];
      },
    ]) {
      const v = withRecheck('positive');
      mutate(v);
      expect(() => validateBriefingImpacts(v, round, item)).toThrow();
    }
  });
  it('shows a source clock disagreement before the preserved price interpretation', async () => {
    const v = withLinkedSources();
    const r = v.companies[0].assessments[0].evidencePlan!.research!;
    r.sources = [];
    r.timeCheck = {
      status: 'publisher_time_disagreement',
      summary: '출처 시각이 8시간 다릅니다.',
      limitation: '최초 공개 시각은 미확정입니다.',
      storedPublishedAt: '2026-10-21T02:33:00Z',
      distributionPublishedAt: '2026-10-21T10:33:00Z',
      storedUrl: 'https://source.test/news',
      distributionUrl: 'https://www.globenewswire.com/news',
    };
    const server = createFakeServer();
    server.on('GET', route, () => json(v));
    render(<BriefingS3Impacts round={round} item={item} />);
    await screen.findByText('원문 발행 시각 확인 필요');
    expect(screen.getByText('출처 시각이 8시간 다릅니다.')).toBeTruthy();
    expect(
      screen.getByText(/기존 뉴스·가격 시점 설명은 저장 당시 기준/),
    ).toBeTruthy();
    expect(screen.getByText('판단 유보 · 인용 근거 검증')).toBeTruthy();
    expect(screen.queryByText('새로 연결한 공식 자료')).toBeNull();
  });
  it('links later official references while keeping the held assessment and original evidence', async () => {
    const server = createFakeServer();
    server.on('GET', route, () => json(withLinkedSources()));
    render(<BriefingS3Impacts round={round} item={item} />);
    await screen.findByText('판단 유보 · 인용 근거 검증');
    await userEvent.click(screen.getByText('보강한 근거·추가로 확인할 자료'));
    expect(screen.getByText('계약 조건을 추가 확인했습니다.')).toBeTruthy();
    await userEvent.click(screen.getByText('공식 출처 · 공식 계약'));
    expect(screen.getByText('공식 원문 보기 ↗').getAttribute('href')).toBe(
      'https://www.sec.gov/fixture',
    );
    expect(screen.getByText(/SEC 접수 시각/)).toBeTruthy();
    expect(screen.getByText('판단 유보 · 인용 근거 검증')).toBeTruthy();
    expect(server.requests.every((r) => r.method === 'GET')).toBe(true);
  });
  it('rejects foreign, future, fake-verification, unsafe and effect-bearing supplemental sources', () => {
    for (const mutate of [
      (
        s: NonNullable<
          NonNullable<
            ReturnType<
              typeof withLinkedSources
            >['companies'][number]['assessments'][number]['evidencePlan']
          >['research']
        >['sources'][number],
      ) => {
        s.companyId = 'foreign';
      },
      (s: { publishedAt: string }) => {
        s.publishedAt = '2026-10-23T00:00:00Z';
      },
      (s: object) => {
        Object.assign(s, { effect: 'positive' });
      },
      (s: object) => {
        Object.assign(s, { historicalVersionVerified: true });
      },
      (s: { url: string }) => {
        s.url = 'https://www.sec.gov@evil.test/';
      },
    ]) {
      const v = withLinkedSources();
      mutate(v.companies[0].assessments[0].evidencePlan!.research!.sources[0]);
      expect(() => validateBriefingImpacts(v, round, item)).toThrow();
    }
  });
});
