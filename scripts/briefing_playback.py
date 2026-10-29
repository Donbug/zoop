#!/usr/bin/env python3
"""Play finished D-BRF-01/02 publications and persist local demo feedback.

Standard library only. Does not import generators, contact providers, or load .env.
The existing frontend is used with its explicit preview-feedback transport.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from briefing_preview_feedback import PreviewFeedbackHttp, PreviewFeedbackStore

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'demo/briefing-playback-2026-10-21_23'
ROUNDS = {'2026-10-21-evening', '2026-10-22-morning',
          '2026-10-22-evening', '2026-10-23-morning'}
FORBIDDEN = {'fullBody', 'prompt', 'messages', 'apiKey', 'accessToken',
             'refreshToken', 'csrfToken', 'requestId', 'reviewer_id', 'modelResponse', 'receipts',
             'inputSha256', 'generationRequestDigest', 'verificationRequestDigest',
             'promptVersion', 'context', 'contextStart', 'contextEnd',
             'aiPriceOutlooks', 'preservedPublication', 'issueFollowUps', 'issueFollowUpReview'}
RESPONSE_FIELDS = {
    'corrections', 'dataAsOf', 'dataWindow', 'date', 'edition', 'emptyReason',
    'generatedAt', 'graphVersion', 'id', 'items', 'marketSummary', 'marketVariables',
    'metadata', 'notice', 'outlook', 'previousComparison', 'publishedAt', 'references',
    'scheduledAt', 'sinceMorning', 'status', 'issueIntelligence', 'issueReading',
    'companyPriceContext', 'editionReview',
}


def check_projection(value):
    if isinstance(value, dict):
        if FORBIDDEN.intersection(value) or value.get('bodyContext') is not None:
            raise ValueError('generation_or_private_data_in_playback')
        for child in value.values():
            check_projection(child)
    elif isinstance(value, list):
        for child in value:
            check_projection(child)


def load_catalog(root=DATA):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest['schemaVersion'] != 'briefing-playback-v1'
            or manifest['scope'] != 'finished_current_issue_read_projection'
            or set(manifest['responseFields']) != RESPONSE_FIELDS
            or manifest['newModelCalls'] != 0 or manifest['newPriceCalls'] != 0):
        raise ValueError('invalid_playback_manifest')
    catalog = {}
    for entry in manifest['rounds']:
        name = entry['file']
        if name not in {r + '.json' for r in ROUNDS} or name in catalog:
            raise ValueError('invalid_or_duplicate_round_file')
        path = root / name
        if path.is_symlink():
            raise ValueError('symlink_round_file')
        raw = path.read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('playback_integrity_failed')
        pack = json.loads(raw)
        check_projection(pack)
        if set(pack) != {'response', 'details'}:
            raise ValueError('not_a_finished_projection')
        response = pack['response']
        if set(response) - RESPONSE_FIELDS:
            raise ValueError('non_display_response_field')
        model = response['issueIntelligence']
        ids = {item['eventId'] for item in response['items']}
        if (response['status'] != 'published' or response['id'] != entry['id']
                or response['date'] != entry['date'] or response['edition'] != entry['edition']
                or name != response['date'] + '-' + response['edition'] + '.json'
                or model['roundId'] != response['id']
                or model['schemaVersion'] != 'issue-intelligence-v1'
                or model['resultVersion'] != entry['resultVersion']
                or len(ids) != entry['itemCount'] or len(ids) != len(response['items'])
                or ids != {issue['issueId'] for issue in model['issues']}
                or any(issue['status'] != 'PASS' for issue in model['issues'])
                or set(pack['details']) != ids):
            raise ValueError('playback_round_contract_failed')
        for event, detail in pack['details'].items():
            if detail['roundId'] != response['id'] or detail['eventId'] != event:
                raise ValueError('playback_detail_identity_failed')
        catalog[name] = pack
    if set(catalog) != {r + '.json' for r in ROUNDS}:
        raise ValueError('four_recorded_rounds_required')
    return catalog


def frontend_environment(env, api_port):
    # Explicit empty values override Vite .env files; a teammate's production
    # endpoint or a previously unset preview flag must not redirect demo votes.
    clean = {k: v for k, v in env.items() if not k.startswith(('VITE_', 'ZOOP_DEV_'))}
    return {**clean, 'VITE_API_BASE_URL': '', 'VITE_BRIEFING_PREVIEW_FEEDBACK': 'true',
            'VITE_GRAPH_DATA_SOURCE': 'api',
            'ZOOP_DEV_API_TARGET': f'http://127.0.0.1:{api_port}',
            'ZOOP_DEV_HTTPS_CERT': '', 'ZOOP_DEV_HTTPS_KEY': ''}


def make_server(catalog, state, api_port, web_port):
    responses = [pack['response'] for pack in catalog.values()]
    by_id = {pack['response']['id']: pack for pack in catalog.values()}
    store = PreviewFeedbackStore(state, responses)

    class Handler(PreviewFeedbackHttp, BaseHTTPRequestHandler):
        feedback_store = store
        feedback_origins = frozenset(f'http://{host}:{web_port}'
                                     for host in ('127.0.0.1', 'localhost'))

        def log_message(self, *_):
            pass  # Do not log cookies, feedback reasons or request identities.

        def local_host(self):
            if self.headers.get('Host') not in {
                f'{host}:{port}' for host in ('127.0.0.1', 'localhost')
                for port in (self.server.server_port, web_port)
            }:
                self.reply(403, {'error': {'message': '로컬 시연 주소로 접속해 주세요.'}})
                return False
            return True

        def reply(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.local_host() or self.feedback_request():
                return
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            path = parsed.path
            if path == '/api/local/briefing-playback':
                self.reply(200, {'mode': 'finished_briefing_playback', 'rounds': len(catalog),
                                 'feedback': 'local_preview', 'newModelCalls': 0, 'newPriceCalls': 0})
                return
            if path == '/api/v1/auth/session':
                self.reply(200, {'authenticated': False, 'kind': 'anonymous', 'user': None,
                                 'setup': None, 'csrfToken': None, 'expiresAt': None})
                return
            if path == '/api/v1/briefings/rounds':
                items = [{k: r[k] for k in ('id', 'date', 'edition', 'status', 'publishedAt')}
                         for r in sorted(responses, key=lambda r: r['dataAsOf'], reverse=True)]
                self.reply(200, {'items': items, 'nextCursor': None})
                return
            if path == '/api/v1/briefings':
                if (set(query) - {'date', 'edition'} or any(len(v) != 1 for v in query.values())
                        or query.get('edition', ['evening'])[0] not in ('morning', 'evening')):
                    self.reply(422, {'error': {'message': '날짜와 출근·퇴근 회차를 확인해 주세요.'}})
                    return
                edition = query.get('edition', ['evening'])[0]
                matches = [r for r in responses if r['edition'] == edition
                           and (not query.get('date') or r['date'] == query['date'][0])]
                if matches:
                    self.reply(200, max(matches, key=lambda r: r['dataAsOf']))
                    return
            match = re.fullmatch(r'/api/v1/briefings/([^/]+)/items/([^/]+)(/impacts)?', path)
            if match:
                pack = by_id.get(unquote(match[1]))
                detail = pack and pack['details'].get(unquote(match[2]))
                if detail:
                    if match[3]:
                        self.reply(200, {'roundId': detail['roundId'], 'eventId': detail['eventId'],
                                         'graphVersion': None, 'status': 'unavailable', 'companies': [],
                                         'message': '이 시연 묶음은 완성 브리핑만 포함합니다. S3 관계 분석은 제공하지 않습니다.',
                                         'metadata': detail['metadata']})
                    else:
                        self.reply(200, detail)
                    return
            self.reply(404, {'error': {'message': '이 시연 묶음에 없는 데이터입니다.'}})

        def do_PUT(self):
            if self.local_host() and not self.feedback_request():
                self.reply(404, {'error': {'message': '시연 평가 저장 경로가 아닙니다.'}})

    return ThreadingHTTPServer(('127.0.0.1', api_port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify all four checked-in projections')
    parser.add_argument('--api-only', action='store_true')
    parser.add_argument('--api-port', type=int, default=18196)
    parser.add_argument('--web-port', type=int, default=13196)
    parser.add_argument('--state-dir', type=Path, default=ROOT / '.local/briefing-playback')
    args = parser.parse_args()
    server = None
    child = None
    try:
        catalog = load_catalog()
        if args.check:
            print(json.dumps({'status': 'CHECKED', 'rounds': len(catalog), 'newModelCalls': 0,
                              'newPriceCalls': 0}))
            return 0
        if not (0 < args.api_port < 65536 and 0 < args.web_port < 65536
                and args.api_port != args.web_port):
            raise ValueError('two_distinct_valid_ports_required')
        vite = ROOT / 'web/node_modules/vite/bin/vite.js'
        node = shutil.which('node')
        if not args.api_only and (not node or not vite.is_file()):
            raise ValueError('run_HUSKY=0_pnpm_--dir_web_install_--frozen-lockfile_first')
        state = args.state_dir.resolve() / 'feedback.sqlite3'
        server = make_server(catalog, state, args.api_port, args.web_port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        if not args.api_only:
            child = subprocess.Popen([node, str(vite), '--host', '127.0.0.1', '--port',
                                      str(args.web_port), '--strictPort', '--mode', 'briefing-demo'],
                                     cwd=ROOT / 'web', env=frontend_environment(os.environ, args.api_port))
        print('완성 브리핑 4회차 재생 · 새 모델/시세 호출 0회', flush=True)
        print(f'평가 저장: {state} (이 브라우저의 시연 평가, 회원·관리자 집계와 별도)', flush=True)
        print(f'http://127.0.0.1:{args.web_port}/briefing?date=2026-10-23&edition=morning&reading=compact', flush=True)
        print('Ctrl-C: 이 실행만 종료. 저장한 시연 평가는 재시작해도 유지됩니다.', flush=True)
        if child:
            return child.wait()
        threading.Event().wait()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f'briefing-playback: {error}', file=sys.stderr)
        return 1
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    sys.exit(main())
