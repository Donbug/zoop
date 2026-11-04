import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import PersonalPriorityIssues from '@/components/briefing/PersonalPriorityIssues';
import IssueCentricBriefing from '@/components/briefing/IssueCentricBriefing';
import {
  personalPriorityOf,
  type PersonalPriority,
} from '@/util/briefingPersonalPriority';
import type { BriefingResponse } from '@/types/briefing';

function priority(): PersonalPriority {
  return {
    schemaVersion: 'personal-relative-priority-view-v1',
    roundId: 'round',
    cutoff: '2026-11-02T17:30:00+09:00',
    resultVersion: 'new-version',
    companyIds: ['one'],
    candidateCount: 1,
    status: 'available',
    items: [
      {
        issueId: 'issue',
        kind: 'new_issue',
        title: '합성 제품 내부 시험 소식',
        reason: '선택 종목과 직접 관련된 변화입니다.',
        originRoundId: 'round',
        originCutoff: '2026-11-02T17:30:00+09:00',
        connections: [
          {
            companyId: 'one',
            name: '합성기업',
            reason: '해당 제품의 제조사입니다.',
          },
        ],
        sources: [
          {
            evidenceId: 'e',
            quote: '제품을 내부에서 시험 중이며 출시는 결정되지 않았다.',
            publishedAt: '2026-11-02T11:00:00+09:00',
            url: 'https://example.test/article',
          },
        ],
        priorAnalysis: [],
        price: null,
      },
    ],
  };
}
function response(value: PersonalPriority) {
  return {
    id: value.roundId,
    dataAsOf: value.cutoff,
    date: '2026-11-02',
    edition: 'evening',
    status: 'published',
    items: [],
    corrections: [],
    personalPriority: value,
    marketSummary: { status: 'unavailable', reason: '없음' },
  } as unknown as BriefingResponse;
}
afterEach(() => vi.unstubAllEnvs());

test('personal source preserves day precision and rejects an observation after cutoff', async () => {
  const value = priority();
  Object.assign(value.items[0].sources[0], {
    publishedAt: null,
    publishedDate: '2026-11-02',
    availableAt: '2026-11-02T11:00:00+09:00',
    eligibilityBasis: 'first_observed',
  });
  expect(personalPriorityOf(response(value))).not.toBeNull();
  render(<PersonalPriorityIssues value={value} />);
  await userEvent.setup().click(screen.getByText('합성 제품 내부 시험 소식'));
  expect(screen.getByText(/게시일 2026-11-02 · 최초 수집/)).not.toBeNull();
  value.items[0].sources[0].availableAt = '2026-11-03T00:00:00Z';
  expect(personalPriorityOf(response(value))).toBeNull();
});

test('D-BRF-02 renders a personal issue even when common-grade selection had no items', () => {
  vi.stubEnv('VITE_BRIEFING_LOCAL_REVIEW', '0');
  render(
    <MemoryRouter>
      <IssueCentricBriefing
        result={response(priority())}
        selectionDetails={{}}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText('합성 제품 내부 시험 소식')).not.toBeNull();
  expect(
    screen.queryByText(/현재 제공 가능한 적격 핵심 이슈가 없습니다/),
  ).toBeNull();
  expect(screen.getByText('새 소식')).not.toBeNull();
});
test.each(['related_reference', 'previous_issue'] as const)(
  'keeps %s distinct from new news',
  async (kind) => {
    const value = priority();
    value.items[0].kind = kind;
    render(<PersonalPriorityIssues value={value} />);
    await userEvent.setup().click(screen.getByText('합성 제품 내부 시험 소식'));
    expect(screen.queryByText('새 소식')).toBeNull();
    expect(
      screen.getByText(
        kind === 'previous_issue' ? '계속 확인할 이슈' : '기존 이슈 관련 소식',
      ),
    ).not.toBeNull();
    expect(
      screen.getByText('제품을 내부에서 시험 중이며 출시는 결정되지 않았다.'),
    ).not.toBeNull();
    expect(
      screen.getByRole('link', { name: /원문 보기/ }).getAttribute('href'),
    ).toBe('https://example.test/article');
  },
);
test('does not invent positive and negative analysis for a verified fact', () => {
  render(<PersonalPriorityIssues value={priority()} />);
  expect(screen.queryByText('긍정 가능성')).toBeNull();
  expect(screen.getByText(/새로운 심층 분석은 아직 없습니다/)).not.toBeNull();
});
test('bound response validation rejects a foreign round, company, future source and excess cards', () => {
  expect(personalPriorityOf(response(priority()))).not.toBeNull();
  const wrong = priority();
  wrong.roundId = 'different';
  const data = response(wrong);
  data.id = 'round';
  expect(personalPriorityOf(data)).toBeNull();
  const company = priority();
  company.items[0].connections[0].companyId = 'other';
  expect(personalPriorityOf(response(company))).toBeNull();
  const future = priority();
  future.items[0].sources[0].publishedAt = '2026-11-03T00:00:00+09:00';
  expect(personalPriorityOf(response(future))).toBeNull();
  const many = priority();
  many.items = Array.from({ length: 4 }, (_, i) => ({
    ...many.items[0],
    issueId: `i${i}`,
  }));
  expect(personalPriorityOf(response(many))).toBeNull();
});
test('empty evidence remains an explicit collection state instead of a fake issue', () => {
  const value = priority();
  value.items = [];
  value.status = 'collection_insufficient';
  render(<PersonalPriorityIssues value={value} />);
  expect(screen.getByText(/확인 가능한 자료를 확보/)).not.toBeNull();
});

function withAnalysis(): PersonalPriority {
  const value = priority();
  value.items[0].aiAnalyses = [
    {
      companyId: 'one',
      companyName: '합성기업',
      roundId: value.roundId,
      cutoff: value.cutoff,
      resultVersion: 'verified-ai-version',
      verificationMode: 'separate_request_same_model',
      direction: 'watch',
      keyPoint: '확인된 사실과 해석을 구분합니다.',
      confirmedFact: '내부 시험이 보도됐습니다.',
      businessImpact:
        '제품 선택지가 늘어날 가능성이 있지만 출시 결정은 확인되지 않았습니다.',
      forMyStocks: '선택한 기업의 제품 계획을 확인할 이슈입니다.',
      outlook:
        '출시 대상과 일정이 공식 확인되면 제품 경쟁력 판단을 갱신합니다.',
      positive: null,
      negative: null,
      priceObservation: null,
      previousChange: {
        status: 'unavailable',
        text: '같은 사건의 이전 판단이 없습니다.',
      },
      nextCheck: '공식 출시 대상과 일정이 확인되는지 봅니다.',
      evidenceIds: ['e'],
    },
  ];
  return value;
}

test('verified personal AI impact, conditional outlook and next check lead the detail', async () => {
  const value = withAnalysis();
  render(<PersonalPriorityIssues value={value} evening />);
  await userEvent.setup().click(screen.getByText('합성 제품 내부 시험 소식'));
  expect(screen.getByText('다음 거래일 전망')).not.toBeNull();
  expect(
    screen.getByText(value.items[0].aiAnalyses![0].businessImpact),
  ).not.toBeNull();
  expect(
    screen.getByText(value.items[0].aiAnalyses![0].outlook),
  ).not.toBeNull();
  expect(screen.getByText('아침 판단 점검')).not.toBeNull();
  expect(
    screen.getByText(value.items[0].aiAnalyses![0].nextCheck),
  ).not.toBeNull();
  expect(screen.queryByText(/새로운 심층 분석은 아직 없습니다/)).toBeNull();
  expect(screen.queryByText('긍정 가능성')).toBeNull();
});

test('AI result cannot cross a round, company or issue evidence boundary', () => {
  const value = withAnalysis();
  expect(personalPriorityOf(response(value))).not.toBeNull();
  value.items[0].aiAnalyses![0].roundId = 'another-round';
  expect(personalPriorityOf(response(value))).toBeNull();
  value.items[0].aiAnalyses![0].roundId = value.roundId;
  value.items[0].aiAnalyses![0].evidenceIds = ['evidence-of-other-issue'];
  expect(personalPriorityOf(response(value))).toBeNull();
});

test('D-BRF-02 record review explains gaps without rewriting the AI direction', async () => {
  const value = withAnalysis();
  const analysis = value.items[0].aiAnalyses![0];
  analysis.recordReview = {
    type: 'local_record_review',
    sourceResultVersion: analysis.resultVersion,
    knownFactor: '시험 보도는 확인됐습니다.',
    missingData: '공식 출시와 실제 판매는 아직 확인되지 않았습니다.',
    nextData: '출시 공지와 판매 자료를 확인합니다.',
    evidenceIds: ['e'],
  };
  expect(personalPriorityOf(response(value))).not.toBeNull();
  render(<PersonalPriorityIssues value={value} evening />);
  await userEvent.setup().click(screen.getByText('합성 제품 내부 시험 소식'));
  await userEvent
    .setup()
    .click(screen.getByText('판단 유보 이유 · 확인된 내용과 부족한 자료'));
  expect(screen.getByText(analysis.recordReview.missingData)).not.toBeNull();
  expect(analysis.direction).toBe('watch');
  expect(screen.queryByText('긍정 가능성')).toBeNull();
});

test('record review cannot cross a model version or evidence boundary', () => {
  const value = withAnalysis();
  const analysis = value.items[0].aiAnalyses![0];
  analysis.recordReview = {
    type: 'local_record_review',
    sourceResultVersion: 'another-version',
    knownFactor: '확인 내용',
    missingData: '부족한 자료',
    nextData: '다음 자료',
    evidenceIds: ['e'],
  };
  expect(personalPriorityOf(response(value))).toBeNull();
  analysis.recordReview.sourceResultVersion = analysis.resultVersion;
  analysis.recordReview.evidenceIds = ['unrelated-source'];
  expect(personalPriorityOf(response(value))).toBeNull();
});

test('an audited absence statement is preserved without a positive factor badge', async () => {
  const value = withAnalysis();
  const analysis = value.items[0].aiAnalyses![0];
  analysis.positive = '원문에서 긍정 요인은 특정할 수 없습니다.';
  analysis.recordReview = {
    type: 'local_record_review',
    sourceResultVersion: analysis.resultVersion,
    knownFactor: '시험 보도 확인',
    missingData: '출시 미확인',
    nextData: '공식 발표 확인',
    evidenceIds: ['e'],
    nonFactorFields: ['positive'],
  };
  render(<PersonalPriorityIssues value={value} />);
  await userEvent.setup().click(screen.getByText('합성 제품 내부 시험 소식'));
  expect(screen.queryByText('긍정 가능성')).toBeNull();
  await userEvent.setup().click(screen.getByText('확인 사실·핵심 판단'));
  expect(screen.getByText(/기존 긍정 항목 문안/)).not.toBeNull();
  expect(analysis.positive).toBe('원문에서 긍정 요인은 특정할 수 없습니다.');
});

function withV3Comparison(): PersonalPriority {
  const value = withAnalysis();
  const analysis = value.items[0].aiAnalyses![0];
  analysis.direction = 'negative';
  analysis.judgmentBasis = {
    promptVersion: 'personal-impact-relative-v3',
    directionReason: '조건부 사업 위험과 실제 손실 규모는 구분합니다.',
    confidence: 'limited',
    effectSizeStatus: 'unquantified',
  };
  analysis.comparison = {
    status: 'same_issue_company',
    baseline: {
      issueId: value.items[0].issueId,
      companyId: analysis.companyId,
      roundId: value.roundId,
      cutoff: value.cutoff,
      resultVersion: 'stored-baseline-v2',
      direction: 'watch',
      businessImpact: '기존 문안의 사업 해석',
      outlook: '기존 문안의 확인 조건',
    },
  };
  return value;
}

test('v3 displays business direction, confidence, unknown scale and the immutable baseline', async () => {
  const value = withV3Comparison();
  expect(personalPriorityOf(response(value))).not.toBeNull();
  render(<PersonalPriorityIssues value={value} />);
  await userEvent.setup().click(screen.getByText('합성 제품 내부 시험 소식'));
  expect(screen.getByText(/판단 확신 제한적/)).not.toBeNull();
  expect(screen.getByText(/효과 규모 미확인/)).not.toBeNull();
  await userEvent.setup().click(screen.getByText('기존 브리핑과 비교'));
  expect(screen.getByText('기존 문안의 사업 해석')).not.toBeNull();
  expect(screen.getByText(/새 뉴스로 인한 판단 변화와 구분/)).not.toBeNull();
});

test('v3 comparison cannot substitute another event or cutoff, or use the current result as baseline', () => {
  const value = withV3Comparison();
  const analysis = value.items[0].aiAnalyses![0];
  const baseline = analysis.comparison!.baseline!;
  baseline.issueId = 'another-event';
  expect(personalPriorityOf(response(value))).toBeNull();
  baseline.issueId = value.items[0].issueId;
  baseline.cutoff = '2026-11-03T17:30:00+09:00';
  expect(personalPriorityOf(response(value))).toBeNull();
  baseline.cutoff = value.cutoff;
  baseline.resultVersion = analysis.resultVersion;
  expect(personalPriorityOf(response(value))).toBeNull();
  analysis.comparison = { status: 'newly_selected', baseline: null };
  expect(personalPriorityOf(response(value))).not.toBeNull();
});

test('preserves the pre-selection summary separately from personal issue judgments', () => {
  const result = response(priority());
  result.marketSummary = {
    text: '합성 보관 요약: 개인 종목 재선정 이전의 범위입니다.',
    resultVersion: 'preserved-summary',
    evidenceIds: ['e'],
    generatedAt: result.dataAsOf!,
  };
  const view = render(
    <MemoryRouter>
      <IssueCentricBriefing result={result} compact selectionDetails={{}} />
    </MemoryRouter>,
  );
  const details = screen
    .getByText('기존 기준의 회차 요약·전망 (보존)')
    .closest('details')!;
  expect(details.open).toBe(false);
  expect(screen.getByText(result.marketSummary.text)).toBeTruthy();
  expect(screen.getByText('합성 제품 내부 시험 소식')).toBeTruthy();
  view.rerender(
    <MemoryRouter>
      <IssueCentricBriefing
        result={result}
        compact={false}
        selectionDetails={{}}
      />
    </MemoryRouter>,
  );
  expect(details.open).toBe(true);
});

test('accepts the same personal cutoff when serialized in UTC', () => {
  const v = priority();
  const result = response(v);
  result.dataAsOf = '2026-11-02T08:30:00Z';
  expect(personalPriorityOf(result)).toBe(v);
});
