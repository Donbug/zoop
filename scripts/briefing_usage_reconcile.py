#!/usr/bin/env python3
"""Restore saved usage receipt acknowledgements. No claim, generation, model retry, or publication."""
import argparse
import json
from pathlib import Path

from briefing_usage import CommandPipe, reconcile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usage-directory', type=Path, required=True)
    parser.add_argument('--ledger-command-file', type=Path, required=True)
    args = parser.parse_args()
    pipe = CommandPipe(json.loads(args.ledger_command_file.read_bytes()))
    try:
        print(json.dumps(reconcile(args.usage_directory, pipe)))
    finally:
        pipe.close()


if __name__ == '__main__':
    main()
