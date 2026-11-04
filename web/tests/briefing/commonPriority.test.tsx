import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import IssueCentricBriefing from '@/components/briefing/IssueCentricBriefing';
import CommonPriorityIssues from '@/components/briefing/CommonPriorityIssues';
import {
  commonPriorityOf,
  type CommonPriority,
} from '@/util/briefingCommonPriority';
import type { BriefingResponse } from '@/types/briefing';

function value(): CommonPriority {
  return {
    schemaVersion: 'common-relative-priority-view-v1',
    roundId: 'round',
    cutoff: '2026-10-30T09:20:00+09:00',
    resultVersion: 'new-selection',
    minimumIssues: 2,
    minimumShortfall: 0,
    candidateCount: 8,
    status: 'available',
    items: ['a', 'b'].map((id, index) => ({
      issueId: id,
      kind: index ? 'previous_issue' : 'relative_issue',
      importance: 1,
      title: `합성 이슈 ${id}`,
      reason: '검증된 낮은 중요도 소식',
      whyNow: '후보 내에서 우선 확인합니다.',
      originRoundId: 'prior',
      originCutoff: '2026-10-29T17:30:00+09:00',
      companies: [
        {
          companyId: 'company',
          name: '합성기업',
          reason: '원문에 명시된 당사자',
        },
      ],
      sources: [
        {
          evidenceId: id,
          quote: '확인된 원문 사실',
          url: 'https://example.test/article',
          publishedAt: '2026-10-29T17:00:00+09:00',
        },
      ],
      prices: [],
    })),
  };
}
function response(v: CommonPriority) {
  return {
    id: v.roundId,
    date: '2026-10-30',
    edition: 'morning',
    dataAsOf: v.cutoff,
    status: 'published',
    items: [],
    corrections: [],
    emptyReason: 'no_issues_in_window',
    marketSummary: { status: 'unavailable', reason: '합성 테스트' },
    commonPriority: v,
  } as unknown as BriefingResponse;
}

test('D-BRF-01 renders two verified relative common issues even if the old publication was empty', () => {
  render(
    <MemoryRouter>
      <IssueCentricBriefing result={response(value())} />
    </MemoryRouter>,
  );
  expect(screen.getByText('합성 이슈 a')).not.toBeNull();
  expect(screen.getByText('합성 이슈 b')).not.toBeNull();
  expect(
    screen.queryByText(
      '이 회차에 새로 선정된 핵심 이슈가 없습니다. 복기·수집 상태는 위 안내를 확인하세요.',
    ),
  ).toBeNull();
});

test('below-threshold and prior issues keep their labels, quotes and links', async () => {
  render(<CommonPriorityIssues value={value()} />);
  expect(screen.getByText('후보 내 우선 소식')).not.toBeNull();
  expect(screen.getByText('이전 이슈 추적')).not.toBeNull();
  await userEvent.setup().click(screen.getByText('합성 이슈 a'));
  expect(screen.getAllByText('확인된 원문 사실')).toHaveLength(2);
  expect(
    screen.getAllByRole('link', { name: /원문 보기/ })[0].getAttribute('href'),
  ).toBe('https://example.test/article');
});

test('common view rejects wrong round, future source, duplicate event and a false minimum claim', () => {
  const v = value();
  expect(commonPriorityOf(response(v))).not.toBeNull();
  v.roundId = 'other';
  expect(commonPriorityOf({ ...response(v), id: 'round' })).toBeNull();
  v.roundId = 'round';
  v.items[1].issueId = v.items[0].issueId;
  expect(commonPriorityOf(response(v))).toBeNull();
  v.items[1].issueId = 'b';
  v.items[0].sources[0].publishedAt = '2026-10-31T09:20:00+09:00';
  expect(commonPriorityOf(response(v))).toBeNull();
  v.items[0].sources[0].publishedAt = '2026-10-29T17:00:00+09:00';
  v.minimumShortfall = 1;
  expect(commonPriorityOf(response(v))).toBeNull();
});

test('D-BRF-02 shows verified business outlook and keeps it bound to company, round and source', async () => {
  const v = value();
  const item = v.items[0];
  item.analysisResultVersion = 'common-ai-version';
  item.aiAnalyses = [
    {
      companyId: 'company',
      companyName: '합성기업',
      roundId: v.roundId,
      cutoff: v.cutoff,
      resultVersion: 'common-ai-version',
      verificationMode: 'separate_request_same_model',
      direction: 'positive',
      keyPoint: '시험 확대 여부를 확인합니다.',
      confirmedFact: '시험을 진행했습니다.',
      businessImpact: '실제 적용 확대 시 공급 기회가 생길 수 있습니다.',
      companyConnection: '시험 당사자입니다.',
      outlook: '납품 조건이 확정되면 가시성을 높여 평가합니다.',
      positive: '적용 확대 시 공급 기회',
      negative: null,
      priceObservation: null,
      previousChange: {
        status: 'unavailable',
        text: '실제 아침 판단 자료가 없습니다.',
      },
      nextCheck: '납품 조건의 확정 여부',
      evidenceIds: ['a'],
      judgmentBasis: {
        promptVersion: 'common-impact-relative-v1',
        directionReason: '시험 사실의 조건부 경로',
        confidence: 'limited',
        effectSizeStatus: 'unquantified',
      },
    },
  ];
  expect(commonPriorityOf(response(v))).not.toBeNull();
  render(<CommonPriorityIssues value={v} evening />);
  await userEvent.setup().click(screen.getByText('합성 이슈 a'));
  expect(screen.getByText('다음 거래일 전망')).not.toBeNull();
  expect(
    screen.getByText('납품 조건이 확정되면 가시성을 높여 평가합니다.'),
  ).not.toBeNull();
  expect(screen.queryByText('위험·불확실성')).toBeNull();
  item.aiAnalyses[0].companyId = 'foreign';
  expect(commonPriorityOf(response(v))).toBeNull();
  item.aiAnalyses[0].companyId = 'company';
  item.aiAnalyses[0].evidenceIds = ['foreign'];
  expect(commonPriorityOf(response(v))).toBeNull();
});
