"""Frozen, source-bound historical daily market values; never a live-price replacement."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import importlib.util
from pathlib import Path
import urllib.error
import urllib.request

_spec = importlib.util.spec_from_file_location("_market_data_base", Path(__file__).with_name("briefing_replay.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
KST = timezone(timedelta(hours=9))
RULE_URL = "https://global.krx.co.kr/contents/GLB/01/0109/0109000000/guide_to_trading_in_the_korean_stock_market.pdf"
IDS = ("kospi", "kosdaq", "usdkrw")
LABELS = {"kospi": "KOSPI", "kosdaq": "KOSDAQ", "usdkrw": "원/달러"}
SYMBOLS = {"kospi": "^KS11", "kosdaq": "^KQ11", "usdkrw": "FX_USDKRW"}


def aware(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError) as error:
        raise base.ReplayError("market_aware_timestamp_required") from error


def number(value):
    if type(value) is bool or value is None:
        raise base.ReplayError("market_number_missing")
    try:
        value = Decimal(str(value).replace(",", ""))
        if not value.is_finite() or value <= 0:
            raise InvalidOperation()
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise base.ReplayError("market_number_invalid")


def provider_urls():
    start = int(datetime(2026, 9, 23, tzinfo=KST).timestamp())
    end = int(datetime(2026, 10, 9, tzinfo=KST).timestamp())
    return {"kospi": f"https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?period1={start}&period2={end}&interval=1d",
            "kosdaq": f"https://query1.finance.yahoo.com/v8/finance/chart/%5EKQ11?period1={start}&period2={end}&interval=1d",
            "usdkrw": "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?pageSize=40&page=1"}


def transport(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Zoop-development/0.1", "Accept": "application/json"})
    opener = urllib.request.build_opener(base.NoRedirect())
    try:
        with opener.open(request, timeout=12) as response:
            return response.status, response.read(1_000_001)
    except urllib.error.HTTPError as error:
        return error.code, error.read(1_000_001)


def fetch_receipts(output, send=transport):
    raw_dir, providers = output / "market/raw", output / "market/providers"
    base.private_dir(raw_dir)
    base.private_dir(providers)
    receipts, new_calls = {}, 0
    for indicator, url in provider_urls().items():
        path = providers / (indicator + ".json")
        if path.exists():
            saved = base.strict_load(base.regular(path))
            raw = base.regular(raw_dir / (saved["sha256"] + ".bin"))
            if saved.get("url") != url or base.digest(raw) != saved["sha256"] or len(raw) != saved["bytes"]:
                raise base.ReplayError("market_cached_raw_binding_mismatch")
            receipts[indicator] = saved
            continue
        try:
            status, raw = send(url)
        except (OSError, TimeoutError):
            status, raw = 0, b""
        if len(raw) > 1_000_000:
            raise base.ReplayError("market_response_size_exceeded")
        sha = base.digest(raw)
        base.write_once(raw_dir / (sha + ".bin"), raw)
        saved = {"source": "naver" if indicator == "usdkrw" else "yahoo", "url": url,
                 "sha256": sha, "bytes": len(raw), "httpStatus": status, "collectedAt": base.now(),
                 "indicatorIds": [indicator]}
        base.save_json(path, saved)
        receipts[indicator] = saved
        new_calls += 1
    return receipts, new_calls


def daily_rows(indicator, raw):
    value = base.strict_load(raw)
    rows = []
    if indicator == "usdkrw":
        if type(value) is not list:
            raise base.ReplayError("fx_history_shape_changed")
        for index, row in enumerate(value):
            day = date.fromisoformat(row["localTradedAt"])
            rows.append({"date": day.isoformat(), "value": number(row["closePrice"]), "rowIndex": index})
    else:
        chart = value.get("chart", {})
        results = chart.get("result")
        if chart.get("error") or type(results) is not list or len(results) != 1:
            raise base.ReplayError("index_provider_error_or_shape_changed")
        result = results[0]
        meta = result.get("meta", {})
        if meta.get("symbol") != SYMBOLS[indicator] or meta.get("exchangeTimezoneName") != "Asia/Seoul":
            raise base.ReplayError("index_symbol_or_timezone_mismatch")
        stamps, closes = result["timestamp"], result["indicators"]["quote"][0]["close"]
        if len(stamps) != len(closes):
            raise base.ReplayError("index_series_length_mismatch")
        for index, (stamp, close) in enumerate(zip(stamps, closes)):
            if close is None:
                continue
            if type(stamp) is not int:
                raise base.ReplayError("index_timestamp_invalid")
            day = datetime.fromtimestamp(stamp, KST).date()
            rows.append({"date": day.isoformat(), "value": number(close), "rowIndex": index})
    if len({row["date"] for row in rows}) != len(rows):
        raise base.ReplayError("duplicate_market_date")
    return sorted(rows, key=lambda row: row["date"])


def source(indicator, receipt):
    fx = indicator == "usdkrw"
    return {"provider": "naver" if fx else "yahoo", "symbol": SYMBOLS[indicator], "url": receipt["url"],
            "name": "하나은행 고시 기준환율(네이버 일별 이력)" if fx else "Yahoo Finance 지수 일별 이력",
            "official": False, "delayNote": "날짜만 제공되는 일별 고시값으로 외환시장 종가·회차 시점 실시간 환율이 아닙니다."
                if fx else "과거 일별 종가입니다. 출근 회차의 장중 값이나 당시 수집본을 입증하지 않습니다."}


def snapshot(round_definition, receipts, output):
    cutoff = aware(round_definition["window"]["to"])
    day = date.fromisoformat(round_definition["date"])
    edition = round_definition["edition"]
    expected = datetime.combine(day, time(9, 20) if edition == "morning" else time(17, 30), KST)
    if edition not in {"morning", "evening"} or cutoff != expected:
        raise base.ReplayError("market_round_cutoff_mismatch")
    indicators, bindings = [], []
    for indicator in IDS:
        receipt = receipts[indicator]
        item = {"id": indicator, "label": LABELS[indicator], "unit": "KRW" if indicator == "usdkrw" else "pt",
                "status": "unavailable", "value": None, "valueKind": None, "observedDate": None, "observedAt": None,
                "baseline": None, "change": None, "changeRate": None, "source": source(indicator, receipt),
                "reason": None, "reasonCode": "no_data"}
        eligible = []
        if receipt["httpStatus"] == 200:
            try:
                rows = daily_rows(indicator, base.regular(output / "market/raw" / (receipt["sha256"] + ".bin")))
                for row in rows:
                    d = date.fromisoformat(row["date"])
                    # No exact FX fixing time exists: a same-date daily quote may be after 17:30.
                    bound = datetime.combine(d + timedelta(days=1), time.min, KST) if indicator == "usdkrw" else datetime.combine(d, time(15, 30), KST)
                    if bound <= cutoff:
                        eligible.append({**row, "availabilityUpperBound": bound.isoformat()})
            except (base.ReplayError, KeyError, ValueError, TypeError):
                item.update({"status": "failed", "reasonCode": "format_changed", "reason": "공급원 형식을 확인하지 못했습니다."})
        else:
            item.update({"status": "failed", "reasonCode": "temporary_failure", "reason": "지표 원본 조회에 실패했습니다."})
        if eligible:
            current, prior = eligible[-1], eligible[-2] if len(eligible) > 1 else None
            delayed = indicator == "usdkrw" or current["date"] != day.isoformat()
            item.update({"status": "delayed" if delayed else "ok", "value": float(current["value"]), "valueKind": "reference" if indicator == "usdkrw" else "close",
                         "observedDate": current["date"], "reasonCode": None,
                         "reason": "회차 마감 전에 확정 가능한 직전 날짜의 일별 고시환율입니다. 당일 고시 마감 시각은 확인되지 않았습니다."
                            if indicator == "usdkrw" else "회차 마감 전 가장 최근 확인된 거래일 종가입니다. 장중 시세는 제공하지 않습니다."})
            if prior:
                change = current["value"] - prior["value"]
                item.update({"baseline": {"value": float(prior["value"]), "date": prior["date"], "at": None},
                             "change": float(change), "changeRate": float(change / prior["value"])})
            bindings.append({"id": indicator, "rawSha256": receipt["sha256"], "sourceDate": current["date"],
                             "availabilityUpperBound": current["availabilityUpperBound"], "sourceRowIndex": current["rowIndex"],
                             "field": "closePrice" if indicator == "usdkrw" else "close", "precision": "day" if indicator == "usdkrw" else "session_close",
                             "baselineDate": prior["date"] if prior else None, "baselineRowIndex": prior["rowIndex"] if prior else None})
        elif item["reason"] is None:
            item["reason"] = "회차 마감 이전의 확인 가능한 지표가 없습니다."
        indicators.append(item)
    fetched = max(r["collectedAt"] for r in receipts.values())
    return {"schemaVersion": "zoop-briefing-market-snapshot-v1", "scope": "historical_snapshot",
            "round": {"date": day.isoformat(), "edition": edition, "cutoff": cutoff.isoformat()}, "fetchedAt": fetched,
            "marketVariables": {"status": "available", "referenceAt": cutoff.isoformat(), "rateCutoffAt": cutoff.isoformat(),
                                "collectedAt": fetched, "indicators": indicators}, "indicatorBindings": bindings,
            "rawRefs": list(receipts.values()), "normalization": {"values": "decimal-half-up-2dp", "change": "difference-of-normalized-values", "changeRate": "change/baseline"}, "retrospective": True, "operationalCollectionGate": False,
            "sessionRule": {"regularCloseKST": "15:30", "source": RULE_URL, "exactSessionCalendarVerified": False},
            "limitations": ["현재 공급원에서 나중에 조회한 과거 일별 값이며 당시 수집본 동일성을 입증하지 않습니다.",
                            "지수는 제공된 일별 거래 기록과 KRX 정규장 마감 기준을 사용합니다. 특별 세션 캘린더/운영 권한은 미연결입니다.",
                            "환율은 직전 날짜까지의 은행 일별 고시값이며 외환시장 종가가 아닙니다."]}
