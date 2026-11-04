"""Preserve publication precision and first observation as distinct source facts."""
from datetime import datetime,date,timedelta,timezone
KST=timezone(timedelta(hours=9))


def aware(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('source_timezone_required')
    return parsed


def available(source):
    if source.get('publishedAt') is not None:return aware(source['publishedAt'])
    if source.get('eligibilityBasis')!='first_observed':raise ValueError('source_clock_unavailable')
    day=date.fromisoformat(source['publishedDate']);observed=aware(source['availableAt'])
    if day>observed.astimezone(KST).date():raise ValueError('source_day_after_observation')
    return observed


def projection(source):
    available(source)
    fields=('evidenceId','quote','url','publishedAt')
    if source.get('publishedAt') is None:fields+=('publishedDate','availableAt','eligibilityBasis')
    return {k:source[k] for k in fields}
