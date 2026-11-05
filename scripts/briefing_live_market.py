"""Capture source-bound daily indicators before a slot; no model calls or publication edits.

An absent bar is not a holiday calendar or a zero return. Bank daily references
are observations at collection time, never FX market closes. A late capture is
retained for diagnosis but cannot become an on-time publication input.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta
from pathlib import Path
import briefing_market_data as market

b = market.base
VERSION = 'briefing-live-market-v1'


def root_for(work, round_id):
    import re
    if not re.fullmatch(r'brf-\d{4}-\d{2}-\d{2}-(morning|evening)', round_id):
        raise b.ReplayError('live_market_round_identity')
    return Path(work) / 'market' / round_id


def definition(round_):
    cutoff = market.aware(round_['windowTo'])
    if (cutoff.astimezone(market.KST).date().isoformat() != round_['date']
            or round_['id'] != 'brf-' + round_['date'] + '-' + round_['edition']
            or round_['edition'] not in ('morning', 'evening')):
        raise b.ReplayError('live_market_round_binding')
    return {'roundId': round_['id'], 'date': round_['date'],
            'edition': round_['edition'], 'cutoff': cutoff.astimezone(market.KST).isoformat()}


def snapshot(round_, receipts, root):
    r = definition(round_); cutoff = market.aware(r['cutoff']); day = cutoff.astimezone(market.KST).date()
    indicators, bindings = [], []
    for key in market.IDS:
        receipt = receipts[key]; collected = market.aware(receipt['collectedAt'])
        src = market.source(key, receipt)
        src['delayNote'] = ('수집 시점에 제공된 은행 일별 고시값으로 외환시장 종가가 아닙니다.' if key == 'usdkrw'
                            else '공급원이 제공한 일별 종가입니다. 장중 경로·뉴스의 가격 효과는 입증하지 않습니다.')
        item = {'id': key, 'label': market.LABELS[key], 'unit': 'KRW' if key == 'usdkrw' else 'pt',
                'status': 'failed', 'value': None, 'valueKind': None, 'observedDate': None, 'observedAt': None,
                'baseline': None, 'change': None, 'changeRate': None, 'source': src,
                'reason': '지표 원본 조회에 실패했습니다.', 'reasonCode': 'temporary_failure'}
        eligible = []
        if receipt['httpStatus'] == 200:
            try:
                raw = b.regular(root / 'market/raw' / (receipt['sha256'] + '.bin'))
                rows = market.daily_rows(key, raw)
                # Today's index row can still be a running daily candle. Require
                # the provider's own same-day session end before calling it close.
                end = None
                if key != 'usdkrw':
                    stamp = b.strict_load(raw)['chart']['result'][0]['meta'].get('currentTradingPeriod', {}).get('regular', {}).get('end')
                    if type(stamp) is int:
                        session_end = datetime.fromtimestamp(stamp, market.KST)
                        if session_end.date() == day: end = session_end
                for row in rows:
                    d = datetime.fromisoformat(row['date']).date()
                    if d > day: continue
                    if key == 'usdkrw':
                        # Exact fixing time is unknown; the HTTP receipt proves
                        # this particular reference was observable at collection.
                        bound = collected
                    elif d == day:
                        if end is None or end > min(collected, cutoff): continue
                        bound = end
                    else:
                        bound = datetime.combine(d + timedelta(days=1), datetime.min.time(), market.KST)
                    if bound <= cutoff and d <= collected.astimezone(market.KST).date():
                        eligible.append({**row, 'availabilityUpperBound': bound.isoformat()})
                item.update(status='unavailable', reason='회차 마감 전 확인 가능한 일별 값이 없습니다.', reasonCode='no_data')
            except (b.ReplayError, KeyError, ValueError, TypeError, OverflowError):
                item.update(reason='공급원 지표 형식을 확인하지 못했습니다.', reasonCode='format_changed')
        if eligible:
            current, prior = eligible[-1], eligible[-2] if len(eligible) > 1 else None
            item.update(status='delayed' if current['date'] != day.isoformat() else 'ok',
                        value=float(current['value']), valueKind='reference' if key == 'usdkrw' else 'close',
                        observedDate=current['date'], reasonCode=None,
                        reason='수집 시점에 제공된 은행 일별 고시값입니다. 외환시장 종가가 아닙니다.' if key == 'usdkrw'
                        else '수집 시점에 확인한 최근 거래일 종가입니다. 새 거래 기록이 없으면 직전 값을 유지합니다.')
            if prior:
                change = current['value'] - prior['value']
                item.update(baseline={'value': float(prior['value']), 'date': prior['date'], 'at': None},
                            change=float(change), changeRate=float(change / prior['value']))
            bindings.append({'id': key, 'rawSha256': receipt['sha256'], 'sourceDate': current['date'],
                             'availabilityUpperBound': current['availabilityUpperBound'], 'sourceRowIndex': current['rowIndex'],
                             'baselineDate': prior['date'] if prior else None})
        indicators.append(item)
    fetched = max(market.aware(r['collectedAt']) for r in receipts.values())
    result = {'schemaVersion': VERSION, 'round': r, 'capturedBeforeCutoff': fetched <= cutoff,
              'marketVariables': {'status': 'available', 'referenceAt': cutoff.isoformat(), 'rateCutoffAt': cutoff.isoformat(),
                                  'collectedAt': fetched.isoformat(), 'indicators': indicators},
              'indicatorBindings': bindings, 'rawRefs': list(receipts.values())}
    result['sha256'] = b.digest(b.canonical(result))
    return result


def collect(work, round_, send=None):
    send = send or market.transport
    root = root_for(work, round_['id']); b.private_dir(root)
    if (root / 'capture.json').exists():
        return load(work, round_, allow_late=True)
    day = market.aware(round_['windowTo']).astimezone(market.KST).date()
    urls = market.provider_urls((day - timedelta(days=32)).isoformat(), (day + timedelta(days=1)).isoformat())
    def bounded(url):
        try:
            status, raw = send(url)
            return (status, raw) if len(raw) <= 1_000_000 else (0, b'')
        except (OSError, TimeoutError): return 0, b''
    receipts, _ = market.fetch_receipts(root, bounded, urls=urls)
    value = snapshot(round_, receipts, root)
    b.save_json(root / 'capture.json', value)
    return value


def load(work, round_, *, allow_late=False):
    root = root_for(work, round_['id'])
    value = b.strict_load(b.regular(root / 'capture.json'))
    if value.get('round') != definition(round_): raise b.ReplayError('live_market_capture_binding')
    day = market.aware(round_['windowTo']).astimezone(market.KST).date()
    urls = market.provider_urls((day - timedelta(days=32)).isoformat(), (day + timedelta(days=1)).isoformat())
    # Existing receipts are verified against their exact URL/raw hash. This
    # path must never repair a missing cache by sending another HTTP request.
    def no_send(_): raise b.ReplayError('live_market_capture_incomplete')
    receipts, _ = market.fetch_receipts(root, no_send, urls=urls)
    expected = snapshot(round_, receipts, root)
    if value != expected: raise b.ReplayError('live_market_capture_changed')
    if not allow_late and not value['capturedBeforeCutoff']: raise b.ReplayError('live_market_late_capture')
    return copy.deepcopy(value)


def publication(work, round_):
    """Missing/corrupt/late market data never withholds a verified news briefing."""
    try: return load(work, round_)
    except (OSError, b.ReplayError, KeyError, ValueError, TypeError): return None
