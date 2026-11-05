"""Opt-in collection -> native registration -> priority publication, one durable slot at a time.

Never activates itself on import. Raw documents/keys/provider bodies stay in owned private state.
"""
from __future__ import annotations
import argparse,json,signal,time
from datetime import datetime,timedelta
from pathlib import Path
import briefing_native_intake as native
import briefing_priority_generation as priority
import briefing_priority_server as producer
from briefing_usage import write_once
server=native.server
VERSION='briefing-auto-chain-v1'
LEAD={'morning':20*60,'evening':30*60}


def round_for(day,edition,cfg=None):
    from briefing_schedule import round_for as scheduled
    return scheduled(day,edition,cfg)


class Journal:
    def __init__(self,cfg,round_id):
        self.root=Path(cfg['work'])/'chain'/round_id;self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        server.require(not self.root.is_symlink() and self.root.stat().st_mode&0o077==0,'private_chain_state')
        self.round_id=round_id
    def __call__(self,stage,status,detail=None):
        server.require(stage in ('collection','native','authority','import','activation','cutoff','generation','publication','slot'),'chain_stage')
        server.require(status in ('started','completed','failed','requires_recovery'),'chain_status')
        # Restrict the journal to operational facts; no source body, prompt, account or provider response.
        safe={k:v for k,v in (detail or {}).items() if k in ('graphVersion','reason','candidateDocuments','selectedDocuments','cutoff')}
        path=self.root/(stage+'-'+status+'.json')
        if path.exists():return
        write_once(path,{'schemaVersion':VERSION,'roundId':self.round_id,'stage':stage,'status':status,'at':server.b.now(),'detail':safe})


def config_check(cfg):
    server.require(cfg.get('enabled') is True and cfg.get('autoChain')==VERSION and cfg.get('priorityContract')==priority.VERSION,'auto_chain_opt_in')
    root=Path(cfg['work']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    server.require(not root.is_symlink() and root.stat().st_mode&0o077==0,'private_work')
    # Literal common->personal reuse saves two requests, never a verification.
    server.require(cfg.get('nativeCallLimit')==(8 if cfg.get('sharePriorityAnalysis') else 6),'native_priority_capacity')
    server.require(cfg.get('additiveGraphAllowed') is True,'additive_graph_opt_in_required')
    server.require(bool(cfg.get('authorizationRef')) and bool(cfg.get('dsn')),'chain_authorization')


def validate_selected_config(cfg):
    import briefing_selected_generation as selected
    from psycopg.conninfo import conninfo_to_dict
    selected_cfg=selected.load_config(Path(cfg['selectedWorkerConfig']))
    server.require(selected_cfg.get('allowedMemberIds')==cfg.get('personalMemberIds',[]),'personal_member_cohort_binding')
    server.require(selected_cfg.get('serverBudgetWork')==cfg['work'],'shared_personal_budget_required')
    common=conninfo_to_dict(cfg['dsn']);personal=conninfo_to_dict(selected_cfg['dsn'])
    server.require(all(common.get(k,default)==personal.get(k,default) for k,default in [('host',''),('port','5432'),('dbname',''),('options','')]),'personal_database_binding')
    server.require(Path(selected_cfg['grants']).resolve()==(Path(cfg['authorityRoot'])/'serving-grants.json').resolve(),'personal_authority_binding')
    return selected_cfg


def run_slot(cfg,edition,*,now=None,sleep=None):
    config_check(cfg);now=now or (lambda:datetime.now(server.KST));sleep=sleep or time.sleep
    round_=round_for(now().astimezone(server.KST).date(),edition,cfg);journal=Journal(cfg,round_['id'])
    journal('slot','started',{'cutoff':round_['windowTo']})
    def timeout(signum,frame):raise TimeoutError('finite_slot_execution_limit')
    previous_handler=signal.signal(signal.SIGALRM,timeout);signal.alarm(45*60)
    try:
        # The producer admits exactly the additive graph activated for this slot before making a model request.
        result=native.run_slot(cfg,edition,round_['windowTo'],producer=producer.produce,observer=journal,now=now,sleep=sleep)
        journal('slot','completed');return result
    except BaseException as error:
        if isinstance(error,ValueError) and str(error)=='briefing_server_another_briefing_writer':raise
        for state in sorted(journal.root.glob('*-started.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            stage=state.name.removesuffix('-started.json')
            if stage!='slot' and not (journal.root/(stage+'-completed.json')).exists():
                journal(stage,'failed',{'reason':'stage_failed'});break
        journal('slot','requires_recovery',{'reason':'interrupted_or_stage_failed'})
        raise
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous_handler)


def work_once(cfg,*,now=None,connect=None,run=None):
    config_check(cfg);now=now or (lambda:datetime.now(server.KST));instant=now().astimezone(server.KST)
    if connect is None:
        import psycopg
        from psycopg.rows import dict_row
        connect=lambda:psycopg.connect(cfg['dsn'],autocommit=True,row_factory=dict_row)
    with connect() as conn:
        for edition in ('morning','evening'):
            r=round_for(instant.date(),edition,cfg);slot=datetime.fromisoformat(r['windowTo']);left=(slot-instant).total_seconds()
            if cfg.get('notBefore') and slot<datetime.fromisoformat(cfg['notBefore']):continue
            if left>LEAD[edition]:continue
            existing=conn.execute('SELECT * FROM briefing_common_schedule_jobs WHERE round_date=%s AND edition=%s',(instant.date(),edition)).fetchone()
            if existing:
                # No automatic replay of a claimed, completed, failed or interrupted slot.
                if existing['status'] in ('completed','requires_recovery') or left>0:continue
                if not conn.execute("SELECT pg_try_advisory_lock(hashtext('zoop-briefing-server-v1')) AS owned").fetchone()['owned']:continue
                try:
                    active=conn.execute("SELECT 1 FROM briefing_attempts WHERE round_id=%s AND status IN ('queued','running','verifying') AND lease_until>now()",(r['id'],)).fetchone()
                    if not active:
                        complete=server.published(conn,existing)
                        state='completed' if complete else 'requires_recovery'
                        journal=Journal(cfg,r['id'])
                        if not complete:
                            latest=conn.execute('SELECT status FROM briefing_attempts WHERE round_id=%s ORDER BY attempt_no DESC LIMIT 1',(r['id'],)).fetchone()
                            if latest is None or latest['status']=='completed':
                                server.record_input_failure(cfg,r,journal.root,stage='collection' if latest is None else 'generation',reason='interrupted_slot_not_resent')
                        conn.execute("UPDATE briefing_common_schedule_jobs SET status=%s,finished_at=now() WHERE id=%s AND status IN ('queued','running')",(state,r['id']))
                        journal('slot','completed' if complete else 'requires_recovery',{'reason':'saved_publication' if complete else 'interrupted_slot_not_resent'})
                finally:conn.execute("SELECT pg_advisory_unlock(hashtext('zoop-briefing-server-v1'))")
                continue
            if left<=10*60:
                # A late boot cannot turn old graph data into a newly collected round.
                if not conn.execute("SELECT pg_try_advisory_lock(hashtext('zoop-briefing-server-v1')) AS owned").fetchone()['owned']:continue
                try:
                    inserted=conn.execute("INSERT INTO briefing_common_schedule_jobs(id,round_date,edition,scheduled_at,window_from,status,finished_at) VALUES(%s,%s,%s,%s,%s,'requires_recovery',now()) ON CONFLICT(round_date,edition) DO NOTHING RETURNING id",(r['id'],instant.date(),edition,slot,datetime.fromisoformat(r['windowFrom']))).fetchone()
                    if inserted:
                        journal=Journal(cfg,r['id']);server.record_input_failure(cfg,r,journal.root,stage='collection',reason='collection_window_missed')
                        journal('slot','requires_recovery',{'reason':'collection_preparation_window_missed'})
                finally:conn.execute("SELECT pg_advisory_unlock(hashtext('zoop-briefing-server-v1'))")
                continue
            try:(run or run_slot)(cfg,edition,now=now)
            except ValueError as error:
                if str(error)!='briefing_server_another_briefing_writer':raise
            return True
    if cfg.get('selectedWorkerConfig'):
        import briefing_selected_generation as selected
        return selected.work_once(validate_selected_config(cfg))
    return False


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--once',action='store_true');args=p.parse_args()
    server.require(not args.config.is_symlink() and args.config.stat().st_mode&0o077==0,'private_config')
    cfg=json.loads(args.config.read_bytes());config_check(cfg)
    while True:
        try:work_once(cfg)
        except Exception as error:print(json.dumps({'schemaVersion':VERSION,'status':'requires_recovery','errorType':type(error).__name__}),flush=True)
        if args.once:return
        time.sleep(30)
if __name__=='__main__':main()
