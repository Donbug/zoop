"""Synthetic replies only -> real selection preview, usage ledger, cached selection and publisher."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_server_runtime as runtime
import briefing_selection_gate as gate
import briefing_priority_server as producer
from test_briefing_priority_generation import Transport

root=Path(sys.argv[1]).resolve(); classpath=sys.argv[2]
request=json.loads(Path(os.environ['SYNTHETIC_SELECTION_REQUEST']).read_bytes()); round_=request['round']
transport=Transport(); runtime.b.authenticated_transport=lambda key: transport
java=[os.environ['JAVA'],'-cp',classpath]
cfg={'work':str(root/'work'),'authorizationRef':'synthetic-selection-test','keyFile':str(root/'never-read-key'),
     'priorityContract':producer.priority.VERSION,'roundCallLimit':32,'nativeCallLimit':24,
     'sharePriorityAnalysis':True,'selectionContinuation':True,
     'serverCommand':java+['com.zoop.briefing.server.BriefingServerCommand'],
     'ledgerCommand':java+['com.zoop.briefing.usage.BriefingUsageCommand','--stdio']}
candidate=root/'work/native'/round_['id']/'candidates-v3/synthetic-native-v2'
# Test-owned fast provider needs no 180-second network window. Java still enforces the real cutoff.
candidate.mkdir(parents=True)
prepared=runtime.java(cfg,'prepare-selection',request,candidate/'test-prepare.json')
with patch.object(gate,'dispatch_window'):
    qualified=gate.qualify(cfg,round_,candidate,prepared['graphVersion'])
assert qualified['status']=='ready'
assert len(transport.requests)==2
while (remaining:=(datetime.fromisoformat(round_['windowTo'])-datetime.now(timezone.utc)).total_seconds())>0:
    time.sleep(min(1,remaining))
job={'id':round_['id'],'round_date':round_['date'],'edition':round_['edition'],
     'scheduled_at':datetime.fromisoformat(round_['scheduledAt']), 'window_from':datetime.fromisoformat(round_['windowFrom'])}
result=producer.produce({**cfg,'qualifiedProducerWork':qualified['producerWork'],'expectedGraphVersion':prepared['graphVersion']},job)
assert result['status']=='published'
assert len(transport.requests)==8,len(transport.requests)
assert len(list((root/'work/budget').glob('*.json')))==8
print(json.dumps({'syntheticPhysicalCalls':8,'cachedSelectionCalls':2,'mode':'qualified'}))
