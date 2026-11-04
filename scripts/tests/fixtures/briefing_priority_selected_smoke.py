"""Authored selected-worker test using a dedicated test DB and synthetic provider only."""
import hashlib,json,os,sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[2]));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
import briefing_selected_generation as worker
import briefing_server_runtime as runtime
from test_briefing_priority_generation import Transport
root=Path(sys.argv[1]).resolve();classpath=sys.argv[2];job_id=sys.argv[3]
u=urlsplit(os.environ['DB_URL'].removeprefix('jdbc:'));schema=parse_qs(u.query)['currentSchema'][0]
dsn='postgresql://company_test@127.0.0.1:'+str(u.port)+u.path+'?'+urlencode({'options':'-csearch_path='+schema})
transport=Transport();runtime.b.authenticated_transport=lambda key:transport
java=[os.environ['JAVA'],'-cp',classpath]
with psycopg.connect(dsn,autocommit=True) as conn:
    cfg={'work':str(root/'selected-work'),'task':'synthetic-priority-selected','dsn':dsn,'keyFile':str(root/'never-read-key'),
        'grants':os.environ['ZOOP_DOCUMENT_READ_GRANTS'],'priorityContract':'priority-business-producer-v1',
        'authorizationRef':'synthetic-priority-test','serverBudgetWork':str(root/'work'),
        'serverLedgerCommand':java+['com.zoop.briefing.usage.BriefingUsageCommand','--stdio']}
    Path(cfg['work']).mkdir(mode=0o700)
    conn.execute("UPDATE briefing_selected_generation_jobs SET status='running' WHERE id=%s AND status='queued'",(job_id,))
    worker.process(conn,cfg,job_id)
    assert conn.execute('SELECT status FROM briefing_selected_generation_jobs WHERE id=%s',(job_id,)).fetchone()[0]=='ready'
    assert len(transport.requests)==4,len(transport.requests)
    # The same completed queue item cannot dispatch another request.
    worker.process(conn,cfg,job_id);assert len(transport.requests)==4
print(json.dumps({'syntheticCalls':len(transport.requests),'mode':'priority-selected'}))
