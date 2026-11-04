"""Versioned prospective KST schedule; saved rounds retain their own original timestamps."""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
KST=ZoneInfo('Asia/Seoul')

def slot(day,edition,cfg=None):
    cfg=cfg or {};policy=cfg.get('schedule',{})
    if edition not in ('morning','evening'):raise ValueError('briefing_schedule_edition')
    effective=date.fromisoformat(policy.get('effectiveFrom','9999-12-31'))
    nominal=('09:20' if edition=='morning' else '17:30') if day<effective else policy.get(edition,'09:20' if edition=='morning' else '17:30')
    parsed=datetime.strptime(nominal,'%H:%M').time()
    if parsed.strftime('%H:%M')!=nominal:raise ValueError('briefing_schedule_time')
    value=datetime.combine(day,parsed,KST)
    test=policy.get('testEveningAt')
    if edition=='evening' and test:
        override=datetime.fromisoformat(test)
        if override.tzinfo is None or override.utcoffset()!=timedelta(hours=9) or override.second or override.microsecond:raise ValueError('briefing_schedule_test_clock')
        if override.date()==day:value=override
    return value

def round_for(day,edition,cfg=None):
    end=slot(day,edition,cfg)
    start=slot(day-timedelta(days=1),'evening',cfg) if edition=='morning' else slot(day,'morning',cfg)
    if not start<end:raise ValueError('briefing_schedule_window')
    return {'id':'brf-'+str(day)+'-'+edition,'date':str(day),'edition':edition,'scheduledAt':end.isoformat(),'windowFrom':start.isoformat(),'windowTo':end.isoformat()}
