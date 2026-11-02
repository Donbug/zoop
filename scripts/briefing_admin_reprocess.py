#!/usr/bin/env python3
"""Private FS070-02 worker bridge; only server-admitted pinned inputs reach this entry point."""
import json
import os
from pathlib import Path
import sys

from briefing_usage_run import run


def execute(job, output):
    command=json.loads(os.environ['ZOOP_BRIEFING_LEDGER_COMMAND'])
    spec=json.loads(Path(job).read_text())
    if spec['operation']=='generation' and os.environ.get('ZOOP_BRIEFING_REPROCESS_ALLOW_LIVE')!='true':
        raise ValueError('live_reprocessing_not_authorized')
    # The key path is operator configuration, never a request field or a usage record.
    key=os.environ.get('ZOOP_BRIEFING_REPROCESS_KEY_FILE')
    return run(job,output,command,execute=True,key_file=key)


if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('Use job.json output-directory')
    try:
        result=execute(sys.argv[1],sys.argv[2])
        print(json.dumps({k:result.get(k) for k in ('status','outcome','newModelCalls')}))
    except Exception:
        # Do not expose model responses, credential files or database exceptions.
        raise SystemExit('reprocess_failed')
