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


def candidate_reserve(cfg):
    """Keep the final publication and one supported selection/repair pair funded."""
    return publication_reserve(cfg) + (4 if cfg.get('selectionContinuation') else 0)


def remaining_native(cfg, round_id):
    from pathlib import Path
    import json
    root = Path(cfg['work']) / 'budget'
    own = [json.loads(p.read_bytes()) for p in root.glob('*.json')]
    own = [r for r in own if r['roundId'] == round_id]
    if any(not (root / 'finished' / (r['requestDigest'] + '.json')).is_file() for r in own):
        raise ValueError('briefing_server_unsettled_call_requires_reconciliation')
    return max(0, min(native_limit(cfg) - sum(r.get('phase') == 'native' for r in own),
                      round_limit(cfg) - len(own) - candidate_reserve(cfg)))


def document_work(cfg, round_id, documents_left=1):
    """Stage ceilings share the same finite document/round budget; no hidden four-call cap."""
    available = remaining_native(cfg, round_id)
    if available < 5:
        raise ValueError('briefing_server_remaining_shared_call_capacity')
    # A long first article cannot take the last normally completable document slot.
    if documents_left > 1:
        # Its own final assessment can still reject it; retain the next source
        # and that additional classification instead of counting only native calls.
        available = max(5, available - 5 - (4 if cfg.get('selectionContinuation') else 0))
    return available, {'extract': 1, 'compare': 1, 'topic': 0, 'relation': 1,
                       'impact': available, 'verify-relation': available, 'verify-impact': available}


def native_limit(cfg):
    value = cfg.get('nativeCallLimit', 12)
    if type(value) is not int or not 1 <= value <= round_limit(cfg):
        raise ValueError('briefing_server_native_call_limit')
    return value


def validate_auto(cfg):
    if native_limit(cfg) > round_limit(cfg) - publication_reserve(cfg):
        raise ValueError('briefing_server_native_priority_capacity')
    if cfg.get('selectionContinuation') and (native_limit(cfg)<5 or round_limit(cfg)-candidate_reserve(cfg)<5):
        raise ValueError('briefing_server_selection_continuation_capacity')


def environment_limit(env):
    raw = env.get('BRIEFING_ROUND_CALL_LIMIT', str(DEFAULT_ROUND_CALLS))
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
        raise ValueError('briefing_server_round_call_limit')
    return round_limit({'roundCallLimit': int(raw)})
