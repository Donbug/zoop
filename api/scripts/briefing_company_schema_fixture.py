#!/usr/bin/env python3
"""Export actual Python provider formats for an independent JVM contract test; no provider calls."""
import importlib.util
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('authored_company_reading_schemas',root/'scripts/briefing_company_reading.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
frozen={'targets':[{'companyId':'authored-A'},{'companyId':'authored-B'}],'sources':{'source-b':{},'source-a':{}}}
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
(output/'frozen.json').write_bytes(r.base.canonical(frozen))
for prefix in ('company_outlook_','company_reading_'):
 for phase in ('generation','verification'):
  schema=(r.company.verification_schema(frozen) if phase=='verification' else
          r.company.generation_schema(frozen) if prefix=='company_outlook_' else r.schema(frozen))
  value={'type':'json_schema','name':prefix+phase,'strict':True,'schema':schema}
  (output/(prefix+phase+'.json')).write_bytes(r.base.canonical(value))

frozen['schemaVersion'] = r.SCHEMA_V2
(output/'frozen-v2.json').write_bytes(r.base.canonical(frozen))
for phase in ('generation','verification'):
 schema = r.schema(frozen) if phase == 'generation' else r.verification_schema(frozen)
 (output/('company_reading_v2_'+phase+'.json')).write_bytes(r.base.canonical({'type':'json_schema','name':'company_reading_'+phase,'strict':True,'schema':schema}))
