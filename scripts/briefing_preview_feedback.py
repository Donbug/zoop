"""Local-preview reader feedback; separate from member/publication feedback.

The host supplies its immutable response catalog and exact allowed browser origins.
No login identity is fabricated, no model is called and no publication is edited.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ENDPOINT = '/api/local/briefing-feedback'
COOKIE = 'zoop_preview_reviewer'
IDENTITY = ('roundId', 'resultVersion', 'feature', 'targetId')


class FeedbackError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class PreviewFeedbackStore:
    def __init__(self, path, responses):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.targets = {}
        for response in responses:
            model = response.get('issueIntelligence') or {}
            if (response.get('status') != 'published' or model.get('roundId') != response['id']
                    or model.get('schemaVersion') != 'issue-intelligence-v1'
                    or not isinstance(model.get('resultVersion'), str)):
                raise ValueError('preview_feedback_unverified_catalog')
            ids = [i['eventId'] for i in response['items']]
            if len(ids) != len(set(ids)) or set(ids) != {i['issueId'] for i in model['issues']}:
                raise ValueError('preview_feedback_catalog_items')
            self.targets[response['id']] = (model['resultVersion'], set(ids))
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS reviewers (
                    id TEXT PRIMARY KEY, csrf TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ratings (
                    reviewer_id TEXT NOT NULL REFERENCES reviewers(id),
                    round_id TEXT NOT NULL, result_version TEXT NOT NULL,
                    feature TEXT NOT NULL CHECK(feature IN ('briefing_round','briefing_issue')),
                    target_id TEXT NOT NULL, value TEXT NOT NULL CHECK(value IN ('up','down','none')),
                    reason TEXT CHECK(reason IS NULL OR (value='down' AND length(reason)<=200)),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(reviewer_id, round_id, result_version, feature, target_id));
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def validate_target(self, value):
        if any(not isinstance(value.get(k), str) or not value[k] or len(value[k]) > 600 for k in IDENTITY):
            raise FeedbackError(422, '평가 대상을 확인하지 못했어요.')
        current = self.targets.get(value['roundId'])
        if not current:
            raise FeedbackError(404, '이 브리핑을 찾지 못했어요.')
        if current[0] != value['resultVersion']:
            raise FeedbackError(409, '브리핑 버전이 바뀌었어요. 새로고침해 주세요.')
        feature, target = value['feature'], value['targetId']
        if not ((feature == 'briefing_round' and target == value['roundId']) or
                (feature == 'briefing_issue' and target in {value['roundId']+'/'+i for i in current[1]})):
            raise FeedbackError(404, '이 회차에 포함된 평가 대상이 아니에요.')

    def reviewer(self, cookie, create=False):
        token = None
        try:
            parsed = SimpleCookie(); parsed.load(cookie or '')
            if COOKIE in parsed:
                token = parsed[COOKIE].value
        except CookieError:
            pass
        if token and re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            identity = hashlib.sha256(token.encode()).hexdigest()
            with self.connect() as db:
                row = db.execute('SELECT csrf FROM reviewers WHERE id=?', (identity,)).fetchone()
            if row:
                return identity, row[0], None
        if not create:
            raise FeedbackError(403, '평가 상태를 다시 확인해 주세요.')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        identity = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT INTO reviewers VALUES (?,?)', (identity, csrf))
        return identity, csrf, f'{COOKIE}={token}; Path={ENDPOINT}; HttpOnly; SameSite=Strict; Max-Age=7776000'

    def read(self, value, cookie):
        self.validate_target(value)
        reviewer, csrf, new_cookie = self.reviewer(cookie, create=True)
        with self.connect() as db:
            row = db.execute('''SELECT value,reason FROM ratings WHERE reviewer_id=?
                AND round_id=? AND result_version=? AND feature=? AND target_id=?''',
                (reviewer, *(value[k] for k in IDENTITY))).fetchone()
        return {**{k:value[k] for k in IDENTITY}, 'storage':'local_preview',
                'value':row[0] if row else 'none', 'reason':row[1] if row else None,
                'csrfToken':csrf}, new_cookie

    def write(self, value, cookie, csrf):
        if set(value) != {*IDENTITY, 'value', 'reason'}:
            raise FeedbackError(422, '평가 요청 형식을 확인해 주세요.')
        self.validate_target(value)
        if value['value'] not in ('up', 'down', 'none'):
            raise FeedbackError(422, '평가 값을 확인해 주세요.')
        reason = value['reason']
        if reason is not None and (not isinstance(reason, str) or len(reason) > 200 or value['value'] != 'down'):
            raise FeedbackError(422, '사유는 도움이 안 됐어요에 200자까지 남길 수 있어요.')
        reason = reason.strip() or None if isinstance(reason, str) else None
        reviewer, expected, _ = self.reviewer(cookie)
        if not isinstance(csrf, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', csrf) or not hmac.compare_digest(expected, csrf):
            raise FeedbackError(403, '평가 상태를 다시 확인해 주세요.')
        at = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('''INSERT INTO ratings VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(reviewer_id,round_id,result_version,feature,target_id)
                DO UPDATE SET value=excluded.value,reason=excluded.reason,updated_at=excluded.updated_at''',
                (reviewer, *(value[k] for k in IDENTITY), value['value'], reason, at, at))
        return {**{k:value[k] for k in IDENTITY}, 'storage':'local_preview',
                'value':value['value'], 'reason':reason}


class PreviewFeedbackHttp:
    """Mix into a loopback-only preview handler; does not enable CORS."""
    feedback_store: PreviewFeedbackStore
    feedback_origins: frozenset

    def feedback_request(self):
        if urlsplit(self.path).path != ENDPOINT:
            return False
        cookie = None
        try:
            origin = self.headers.get('Origin')
            if origin and origin not in self.feedback_origins:
                raise FeedbackError(403, '허용되지 않은 화면의 평가 요청이에요.')
            if self.command == 'GET':
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) != set(IDENTITY) or any(len(v) != 1 for v in query.values()):
                    raise FeedbackError(422, '평가 대상을 확인해 주세요.')
                result, cookie = self.feedback_store.read({k:v[0] for k,v in query.items()}, self.headers.get('Cookie'))
            elif self.command == 'PUT':
                if origin not in self.feedback_origins:
                    raise FeedbackError(403, '원래 브리핑 화면에서 다시 시도해 주세요.')
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    raise FeedbackError(415, '평가 요청 형식을 확인해 주세요.')
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 4096:
                        raise ValueError()
                    value = json.loads(self.rfile.read(length))
                    if not isinstance(value, dict):
                        raise ValueError()
                except (ValueError, UnicodeDecodeError):
                    raise FeedbackError(422, '평가 요청 형식을 확인해 주세요.')
                result = self.feedback_store.write(value, self.headers.get('Cookie'), self.headers.get('X-Preview-CSRF-Token'))
            else:
                raise FeedbackError(405, '지원하지 않는 요청이에요.')
            status = 200
        except FeedbackError as error:
            status, result = error.status, {'error':{'message':error.message}}
        except sqlite3.Error:
            status, result = 503, {'error':{'message':'평가 저장소에 연결하지 못했어요. 다시 시도해 주세요.'}}
        raw = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers(); self.wfile.write(raw)
        return True
