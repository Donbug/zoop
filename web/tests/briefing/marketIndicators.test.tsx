import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import MarketIndicators from '@/components/briefing/MarketIndicators';
import type { MarketIndicator } from '@/types/briefing';

// D-BRF-01·02 / FS031: 합성 저장값으로 관측·비교 기준과 누락 상태를 검증한다.
function indicator(overrides: Partial<MarketIndicator> = {}): MarketIndicator {
  return {
    id: 'kospi',
    label: 'KOSPI',
    unit: 'pt',
    status: 'ok',
    value: 2600.25,
    valueKind: 'close',
    observedDate: '2026-10-13',
    observedAt: null,
    baseline: { value: 2500, date: '2026-10-12', at: null },
    change: 100.25,
    changeRate: 0.0401,
    source: { name: '합성 지수 출처', official: false, delayNote: null },
    reason: null,
    ...overrides,
  };
}

function card(label: string) {
  const element = screen.getByText(label).closest('li');
  if (!element) throw new Error(`지표 카드 없음: ${label}`);
  return within(element);
}

describe('D-BRF-01·02 저장된 주요 시장 지표', () => {
  it('does not render a source disclosure or comparison basis in compact mode', () => {
    render(
      <MarketIndicators
        compact
        variables={{
          status: 'available',
          collectedAt: '2026-10-14T07:35:00+09:00',
          indicators: [
            indicator({
              source: {
                name: '합성 지수 출처',
                official: false,
                delayNote: '지연 가능',
                url: 'https://example.com/kospi',
              },
            }),
          ],
        }}
      />,
    );

    expect(screen.queryByLabelText('시장 지표 안내')).toBeNull();
    expect(screen.queryByText(/2026-10-12 대비/)).toBeNull();
    expect(screen.queryByText(/합성 지수 출처/)).toBeNull();
    expect(card('KOSPI').getByText('2,600.25 pt')).toBeTruthy();
  });

  it('shows all three stored values, observation dates, baselines and nonzero changes', () => {
    render(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [
            indicator({ observedAt: '2026-10-14T08:00:00+09:00' }),
            indicator({
              id: 'kosdaq',
              value: 800.5,
              change: -3.25,
              changeRate: -0.004,
            }),
            indicator({
              id: 'usdkrw',
              unit: 'KRW',
              value: 1380.75,
              change: 8.5,
              changeRate: 0.0062,
            }),
          ],
        }}
      />,
    );

    const kospi = card('KOSPI');
    expect(kospi.getByText('2026-10-13 종가')).toBeTruthy();
    expect(kospi.queryByText(/2026-10-14/)).toBeNull();
    expect(kospi.getByText('2026-10-12 대비')).toBeTruthy();
    expect(kospi.getByText('2,600.25 pt')).toBeTruthy();
    expect(kospi.getByText('▲ +100.25 (+4.01%)')).toBeTruthy();
    expect(card('KOSDAQ').getByText('800.5 pt')).toBeTruthy();
    // 저장된 변동과 등락률은 value/baseline으로 다시 계산하지 않는다.
    expect(card('KOSDAQ').getByText('▼ -3.25 (-0.4%)')).toBeTruthy();
    expect(card('원/달러').getByText('1,380.75원')).toBeTruthy();
    expect(card('원/달러').getByText('▲ +8.5원 (+0.62%)')).toBeTruthy();
  });

  it('keeps an actual FX close distinct from an explicitly timed bank reference', () => {
    const { rerender } = render(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [indicator({ id: 'usdkrw', unit: 'KRW' })],
        }}
      />,
    );
    expect(card('원/달러').getByText('2026-10-13 종가')).toBeTruthy();
    rerender(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [
            indicator({
              id: 'usdkrw',
              unit: 'KRW',
              valueKind: 'reference',
              observedAt: '2026-10-13T14:30:00+09:00',
            }),
          ],
        }}
      />,
    );
    expect(card('원/달러').getByText(/14:30 KST 고시값/)).toBeTruthy();
    expect(card('원/달러').queryByText(/종가/)).toBeNull();
  });

  it.each(['reference', 'close'] as const)(
    'labels bank daily FX kind %s without inventing a market close time',
    (valueKind) => {
      render(
        <MarketIndicators
          variables={{
            status: 'available',
            indicators: [
              indicator({
                id: 'usdkrw',
                unit: 'KRW',
                status: 'delayed',
                value: 1375.5,
                valueKind,
                observedDate: '2026-10-12',
                observedAt: null,
                baseline: { value: 1369.25, date: '2026-10-09', at: null },
                change: 6.25,
                changeRate: 0.0046,
                source: {
                  name: '네이버 금융 · 하나은행',
                  official: false,
                  delayNote: '은행 일별 고시값 · 고시 시각 미제공',
                },
                reason: '이전 날짜의 고시값을 사용했어요.',
              }),
            ],
          }}
        />,
      );

      const fx = card('원/달러');
      expect(fx.getByText('지연')).toBeTruthy();
      expect(fx.getByText('2026-10-12 일별 고시값')).toBeTruthy();
      expect(fx.getByText('2026-10-09 대비')).toBeTruthy();
      expect(fx.getByText('▲ +6.25원 (+0.46%)')).toBeTruthy();
      expect(fx.getByText('이전 날짜의 고시값을 사용했어요.')).toBeTruthy();
      expect(
        fx.getByText(
          '출처 네이버 금융 · 하나은행 · 비공식 · 은행 일별 고시값 · 고시 시각 미제공',
        ),
      ).toBeTruthy();
      expect(fx.queryByText(/종가|KST/)).toBeNull();
    },
  );

  it('keeps the stored observation and baseline times for a timestamped FX value', () => {
    render(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [
            indicator({
              id: 'usdkrw',
              unit: 'KRW',
              valueKind: 'latest',
              observedAt: '2026-10-13T09:15:00+09:00',
              baseline: {
                value: 1370,
                date: '2026-10-12',
                at: '2026-10-12T15:30:00+09:00',
              },
            }),
          ],
        }}
      />,
    );

    const fx = card('원/달러');
    expect(fx.getByText('2026-10-13 09:15 KST 기준')).toBeTruthy();
    expect(fx.getByText('2026-10-12 15:30 KST 대비')).toBeTruthy();
    expect(fx.queryByText(/일별 고시값|종가/)).toBeNull();
  });

  it('preserves an unavailable round and absent indicators without fabricating values', () => {
    const { rerender } = render(
      <MarketIndicators
        variables={{ status: 'unavailable', reason: '당시 지표 미수집' }}
      />,
    );
    expect(screen.getByText('당시 지표 미수집')).toBeTruthy();
    expect(screen.getAllByText('이 회차에 저장된 지표가 없어요.')).toHaveLength(
      3,
    );
    expect(screen.queryByText(/ pt|원$/)).toBeNull();

    rerender(<MarketIndicators />);
    expect(screen.getAllByText('지표 데이터 준비 중')).toHaveLength(3);
  });

  it('hides failed, unavailable and null values while retaining their reasons and sources', () => {
    render(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [
            indicator({
              status: 'failed',
              value: 999,
              reason: '지수 조회 실패',
            }),
            indicator({
              id: 'kosdaq',
              status: 'unavailable',
              value: 888,
              reason: '당시 지수 없음',
            }),
            indicator({
              id: 'usdkrw',
              unit: 'KRW',
              status: 'delayed',
              value: null,
              reason: '환율 값 확인 중',
            }),
          ],
        }}
      />,
    );

    expect(card('KOSPI').getByText('조회 실패')).toBeTruthy();
    expect(card('KOSPI').getByText('지수 조회 실패')).toBeTruthy();
    expect(
      card('KOSPI').getByText('출처 합성 지수 출처 · 비공식'),
    ).toBeTruthy();
    expect(card('KOSDAQ').getByText('사용 불가')).toBeTruthy();
    expect(card('KOSDAQ').getByText('당시 지수 없음')).toBeTruthy();
    expect(card('원/달러').getByText('환율 값 확인 중')).toBeTruthy();
    expect(screen.queryByText(/999 pt|888 pt|0원/)).toBeNull();
    expect(screen.queryByText(/종가|일별 고시값|대비|▲|▼/)).toBeNull();
  });

  it('distinguishes missing observation, baseline and change from a stored zero', () => {
    render(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [
            indicator({
              observedDate: null,
              observedAt: null,
              baseline: null,
              change: null,
              changeRate: null,
              source: null,
            }),
            indicator({ id: 'kosdaq', change: 0, changeRate: null }),
          ],
        }}
      />,
    );

    expect(card('KOSPI').getByText('시각 미상 종가')).toBeTruthy();
    expect(card('KOSPI').getByText('비교 기준 확인되지 않음')).toBeTruthy();
    expect(card('KOSPI').getByText('변동 확인되지 않음')).toBeTruthy();
    expect(card('KOSPI').queryByText(/출처/)).toBeNull();
    expect(card('KOSDAQ').getByText('0 (등락률 없음)')).toBeTruthy();
  });

  it('updates to another saved round without making a realtime request', () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const { rerender } = render(
      <MarketIndicators
        variables={{ status: 'available', indicators: [indicator()] }}
      />,
    );
    rerender(
      <MarketIndicators
        variables={{
          status: 'available',
          indicators: [
            indicator({
              value: 2620.5,
              observedDate: '2026-10-14',
              baseline: { value: 2600.25, date: '2026-10-13', at: null },
              change: 20.25,
              changeRate: 0.0078,
            }),
          ],
        }}
      />,
    );

    const kospi = card('KOSPI');
    expect(kospi.getByText('2026-10-14 종가')).toBeTruthy();
    expect(kospi.getByText('2026-10-13 대비')).toBeTruthy();
    expect(kospi.getByText('2,620.5 pt')).toBeTruthy();
    expect(kospi.getByText('▲ +20.25 (+0.78%)')).toBeTruthy();
    expect(kospi.queryByText('2,600.25 pt')).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
