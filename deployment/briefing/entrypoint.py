"""Render task-local private config from ECS Secret environment; never print secret values."""
import json,os,re,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit
import briefing_server_runtime as runtime

def private_file(path,text):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)

def main():
    if sys.argv[1:]==['--check']:
        assert runtime.b.MODEL=='gpt-6-luna'
        import briefing_auto_chain,briefing_priority_generation
        assert all(briefing_priority_generation.prompt_for(stage).is_file() for stage in ('priority-common','priority-personal','priority-summary'))
        print('briefing-runtime-image-ready');return
    if os.environ.get('BRIEFING_SERVER_ENABLED')!='true':raise ValueError('explicit_server_enable_required')
    temp=Path(tempfile.mkdtemp(prefix='zoop-briefing-',dir='/tmp'))
    key=os.environ.pop('OPENAI_API_KEY')
    if not key or any(c.isspace() for c in key):raise ValueError('provider_key_format')
    private_file(temp/'provider-key','OPENAI_API_KEY='+key+'\n')
    if os.environ.get('TYPESAFE_API_KEY'):
        verifier=os.environ.pop('TYPESAFE_API_KEY')
        if not verifier or any(c.isspace() for c in verifier):raise ValueError('verifier_key_format')
        private_file(temp/'verifier-key','TYPESAFE_API_KEY='+verifier+'\n')
    endpoint=urlsplit(os.environ['DB_URL'].removeprefix('jdbc:'))
    dsn={'host':endpoint.hostname,'port':endpoint.port or 5432,'dbname':endpoint.path.lstrip('/'),
         'user':os.environ['DB_USERNAME'],'password':os.environ['DB_PASSWORD'],'application_name':'zoop-briefing-server-v1'}
    # Psycopg keyword conninfo rendering handles passwords without interpolation into a shell or URL.
    from psycopg.conninfo import make_conninfo
    launcher=['java','-Xms32m','-Xmx256m','-cp','/opt/zoop/briefing/app.jar']
    cfg={'enabled':True,'dsn':make_conninfo(**dsn),'work':os.environ['BRIEFING_SERVER_WORK_ROOT'],
         'keyFile':str(temp/'provider-key'),'authorizationRef':os.environ['BRIEFING_SERVER_AUTHORIZATION_REF'],
         'serverCommand':launcher[:3]+['-Dloader.main=com.zoop.briefing.server.BriefingServerCommand']+launcher[3:]+['org.springframework.boot.loader.launch.PropertiesLauncher'],
         'ledgerCommand':launcher[:3]+['-Dloader.main=com.zoop.briefing.usage.BriefingUsageCommand']+launcher[3:]+['org.springframework.boot.loader.launch.PropertiesLauncher','--stdio'],
         'inputGraceSeconds':1800}
    cfg.update({'companyCatalogue':'/opt/zoop/briefing/company-catalogue.json',
        'authorityRoot':os.environ.get('BRIEFING_SERVER_AUTHORITY_ROOT','/mnt/zoop-artifacts/briefing_server_authority'),
        'originalSourceAuthority':'/mnt/zoop-authority/serving-authorities.json','verifierKeyFile':str(temp/'verifier-key'),
        'nativeCommand':launcher[:3]+['-Dloader.main=com.zoop.briefing.server.BriefingNativeCommand']+launcher[3:]+['org.springframework.boot.loader.launch.PropertiesLauncher']})
    os.environ.update({'ZOOP_STATE_DIR':'/tmp/zoop-unused-app-state','ZOOP_AI_WORKER_STATE_DIR':'/tmp/zoop-unused-ai-worker-state'})
    if os.environ.get('BRIEFING_AUTO_CHAIN_ENABLED')=='true':
        import briefing_auto_chain
        cfg.update({'autoChain':briefing_auto_chain.VERSION,'priorityContract':'priority-business-producer-v1','nativeCallLimit':6,'additiveGraphAllowed':os.environ.get('BRIEFING_SERVER_ADDITIVE_GRAPH_ALLOWED')=='true'})
        if not (temp/'verifier-key').exists():raise ValueError('native_verifier_required')
        cfg['originalSourceAuthority']=os.environ['BRIEFING_ORIGINAL_SOURCE_AUTHORITY']
        cfg['originalReadGrants']=os.environ['BRIEFING_ORIGINAL_READ_GRANTS']
        authority=Path(cfg['authorityRoot'])
        if str(authority/'serving-delegates.json')==cfg['originalSourceAuthority'] or str(authority/'serving-grants.json')==cfg['originalReadGrants']:raise ValueError('authority_self_delegation')
        if sys.argv[1:]==['--initialize-authority']:
            import briefing_native_intake
            briefing_auto_chain.config_check(cfg);briefing_native_intake.initialize_authority(cfg)
            print('briefing-source-authority-initialized');return
        os.environ.update({'ZOOP_DOCUMENT_READ_INGESTION_SOURCES':str(authority/'serving-delegates.json'),'ZOOP_DOCUMENT_READ_GRANTS':str(authority/'serving-grants.json'),'BRIEFING_SERVER_SOURCE_SCOPE':str(authority/'model-scope.json')})
        cfg['selectedWorkerConfig']=os.environ['BRIEFING_SELECTED_WORKER_CONFIG']
        briefing_auto_chain.validate_selected_config(cfg)
        if sys.argv[1:]:
            if len(sys.argv)==3 and sys.argv[1]=='--slot' and sys.argv[2] in ('morning','evening'):
                briefing_auto_chain.run_slot(cfg,sys.argv[2]);return
            raise ValueError('auto_chain_slot_arguments')
        private_file(temp/'config.json',json.dumps(cfg))
        sys.argv=['briefing_auto_chain','--config',str(temp/'config.json')]
        briefing_auto_chain.main();return
    if sys.argv[1:]==['--initialize-authority']:
        import briefing_native_intake
        briefing_native_intake.initialize_authority(cfg);print('briefing-source-authority-initialized');return
    if len(sys.argv)>2 and sys.argv[1] in ('--slot','--recover-unpaid-slot') and sys.argv[2] in ('morning','evening'):
        import briefing_native_intake,signal
        def timeout(signum,frame):raise TimeoutError('finite_slot_execution_limit')
        signal.signal(signal.SIGALRM,timeout);signal.alarm(45*60)
        cutoff=sys.argv[4] if len(sys.argv)==5 and sys.argv[3]=='--cutoff' else None
        if len(sys.argv) not in (3,5) or (len(sys.argv)==5 and sys.argv[3]!='--cutoff'):raise ValueError('slot_arguments')
        briefing_native_intake.run_slot(cfg,sys.argv[2],cutoff,recover_unpaid=sys.argv[1]=='--recover-unpaid-slot');return
    private_file(temp/'config.json',json.dumps(cfg))
    sys.argv=['briefing_server_runtime','--config',str(temp/'config.json')]
    runtime.main()

if __name__=='__main__':
    try:main()
    except Exception as error:
        scope='temporary' if str(getattr(error,'filename','')).startswith('/tmp/') else 'artifact' if str(getattr(error,'filename','')).startswith('/mnt/zoop-artifacts') else 'state' if str(getattr(error,'filename','')).startswith('/mnt/zoop-briefing') else 'other'
        code=str(error) if isinstance(error,ValueError) and re.fullmatch(r'briefing_server_[a-z0-9_]{1,150}',str(error)) else None
        print('briefing-runtime-stopped:'+type(error).__name__+':scope='+scope+':errno='+str(getattr(error,'errno',None))+':code='+str(code),file=sys.stderr);raise SystemExit(1)
