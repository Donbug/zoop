"""Synthetic provider -> real fenced publisher integration driver. No network/model key access."""
import json,os,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import briefing_server_runtime as runtime
import briefing_priority_server as producer
from test_briefing_priority_generation import Transport
root=Path(sys.argv[1]).resolve();classpath=sys.argv[2];edition=sys.argv[3]
transport=Transport();runtime.b.authenticated_transport=lambda key:transport
java=[os.environ['JAVA'],'-cp',classpath]
cfg={'work':str(root/'work'),'authorizationRef':'synthetic-priority-test','keyFile':str(root/'never-read-key'),
     'priorityContract':producer.priority.VERSION,
     'serverCommand':java+['com.zoop.briefing.server.BriefingServerCommand'],
     'ledgerCommand':java+['com.zoop.briefing.usage.BriefingUsageCommand','--stdio']}
job={'id':'brf-2026-11-02-'+edition,'round_date':'2026-11-02','edition':edition,
     'scheduled_at':datetime.fromisoformat('2026-11-02T01:03:03+00:00'),
     'window_from':datetime.fromisoformat('2026-10-07T00:00:00+00:00')}
result=producer.produce(cfg,job)
assert result['status']=='published'
assert len(transport.requests)==10,len(transport.requests)
print(json.dumps({'syntheticCalls':len(transport.requests),'mode':'priority'}))
