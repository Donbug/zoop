"""실제 UI 조작으로 PNG·좌표·클릭 결과를 저장한다. 의존성은 uv 일회성 실행."""
from pathlib import Path
import argparse, json, re, time, os, subprocess, shutil, urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'captures'
OUT.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://plan.localhost:5194')
parser.add_argument('--manage-servers', action='store_true')
parser.add_argument('--with-admin-containers', action='store_true')
parser.add_argument('--slides', nargs='+', choices=[s['id'] for s in json.loads((OUT/'manifest.json').read_text()) if not s['id'].startswith('A-')], help='지정 일반 화면만 다시 캡처하고 나머지 이미지와 metadata를 보존한다')
parser.add_argument('--state-source', type=Path, default=ROOT/'prototype/bff/var', help='읽기 전용 원본 상태. 부분 캡처에서는 발행 회차도 그대로 복사한다')
args = parser.parse_args()
slides = []
processes = []
started_containers=[]
DETAILS=json.loads((OUT/'screen-details.json').read_text())
click_history=[]
previous_manifest=json.loads((OUT/'manifest.json').read_text())
previous_records={s['id']:s for s in previous_manifest}
if args.slides:
    for s in previous_manifest:
        if s.get('pair'):
            previous_records[s['id']+'-before']=s
            previous_records[s['id']+'-after']=json.loads((OUT/s['pair'].replace('.png','.json')).read_text())
old_history=json.loads((OUT/'interaction-history.json').read_text()) if args.slides else []
api_calls=[]
tracked_contexts=set()
isolated_state=None


def ready(url):
    for _ in range(120):
        try:
            urllib.request.urlopen(url, timeout=2).close()
            return
        except Exception:
            time.sleep(.5)
    raise RuntimeError(f'서버 준비 실패: {url}')


def start_servers():
    global isolated_state
    import sqlite3, tempfile
    target = Path(tempfile.mkdtemp(prefix='zoop-screen-plan-'))
    isolated_state=target
    # SQLite backup API는 WAL을 포함한 일관된 읽기 사본을 만든다. 원본은 수정하지 않는다.
    shutil.copytree(args.state_source/'graph', target/'graph')
    with sqlite3.connect(f'file:{args.state_source/"zoop-admin.sqlite3"}?mode=ro', uri=True) as source_db:
        with sqlite3.connect(target/'zoop-admin.sqlite3') as target_db:
            source_db.backup(target_db)
    env = os.environ | {'UV_OFFLINE':'1', 'ZOOP_SNAPSHOT_PATH': str(ROOT/'prototype/bff/fixtures/poc-real-inspect.json'), 'ZOOP_COMPANY_CATALOG': str(ROOT/'prototype/bff/fixtures/poc-real-companies.json'), 'ZOOP_BRIEFING_SCHEDULER':'off'}
    if not args.slides:
        # 전체 캡처의 기존 시연 회차 재생성 경로는 유지한다. 부분 캡처에서는 실행하지 않는다.
        rebuilt=target/'replayed'
        subprocess.run(['uv','run','--offline','python','scripts/rebuild_demo_briefings.py','--source',str(target),'--target',str(rebuilt),'--from','2026-09-16'],cwd=ROOT/'prototype/bff',env=env,check=True)
        target=rebuilt
    # 부분 캡처는 기존 발행본을 재생성하지 않는다. 모델 실행이나 관리자 작업도 없다.
    processes.append(subprocess.Popen(['uv','run','--offline','uvicorn','zoop_bff.main:app','--host','127.0.0.1','--port','8824'],cwd=ROOT/'prototype/bff',env=env | {'ZOOP_STATE_DIR':str(target)}, start_new_session=True))
    # pnpm dev의 predev 토큰 생성(소스 쓰기)을 피하고 동일 Vite 서버를 직접 띄운다.
    processes.append(subprocess.Popen(['pnpm','exec','vite','--host','127.0.0.1','--port','5194','--strictPort'],cwd=ROOT/'prototype/web',env=os.environ | {'ZOOP_BFF_URL':'http://127.0.0.1:8824'}, start_new_session=True))
    ready('http://127.0.0.1:8824/api/health')
    ready(args.url+'/login')


def settle(page):
    page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')
    page.mouse.move(1,1)
    page.wait_for_function("""()=>[...document.querySelectorAll('[data-graph-canvas]')].every(e=>{
        let f=e[Object.getOwnPropertyNames(e).find(k=>k.startsWith('__reactFiber$'))],cy=e._cyreg?.cy;
        while(f&&!cy){let h=f.memoizedState;while(h){const v=h.memoizedState?.current;if(v&&typeof v.nodes==='function'&&typeof v.zoom==='function'){cy=v;break;}h=h.next;}f=f.return;}
        return cy&&!cy.animated()&&!cy.nodes().some(n=>n.animated());
    })""",timeout=30000)
    # 그래프·노드 애니메이션 종료 후 LOD idle 140ms보다 길게 기다린다.
    page.wait_for_timeout(750)


def loc(page, role, name, exact=True):
    if role=='css': return page.locator(name).first
    if role=='canvas-node': return CanvasTarget(page,name)
    return page.get_by_role(role,name=name,exact=exact).first


class CanvasTarget:
    """Cytoscape 렌더 좌표를 읽고 실제 마우스 클릭한다(선택 상태를 주입하지 않음)."""
    def __init__(self,page,node_id):
        self.page=page; self.node_id=node_id
    def scroll_into_view_if_needed(self):
        self.page.locator('[data-graph-canvas]').scroll_into_view_if_needed()
    def bounding_box(self):
        return self.page.evaluate("""id=>{
            const e=document.querySelector('[data-graph-canvas]');
            let f=e[Object.getOwnPropertyNames(e).find(k=>k.startsWith('__reactFiber$'))];
            let cy=e._cyreg?.cy;
            while(f&&!cy){let h=f.memoizedState;while(h){const v=h.memoizedState?.current;if(v&&typeof v.nodes==='function'&&typeof v.zoom==='function'){cy=v;break;}h=h.next;}f=f.return;}
            if(!cy)throw Error('실제 캔버스 좌표를 읽을 수 없음');
            const n=cy.getElementById(id),p=n.renderedPosition(),r=e.getBoundingClientRect(),d=n.renderedWidth();
            return {x:r.x+p.x-d/2,y:r.y+p.y-d/2,width:d,height:d};
        }""",self.node_id)
    def click(self):
        b=self.bounding_box();self.page.mouse.click(b['x']+b['width']/2,b['y']+b['height']/2)


def safe_route(url):
    route=url.removeprefix(args.url)
    return '/mock-idp' if route.startswith('/mock-idp') else route


def observed_click(page, element, selector):
    before=page.url.removeprefix(args.url)
    if before.startswith('/mock-idp'): before='/mock-idp'
    element.click()
    settle(page)
    evidence={'selector':selector,'before':before,'url':safe_route(page.url),'visibleText':page.locator('body').inner_text()}
    click_history.append(evidence)
    return evidence


def click(page, role, name, exact=True):
    l=loc(page,role,name,not isinstance(name,re.Pattern) and exact)
    observed_click(page,l,{'role':role,'name':name.pattern if isinstance(name,re.Pattern) else name,'regex':isinstance(name,re.Pattern)})
    return l


def goto(page, route):
    if page.context not in tracked_contexts:
        tracked_contexts.add(page.context)
        page.context.on('request',lambda request: api_calls.append({'method':request.method,'path':urllib.parse.urlsplit(request.url).path}) if '/api/' in urllib.parse.urlsplit(request.url).path else None)
    page.goto(args.url+route)
    settle(page)


# 요구사항 정의서 2026-10-06의 기능 의미 기준(doc-delta §2.2).
REQ={**{f'FS{n:03}':n for n in range(1,28)}, 'FS011-01':11,'FS011-02':11,
     **{f'FS{n:03}':n for n in range(28,37)}, **{f'FS{n:03}':n for n in range(38,50)},
     'FS050-01':50,'FS050-02':50,'FS051':51,'FS052-01':52,'FS052-02':52,'FS053':53,
     'FS054':66,'FS055':67,'FS056':68,'FS058':70,'FS059':71,'FS060':72,'FS061':73,'FS062':74,'FS063':75,'FS064':76,'FS065':77,
     'FS066-01':78,'FS066-02':78,'FS066-03':78,'FS067-01':79,'FS067-02':79,'FS067-03':79,'FS068':80,'FS069-01':81,'FS069-02':81,
     'FS070-01':82,'FS070-02':82,'FS071-01':83,'FS071-02':83,'FS072':84,'FS073':85,
     **{f'NFS{n:03}':n+53 for n in range(1,13)}}
REQ['FS042']=41  # 10-08 시점 관계 그래프. 구 FS042 재무 ID 충돌은 문서에 별도 보존한다.

def control_locator(page, control):
    if control['role']=='css': return page.locator(control['name']).first
    name=re.compile(control['name']) if control.get('regex') else control['name']
    return loc(page,control['role'],name,not control.get('regex',False))


def restore_page(page, url, scroll, inputs):
    page.goto(url); settle(page)
    fields=page.locator('input')
    for n,field in enumerate(inputs):
        if n<fields.count() and field['type'] not in ('checkbox','radio','range','file','hidden','button','submit'):
            target=fields.nth(n)
            if target.is_visible() and target.is_editable(): target.fill(field['value'])
    page.evaluate('([x,y])=>window.scrollTo(x,y)',scroll)
    settle(page)


def probe_control(page, control, sid):
    mode=control['mode']
    if mode=='ref': return {'reference':control['ref'],'selector':control}
    l=control_locator(page,control)
    url=page.url; scroll=page.evaluate('[scrollX,scrollY]')
    inputs=page.locator('input').evaluate_all('(xs)=>xs.map(x=>({type:x.type,value:x.value}))')
    selector={k:control[k] for k in ('role','name','regex') if k in control}
    if mode=='input':
        old=l.input_value()
        l.click()
        value='screen-plan@example.test' if 'email' in (l.get_attribute('type') or '') else '삼성'
        if l.get_attribute('type')=='password': value='Verification-2026!'
        l.fill(value); settle(page)
        proof={'selector':selector,'url':safe_route(page.url),'visibleText':page.locator('body').inner_text(),'inputType':l.get_attribute('type'),'inputWasEntered':True}
        l.fill(old); settle(page)
    elif mode=='disabled':
        assert not l.is_enabled(), (sid,control)
        b=l.bounding_box(); page.mouse.click(b['x']+b['width']/2,b['y']+b['height']/2); settle(page)
        proof={'selector':selector,'url':safe_route(page.url),'visibleText':page.locator('body').inner_text(),'disabled':True}
    elif mode=='popup':
        before_pages=list(page.context.pages)
        href=l.get_attribute('href')
        proof=observed_click(page,l,selector)
        opened=[p for p in page.context.pages if p not in before_pages]
        proof['openedNewWindow']=bool(opened); proof['linkUrl']=href
        for popup in opened:
            proof['externalUrl']=popup.url; popup.close()
    else:
        proof=observed_click(page,l,selector)
        if mode in ('toggle','watch'):
            observed_click(page,control_locator(page,control),selector)
        elif mode=='picked':
            observed_click(page,page.locator(control['restore_css']).first,{'role':'css','name':control['restore_css']})
        elif mode=='undo':
            click(page,control['undo_role'],control['undo_name'])
        elif mode=='escape':
            page.keyboard.press('Escape'); settle(page)
            # details 표는 Escape로 접히지 않으므로 toggle 모드를 사용한다.
        elif mode=='overlay':
            click(page,'button',control['close'])
        elif mode=='overlay_close':
            click(page,control['open_role'],control['open_name'])
        elif mode=='tour':
            page.goto(url); settle(page)
            for _ in range(control['step']-1): click(page,'button','다음')
        else:
            restore_page(page,url,scroll,inputs)
    click_history.append(proof)
    return proof


def state_details(sid):
    family=sid.split('-')[1]
    base=DETAILS['families'][family].copy()
    info=DETAILS['screens'].get(sid,{})
    for k in ('states','source','images'):
        if k in info: base[k]=info[k]
    for path in base['images']:
        assert (ROOT/path).is_file(), path
    if family=='ADM' and '{page}' in base['source']:
        base['source']=base['source'].replace('{page}','dashboard')
    return base

def snap(page, sid, title, fs, entry, states='기본', checks=None, note='', suffix=''):
    if args.slides and sid not in args.slides:
        # 이전 화면은 쓰지 않지만 다음 화면 진입에 필요한 실제 주 조작은 유지한다.
        for role,name,_,_ in checks or []:
            observed_click(page,loc(page,role,name,not isinstance(name,re.Pattern)),{'role':role,'name':name.pattern if isinstance(name,re.Pattern) else name})
        return previous_records[sid+suffix].copy()
    req='·'.join(str(n) for n in sorted({REQ[k] for k in fs.split('·') if k in REQ}))
    settle(page)
    key=sid+suffix
    extras=DETAILS['screens'].get(key,DETAILS['screens'].get(sid,{})).get('controls',[])
    actions=[{'role':role,'name':name.pattern if isinstance(name,re.Pattern) else name,'regex':isinstance(name,re.Pattern),'result':result,'destination':dest,'mode':'primary'} for role,name,result,dest in checks or []]
    actions.extend(extras)
    # 기본 캡처의 주요 동작은 3~6개. 모바일 뒤 화면은 앞 화면 번호에 이어 표시한다.
    offset=len(json.loads((OUT/f'{sid}-before.json').read_text())['markers']) if suffix=='-after' else 0
    if suffix=='-after':
        assert len(actions)+offset<=6,(key,len(actions),offset)
    else:
        assert 3<=len(actions)<=6,(key,len(actions))
    for action in actions[:len(checks or [])]:
        control_locator(page,action).scroll_into_view_if_needed()
    settle(page)
    markers=[]
    for action in actions:
        element=control_locator(page,action)
        b=element.bounding_box()
        if not b or b['x']<0 or b['y']<0 or b['x']+b['width']>page.viewport_size['width']+.5 or b['y']+b['height']>page.viewport_size['height']+.5:
            raise RuntimeError(f'번호 대상이 화면 밖: {key}: {action}: {b}')
        if action['role']!='canvas-node':
            uncovered=element.evaluate('(el)=>{const r=el.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return Boolean(hit&&(el.contains(hit)||hit.contains(el)));}')
            if not uncovered: raise RuntimeError(f'번호 대상이 다른 요소에 가림: {key}: {action}')
        markers.append({'number':offset+len(markers)+1,'selector':{k:action[k] for k in ('role','name','regex') if k in action},'box':b,'result':action['result'],'destination':action['destination'],'mode':action['mode']})
    state=state_details(sid)
    image_path=OUT/f'{key}.png'
    image_bytes=page.screenshot(full_page=False)
    if not image_path.exists() or image_path.read_bytes()!=image_bytes:
        image_path.write_bytes(image_bytes)
    route=page.url.removeprefix(args.url)
    if '/mock-idp' in route: route='/mock-idp'
    visible=page.locator('body').inner_text()
    if states=='기본' and any(text in visible for text in ('불러오지 못했어요','확인하지 못했어요')):
        states='부분 실패 · 받은 영역 유지'
    record={'id':sid,'title':title,'route':route,'viewport':page.viewport_size,'fs':fs,'requirements':req,'entry':entry,'states':state['states'],'capturedState':states,'stateSource':state['source'],'stateImages':state['images'],'note':note,'markers':markers,'image':f'{key}.png','visibleText':visible,'clickEvidence':[]}
    # 사진을 먼저 고정한 뒤 실제 조작한다. 탐색·토글은 원래 상태로 복귀한다.
    for index,action in enumerate(extras,len(checks or [])+1):
        evidence=probe_control(page,action,key)
        if action['mode']=='popup' and not evidence['openedNewWindow']:
            markers[index-1]['result']='원문 링크를 눌렀으나 이 실행에서 새 창 이동은 미관측'
        evidence['number']=offset+index; record['clickEvidence'].append(evidence)
    for index,(role,name,result,dest) in enumerate(checks or [],1):
        name_for=re.compile(name.pattern) if isinstance(name,re.Pattern) else name
        evidence=observed_click(page,loc(page,role,name_for,not isinstance(name,re.Pattern)),{'role':role,'name':name.pattern if isinstance(name,re.Pattern) else name})
        evidence['number']=offset+index; record['clickEvidence'].append(evidence)
    record['clickEvidence'].sort(key=lambda x:x['number'])
    (OUT/f'{key}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    if not suffix:
        slides.append(record)
    print('CAPTURE',key,record['route'],flush=True)
    return record


def member(page):
    goto(page,'/login')
    click(page,'button','로그인')
    page.wait_for_selector('[data-graph-canvas]')
    settle(page)


def select_company(page):
    goto(page,'/?mode=all')
    CanvasTarget(page,'KRX:005930').click()
    settle(page)
    page.get_by_role('link',name='기업 상세',exact=True).wait_for()
    settle(page)


# 관심 종목 추천은 제거됐다(2026-10-10). 검색을 실행한 결과 행을 직접 눌러 고른다.
WATCH_PICKS=[('NVIDIA',['NVIDIA']),('SK',['SK하이닉스']),('삼성',['삼성전자','삼성SDI'])]


def pick_watchlist_by_search(page):
    assert not page.locator('[aria-labelledby="onboarding-recommended"], ul[aria-label="추천 종목"]').count(), '추천 영역이 남아 있음'
    form=page.get_by_role('search',name='종목 검색',exact=True)
    for query,names in WATCH_PICKS:
        form.get_by_placeholder('종목명이나 종목 코드').fill(query)
        observed_click(page,form.get_by_role('button',name='검색',exact=True),{'role':'button','name':'검색','query':query})
        results=page.get_by_role('list',name=f'‘{query}’ 검색 결과',exact=True)
        for name in names:
            observed_click(page,results.get_by_role('button',name=re.compile('^'+re.escape(name))).first,{'role':'button','name':name,'list':f'‘{query}’ 검색 결과'})
    expect(page.get_by_role('button',name='4개 종목으로 시작하기',exact=True)).to_be_visible()
    assert not any(c['path']=='/api/me/recommendations' for c in api_calls), '온보딩이 추천 API를 요청함'


def run_watchlist_only(browser):
    previous=json.loads((OUT/'manifest.json').read_text())
    old_history=json.loads((OUT/'interaction-history.json').read_text()) if (OUT/'interaction-history.json').exists() else []
    context=browser.new_context(viewport={'width':1440,'height':900},device_scale_factor=1,locale='ko-KR',timezone_id='Asia/Seoul',reduced_motion='reduce')
    page=context.new_page();goto(page,'/signup')
    page.get_by_label('이메일',exact=True).fill(f'plan-watch-{time.time_ns()}@example.test')
    page.get_by_label('비밀번호',exact=True).fill('PlanDemo-2026!')
    page.get_by_label('표시 이름',exact=True).fill('화면계획 시연')
    page.get_by_role('checkbox',name='모두 동의',exact=True).check()
    click(page,'button','가입하고 시작하기')
    click(page,'button',re.compile('지금 주식에 투자'))
    click(page,'button','선택한 가상 계좌 연결하기')
    click(page,'button','관심 종목도 고르기')
    pick_watchlist_by_search(page)
    if 'D-WAT-01b' in args.slides:
        snap(page,'D-WAT-01b','관심 종목 4개 선택','FS012','검색 3회 실행 후 결과 행 네 번 선택',states='4개 선택',checks=[('button','NVIDIA 빼기','선택 목록에서 NVIDIA를 빼고 3개로 바꿔요.','D-WAT-01')],note='3개 상한 없이 실제 검색으로 4개를 선택했어요.')
    picked=page.locator('section[aria-labelledby="onboarding-picked"] button')
    while picked.count(): picked.first.click()
    expect(page.get_by_text('고르지 않아도 보유 종목 기준 내 종목 지도로 시작할 수 있어요.',exact=True)).to_be_visible()
    if 'D-WAT-01' in args.slides:
        snap(page,'D-WAT-01','관심 종목 선택','FS011-01·FS012·FS013','모의 보유 3개 연결 후 관심 종목 고르기',states='선택 0개 · 검색 결과',checks=[('button','고르지 않고 지도 보기','관심 0개를 저장하고 보유 종목 기준 내 종목 지도를 열어요.','D-GRP-01b')],note='관심 0개여도 연결한 보유 종목을 기준으로 시작해요. 추천 목록 없이 검색으로만 골라요.')
    assert not any(c['path']=='/api/me/recommendations' for c in api_calls), '온보딩이 추천 API를 요청함'
    updated={s['id']:s for s in slides}
    merged=[updated.get(s['id'],s) for s in previous]
    (OUT/'manifest.json').write_text(json.dumps(merged,ensure_ascii=False,indent=2))
    (OUT/'interaction-history.json').write_text(json.dumps(old_history+click_history,ensure_ascii=False,indent=2))
    (OUT/'targeted-capture.json').write_text(json.dumps({'selected':args.slides,'updated':list(updated),'otherCapturesUnchanged':True,'stateSource':str(args.state_source),'scheduler':'off','modelCalls':0,'adminOperations':0,'recommendationRequests':0,'apiCalls':api_calls},ensure_ascii=False,indent=2))
    context.close()
    print('DONE targeted',','.join(updated),flush=True)


def run(browser):
    context=browser.new_context(viewport={'width':1440,'height':900},device_scale_factor=1,locale='ko-KR',timezone_id='Asia/Seoul',reduced_motion='reduce')
    page=context.new_page()
    goto(page,'/login')
    snap(page, 'D-AUT-01', '시작·이메일 로그인', 'FS001·FS002·FS005·FS006', '세션 없는 시작 화면',checks=[('link','이메일로 회원가입','이메일 가입 폼을 열어요.','D-AUT-02')])
    page.get_by_text('본문 보기',exact=True).first.click()
    snap(page, 'D-AUT-02', '이메일 회원가입', 'FS003·FS006', '시작 화면 → 이메일로 회원가입',checks=[],states='기본 · 필수 약관 본문 미제공',note='이메일 로그인 폼은 D-AUT-01에 통합. 약관 본문은 실제로 준비 중이에요.')
    goto(page,'/login'); click(page,'link','개발용 모의 로그인으로 계속')
    snap(page,'D-AUT-03','개발용 모의 소셜 제공자','FS004·FS061','시작 → 개발용 모의 로그인으로 계속',checks=[('button','취소','동의를 취소하고 시작 화면에 취소 안내를 보여줘요.','D-AUT-01')],note='실제 소셜 IdP가 아니에요. 동의·가입 성공은 이 캡처에서 실행하지 않았어요.')
    goto(page,'/signup')
    # 격리 상태에만 새 회원을 만든다. 실제 계정/서비스 데이터가 아니다.
    page.get_by_label('이메일',exact=True).fill(f'plan-{time.time_ns()}@example.test')
    page.get_by_label('비밀번호',exact=True).fill('PlanDemo-2026!')
    page.get_by_label('표시 이름',exact=True).fill('화면계획 시연')
    page.get_by_role('checkbox',name='모두 동의',exact=True).check()
    click(page,'button','가입하고 시작하기')
    snap(page, 'D-ONB-01', '투자 여부 선택', 'FS008', '가입 성공 후 초기 설정',checks=[('button',re.compile('지금 주식에 투자'), '가상 계좌 선택 단계로 가요.','D-ONB-02')])
    snap(page, 'D-ONB-02', '가상 계좌 연결', 'FS009·FS010·FS062', '투자 중 선택',checks=[('button','선택한 가상 계좌 연결하기','모의 보유 종목을 표시해요.','D-ONB-02')],states='기본 · 모의 데이터',note='실제 증권 계좌가 아니에요.')
    click(page,'button','관심 종목도 고르기')
    pick_watchlist_by_search(page)
    snap(page,'D-WAT-01b','관심 종목 4개 선택','FS012','검색 3회 실행 후 결과 행 네 번 선택',states='4개 선택',checks=[('button','NVIDIA 빼기','선택 목록에서 NVIDIA를 빼고 3개로 바꿔요.','D-WAT-01')],note='3개 상한을 두지 않는 것을 실제 검색 4개 선택으로 확인했어요.')
    picked=page.locator('section[aria-labelledby="onboarding-picked"] button')
    while picked.count(): picked.first.click()
    snap(page, 'D-WAT-01', '관심 종목 선택', 'FS011-01·FS012·FS013', '계좌 연결 후 관심 종목도 고르기',checks=[('button','고르지 않고 지도 보기','관심 0개를 저장하고, 연결한 모의 보유 기준 내 종목 지도를 열어요.','D-GRP-01b')],states='선택 0개 · 검색 결과',note='개수 제한 없음. 추천 목록 없이 검색을 실행해 골라요. 이 캡처에서는 모의 보유 3개가 연결되어 있어요.')
    # 모든 5단계를 실제 다음 버튼으로 열어 보존한다.
    goto(page,'/?mode=all&tour=1')
    for step in range(1,6):
        name='마치기' if step==5 else '다음'
        snap(page, 'D-GRP-T' if step==1 else f'D-GRP-T{step}', f'지도 튜토리얼 {step}/5', 'FS015·FS016', '지도에서 튜토리얼 다시 보기',checks=[('button',name,'다음 단계로 가요.' if step<5 else '완료를 저장하고 튜토리얼을 닫아요.','D-GRP-T' if step<5 else 'D-GRP-01')],note='1 이동 → 2 대상 선택 → 3 영향 경로 → 4 근거 → 5 AI. 다음 버튼으로 단계 확인. 실습 자동 진행은 별도 동작이에요.')
    context.close()
    context=browser.new_context(viewport={'width':1440,'height':900},device_scale_factor=1,locale='ko-KR',timezone_id='Asia/Seoul',reduced_motion='reduce')
    page=context.new_page(); member(page)
    goto(page,'/?mode=all')
    snap(page, 'D-GRP-01', '시장 전체 지도', 'FS018·FS019', '회원 또는 비회원의 전체 지도',checks=[('button','지도 읽는 법','크기·거리는 인과·중요도가 아니라는 설명을 열어요.','D-GRP-01')])
    select_company(page)
    snap(page, 'D-GRP-03', '기업 패널·시세·1개월 추이', 'FS020·FS026·FS027', '지도 삼성전자 노드를 직접 누르기',checks=[],note='아래로 스크롤하면 모의 보유·사건·관련 기업·뉴스를 확인해요. 주요 지표는 기본 접힘이에요.')
    click(page,'link','기업 상세')
    select_company(page)
    # 사건 제목 버튼과 근거 버튼 중 제목을 고른다.
    buttons=page.locator('section[aria-label="직접 이슈"]').get_by_role('button')
    chosen=next(b for b in buttons.all() if not re.search('근거|직접 관련|설명',b.inner_text()) and b.inner_text().strip())
    observed_click(page,chosen,{'role':'button','name':chosen.inner_text().strip()})
    snap(page, 'D-GRP-06', '기업에서 여는 영향 경로', 'FS022·FS024', '기업 패널 → 직접 이슈 제목',checks=[('button',re.compile('근거 .*건 보기'),'인용문과 출처를 근거 창에서 보여줘요.','D-GRP-05')],note='팀 v1.7 D-GRP-06 간선 모달 대신 영향 경로. 사건–기업 선은 표시 전용이에요.')
    snap(page, 'D-GRP-05', '근거 문서 창', 'FS024', '사건·관계·영향 경로의 근거 버튼',checks=[('button','근거 창 닫기','근거 창을 닫고 영향 경로를 유지해요.','D-GRP-06')])
    goto(page,'/?mode=all')
    CanvasTarget(page,'issue-04153e2e4c2a1b58e40a0e57').click(); settle(page)
    snap(page, 'D-GRP-02', '사건 패널', 'FS021·FS024', '지도 사건 노드를 직접 누르기',checks=[('button',re.compile('근거 .*건 보기'),'사건에 연결된 인용문을 열어요.','D-GRP-05')],note='데모에는 실제 모델 판정값이 없어 표시하지 않아요.')
    select_company(page)
    click(page,'button','이 노드 중심으로 보기')
    snap(page,'D-GRP-07b','선택 기업 포커스','FS020','기업 패널 → 이 노드 중심으로 보기',checks=[('button','전체 보기','포커스를 풀고 전체 지도 배치로 돌아가요.','D-GRP-01')],note='삼성전자와 이어진 사건을 중심으로 보여줘요.')
    select_company(page)
    click(page,'button','다른 기업과의 연결 보기')
    target=page.get_by_role('button',name=re.compile('^NVIDIA')).last
    target.click(); settle(page)
    snap(page, 'D-GRP-07', '포커스·두 기업 사이 경로', 'FS020·FS023', '기업 패널 → 다른 기업과의 연결 보기 → NVIDIA',checks=[('button','전체 보기','두 기업 경로를 풀고 전체 지도를 보여줘요.','D-GRP-01')],note='경로는 실제 사건을 거쳐요. 주가의 원인·영향 크기가 아니에요.')
    # 연결선은 기업 패널의 관련 기업 행에서 실제로 연다.
    select_company(page)
    related=page.locator('section[aria-label="관련 기업"] li button')
    if not related.count():
        # 사건 공유 섹션의 버튼 접근 이름을 읽어 첫 연결선을 찾는다.
        related=page.locator('aside[aria-label="상세"]').get_by_role('button',name=re.compile('같은 사건|공유 사건'))
    related.first.click(); settle(page)
    snap(page, 'D-GRP-04', '연결선 상세', 'FS023·FS024', '기업 패널의 사건 공유 기업 선택',checks=[('button',re.compile('근거 .*건 보기'),'공유 사건의 근거를 한 창에서 보여줘요.','D-GRP-05')],note='기업 간 사건 공유·사건 간 후속 관계만 선택해요. 공급·경쟁 직결 관계를 만들지 않아요.')
    goto(page,'/companies?q=삼성')
    snap(page,'D-STK-01','종목 메뉴·검색·관심','FS037·FS027','헤더 종목 → 삼성 검색',checks=[('link','삼성전자 기업 상세','선택 기업의 상세 화면으로 이동해요.','D-COM-01')],note='지도 목록 보기를 대체하는 독립 메뉴예요. 비회원도 시장 전체 목록을 볼 수 있어요.')
    goto(page,'/companies/KRX%3A005930')
    snap(page, 'D-COM-01', '기업 상세·시세·모의 보유', 'FS038·FS039·FS040·FS044', '기업 패널 → 기업 상세',checks=[('tab','문서','이 기업 사건의 근거 문서 목록을 보여줘요.','D-COM-02')],note='시세·보유 영역의 출처·기준 시각을 확인해요. 차트·인과관계 고지는 D-COM-01b에서 확인해요.')
    snap(page, 'D-COM-02', '사건 타임라인·문서 탭', 'FS040·FS041·FS043', '기업 상세의 문서 탭',checks=[('tab','사건','기간별 사건 타임라인으로 돌아가요.','D-COM-01')])
    page.get_by_role('radiogroup',name='조회 기간').evaluate('(el)=>window.scrollTo(0,scrollY+el.getBoundingClientRect().top-88)')
    settle(page)
    snap(page,'D-COM-01b','차트·시간 버킷·인과관계 고지','FS040·FS041','기업 상세 사건 탭에서 차트 아래까지 스크롤',checks=[('radio','1년','차트와 사건을 주 단위 버킷의 1년으로 바꿔요.','D-COM-01b')],note='1일/1주/1개월/1년과 해상도를 함께 표시해요. 시점 겹침은 인과관계가 아니에요.')
    detail_route='/companies/KRX%3A005930?period=1m&asOf=2026-09-30T23%3A59%3A59%2B09%3A00&tab=events'
    goto(page,detail_route)
    snap(page,'D-COM-03','기업 상세·좌측 기업 전환','FS038·FS044','기업 상세의 기업 전환 사이드바',checks=[('css','aside[aria-label="기업 전환"] ul[aria-label="보유 기업"] li:nth-child(1) button','기업을 바꾸고 기간·기준 시점·탭은 유지해요.','D-COM-03')],note='검색·보유·관심·최근·연결 기업. 기업 전환 시 사건·버킷 선택은 해제해요.')
    assert '/companies/NASDAQ%3ANVDA' in page.url and 'asOf=2026-09-30' in page.url
    goto(page,detail_route)
    snap(page,'D-COM-04','기업 중심 관계 그래프','FS038·FS040·FS042·FS044','기업 상세 오른쪽 관계 그래프',checks=[('button','지도에서 보기','같은 기업·기준 시점의 지도로 이동해요.','D-GRP-01')],note='FS0??를 FS042 시점 기반 관계 그래프로 정리했어요. 기존 FS042 재무와 ID 충돌은 남아 있어요. asOf 이전 공개 관계만 표시해요.')
    goto(page,detail_route)
    marker=page.get_by_role('group',name='사건이 있었던 시간 버킷').get_by_role('button').first
    marker.wait_for(); marker.scroll_into_view_if_needed(); settle(page)
    marker_name=marker.get_attribute('aria-label')
    snap(page,'D-COM-05','타임라인 버킷·차트·그래프 연동','FS040·FS041·FS042·FS044','차트의 사건 수 표식 선택',checks=[('button',marker_name,'해당 버킷의 사건을 펼치고 차트·관계 그래프에 강조해요.','D-COM-05')],note='FS042는 시점 관계 조회예요. 기존 재무 ID와 충돌은 별도 확인해요. 복수 사건은 합치지 않으며 issue 주소로 복원해요.')
    goto(page,detail_route)
    slider=page.get_by_role('slider',name='차트 기준 시점. 화살표로 이동하고 Enter로 선택해요')
    slider.scroll_into_view_if_needed(); settle(page)
    snap(page,'D-COM-06','차트 시점 선택·asOf 변경','FS040·FS041·FS042·FS044','실제 거래 바를 눌러 공개 기준 시점 변경',checks=[('slider','차트 기준 시점. 화살표로 이동하고 Enter로 선택해요','누른 거래 바의 시각으로 asOf를 바꾸고 관계·사건을 다시 조회해요.','D-COM-06')],note='FS042는 시점 관계 조회예요. 기존 재무 ID와 충돌은 별도 확인해요. period·asOf·tab·issue로 복원하며 최신 시점으로 돌아가요.')
    goto(page,'/design-system#c-price')
    page.locator('#c-price').scroll_into_view_if_needed(); settle(page)
    snap(page,'D-SEN-01','긍부정 표시 규칙·디자인시스템 예시','FS021','디자인시스템의 판정 예시',note='디자인시스템 예시만 캡처했어요. 실제 모델 호출 전이며 데모 기사에는 판정값이 없어요. 중성 글자·아이콘·AI 판정으로 구분하고 주가 등락색·확률을 쓰지 않아요.')
    goto(page,'/design-system#c-briefing')
    page.locator('#c-briefing').scroll_into_view_if_needed(); settle(page)
    snap(page,'D-SEN-02','회차 판단·디자인시스템 예시','FS028·FS029·FS030','디자인시스템 BriefingCard 예시',note='디자인시스템 예시이며 데모 브리핑에는 outlook 값이 없어요. 회차 판단과 사유는 발행 시 고정하며 주가 전망이 아니에요.')
    goto(page,'/me/stocks')
    page.get_by_placeholder('종목명이나 종목 코드').fill('삼성')
    snap(page, 'D-MY-01', '내 종목 관리', 'FS027·FS054·FS062', '회원 → 상단 내 종목',checks=[('button','검색','입력한 이름의 종목 검색 결과를 보여줘요.','D-MY-01')],note='보유는 모의 계좌, 관심은 직접 등록한 목록이에요.')
    # AI 연결·되묻기와 저장된 작업 회수.
    select_company(page); click(page,'button','AI에게 묻기')
    click(page,'button','새 대화')
    snap(page, 'D-AI-01', 'AI 질문·대상 연결', 'FS025·FS045·FS047·FS048', '선택한 기업 → AI에게 묻기 → 새 대화',checks=[('checkbox',re.compile('^삼성전자'),'삼성전자를 질문 연결 대상에서 빼요. 질문 대상이 없음으로 바뀌어요.','D-AI-01')],note='승인된 근거를 사용하는 규칙 기반 예시 답변이에요. 생성형 모델 호출은 없어요.')
    page.get_by_role('textbox',name=re.compile('질문')).fill('그 기업은 언제?')
    click(page,'button','보내기')
    page.get_by_text(re.compile('어느 대상인지 알 수 없어요')).first.wait_for(); settle(page)
    snap(page, 'D-AI-01b', 'AI 되묻기', 'FS047', '불명확한 질문 전송',checks=[],states='대상·기간 확인',note='질문 원문: 그 기업은 언제?')
    page.reload(); settle(page)
    # 재진입에서 같은 대화·작업을 회수한다.
    if page.get_by_role('button',name='AI에게 묻기',exact=True).count():
        click(page,'button','AI에게 묻기')
    snap(page, 'D-AI-02', 'AI 작업 복구·오류 구분', 'FS046·FS049·FS051·FS052-02·FS053·NFS003', '질문 전송 후 새로고침 → AI 재열기',checks=[],states='저장한 대화·되묻기 회수',note='이번 캡처는 복구 상태예요. 기술 오류·허용된 재실행은 캡처하지 않아 결과를 단정하지 않아요.')
    # 실서비스 장애가 아니라 조회 실패 UI를 503으로 재현한다. 질문 작업을 다시 실행하지 않는다.
    page.route('**/api/chat/sessions/current',lambda route:route.fulfill(status=503,content_type='application/json',body='{\"code\":\"temporary_unavailable\",\"message\":\"일시 조회 장애\"}'))
    page.reload(); settle(page); click(page,'button','AI에게 묻기')
    page.get_by_text('이전 대화를 확인하지 못했어요',exact=True).wait_for()
    page.unroute('**/api/chat/sessions/current')
    snap(page,'D-AI-02b','AI 대화 조회 오류·다시 확인','FS053·NFS003','대화 조회 응답을 503으로 재현',states='일시 조회 오류(재현)',checks=[('button','다시 시도','기존 대화를 다시 조회하고 저장한 결과를 회수해요.','D-AI-02')],note='조회 요청만 일시 차단했어요. 새 질문 생성이나 작업 재실행은 하지 않아요.')
    expect(page.get_by_text('이전 대화를 확인하지 못했어요',exact=True)).not_to_be_visible()
    # 관리자: 컨테이너 의존 화면도 실패 상태를 사실대로 남긴다.
    if not args.slides:
        goto(page,'/admin/login')
        page.get_by_label('관리자 이메일',exact=True).fill('admin@zoop.local')
        page.get_by_label('비밀번호',exact=True).fill('zoop-admin')
        snap(page,'A-ADM-05c','관리자 로그인','FS073·NFS001','관리자 세션이 없는 /admin 진입',checks=[('button','관리자 로그인','관리자 세션을 만들고 운영 대시보드로 들어가요.','A-ADM-01')])
        admin=[
            ('A-ADM-01','운영 대시보드','/admin','FS072','이슈 관제'),
            ('A-ADM-02','통계·AI 품질','/admin/stats','FS065','선호도'),
            ('A-ADM-02b','선호도·대화록','/admin/feedback','FS066-02·FS066-03','이슈 관제'),
            ('A-ADM-03','그래프 관제·검수','/admin/pipeline','FS067-01·FS067-02·FS067-03','AI 운영'),
            ('A-ADM-04','AI·브리핑 운영','/admin/briefings','FS070-01·FS070-02·FS071-01·FS071-02','AI 운영'),
            ('A-ADM-04b','AI 사용량·오류','/admin/ai','FS068','회원 관리'),
            ('A-ADM-05','회원·접근 관리','/admin/members','FS069-01·FS069-02·FS073','감사 로그'),
            ('A-ADM-05b','관리자 감사 로그','/admin/audit','NFS008','대시보드'),
        ]
        for sid,title,route,fs,nav in admin:
            goto(page,route)
            destinations={'이슈 관제':'A-ADM-03','선호도':'A-ADM-02b','AI 운영':'A-ADM-04b','회원 관리':'A-ADM-05','감사 로그':'A-ADM-05b','대시보드':'A-ADM-01'}
            note='문서×기업 판정(document-sentiment)·회차 판단(briefing-outlook)의 사용량 행이 있어요. 실제 모델 호출 전이며 데모 판정값은 없어요.' if sid=='A-ADM-04b' else '팀 v1.7 42쪽의 최종 5개 묶음 기준. 검수·차단·정정 실행은 이번 문서에서 실행하지 않았어요.'
            snap(page, sid, title, fs, '관리자 로그인 후 전용 메뉴',checks=[('link',nav,'관리자 메뉴의 해당 운영 화면을 열어요.',destinations[nav])],note=note)
    # 변경 중인 필터·브리핑을 마지막에 캡처한다.
    goto(page,'/?mode=personal')
    snap(page, 'D-GRP-01b', '내 종목 지도·범위 필터', 'FS017·FS019·FS026', '회원 → 내 종목 모드',checks=[('radio',re.compile('^보유 종목'),'보유 기준 기업과 연결 사건 범위로 좁혀요.','D-GRP-01b')],note='전체·보유·관심은 내 종목 모드 안의 필터예요. 깊이 1단계는 프로토타입 가정이에요.')
    goto(page,'/briefing')
    # 두 회차에 실제 사건이 있는 9/17을 골라 변화 목록도 보여 준다.
    chosen='2026-09-17'
    goto(page,f'/briefing?date={chosen}&edition=morning')
    click(page,'radio','출근')
    snap(page, 'D-BRF-01', '출근 브리핑', 'FS028·FS030·FS031·FS033·FS035', '브리핑 → 발행일 → 출근',checks=[('radio','퇴근','같은 발행일 퇴근 회차를 보여줘요.','D-BRF-02')],note='07:40 생성 시작. 시장 요약 서술문은 생산자가 없어 두지 않아요.')
    snap(page, 'D-BRF-02', '퇴근 브리핑·회차 비교', 'FS029·FS030·FS031·FS033·FS035', '브리핑 → 발행일 → 퇴근',checks=[('link','이 회차 전체 관계 그래프','발행 당시 관계·근거의 지도를 열어요.','D-BRF-04')],note='18:10 생성 시작. 팀 D-BRF-03 장 마감 보드의 회차 비교 의도를 여기로 흡수했어요.')
    snap(page, 'D-BRF-04', '회차 기준 지도', 'FS032·FS035', '브리핑 → 이 회차 전체 관계 그래프',checks=[('link','브리핑으로','회차 브리핑으로 돌아가요.','D-BRF-02')],note='주소의 round로 발행 당시 자료를 고정해요. 최신 자료로 대체하지 않아요.')
    # 모바일: 같은 화면의 누르기 전/후 두 장과 두 좌표 JSON.
    page.set_viewport_size({'width':390,'height':844})
    goto(page,'/?mode=all')
    click(page,'button','화면에 맞추기')
    m=snap(page,'M-GRP-01','지도·바텀시트','FS018·FS020','모바일 시장 전체 지도',checks=[('canvas-node','KRX:005930','기업 바텀시트를 열어요.','D-GRP-03')],suffix='-before')
    n=snap(page, 'M-GRP-01', '지도·바텀시트', 'FS018·FS020', '모바일 기업 선택',checks=[],suffix='-after')
    m['pair']=n['image']; slides.append(m)
    goto(page,'/companies/KRX%3A005930')
    m=snap(page, 'M-COM-01', '기업 상세·문서 전환', 'FS038·FS043', '모바일 기업 상세',checks=[('tab','문서','근거 문서 탭으로 바꿔요.','D-COM-02')],suffix='-before')
    n=snap(page, 'M-COM-01', '기업 상세·문서 전환', 'FS038·FS043', '문서 탭 선택 뒤',checks=[],suffix='-after'); m['pair']=n['image']; slides.append(m)
    goto(page,'/companies?q=삼성')
    m=snap(page,'M-STK-01','종목 메뉴·기업 상세 이동','FS037·FS027','모바일 하단 종목 → 삼성 검색',checks=[('link','삼성전자 기업 상세','선택 기업의 상세로 이동해요.','M-COM-01')],suffix='-before')
    n=snap(page,'M-STK-01','종목 메뉴·기업 상세 이동','FS037·FS027','기업 상세 이동 뒤',checks=[],suffix='-after'); m['pair']=n['image']; slides.append(m)
    goto(page,detail_route)
    m=snap(page,'M-COM-02','모바일 기업 전환 시트','FS038·FS044','기업 상세 → 다른 기업 보기',checks=[('button','삼성전자 · 다른 기업 보기','검색·보유·관심·최근·연결 기업의 전환 시트를 열어요.','M-COM-02')],suffix='-before')
    n=snap(page,'M-COM-02','모바일 기업 전환 시트','FS038·FS044','기업 전환 시트 열린 뒤',checks=[('css','[role="dialog"] ul[aria-label="보유 기업"] li:nth-child(1) button','기업을 바꾸고 기간·기준 시점·탭은 유지해요.','M-COM-01')],suffix='-after'); m['pair']=n['image']; slides.append(m)
    assert '/companies/NASDAQ%3ANVDA' in page.url and 'asOf=2026-09-30' in page.url
    goto(page,'/?mode=all')
    m=snap(page, 'M-AI-01', '하단 AI 탭', 'FS045·FS052-02', '모바일 하단 AI 탭',checks=[('button','AI','AI 질문 창을 열어요. 화면 라우트는 유지해요.','D-AI-01')],suffix='-before')
    n=snap(page, 'M-AI-01', '하단 AI 탭', 'FS045·FS052-02', 'AI 탭 선택 뒤',checks=[],suffix='-after'); m['pair']=n['image']; slides.append(m)
    goto(page,'/briefing')
    goto(page,f'/briefing?date={chosen}&edition=morning')
    click(page,'radio','출근')
    m=snap(page, 'M-BRF-01', '퇴근 브리핑·아침 이후 변경', 'FS029·FS031·FS033', '모바일 발행일 → 출근',checks=[('radio','퇴근','같은 날 퇴근 회차와 아침 이후 변경을 보여줘요.','D-BRF-02')],suffix='-before')
    # 아래 구역을 스크롤해 변화 목록이 있는 경우 실제로 보인다.
    delta=page.get_by_text(re.compile('아침 이후 바뀐 내용'))
    if delta.count(): delta.first.scroll_into_view_if_needed()
    n=snap(page, 'M-BRF-01', '퇴근 브리핑·아침 이후 변경', 'FS029·FS031·FS033', '퇴근 선택 뒤 변경 구역까지 스크롤',checks=[],suffix='-after'); m['pair']=n['image']; slides.append(m)
    context.close()
    guest=browser.new_context(viewport={'width':1440,'height':900},locale='ko-KR',reduced_motion='reduce')
    g=guest.new_page(); goto(g,'/login'); click(g,'button','로그인 없이 둘러보기')
    click(g,'button','둘러보기 시작')
    # 첫 튜토리얼은 권한 확인 전에 닫는다.
    if g.get_by_role('button',name='튜토리얼 건너뛰기',exact=True).count(): click(g,'button','튜토리얼 건너뛰기')
    click(g,'radio','내 종목 (로그인 필요)')
    personal_text=g.locator('body').inner_text()
    assert '로그인하면 내 종목 지도를 볼 수 있어요' in personal_text
    select_company(g); click(g,'button','AI에게 묻기')
    ai_text=g.locator('body').inner_text()
    assert '비회원은 질문을 보낼 수 없어요' in ai_text
    assert not g.get_by_role('button',name='보내기',exact=True).count()
    goto(g,'/me/stocks'); stocks_text=g.locator('body').inner_text()
    assert '로그인하면 내 종목을 관리할 수 있어요' in stocks_text
    goto(g,'/companies?q=삼성')
    assert g.get_by_role('link',name='삼성전자 기업 상세',exact=True).is_visible()
    guest_catalog_text=g.locator('body').inner_text()
    click(g,'link','삼성전자 기업 상세')
    guest_company_text=g.locator('body').inner_text()
    assert '삼성전자' in guest_company_text
    goto(g,'/briefing?date=2026-09-17&edition=evening')
    briefing_text=g.locator('body').inner_text(); assert '퇴근 브리핑' in briefing_text
    goto(g,'/admin'); assert '/admin/login' in g.url
    if not args.slides:
        (OUT/'auth-proof.json').write_text(json.dumps({'guestPersonal':personal_text,'guestAI':ai_text,'guestStocks':stocks_text,'guestCatalog':guest_catalog_text,'guestCompany':guest_company_text,'guestBriefing':briefing_text,'adminRedirect':g.url,'guestSendButtonCount':0},ensure_ascii=False,indent=2))
    guest.close()
    # 기존 이동 참조도 이번 실행의 실제 클릭 이력으로만 확정한다.
    if args.slides: slides[:]=[s for s in slides if s['id'] in args.slides]
    records=list(slides)
    records.extend(json.loads((OUT/s['pair'].replace('.png','.json')).read_text()) for s in slides if s.get('pair'))
    for record in records:
        for evidence in record['clickEvidence']:
            if 'reference' not in evidence: continue
            selector=evidence['selector']
            matches=[h for h in click_history if h['selector'].get('role')==selector['role'] and (re.search(selector['name'],h['selector'].get('name','')) if selector.get('regex') else h['selector'].get('name')==selector['name'])]
            assert matches, (record['id'],selector,'실제 클릭 참조 없음')
            evidence['verifiedInteraction']=matches[0]
        (OUT/record['image'].replace('.png','.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
    (OUT/'interaction-history.json').write_text(json.dumps(old_history+click_history,ensure_ascii=False,indent=2))
    for name in ('failure.png','failure.json'):
        (OUT/name).unlink(missing_ok=True)
    updated={s['id']:s for s in slides}
    merged=[updated.get(s['id'],s) for s in previous_manifest] if args.slides else slides
    (OUT/'manifest.json').write_text(json.dumps(merged,ensure_ascii=False,indent=2))
    if args.slides:
        (OUT/'targeted-capture.json').write_text(json.dumps({'revision':'v2.1 · 10-08 정합화','selected':args.slides,'updated':list(updated),'otherCapturesUnchanged':True,'stateSource':str(args.state_source),'scheduler':'off','modelCalls':0,'adminOperations':0,'apiCalls':api_calls},ensure_ascii=False,indent=2))
    print('DONE',len(slides),'slides',flush=True)

try:
    if args.with_admin_containers:
        for name in ('zoop-poc-postgres-1','zoop-poc-neo4j-1','zoop-poc-neo4j-real2'):
            status=subprocess.check_output(['docker','inspect','--format','{{.State.Status}}',name],text=True).strip()
            if status!='running':
                subprocess.run(['docker','start',name],check=True); started_containers.append(name)
    if args.manage_servers: start_servers()
    with sync_playwright() as p:
        executable=Path.home()/'Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
        browser=p.chromium.launch(executable_path=str(executable))
        try:
            run_watchlist_only(browser) if args.slides and set(args.slides)<= {'D-WAT-01','D-WAT-01b'} else run(browser)
        except Exception as error:
            import traceback
            traceback.print_exc()
            for context in browser.contexts:
                for page in context.pages:
                    (OUT/'failure.json').write_text(json.dumps({'error':str(error),'url':page.url,'text':page.locator('body').inner_text(),'aria':page.locator('body').aria_snapshot()},ensure_ascii=False,indent=2))
                    try: page.screenshot(path=str(OUT/'failure.png'),timeout=10000)
                    except Exception as capture_error: print('FAILURE screenshot:',capture_error,flush=True)
            raise
        finally:
            browser.close()
finally:
    import signal
    for process in reversed(processes):
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
    if started_containers:
        subprocess.run(['docker','stop',*started_containers],check=True)
    if isolated_state is not None: shutil.rmtree(isolated_state)
