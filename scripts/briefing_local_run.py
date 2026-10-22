#!/usr/bin/env python3
"""Explicit one-round local execution. Offline by default; never merges or deploys."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

import briefing_replay as base
import briefing_local_window as local
ROOT=Path(__file__).resolve().parents[1]

def command(args,log,env=None):
    with log.open("ab") as stream:
        os.chmod(log,0o600)
        result=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:raise base.ReplayError("local_stage_failed_"+log.stem)

def create_database(args):
    if not args.database.startswith("zoop_briefing_replay_local_") or not args.database.replace("_","").isalnum():
        raise base.ReplayError("dedicated_local_database_required")
    import psycopg
    from psycopg import sql
    with psycopg.connect(host="127.0.0.1",port=args.pg_port,dbname="postgres",user=args.pg_user,autocommit=True) as db:
        if not db.execute("select 1 from pg_database where datname=%s",(args.database,)).fetchone():
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.database)))

def free_port(port):
    with socket.socket() as sock:sock.bind(("127.0.0.1",port))

def start(args,work,jar,common,env,round_id):
    runtime=work/"runtime.json"
    if runtime.exists():
        saved=base.strict_load(base.regular(runtime))
        if saved.get("roundId")!=round_id:raise base.ReplayError("local_runtime_identity_changed")
        return saved
    free_port(args.api_port);free_port(args.web_port)
    api_log=(work/"api.log").open("ab");os.chmod(work/"api.log",0o600)
    api=subprocess.Popen([str(Path(args.java_home)/"bin/java"),"-jar",str(jar),*common,
        "--server.address=127.0.0.1","--server.port="+str(args.api_port),
        "--zoop.briefing.replay.read-enabled=true"],cwd=ROOT,env=env,stdout=api_log,stderr=subprocess.STDOUT)
    api_log.close()
    target="http://127.0.0.1:"+str(args.api_port)+"/api/v1/briefings/"+round_id+"/graph"
    for _ in range(90):
        if api.poll() is not None:raise base.ReplayError("local_api_start_failed")
        try:
            with urllib.request.urlopen(target,timeout=2) as res:
                value=json.load(res)
                if value.get("status")=="available":break
        except Exception:time.sleep(1)
    else:raise base.ReplayError("local_graph_http_unavailable")
    node_modules=ROOT/"web/node_modules"
    if not node_modules.exists():
        if not args.node_modules:raise base.ReplayError("node_modules_path_required")
        node_modules.symlink_to(Path(args.node_modules).resolve(),target_is_directory=True)
    web_env={k:v for k,v in os.environ.items() if not any(word in k for word in ("API_KEY","TOKEN","SECRET","PASSWORD"))}
    web_env["ZOOP_DEV_API_TARGET"]="http://127.0.0.1:"+str(args.api_port)
    web_log=(work/"web.log").open("ab");os.chmod(work/"web.log",0o600)
    web=subprocess.Popen([str(node_modules/".bin/vite"),"--host","127.0.0.1","--port",str(args.web_port),"--strictPort"],
        cwd=ROOT/"web",env=web_env,stdout=web_log,stderr=subprocess.STDOUT);web_log.close()
    value={"roundId":round_id,"database":args.database,"apiPort":args.api_port,"webPort":args.web_port,
        "apiPid":api.pid,"webPid":web.pid,"briefingUrl":"http://127.0.0.1:"+str(args.web_port)+"/briefing?reading=compact",
        "mapUrl":"http://127.0.0.1:"+str(args.web_port)+"/?round="+round_id,
        "mode":local.MODE,"productionAuthorized":False}
    base.save_json(runtime,value)
    return value

def run(args):
    work=Path(args.output).resolve()
    plan={"mode":local.MODE,"output":str(work),"maximumNewModelCalls":args.max_calls,
        "database":args.database,"stages":["collect","extract_and_group","select_and_generate_and_verify","database_import","graph_register","http_and_frontend"],
        "productionAuthorized":False,"automaticPublication":False}
    if not args.execute:return {**plan,"status":"OFFLINE","newPaidCalls":0}
    if not (1<=args.max_calls<=40):raise base.ReplayError("local_call_budget_invalid")
    base.private_dir(work);base.private_dir(work/"logs")
    env={k:v for k,v in os.environ.items() if not any(word in k for word in ("API_KEY","TOKEN","SECRET","PASSWORD"))}
    env["PYTHONDONTWRITEBYTECODE"]="1"
    env["PYTHONPATH"]=str(ROOT/"ai/pipeline/src")
    collected=work/"collection";summary=collected/"collection-summary.json"
    if not summary.exists():
        command([sys.executable,ROOT/"scripts/briefing_live_collection.py","--output",collected,"--companies",args.companies,
            "--search-key-file",args.search_key_file,"--window-from",args.window_from,"--discovery-to",args.discovery_to,
            "--authorization-ref",args.authorization_ref,"--edition",args.edition],work/"logs/collection.log",env)
    collection=base.strict_load(base.regular(summary))
    if collection["status"]!="COMPLETE" or collection["documents"]==0:raise base.ReplayError("local_no_verified_sources")
    local.load(collected/"round-spec.json",base.digest(base.regular(collected/"sources.jsonl")))
    grouping=work/"grouping";rounds=work/args.round_output
    prior = {p.stem.removesuffix(".pending") for p in work.glob("rounds*/calls/*.pending.json") if p.parent.parent != rounds}
    current = {p.stem.removesuffix(".pending") for p in (grouping/"calls").glob("*.pending.json")}
    phase_limit = args.max_calls - len(prior-current)
    if phase_limit <= 0: raise base.ReplayError("local_prior_calls_exhausted_budget")
    common_py=["--sources",collected/"sources.jsonl","--clocks",collected/"clocks.json","--round-spec",collected/"round-spec.json",
        "--user-inbox-ref",args.authorization_ref,"--max-calls",str(phase_limit),"--execute-authorized","--key-file",args.key_file]
    command([sys.executable,ROOT/"scripts/briefing_issue_pipeline.py","--poc-root",args.poc_root,"--seed",args.seed,
        "--companies",args.companies,"--output",grouping,"--batch-size","12","--comparison-batch-size","8","--workers","2",
        "--comparison-wire","article-catalog-v1","--company-projection","canonical-evidence-v1",*common_py],work/"logs/grouping.log",env)
    command([sys.executable,ROOT/"scripts/briefing_grouped_run.py","--archive",grouping/"grouped-issues.json","--output",rounds,
        "--max-repairs","1","--publication-catalog",args.publication_catalog,*common_py],work/"logs/briefing.log",env)
    bundle=base.strict_load(base.regular(rounds/"bundle-v2.json"))
    row=bundle["rounds"][0]
    if len(bundle["rounds"])!=1 or row["selectionStatus"]!="SELECTED":raise base.ReplayError("local_round_withheld")
    env["JAVA_HOME"]=args.java_home
    command([ROOT/"api/gradlew","-p",ROOT/"api","bootJar","--console=plain"],work/"logs/build.log",env)
    jar=next(p for p in (ROOT/"api/build/libs").glob("*.jar") if not p.name.endswith("-plain.jar"))
    create_database(args)
    base.private_dir(work/"artifacts")
    csrf=work/".csrf-key"
    if not csrf.exists():base.write_once(csrf,secrets.token_urlsafe(32).encode())
    env["ZOOP_AUTH_CSRF_ACTIVE_KEY_ID"]="local119"
    env["ZOOP_AUTH_CSRF_KEYS"]="local119="+csrf.read_text()
    env["ZOOP_AUTH_ALLOWED_ORIGINS"]="http://127.0.0.1:"+str(args.web_port)
    jdbc="jdbc:postgresql://127.0.0.1:"+str(args.pg_port)+"/"+args.database
    common=["--spring.profiles.active=local","--spring.datasource.url="+jdbc,
        "--spring.datasource.username="+args.pg_user,"--spring.datasource.password=",
        "--spring.datasource.hikari.maximum-pool-size=3","--spring.datasource.hikari.minimum-idle=1",
        "--zoop.briefing.replay.manifest="+str(work/"manifest.json"),"--zoop.document-read.grants="+str(work/"grants.json"),
        "--zoop.document-read.artifact-root="+str(work/"artifacts"),
        "--zoop.graph.snapshot.source=artifact","--zoop.graph.snapshot.artifact-root="+str(work/"artifacts")]
    command([Path(args.java_home)/"bin/java","-jar",jar,*[a for a in common if not a.startswith("--zoop.document-read.grants=")],
        "--zoop.document-read.grants=","--spring.main.web-application-type=none",
        "--zoop.briefing.replay.import-enabled=true","--zoop.briefing.replay.source="+str(collected/"sources.jsonl"),
        "--zoop.briefing.replay.bundle="+str(rounds/"bundle-v2.json"),"--zoop.briefing.replay.artifact-root="+str(work/"artifacts"),
        "--zoop.briefing.replay.grants="+str(work/"grants.json"),
        "--zoop.briefing.replay.expected-source-sha256="+bundle["sourceFileSha256"],
        "--zoop.briefing.replay.user-inbox-ref="+args.authorization_ref,
        "--zoop.briefing.replay.clocks="+str(collected/"clocks.json"),
        "--zoop.briefing.replay.maximum-paid-calls="+str(args.max_calls)],work/"logs/import.log",env)
    command([Path(args.java_home)/"bin/java","-jar",jar,*common,"--spring.main.web-application-type=none",
        "--server.address=127.0.0.1","--zoop.briefing.replay.read-enabled=true",
        "--zoop.briefing.graph-reconstruction.enabled=true"],work/"logs/graph.log",env)
    result={**plan,"status":"COMPLETE","roundId":row["roundId"],"selectedIssues":len(row["selected"]),
        "documents":collection["documents"],"modelReservations":len(prior | {p.stem.removesuffix(".pending") for p in (rounds/"calls").glob("*.pending.json")})}
    if args.serve:result["runtime"]=start(args,work,jar,common,env,row["roundId"])
    base.save_json(work/"completed.json",result)
    return result

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for field in ["output","companies","poc-root","seed","search-key-file","key-file","window-from","discovery-to","authorization-ref","java-home"]:
        p.add_argument("--"+field,required=True)
    p.add_argument("--max-calls",type=int,default=40)
    p.add_argument("--database",required=True)
    p.add_argument("--pg-port",type=int,default=55496);p.add_argument("--pg-user",default="company_test")
    p.add_argument("--api-port",type=int,default=18119);p.add_argument("--web-port",type=int,default=13119)
    p.add_argument("--edition",choices=["morning","evening"],default="evening")
    p.add_argument("--node-modules")
    p.add_argument("--publication-catalog",default=str(ROOT/"api/src/main/resources/company/demo-companies.json"))
    p.add_argument("--round-output",default="rounds")
    p.add_argument("--execute",action="store_true");p.add_argument("--serve",action="store_true")
    return p

if __name__=="__main__":
    try:print(json.dumps(run(parser().parse_args()),ensure_ascii=False),flush=True)
    except Exception as exc:
        print(json.dumps({"status":"FAILED","code":str(exc) if isinstance(exc,base.ReplayError) else type(exc).__name__}),flush=True)
        raise SystemExit(1)
