"""Narrow, offline redaction for a captured publisher's browser analytics config."""
import json

MARKER = '[REDACTED_CREDENTIAL]'
POINTER = '/analytics/tags/permutive/workspace_api_key'


def redact_publisher_config(raw):
    """Preserve every other byte; reject ambiguous encodings or multiple configs."""
    lines = raw.splitlines(keepends=True)
    changed = 0
    for index, line in enumerate(lines):
        try:
            data = json.loads(line)
            value = data['analytics']['tags']['permutive']['workspace_api_key']
        except (ValueError, KeyError, TypeError):
            continue
        if value == MARKER:
            continue
        if not isinstance(value, str) or not value:
            raise ValueError('Unexpected publisher config value')
        encoded = json.dumps(value).encode()
        if line.count(encoded) != 1:
            raise ValueError('Ambiguous publisher config encoding')
        lines[index] = line.replace(encoded, json.dumps(MARKER).encode(), 1)
        changed += 1
    if changed != 1:
        raise ValueError('Expected exactly one publisher config redaction')
    return b''.join(lines)
