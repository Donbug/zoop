"""Render task-local private config from ECS Secret environment; never print secret values."""
import json,os,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit
import briefing_server_runtime as runtime

def private_file(path,text):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)

def main():
    if sys.argv[1:]==['--check']:
        assert runtime.b.MODEL=='gpt-6-luna'
        print('briefing-runtime-image-ready');return
    if os.environ.get('BRIEFING_SERVER_ENABLED')!='true':raise ValueError('explicit_server_enable_required')
    temp=Path(tempfile.mkdtemp(prefix='zoop-briefing-',dir='/tmp'))
    key=os.environ.pop('OPENAI_API_KEY')
    if not key or any(c.isspace() for c in key):raise ValueError('provider_key_format')
    private_file(temp/'provider-key','OPENAI_API_KEY='+key+'\n')
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
    private_file(temp/'config.json',json.dumps(cfg))
    sys.argv=['briefing_server_runtime','--config',str(temp/'config.json')]
    runtime.main()

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('briefing-runtime-stopped:'+type(error).__name__,file=sys.stderr);raise SystemExit(1)
