"""Archive public history and project regular-session prices strictly before an edition cutoff.

Development replay only: historical provider data retrieved later is not a contemporary capture.
Never use regularMarketPrice, adjusted close, an unfinished bar or a same-day morning daily close.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location('_company_market', Path(__file__).with_name('briefing_market_data.py'))
market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(market)
base = market.base


def identity(company_id):
    exchange, symbol = company_id.split(':')
    if exchange == 'KRX' and len(symbol) == 6 and symbol.isdigit():
        return symbol + '.KS', 'KRW', 'Asia/Seoul'
    if exchange in {'NASDAQ', 'NYSE'} and symbol.isascii() and symbol.isalpha() and len(symbol) <= 5:
        return symbol, 'USD', 'America/New_York'
    raise ValueError('unsupported_company_market')


def url(company_id, interval):
    symbol, _, _ = identity(company_id)
    # Replay fixture range; an operational collector needs an exchange calendar and licensed feed.
    start = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp())
    return (f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe="")}'
            f'?period1={start}&period2={end}&interval={interval}&includePrePost=false&events=splits%2Cdiv')


def collect(company_ids, output, send=market.transport):
    receipts = {}
    for cid in sorted(set(company_ids)):
        values = []
        for interval in ('5m', '1d'):
            directory = output / 'company-prices'
            base.private_dir(directory)
            key = cid.replace(':', '-') + '-' + interval
            path = directory / (key + '.json')
            if path.exists():
                saved = base.strict_load(base.regular(path))
                raw = base.regular(directory / (saved['sha256'] + '.bin'))
                if saved['url'] != url(cid, interval) or base.digest(raw) != saved['sha256'] or len(raw) != saved['bytes']:
                    raise ValueError('company_price_cache_changed')
            else:
                status, raw = send(url(cid, interval))
                if len(raw) > 1_000_000:
                    raise ValueError('company_price_response_too_large')
                sha = base.digest(raw)
                base.write_once(directory / (sha + '.bin'), raw)
                saved = {'companyId': cid, 'interval': interval, 'url': url(cid, interval),
                         'httpStatus': status, 'sha256': sha, 'bytes': len(raw), 'collectedAt': base.now()}
                base.write_once(path, base.canonical(saved))
            values.append(saved)
        receipts[cid] = values
    return receipts


def points(cid, cutoff, receipts, output):
    symbol, currency, zone_name = identity(cid)
    zone = ZoneInfo(zone_name)
    found = []
    for receipt in receipts:
        if receipt['companyId'] != cid or receipt['url'] != url(cid, receipt['interval']):
            raise ValueError('company_price_identity')
        raw = base.regular(output / 'company-prices' / (receipt['sha256'] + '.bin'))
        if base.digest(raw) != receipt['sha256'] or len(raw) != receipt['bytes']:
            raise ValueError('company_price_raw_changed')
        if receipt['httpStatus'] != 200:
            continue
        result = base.strict_load(raw)['chart']['result'][0]
        meta = result['meta']
        if (meta['symbol'], meta['currency'], meta['exchangeTimezoneName']) != (symbol, currency, zone_name):
            raise ValueError('company_price_provider_identity')
        if result.get('events', {}).get('splits'):
            raise ValueError('company_price_split_requires_adjustment_policy')
        stamps = result.get('timestamp', [])
        closes = result['indicators']['quote'][0]['close']
        if len(stamps) != len(closes) or len(set(stamps)) != len(stamps):
            raise ValueError('company_price_series')
        for stamp, value in zip(stamps, closes):
            if value is None:
                continue
            if type(stamp) is not int:
                raise ValueError('company_price_timestamp')
            if not 1790812800 <= stamp < 1791504000:
                continue
            start = datetime.fromtimestamp(stamp, zone)
            if start.weekday() >= 5:
                continue
            opening = datetime.combine(start.date(), time(9) if currency == 'KRW' else time(9, 30), zone)
            closing = datetime.combine(start.date(), time(15, 30) if currency == 'KRW' else time(16), zone)
            if receipt['interval'] == '1d':
                end = closing
                kind = 'daily_close'
            else:
                end = start + timedelta(minutes=5)
                if start < opening or end > closing:
                    continue
                kind = 'five_minute_close'
            if end > cutoff:
                continue
            # Do not promote a provider's appended live terminal point to a daily close.
            if receipt['interval'] == '1d' and start != opening:
                continue
            found.append({'value': str(market.number(value)), 'observedAt': end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                          'kind': kind, 'sessionDate': start.date().isoformat()})
    return sorted(found, key=lambda p: (market.aware(p['observedAt']), p['kind'] == 'daily_close'))


def snapshot(cid, cutoff_string, receipts, output):
    cutoff = market.aware(cutoff_string)
    _, currency, zone = identity(cid)
    result = {'companyId': cid, 'cutoff': cutoff_string, 'currency': currency, 'exchangeTimezone': zone,
              'source': 'Yahoo Finance', 'official': False,
              'note': '나중에 조회한 과거 정규장 이력입니다. 5분봉은 종료 후 사용하며 당시 수집·실시간 시세는 입증하지 않습니다.',
              'sources': receipts, 'status': 'unavailable', 'reason': 'eligible_price_missing', 'latest': None,
              'baseline': None, 'comparisonStatus': 'unavailable', 'change': None, 'changeRate': None}
    try:
        eligible = points(cid, cutoff, receipts, output)
    except (KeyError, ValueError, TypeError, IndexError, base.ReplayError):
        result['reason'] = 'provider_history_unverified'
        return result
    if not eligible:
        return result
    latest = eligible[-1]
    morning = cutoff.astimezone(market.KST).replace(hour=9, minute=20, second=0, microsecond=0)
    evening = cutoff > morning
    baseline = [p for p in eligible if market.aware(p['observedAt']) <= morning] if evening else [
        p for p in eligible if p['kind'] == 'daily_close' and p['sessionDate'] < latest['sessionDate']]
    result.update(status='available', reason=None, latest=latest, baseline=baseline[-1] if baseline else None,
                  baselineKind='morning_cutoff' if evening else 'previous_close')
    if baseline:
        if evening and market.aware(latest['observedAt']) <= market.aware(baseline[-1]['observedAt']):
            result['comparisonStatus'] = 'no_new_session'
        else:
            change = Decimal(latest['value']) - Decimal(baseline[-1]['value'])
            rate = (change / Decimal(baseline[-1]['value']) * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            result.update(comparisonStatus='available', change=str(change), changeRate=str(rate))
    return result
