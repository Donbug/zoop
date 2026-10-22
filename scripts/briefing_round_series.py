"""Explicit consecutive historical windows; never changes operational collection clocks."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import briefing_replay as base
SCHEMA = 'zoop-briefing-round-series-v1'


def require(value):
    if not value:
        raise ValueError('invalid series')


def load(path, source_sha=None):
    value = base.strict_load(base.regular(Path(path)))
    try:
        require(value['schemaVersion'] == SCHEMA and value['retrospectiveBodies'] is True
                and value['productionAuthorized'] is False)
        rounds = value['rounds']; require(1 <= len(rounds) <= 14)
        previous = None
        for row in rounds:
            require(row['edition'] in ('morning', 'evening') and row['window']['openStart'] is False)
            start = datetime.fromisoformat(row['window']['from']); end = datetime.fromisoformat(row['window']['to'])
            require(start.tzinfo is not None and end.tzinfo is not None and start < end <= datetime.now(timezone.utc))
            kst = end.astimezone(ZoneInfo('Asia/Seoul'))
            require(kst.date().isoformat() == row['date'])
            require((kst.hour, kst.minute, kst.second, kst.microsecond) == ((9,20,0,0) if row['edition']=='morning' else (17,30,0,0)))
            expected = kst.replace(hour=17,minute=30)-timedelta(days=1) if row['edition']=='morning' else kst.replace(hour=9,minute=20)
            require(start == expected and (previous is None or start == previous))
            previous = end
        if source_sha is not None: require(value['sourceFileSha256'] == source_sha)
    except (KeyError, TypeError, ValueError):
        raise base.ReplayError('round_series_invalid') from None
    return value
