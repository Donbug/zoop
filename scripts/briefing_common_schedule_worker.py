"""Server common-briefing queue consumer; never uses the demo import/run scripts.

The private operator config binds a deployed producer command. That producer must
collect/select/generate/validate/publish with the existing usage/publisher guards.
Exit status alone is never publication proof. An interrupted invocation is not
replayed automatically, because its provider outcome may be unknown.
"""
from __future__ import annotations
import argparse,json,os,subprocess,time
from pathlib import Path
from datetime import UTC, datetime

def command_for(config,job):
    command=config.get('producerCommand')
    if not isinstance(command,list) or not command or any(not isinstance(x,str) or not x for x in command):
        raise ValueError('configured_common_producer_required')
    if any(Path(x).name in ('briefing_local_run.py','briefing_round_flow.py','briefing_replay.py') for x in command):
        raise ValueError('demo_producer_forbidden')
    fields={'roundId':job['id'],'date':str(job['round_date']),'edition':job['edition'],
            'cutoff':job['scheduled_at'].isoformat(),'windowFrom':job['window_from'].isoformat()}
    return [arg.format_map(fields) for arg in command]

def run_producer(config,job,*,invoke=None):
    command=command_for(config,job)
    invoke=invoke or subprocess.run
    # No shell; arguments are from private operator configuration plus exact queue fields.
    result=invoke(command,env=os.environ.copy(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL,timeout=config.get('producerTimeoutSeconds',1800),check=False)
    if result.returncode!=0:raise ValueError('common_producer_outcome_requires_recovery')

def published(conn,job):
    return bool(conn.execute("""
      SELECT 1 FROM briefing_rounds r JOIN briefing_personal_pools p ON p.round_id=r.id
      WHERE r.id=%s AND r.round_date=%s AND r.edition=%s AND r.scheduled_at=%s AND r.window_to=%s
      AND r.window_from=%s AND r.status='published' AND r.published_at IS NOT NULL
      AND r.payload_sha256=encode(sha256(convert_to(r.published_payload::text,'UTF8')),'hex')
      AND p.snapshot->>'publicationPayloadSha256'=r.payload_sha256 AND (p.snapshot->>'complete')::boolean IS TRUE
      AND p.snapshot_sha256=encode(sha256(convert_to(p.snapshot::text,'UTF8')),'hex') LIMIT 1
      """,(job['id'],job['round_date'],job['edition'],job['scheduled_at'],job['scheduled_at'],job['window_from'])).fetchone())

def work_once(config):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(config['dsn'],autocommit=True,row_factory=dict_row) as conn:
        with conn.transaction():
            job=conn.execute("SELECT * FROM briefing_common_schedule_jobs WHERE status='queued' ORDER BY scheduled_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if not job:return False
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='running' WHERE id=%s",(job['id'],))
        try:
            if not published(conn,job):run_producer(config,job)
            if not published(conn,job):raise ValueError('validated_publication_and_candidate_pool_required')
            state='completed'
        except Exception:
            state='requires_recovery'
        conn.execute("UPDATE briefing_common_schedule_jobs SET status=%s,finished_at=now() WHERE id=%s AND status='running'",(state,job['id']))
        print(json.dumps({'roundId':job['id'],'status':state}),flush=True)
        return True

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True,type=Path);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.config.is_symlink() or args.config.stat().st_mode&0o077:raise ValueError('private_operator_config_required')
    cfg=json.loads(args.config.read_text());command_for(cfg,{'id':'check','round_date':'check','edition':'morning','scheduled_at':datetime.now(UTC),'window_from':datetime.now(UTC)})
    if cfg.get('enabled') is not True:raise ValueError('explicit_common_worker_enable_required')
    while True:
        found=work_once(cfg)
        if args.once:return
        if not found:time.sleep(5)
if __name__=='__main__':main()
