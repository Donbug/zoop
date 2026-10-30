"""Compile verified PERSONAL AI revisions to append-only SQL; never updates a shared publication."""
import argparse
import json
from pathlib import Path
import briefing_personal_ai as p
import briefing_issue_intelligence_view as receipt_view


def sql(member_id, recorded, calls):
    generation,verification=p.prove_record(recorded,calls)
    proofs=[]
    for key in (generation,verification):
        call=next(c for c in calls if c['key']==key)
        raw_request=call['_request'];raw_response=call['_response']
        proofs.append({'request':raw_request.decode(),'response':raw_response.decode(),
            'requestSha256':p.b.digest(raw_request),'responseSha256':p.b.digest(raw_response)})
    result=recorded['result'];data={'basis':result['selectionBasis'],'frozen':recorded['frozen'],'result':result,'proof':proofs}
    text=p.b.canonical(data).decode();tag='$personal_ai_'+p.b.digest(text.encode())[:16]+'$';mid=member_id.replace("'","''")
    return ("INSERT INTO briefing_personal_analyses(member_id,round_id,result_version,selection_basis,input_snapshot,result,result_sha256,provider_proof)\n"
        f"SELECT '{mid}',p->'result'->>'roundId',p->'result'->>'resultVersion',p->'basis',p->'frozen',p->'result',"
        "encode(sha256(convert_to((p->'result')::text,'UTF8')),'hex'),p->'proof'\n"
        f"FROM (SELECT {tag}{text}{tag}::jsonb p) value\n"
        f"WHERE EXISTS(SELECT 1 FROM members WHERE id='{mid}' AND status='active') "
        "AND EXISTS(SELECT 1 FROM briefing_personal_pools WHERE round_id=p->'result'->>'roundId' AND input_sha256=p->'basis'->>'poolVersion')\n"
        "ON CONFLICT(member_id,result_version) DO NOTHING;\n")


def calls_from(folders):
    calls=[]
    for folder in folders:
        for c in receipt_view.verified_calls(folder):
            root=Path(folder)/'calls';c['_request']=p.b.regular(root/(c['key']+'.request.json'))
            c['_response']=p.b.regular(root/(c['key']+'.response.json'));calls.append(c)
    return calls


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--member-id',required=True)
    parser.add_argument('--calls',type=Path,action='append',required=True);parser.add_argument('--record',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    calls=calls_from(args.calls);p.b.private_dir(args.output)
    for path in args.record:
        saved=p.b.strict_load(p.b.regular(path))
        if saved['status']!='PASS':raise ValueError('unverified_personal_revision_not_imported')
        p.b.write_once(args.output/(path.stem+'.sql'),sql(args.member_id,saved,calls).encode())

if __name__=='__main__':main()
