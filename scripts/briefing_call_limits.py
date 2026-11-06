"""Shared physical-call policy. Money limits and unknown-send reservations stay unchanged."""

DEFAULT_ROUND_CALLS = 16
MAX_ROUND_CALLS = 64
RECOMMENDED_ROUND_CALLS = 32


def round_limit(cfg):
    value = cfg.get('roundCallLimit', DEFAULT_ROUND_CALLS)
    if type(value) is not int or not DEFAULT_ROUND_CALLS <= value <= MAX_ROUND_CALLS:
        raise ValueError('briefing_server_round_call_limit')
    return value


def publication_reserve(cfg):
    return 8 if cfg.get('sharePriorityAnalysis') else 10


def native_limit(cfg):
    value = cfg.get('nativeCallLimit', 12)
    if type(value) is not int or not 1 <= value <= round_limit(cfg):
        raise ValueError('briefing_server_native_call_limit')
    return value


def validate_auto(cfg):
    if native_limit(cfg) > round_limit(cfg) - publication_reserve(cfg):
        raise ValueError('briefing_server_native_priority_capacity')


def environment_limit(env):
    raw = env.get('BRIEFING_ROUND_CALL_LIMIT', str(DEFAULT_ROUND_CALLS))
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
        raise ValueError('briefing_server_round_call_limit')
    return round_limit({'roundCallLimit': int(raw)})
