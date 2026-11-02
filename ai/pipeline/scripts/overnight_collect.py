"""Full-roster private acquisition, with atomic references and admission-only stop.

prepare freezes resource policy, source descriptors and read-only prior exclusions.
check and smoke are offline; run requires Main's launch reference. Independent
origins run concurrently, but a finite admitted child is never killed at cutoff.
Only the model controller writes events.jsonl. This collector never sends models,
changes historical rights, clears access denials, or retries an uncertain attempt.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from zoop_ai_pipeline.live_funding import FINISH_RESERVE_SECONDS, TERMINATION_GRACE_SECONDS, SEND_BEFORE_ENV, require_send_window
REPO = Path(__file__).resolve().parents[3]
AFTERNOON = Path('/Users/asqi/zoop-collection-2026-10-27-afternoon')
OLD = Path('/Users/asqi/zoop-private-news-2026-07-25_2026-10-25')
BACKFILL = Path('/Users/asqi/zoop-korea-backfill-2026-10-25')
NIGHT = Path('/Users/asqi/zoop-overnight-20261027/collection')
FOREIGN = Path('/Users/asqi/zoop-source-pilot-2026-10-25/native-continuation-20261025')
OLD_ROOTS = (AFTERNOON, OLD, BACKFILL, NIGHT,
             Path('/Users/asqi/zoop-collection-work-2026-10-24'),
             Path('/Users/asqi/zoop-collection-work-2026-10-23'),
             Path('/Users/asqi/zoop-corpus-review-pack-2026-10-25-government'))
RUN_ID = 'daytime-full-scope-20261028'
ROUTES = {'policy-news': '/news/policyNewsList.do', 'press-release': '/briefing/pressReleaseList.do',
          'clarifications': '/briefing/actuallyList.do'}
SET_BOUNDARIES = {'set_request_budget', 'set_byte_budget', 'set_time_budget'}
NORMAL_ENDS = {None, 'listing-end', 'channel-document-cap', 'channel-page-cap', *SET_BOUNDARIES}
BLOCKS = {'prior_host_blocked', 'host_blocked', 'robots_denied', 'robots_malformed',
          'robots_unavailable', 'http_401', 'http_403', 'http_429', 'blocked_provider_429'}
BUDGET_KEYS = ('requests', 'bytes')
LEGACY_PRIVATE = {
    'hankyung-daily': ('editorial', ['www.hankyung.com']),
    'etnews-ai': ('editorial', ['www.etnews.com']),
    'fnnews-sitemaps': ('editorial', ['www.fnnews.com']),
    'nvidia-newsroom': ('corporate-pr', ['nvidianews.nvidia.com']),
    'amd-newsroom': ('corporate-pr', ['newsroom.amd.com']),
    'naver-press': ('corporate-pr', ['www.navercorp.com']),
    'apple-newsroom': ('corporate-pr', ['www.apple.com']),
}
INTERNATIONAL = {
    'yahoo-finance': 'finance.yahoo.com', 'cnbc': 'www.cnbc.com', 'reuters': 'www.reuters.com',
    'bbc': 'www.bbc.com', 'dw': 'www.dw.com', 'france24': 'www.france24.com',
    'al-jazeera': 'www.aljazeera.com', 'techcrunch': 'techcrunch.com', 'the-verge': 'www.theverge.com',
    'ars-technica': 'arstechnica.com', 'zdnet': 'www.zdnet.com', 'toms-hardware': 'www.tomshardware.com',
    'the-register': 'www.theregister.com', 'business-standard': 'www.business-standard.com',
    'times-of-india': 'timesofindia.indiatimes.com', 'channel-newsasia': 'www.channelnewsasia.com',
}
COMPANIES = {
    'openai-newsroom': 'OpenAI', 'anthropic-newsroom': 'Anthropic', 'asml-newsroom': 'ASML',
    'tsmc-newsroom': 'TSMC', 'samsung-newsroom': 'Samsung Electronics', 'nvidia-newsroom': 'NVIDIA',
    'amd-newsroom': 'AMD', 'apple-newsroom': 'Apple', 'skhynix-newsroom': 'SK hynix',
    'micron-newsroom': 'Micron', 'microsoft-newsroom': 'Microsoft', 'naver-press': 'NAVER',
    'kakao-newsroom': 'Kakao', 'meta-newsroom': 'Meta', 'amazon-newsroom': 'Amazon',
    'lg-cns-newsroom': 'LG CNS', 'samsung-sds-newsroom': 'Samsung SDS',
    'hanmi-semiconductor-newsroom': 'Hanmi Semiconductor', 'db-hitek-newsroom': 'DB HiTek',
    'sk-telecom-newsroom': 'SK Telecom', 'alphabet-newsroom': 'Alphabet', 'intel-newsroom': 'Intel',
    'broadcom-newsroom': 'Broadcom', 'arm-newsroom': 'Arm Holdings',
}
EXTRA = {
    'nvidia-blog': ('corporate-pr', 'PoC feed port'),
    'samsung-ir': ('corporate-pr', 'native_pdf_index_adapter_missing'),
    'yonhap-rss': ('editorial', 'modern_feed_adapter_missing'),
    'inews24': ('editorial', 'direct_adapter_missing_provider_denial_not_publisher_denial'),
    'fsc-press-releases': ('government', 'modern_feed_adapter_missing'),
    'bis-federal-register': ('government', 'modern_api_adapter_missing'),
    'opendart': ('government', 'modern_adapter_missing_credentials_not_inspected'),
    'krx-kind': ('government', 'prior_access_block_no_approved_api_route'),
    'eu-commission': ('government', 'retained_native_pilot_no_archive_scheduler'),
    'eu-employment': ('government', 'retained_native_pilot_no_archive_scheduler'),
    'govuk-cma': ('government', 'retained_native_pilot_no_archive_scheduler'),
    'ons': ('government', 'pilot_canonical_mismatch_no_retry'),
    'naver-api-hub': ('discovery', 'modern_adapter_missing_credentials_not_inspected'),
    'exa': ('discovery', 'modern_adapter_missing_credentials_not_inspected'),
    'tavily': ('discovery', 'modern_adapter_missing_credentials_not_inspected'),
}
FOREIGN_ROWS = {'eu-arctic-oct20': 'eu-commission', 'eu-ai-skills-oct23': 'eu-employment',
                'govuk-cma-1-corrective': 'govuk-cma', 'govuk-cma-2-corrective': 'govuk-cma'}
SOURCE_ALIASES = {
    'alphabet-blog': 'alphabet-newsroom', 'amazon-press': 'amazon-newsroom',
    'tsmc-news': 'tsmc-newsroom', 'sktelecom-newsroom': 'sk-telecom-newsroom',
    'naver-corp-press': 'naver-press', 'channelnewsasia': 'channel-newsasia',
    'aljazeera': 'al-jazeera', 'arstechnica': 'ars-technica', 'tomshardware': 'toms-hardware',
    'theregister': 'the-register', 'theverge': 'the-verge', 'timesofindia': 'times-of-india',
    'lgcns-newsroom': 'lg-cns-newsroom', 'samsungsds-newsroom': 'samsung-sds-newsroom',
    'hanmi-newsroom': 'hanmi-semiconductor-newsroom', 'dbhitek-newsroom': 'db-hitek-newsroom',
    'hankyung': 'hankyung-daily', 'etnews': 'etnews-ai', 'fnnews': 'fnnews-sitemaps',
    'fsc': 'fsc-press-releases', 'federal-register-bis': 'bis-federal-register',
    'govuk': 'govuk-cma', 'hn': 'hacker-news', 'gdelt': 'gdelt-doc', 'kind': 'krx-kind',
    'asml-press': 'asml-newsroom', 'broadcom-news': 'broadcom-newsroom', 'micron-press': 'micron-newsroom',
    'yonhap-domestic-rss': 'yonhap-rss', 'fsc-press': 'fsc-press-releases', 'ons-uk': 'ons',
    'kind-krx': 'krx-kind', 'korea-policy-portal': 'korea-portal', 'hn-discovery': 'hacker-news',
}


def utc():
    return datetime.now(timezone.utc)


def stamp():
    return utc().isoformat()


def load(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic(path, value, *, immutable=False, text=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '.stage-' + uuid.uuid4().hex)
    raw = value.encode('utf-8') if text else (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def verified_path(path):
    path = Path(os.path.abspath(path))
    if path.resolve(strict=True) != path or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('reference_not_regular_absolute_file')
    return path


def ref(path):
    path = verified_path(path)
    return {'path': str(path), 'sha256': sha(path)}


def url_key(value):
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                      urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True))), ''))


def exclusion_sets(value=None):
    value = value or {}
    result = {'newsIds': set(value.get('newsIds', [])), 'urls': set(value.get('urls', [])),
              'blockedHosts': set(value.get('blockedHosts', [])), 'hostDelays': dict(value.get('hostDelays', {}))}
    if 'noReplayUrls' in value:
        result['noReplayUrls'] = set(value['noReplayUrls'])
    return result


def frozen_exclusions(value):
    return {key: sorted(item) if isinstance(item, set) else item for key, item in value.items()}


def deny(value, exclusion):
    if url_key(value) in exclusion.get('noReplayUrls', ()):
        return 'prior_url_no_replay'
    if urlsplit(value).hostname in exclusion['blockedHosts']:
        return 'prior_host_blocked'
    if url_key(value) in exclusion['urls']:
        return 'prior_url_excluded'
    return None


def state_rows(data, directory, table, *, immutable=False):
    """Read settled queue rows without opening a mutating collector State."""
    value = data.get(table, {})
    if isinstance(value, dict):
        yield from value.values()
    elif isinstance(value, list):
        yield from value
    elif value == 'sqlite:' + table and table in ('candidates', 'tasks', 'attempts'):
        path = verified_path(directory / 'QUEUE.sqlite3')
        if immutable and any(path.with_name(path.name + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('prior_queue_unsettled_no_recovery')
        db = sqlite3.connect(path.as_uri() + ('?mode=ro&immutable=1' if immutable else '?mode=ro'), uri=True, isolation_level=None)
        try:
            cursor = db.execute('SELECT value FROM ' + table)
            while rows := cursor.fetchmany(128):
                for row in rows:
                    yield json.loads(row[0])
        finally:
            db.close()
    else:
        raise ValueError('private_queue_reference_invalid')


def native_unattempted(item):
    return (item.get('outcome') == 'pending' and item.get('phase') == 'planned') or item.get('reason') in SET_BOUNDARIES


def absorb_state(path, exclusion, *, keep_unattempted=False, immutable=False):
    envelope = load(path)
    data = envelope.get('state', envelope)
    binding = load(path.parent / 'PLAN.json')
    config = binding.get('config', binding)
    exclusion['blockedHosts'].update(data.get('blocked', []))
    for host, delay in data.get('delays', {}).items():
        exclusion['hostDelays'][host] = max(exclusion['hostDelays'].get(host, 0), delay)
    if config.get('schemaVersion') == 'zoop-official-source-config-1':
        for item in data.get('tasks', {}).values():
            if item['status'] != 'pending':
                exclusion['urls'].add(url_key(item['task']['url']))
        return
    pending = data.get('pendingRequest')
    if pending:
        if pending.get('url'):
            exclusion['urls'].add(url_key(pending['url']))
            identifier = dict(parse_qsl(urlsplit(pending['url']).query)).get('newsId', '')
            if re.fullmatch(r'\d{9}', identifier):
                exclusion['newsIds'].add(identifier)
        else:
            exclusion['blockedHosts'].add(pending['host'])
    if 'items' in data:
        for identifier, item in data['items'].items():
            if keep_unattempted and native_unattempted(item):
                continue
            exclusion['newsIds'].add(identifier)
            exclusion['urls'].add(url_key(item['candidate']['url']))
        for channel, item in data['channels'].items():
            if item.get('reason') not in NORMAL_ENDS or data.get('pendingListing') == channel:
                query = urlencode({'pageIndex': item['page'], 'startDate': config['fromDay'], 'endDate': config['throughDay']})
                exclusion['urls'].add(url_key(config['listingOrigin'] + ROUTES[channel] + '?' + query))
    else:
        for item in state_rows(data, path.parent, 'candidates', immutable=immutable):
            if item['status'] != 'pending':
                exclusion['urls'].add(url_key(item['url']))
        for task in state_rows(data, path.parent, 'tasks', immutable=immutable):
            if task['status'] in ('refused', 'unknown', 'attempting'):
                exclusion['urls'].add(url_key(task['task']['url']))
        for attempt in state_rows(data, path.parent, 'attempts', immutable=immutable):
            if attempt.get('status') == 'deferred':
                continue
            for key in ('requestUrl', 'finalUrl'):
                value = attempt.get('response', {}).get(key)
                if value:
                    exclusion['urls'].add(url_key(value))
            value = attempt.get('articleMetadata', {}).get('canonicalUrl')
            if value:
                exclusion['urls'].add(url_key(value))
    # Committed v1/v2 records are immutable evidence even after interrupted state saves.
    for path in path.parent.glob('private-news-*.json'):
        if path.name.endswith('.extraction.json'):
            continue
        record = load(path)
        for key in ('requestUrl', 'finalUrl', 'canonicalUrl'):
            if record.get(key):
                exclusion['urls'].add(url_key(record[key]))


def source_pins():
    folder = REPO / 'ai/pipeline/src/zoop_ai_pipeline'
    files = set()
    for pattern in ('ingestion*.py', 'collection*.py', 'korea*.py', 'private_*.py', 'publication_evidence.py',
                    'news_*.py', 'hn_discovery.py', 'extraction_fallback.py', 'live_budget.py', 'live_funding.py',
                    'relation_contracts.py', 'direct_deepseek.py', 'private_processing.py', 'fallback_decision.py', 'fetch_pacing.py', 'official_source*.py'):
        files.update(folder.glob(pattern))
    files.update(path for path in (folder / '_defuddle').glob('*') if path.is_file() and path.suffix in ('.mjs', '.json'))
    files.add(Path(__file__).resolve())
    files.add(Path(__file__).with_name('overnight_metrics.py'))
    files.add(Path(__file__).with_name('retained_news_replay.py'))
    files.add(Path(__file__).with_name('collection_history.py'))
    return {str(path): sha(path) for path in sorted(files)}


def source_matrix(descriptors, research=None, catalog=()):
    rows = {}

    def add(identifier, category, label=None, hosts=(), reason='adapter_missing'):
        rows[identifier] = {'sourceId': identifier, 'category': category, 'label': label or identifier,
                            'hosts': list(hosts), 'kind': None, 'status': 'unsupported', 'reasonCode': reason}

    for identifier, (category, hosts) in LEGACY_PRIVATE.items():
        add(identifier, category, hosts=hosts)
        rows[identifier].update(kind='private', status='supported', reasonCode=None)
    for identifier, company in COMPANIES.items():
        if identifier not in rows:
            add(identifier, 'corporate-pr', company)
        rows[identifier].update(company=company, roster='company_newsroom')
    for identifier, host in INTERNATIONAL.items():
        add(identifier, 'editorial', hosts=[host])
        rows[identifier].update(roster='international_publisher', discoveryMethod='direct-publisher-not-gdelt')
    for identifier, (category, reason) in EXTRA.items():
        add(identifier, category, reason=reason)
    for descriptor in descriptors:
        identifier = descriptor['sourceId']
        # Match a configured publisher host even if research uses a different slug.
        matching = next((key for key, host in INTERNATIONAL.items() if host in descriptor['articleHosts']),
                        SOURCE_ALIASES.get(identifier, identifier))
        if matching not in rows:
            add(matching, descriptor['category'])
        if matching != identifier:
            rows[matching]['adapterSourceId'] = identifier
        origins = {urlsplit(origin).hostname for surface in descriptor['discovery'] for origin in surface['origins']}
        rows[matching].update(kind='private', status='supported', reasonCode=None, descriptor=descriptor,
                              hosts=sorted(set(descriptor['articleHosts']) | origins),
                              evidenceStatus=descriptor['evidenceStatus'])
        if descriptor.get('accessStatus', '').startswith('blocked-'):
            rows[matching].update(status='blocked', reasonCode=descriptor['accessStatus'],
                                  accessReason=descriptor.get('accessReason'), retry=False)
    for channel in ROUTES:
        add('korea-' + channel, 'government', hosts=['www.korea.kr', 'm.korea.kr'])
        rows['korea-' + channel].update(kind='native', channel=channel, status='supported', reasonCode=None,
                                      adapterSourceId='korea-portal')
    add('hacker-news', 'discovery', hosts=['hacker-news.firebaseio.com'])
    rows['hacker-news'].update(kind='hn', status='supported', reasonCode=None, bodyAcquisition='unsupported',
                              backfillCapability='unsupported', coverageMeaning='current link metadata only; not article acquisition')
    add('gdelt-doc', 'discovery', hosts=['api.gdeltproject.org'])
    rows['gdelt-doc'].update(status='blocked', reasonCode='blocked_provider_429', retry=False)
    for fact in (research or {}).get('sources', []):
        canonical_id = SOURCE_ALIASES.get(fact['id'], fact['id'])
        matches = [key for key, row in rows.items() if key == canonical_id or fact.get('host') in row['hosts']]
        if not matches and canonical_id == 'korea-portal':
            matches = ['korea-' + channel for channel in ROUTES]
        if not matches:
            add(canonical_id, 'government' if fact.get('roster') == 'government_regulator' else
                'corporate-pr' if fact.get('roster') == 'company_newsroom' else 'editorial',
                fact.get('name'), [fact['host']] if fact.get('host') else [])
            matches = [canonical_id]
        for match in matches:
            rows[match]['routeEvidence'] = fact
            if not rows[match]['hosts'] and fact.get('host'):
                rows[match]['hosts'] = [fact['host']]
            if fact.get('status') in ('policy_denied', 'blocked_observed'):
                rows[match].update(status='blocked', reasonCode=(
                    'blocked_provider_429' if match == 'gdelt-doc' else
                    'publisher_policy_denied' if fact['status'] == 'policy_denied' else 'source_access_block_observed'),
                    retry=False)
    for capability in catalog:
        identifier = SOURCE_ALIASES.get(capability['sourceId'], capability['sourceId'])
        if identifier not in rows:
            add(identifier, capability['category'], hosts=capability.get('articleHosts', []))
        rows[identifier]['capability'] = capability
        if capability.get('discoveryStatus', '').startswith('blocked-'):
            rows[identifier].update(status='blocked', reasonCode=capability['discoveryStatus'], retry=False)
        if capability.get('reason') and rows[identifier]['status'] == 'unsupported':
            rows[identifier]['reasonCode'] = capability['reason']
    for row in rows.values():
        row['admissionStatus'] = row['status']
    return list(rows.values())


def register_official_sources(rows, options):
    from zoop_ai_pipeline import official_source_adapters as official
    by_id = {row['sourceId']: row for row in rows}
    for identifier, source in (('bis-federal-register', 'federal-register-bis'), ('opendart', 'opendart'), ('sec-edgar', 'sec-edgar')):
        if identifier not in by_id:
            by_id[identifier] = {'sourceId': identifier, 'category': 'government', 'label': identifier}
            rows.append(by_id[identifier])
        selected = official.plan(source, options['fromDay'], options['throughDay'],
                                 tickers=tuple(options.get('dartTickers', [])), ciks=tuple(options.get('secCiks', [])))
        by_id[identifier].update(kind='official', adapterSourceId=source, hosts=list(official.source_hosts(source)),
                                 status='supported', admissionStatus='supported', reasonCode=None,
                                 officialPrerequisites=list(selected.prerequisites),
                                 capability={'adapter': 'official-protocol', 'bodyStatus': 'official-source-record-1',
                                             'discoveryStatus': 'implemented-not-live-verified'})
    return rows


def policy(requests, bytes_, seconds, *, private=False):
    result = {'schemaVersion': 'zoop-collection-policy-1', 'userAgent': 'ZoopPrivateNews/1.0',
              'timeoutSeconds': 20, 'minIntervalSeconds': 2, 'maxRequests': requests,
              'maxResponseBytes': min(2_000_000, bytes_), 'maxTotalBytes': bytes_, 'maxTotalSeconds': seconds,
              'maxRedirects': 2 if private else 0, 'allowedMediaTypes': ['text/html'], 'syntheticLoopback': False}
    if private:
        result['contactUrl'] = 'https://github.com/Donbug/zoop/blob/cb71c29db03200cd83b123e8b5fab8d3efb8cc22/ai/pipeline/README.md#collector-contact'
    return result


def all_plans(manifest, ledger):
    return [*manifest['plans'], *ledger.get('continuations', [])]


def resource_concurrency(rows, requested):
    cpu = os.cpu_count() or 1
    try:
        memory = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (ValueError, OSError):
        memory = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True)) if sys.platform == 'darwin' else 2_147_483_648
    fd_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    sources = sum(row['status'] == 'supported' for row in rows)
    memory_slots = max(1, memory // (4 * 536_870_912))
    fd_slots = max(1, (fd_limit - 64) // 4) if fd_limit != resource.RLIM_INFINITY else sources
    available = max(1, min(sources, cpu * 2, memory_slots, fd_slots))
    return min(requested, available) if requested else available, {
        'requested': requested or 'all-available-origins', 'supportedSources': sources, 'cpuCount': cpu,
        'physicalMemoryBytes': memory, 'memoryFraction': '1/4', 'perWorkerMemoryReserveBytes': 536_870_912,
        'fdSoftLimit': fd_limit, 'resourceCeiling': available, 'diskBackpressure': 'live free-space check before each admission'}


def fair_plans(manifest, ledger):
    plans = all_plans(manifest, ledger)
    origins, sources = {}, {}
    for plan in plans:
        if ledger['plans'].get(plan['id'], {}).get('startedAt'):
            sources[plan['rowId']] = sources.get(plan['rowId'], 0) + 1
            for host in plan['hosts']:
                origins[host] = origins.get(host, 0) + 1
    return sorted(plans, key=lambda plan: (
        max((origins.get(host, 0) for host in plan['hosts']), default=0), sources.get(plan['rowId'], 0),
        plan['freshness'] == 'backfill', plan.get('generation', 0)))


def enqueue_continuation(root, manifest, ledger, plan, record):
    if record.get('continuationPlanId') or record['status'] != 'finished':
        return
    summary = record.get('summary') or {}
    state = Path(plan['configTemplate']['stateDir'])
    if plan['kind'] in ('private', 'official'):
        eligible = summary.get('continuationEligible') is True
    elif plan['kind'] == 'native':
        reasons = {summary.get('reason'), *(c.get('reason') for c in summary.get('channels', {}).values())}
        eligible = (not summary.get('usage', {}).get('unknownRequests') and
                    bool(reasons & {'document-cap', 'candidate-cap', 'listing-page-cap',
                                    'channel-document-cap', 'channel-page-cap', *SET_BOUNDARIES}))
    else:
        eligible = False
    if not eligible:
        return
    generation = plan.get('generation', 0) + 1
    root_id = plan.get('rootPlanId', plan['id'])
    identifier = root_id[:48] + '-c' + str(generation)
    successor = copy.deepcopy(plan)
    successor.update(id=identifier, generation=generation, rootPlanId=root_id, predecessorId=plan['id'])
    successor.pop('funding', None)
    config = successor['configTemplate']
    config.update(planId=identifier, stateDir=str(root / 'state' / identifier))
    config.pop('fallback', None)
    if plan['kind'] == 'private':
        config['selectionMode'] = 'backfill'
        config['predecessor'] = {'stateDir': str(state), 'planSha256': ref(state / 'PLAN.json')['sha256'],
                                 'stateSha256': ref(state / 'STATE.json')['sha256'],
                                 'queueSha256': ref(state / 'QUEUE.sqlite3')['sha256']}
        if manifest['options'].get('fundingConfig'):
            attach_fallback(successor, root, manifest['options'])
    elif plan['kind'] == 'official':
        config['predecessor'] = {'stateDir': str(state), 'planSha256': ref(state / 'PLAN.json')['sha256'],
                                 'stateSha256': ref(state / 'STATE.json')['sha256']}
    else:
        successor['nativePredecessor'] = {'plan': ref(state / 'PLAN.json'), 'state': ref(state / 'STATE.json')}
    ledger.setdefault('continuations', []).append(successor)
    record['continuationPlanId'] = identifier


def build_plans(rows, root, options, native_template, aliases, rights):
    plans = []
    windows = [('fresh', options['freshFromDay'], options['throughDay']),
               ('backfill', options['fromDay'], (date.fromisoformat(options['freshFromDay']) - timedelta(days=1)).isoformat())]
    for freshness, start, end in windows:
        if start > end:
            continue
        for row in rows:
            if row['status'] != 'supported':
                continue
            if row['kind'] in ('hn', 'private') and freshness != 'fresh':
                continue
            ranges = [(options['fromDay'], options['throughDay'])] if row['kind'] == 'private' else [(start, end)]
            if row['kind'] == 'native':
                # Day partitions avoid an arbitrary 50/100/150-document day quota;
                # existing worker safety ceilings remain visible as partial, not exhaustion.
                ranges = [(day.isoformat(), day.isoformat()) for day in
                          (date.fromisoformat(end) - timedelta(days=n)
                           for n in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1))]
            for first, last in ranges:
                identifier = f"day-{row['sourceId']}-{freshness[0]}-{first.replace('-', '')}"
                if len(identifier) > 61:
                    identifier = identifier[:44] + '-' + hashlib.sha256(identifier.encode()).hexdigest()[:16]
                state = str(root / 'state' / identifier)
                requests = min(options['setRequests'], 5000 if row['kind'] == 'native' else 20000)
                p = policy(requests, options['setBytes'], options['setSeconds'], private=row['kind'] == 'private')
                if row['kind'] == 'private':
                    if row.get('adapterSourceId', row['sourceId']) == 'fnnews-sitemaps':
                        p['maxDiscoveryResponseBytes'] = 10_000_000
                    source = {'name': row.get('adapterSourceId', row['sourceId']), 'sourceType': row['category'],
                              'queries': [], 'reliability': 'Source statement; not independent verification'}
                    if row.get('descriptor'):
                        source['descriptor'] = row['descriptor']
                    config = {'schemaVersion': 'zoop-private-news-config-2', 'planId': identifier, 'stateDir': state,
                              'fromDay': first, 'throughDay': last, 'operatorApprovalRef': options['approvalRef'],
                              'sources': [source], 'exactArticleHosts': row.get('descriptor', {}).get('articleHosts', row['hosts']), 'policy': p,
                              'selectionMode': 'fresh-first' if freshness == 'fresh' else 'backfill', 'companyAliases': aliases}
                elif row['kind'] == 'official':
                    from zoop_ai_pipeline.official_source_adapters import MEDIA
                    p['allowedMediaTypes'] = list(MEDIA)
                    config = {'schemaVersion': 'zoop-official-source-config-1', 'planId': identifier, 'stateDir': state,
                              'sourceId': row['adapterSourceId'], 'fromDay': first, 'throughDay': last,
                              'operatorApprovalRef': options['approvalRef'], 'policy': p,
                              'tickers': options.get('dartTickers', []), 'ciks': options.get('secCiks', []),
                              'secCompany': options.get('secCompany'), 'secContact': options.get('secContact')}
                elif row['kind'] == 'native':
                    config = copy.deepcopy(native_template)
                    config.update(planId=identifier, stateDir=state, fromDay=first, throughDay=last, policy=p,
                                  maxDocuments=400, maxCandidates=800, maxListingPages=60,
                                  channels=[{'name': row['channel'], 'maxDocuments': 400, 'maxPages': 60}], rightsEvidence=rights)
                    config['grant'].update(grantId='daytime-kogl1-text-20261028', revision='daytime-item-kogl1-20261028', expiresAt=None,
                                           evidence=[f"{options['approvalRef']}; unchanged item-local KOGL1 gate. Rights evidence {rights['path']} sha256 {rights['sha256']}. No model sends/publication."])
                else:
                    config = {'stateDir': state, 'config': {'schemaVersion': 'zoop-hn-discovery-config-1', 'feed': 'new',
                              'limit': 50, 'userAgent': 'ZoopDiscovery/1.0', 'timeoutSeconds': 20,
                              'maxTotalSeconds': min(options['setSeconds'], 3600), 'maxRequests': 52,
                              'maxResponseBytes': 1_000_000, 'maxTotalBytes': 10_000_000, 'minIntervalSeconds': 2}}
                    p = config['config']
                plans.append({'id': identifier, 'kind': row['kind'], 'rowId': row['sourceId'],
                              'sourceId': row.get('adapterSourceId', row['sourceId']),
                              'freshness': 'unknown' if row['kind'] == 'private' else freshness,
                              'hosts': row['hosts'], 'configTemplate': config,
                              'ceilings': {'requests': p['maxRequests'], 'bytes': p['maxTotalBytes'] + max(p['maxResponseBytes'], p.get('maxDiscoveryResponseBytes', 0)),
                                           'seconds': p['maxTotalSeconds']}})
    # Rotate the Korea channels at each backfill day; independent origins can
    # pass a busy portal origin without a global host bottleneck.
    plans.sort(key=lambda plan: (plan['freshness'] == 'backfill', plan['kind'] == 'native',
                                -date.fromisoformat(plan['configTemplate'].get('fromDay', options['throughDay'])).toordinal(),
                                plan['rowId']))
    return plans


def private_items(state_dir, cache=None):
    state_dir = Path(state_dir).resolve(strict=True)
    binding = load(state_dir / 'PLAN.json')
    plan_id = binding['config']['planId']
    expected_plan_digest = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                                    separators=(',', ':')).encode()).hexdigest()
    result = []
    for path in sorted(state_dir.glob('private-news-*.json')):
        if path.name.endswith('.extraction.json'):
            continue
        path = verified_path(path)
        if cache is not None and str(path) in cache:
            result.append(cache[str(path)])
            continue
        raw = path.read_bytes()
        record = json.loads(raw)
        identifier = record['privateId']
        body = verified_path(path.with_suffix('.raw'))
        if (path.name != identifier + '.json' or record['schemaVersion'] not in ('zoop-private-news-record-1', 'zoop-private-news-record-2', 'zoop-private-news-record-3')
                or record.get('planDigest') != expected_plan_digest
                or record['source'] not in {source['name'] for source in binding['config']['sources']}
                or sha(body) != record['rawSha256'] or body.stat().st_size != record['rawBytes']
                or hashlib.sha256(record['prepared']['text'].encode()).hexdigest() != record['textSha256']):
            raise ValueError('private_record_pin_invalid')
        if record['schemaVersion'] in ('zoop-private-news-record-2', 'zoop-private-news-record-3'):
            extraction = record['extractionArtifact']
            sidecar = verified_path(state_dir / extraction['file'])
            if sidecar.parent != state_dir or sha(sidecar) != extraction['sha256']:
                raise ValueError('private_extraction_artifact_pin_invalid')
        if record['schemaVersion'] == 'zoop-private-news-record-3':
            from zoop_ai_pipeline.ingestion_contracts import FileRef
            from zoop_ai_pipeline.private_retained import read_record
            read_record(state_dir, FileRef(file=path.name, sha256=hashlib.sha256(raw).hexdigest()))
        result.append({'sourceId': record['source'], 'stateDir': str(state_dir), 'recordPath': str(path),
                       'recordSha256': hashlib.sha256(raw).hexdigest(), 'privateId': identifier, 'planId': plan_id})
        if cache is not None:
            cache[str(path)] = result[-1]
    return result


def official_items(state_dir, cache=None):
    state_dir = Path(state_dir).resolve(strict=True)
    binding = load(state_dir / 'PLAN.json')
    plan_digest = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    result = []
    for path in sorted(state_dir.glob('official-source-*.json')):
        if path.name.endswith('.extraction.json'):
            continue
        path = verified_path(path)
        if cache is not None and str(path) in cache:
            result.append(cache[str(path)])
            continue
        raw = path.read_bytes()
        record = json.loads(raw)
        identifier = record['privateId']
        container = verified_path(state_dir / (identifier + '.raw'))
        if (record['schemaVersion'] != 'zoop-official-source-record-1' or path.name != identifier + '.json'
                or record['planId'] != binding['planId'] or record['source'] != binding['sourceId']
                or record['planDigest'] != plan_digest or sha(container) != record['rawSha256']
                or container.stat().st_size != record['rawBytes']):
            raise ValueError('official_record_pin_invalid')
        for key, suffix in (('bodyArtifact', '.body.md'), ('extractionArtifact', '.extraction.json')):
            artifact = record[key]
            if artifact['file'] != identifier + suffix or sha(verified_path(state_dir / artifact['file'])) != artifact['sha256']:
                raise ValueError('official_artifact_pin_invalid')
        if (record['bodyArtifact']['sha256'] != record['textSha256']
                or hashlib.sha256(record['prepared']['text'].encode()).hexdigest() != record['textSha256']):
            raise ValueError('official_derived_text_pin_invalid')
        item = {'sourceId': record['source'], 'stateDir': str(state_dir), 'recordPath': str(path),
                'recordSha256': hashlib.sha256(raw).hexdigest(), 'privateId': identifier, 'planId': record['planId']}
        result.append(item)
        if cache is not None:
            cache[str(path)] = item
    return result


def native_items(plan, cache=None):
    state_dir = Path(plan['configTemplate']['stateDir']).resolve()
    state_path = state_dir / 'STATE.json'
    if not state_path.exists():
        return []
    data = load(state_path)
    result = []
    for identifier, record in data['items'].items():
        if record['outcome'] != 'exported':
            continue
        item = state_dir / 'items' / identifier
        export = state_dir / record['exportFile']
        if cache is not None and str(export) in cache:
            result.append(cache[str(export)])
            continue
        ingestion = load(item / 'ingestion-result.json')
        selected = ingestion['documentRefs'][0]
        selector = {'schemaVersion': 'zoop-ingestion-s2-1', 'roundId': 'item-' + identifier, 'sourceId': 'korea-portal',
                    **{key: selected[key] for key in ('page', 'ordinal', 'documentId', 'rawVersion', 'documentVersion')}}
        collection = load(item / 'collection-result.json')
        collection_dir = Path(collection['manifestPath']).parent
        rights = load(item / 'rights.json')
        if rights['license'] != 'KOGL-type-1-text-only' or rights['bodySha256'] != record['nativeBodySha256']:
            raise ValueError('native_rights_identity_mismatch')
        paths = {'exportPath': export, 'acquisitionRegistryPath': item / 'sources.json', 'rightsProofPath': item / 'rights.json',
                 'collectionResultPath': item / 'collection-result.json', 'ingestionResultPath': item / 'ingestion-result.json',
                 'acquisitionManifestPath': Path(collection['manifestPath']), 'acquisitionRecordPath': collection_dir / 'collection.json',
                 'nativeReceiptPath': collection_dir / 'receipts' / (record['nativeReceiptSha256'] + '.json'),
                 'nativeBodyPath': collection_dir / 'bodies' / (record['nativeBodySha256'] + '.bin')}
        result.append({'newsId': identifier, 'sourceId': 'korea-portal', 'sourceScopeId': identifier, 'sourceKind': record['candidate']['channel'],
                       'planId': plan['id'], 'documentId': selected['documentId'], 'documentVersion': selected['documentVersion'],
                       'rawVersion': selected['rawVersion'], 'owningIngestionStateDir': str(item / 'ingestion'), 'observation': selector,
                       'nativeInputRoot': str(state_dir / 'native'), 'acquisitionRequestPath': None,
                       'acquisitionRequestDigest': collection['requestDigest'],
                       **{key: str(value) for key, value in paths.items()}, 'fileRefs': [ref(path) for path in paths.values()],
                       'fileSha256': sha(export), 'fetchedAt': record['fetchedAt'], 'observedAt': record['fetchedAt'],
                       'publishedAt': record['candidate']['publicationDay'], 'publicationPrecision': 'day',
                       'itemLicense': rights['license'], 'rights': 'known', 'modelSend': False, 'publicUse': False,
                       'requiresNewProcessingGrant': True, 'freshness': plan['freshness']})
        if cache is not None:
            cache[str(export)] = result[-1]
    return result


def foreign_items(inventory_path):
    inventory_path = verified_path(inventory_path)
    base = inventory_path.parent
    result = []
    for record in load(inventory_path)['documents']:
        export = verified_path(record['export']['path'])
        if sha(export) != record['export']['sha256']:
            raise ValueError('foreign_export_pin_changed')
        document = load(export)
        obs = document['observation']
        key = obs['sourceId']
        corrected = key.startswith('govuk-')
        registry = base / ('govuk-corrective/followup-sources.json' if corrected else 'reingest-sources.json')
        source = next(s for s in load(registry)['sources'] if s['sourceId'] == key)
        native = Path(source['inputRoot'])
        collection_dir = Path(record['manifest']['path']).parent
        receipt = native / obs['collection']['receipt']['file']
        acquisition = load(collection_dir / 'collection.json')
        paths = {'exportPath': export, 'acquisitionRegistryPath': registry, 'rightsProofPath': inventory_path,
                 'collectionResultPath': collection_dir / 'collection.json', 'ingestionResultPath': export.parent / 'ingest-result.json',
                 'acquisitionManifestPath': record['manifest']['path'], 'acquisitionRecordPath': collection_dir / 'collection.json',
                 'nativeReceiptPath': receipt, 'nativeBodyPath': record['raw']['path']}
        for name in ('manifest', 'raw', 'receipt'):
            if ref(record[name]['path'])['sha256'] != record[name]['sha256']:
                raise ValueError('foreign_provenance_pin_changed')
        selector = {'schemaVersion': 'zoop-ingestion-s2-1', **{k: obs[k] for k in
                    ('roundId', 'sourceId', 'page', 'ordinal', 'documentId', 'rawVersion', 'documentVersion')}}
        result.append({'newsId': key, 'sourceId': key, 'sourceScopeId': key, 'sourceKind': 'foreign-official',
                       'planId': 'reused-foreign-pilot-20261025', 'documentId': obs['documentId'],
                       'documentVersion': obs['documentVersion'], 'rawVersion': obs['rawVersion'], 'observation': selector,
                       'owningIngestionStateDir': str(base / ('govuk-corrective/followup-state' if corrected else 'reingestion-state')),
                       'nativeInputRoot': str(native), 'acquisitionRequestPath': None,
                       'acquisitionRequestDigest': acquisition.get('requestDigest'),
                       **{key: str(value) for key, value in paths.items()}, 'fileRefs': [ref(path) for path in paths.values()],
                       'fileSha256': sha(export), 'fetchedAt': obs['collection']['fetchedAt'], 'observedAt': obs['observedAt'],
                       'publishedAt': obs['collection']['published']['raw'],
                       'publicationPrecision': obs['collection']['published']['precision'],
                       'itemLicense': 'CC-BY-4.0' if not corrected else 'OGL-3.0', 'rights': source['grant']['rights'],
                       'modelSend': False, 'publicUse': False, 'requiresNewProcessingGrant': True, 'freshness': 'reused'})
    return result


def reused_corpus(roots, foreign_inventory):
    native, private, references, states, errors = [], [], [], [], []
    seen = set()
    for root in roots:
        if not root.exists():
            errors.append({'path': str(root), 'reasonCode': 'retained_root_missing'})
            continue
        for name in ('manifest.json', 'PACKAGE.json'):
            path = root / name
            if path.exists():
                references.append({'kind': 'retained-corpus-reference', 'inventory': ref(path),
                                   'freshness': 'reused', 'newCollection': False,
                                   'note': 'May overlap indexed acquisition records; never counted as new collection.'})
        # Offline denied smoke states under evidence/ are not publisher denials.
        candidates = set(root.glob('*state*/STATE.json')) | set(root.glob('state/*/STATE.json'))
        for path in sorted(candidates):
            if path.parent in seen or not (path.parent / 'PLAN.json').exists():
                continue
            seen.add(path.parent)
            binding = load(path.parent / 'PLAN.json')
            config = binding.get('config', {})
            schema = config.get('schemaVersion', '')
            if schema not in ('zoop-private-news-config-1', 'zoop-private-news-config-2', 'zoop-korea-corpus-1'):
                continue
            states.append(ref(path))
            plan = {'id': config['planId'], 'freshness': 'reused', 'configTemplate': config}
            try:
                items = native_items(plan) if schema == 'zoop-korea-corpus-1' else private_items(path.parent)
                (native if schema == 'zoop-korea-corpus-1' else private).extend(items)
                references.append({'kind': 'native' if schema == 'zoop-korea-corpus-1' else 'private',
                                   'stateDir': str(path.parent), 'planId': config['planId'], 'count': len(items),
                                   'freshness': 'reused', 'newCollection': False, 'state': ref(path)})
            except (OSError, ValueError, KeyError) as exc:
                errors.append({'path': str(path.parent), 'reasonCode': type(exc).__name__ + ':retained_reference_invalid'})
    if foreign_inventory.exists():
        native.extend(foreign_items(foreign_inventory))
        references.append({'kind': 'native', 'inventory': ref(foreign_inventory), 'freshness': 'reused', 'newCollection': False})
    else:
        errors.append({'path': str(foreign_inventory), 'reasonCode': 'foreign_inventory_missing'})
    return {'nativeItems': unique_items(native, 'exportPath'), 'privateItems': unique_items(private, 'recordPath'),
            'reusedCorpus': references, 'priorStates': states, 'errors': errors}


def unique_items(items, key):
    selected = {}
    for item in items:
        prior = selected.setdefault(item[key], item)
        if prior != item:
            raise ValueError('retained_reference_conflict')
    return list(selected.values())


def prepare(root, options, research_path=None):
    from zoop_ai_pipeline.news_sources import source_catalog, source_descriptors
    os.umask(0o077)
    root = Path(os.path.abspath(root))
    if (root.resolve() != root or root == REPO or root.is_relative_to(REPO)
            or any(root == prior or root.is_relative_to(prior) or prior.is_relative_to(root) for prior in OLD_ROOTS)):
        raise ValueError('new_collection_namespace_required')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (root / 'PLAN.json').exists():
        raise ValueError('plan_already_frozen')
    for name in ('configs', 'state', 'logs', 'evidence'):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    if research_path is None:
        raise ValueError('complete_source_route_manifest_required')
    research = load(research_path)
    source_ids = [row['id'] for row in research['sources']]
    if len(source_ids) != 58 or len(set(source_ids)) != 58:
        raise ValueError('complete_58_source_roster_required')
    descriptors = [item.wire() for item in source_descriptors()]
    rows = register_official_sources(source_matrix(descriptors, research, source_catalog()), options)
    options['concurrency'], options['resourceAdmission'] = resource_concurrency(rows, options.get('concurrency'))
    research_origin = ref(research_path)
    research_path = root / 'evidence/SOURCE_ROUTES.json'
    atomic(research_path, research, immutable=True)
    retained = reused_corpus(OLD_ROOTS, FOREIGN / 'FINAL_INVENTORY.json')
    exclusions = exclusion_sets()
    exclusions['blockedHosts'].add('api.gdeltproject.org')
    for item in retained['priorStates']:
        absorb_state(Path(item['path']), exclusions)
    if options.get('priorCollections'):
        import collection_history
        options['priorCollectionEvidence'] = collection_history.include(
            options['priorCollections'], root, retained, exclusions)
    if options.get('replayPackages'):
        import collection_history
        options['replayPackageEvidence'] = collection_history.include_replays(
            options['replayPackages'], root, retained, exclusions)
    prior_ids = AFTERNOON / 'configs/native-exclusions-prior-union.json'
    exclusions['newsIds'].update(load(prior_ids)['newsIds'])
    for item in retained['nativeItems']:
        document = load(item['exportPath'])
        if document['observation'].get('url'):
            exclusions['urls'].add(url_key(document['observation']['url']))
    atomic(root / 'evidence/REUSED_CORPUS.json', retained, immutable=True)
    atomic(root / 'evidence/PRIOR_EXCLUSIONS.json', frozen_exclusions(exclusions), immutable=True)
    rights = {'schemaVersion': 'zoop-korea-operator-evidence-1', 'authorization': options['approvalRef'],
              'itemGate': 'Unchanged exact article-local KOGL1 text-only gate; no media/attachments/third-party content.',
              'priorEvidence': ref(AFTERNOON / 'configs/native-rights-evidence-20261027.json'),
              'executionWindow': {'fromDay': options['fromDay'], 'throughDay': options['throughDay'], 'stopNewWorkAt': options['stopNewWorkAt']},
              'modelSend': False, 'publicUse': False}
    atomic(root / 'configs/rights-evidence.json', rights, immutable=True)
    native_template = load(AFTERNOON / 'configs/afternoon-korea-20261026-20261027.json')
    aliases = load(AFTERNOON / 'configs/afternoon-corporate-20261026-20261027.json')['companyAliases']
    plans = build_plans(rows, root, options, native_template, aliases, ref(root / 'configs/rights-evidence.json'))
    if options.get('knownUnsentProof'):
        from zoop_ai_pipeline.private_continuation import collection_plans
        plans = collection_plans(options['knownUnsentProof'], root, options) + plans
    run_config = None
    if options.get('fundingConfig'):
        run_config = validate_run_config(options['fundingConfig'], root, options['stopNewWorkAt'])
        options['finishBy'] = run_config['finishBy']
        for plan in plans:
            if plan['kind'] == 'private':
                attach_fallback(plan, root, options)
    manifest = {'schemaVersion': 'zoop-daytime-collection-plan-2', 'createdAt': stamp(), 'runId': run_config['runId'] if run_config else RUN_ID,
                'options': options, 'sourcePins': source_pins(), 'sourceMatrix': rows, 'plans': plans,
                'researchSources': research['sources'],
                'priorExclusions': ref(root / 'evidence/PRIOR_EXCLUSIONS.json'),
                'reusedCorpus': ref(root / 'evidence/REUSED_CORPUS.json'), 'rightsEvidence': ref(root / 'configs/rights-evidence.json'),
                'routeResearch': ref(research_path) if research_path else None,
                'routeResearchOrigin': research_origin,
                'modelSend': False, 'publicUse': False, 'noUnknownRetry': True, 'stopPolicy': 'close-admission-drain-finite-children'}
    if options.get('replayPackageEvidence'):
        manifest['replayPackages'] = options['replayPackageEvidence']
    atomic(root / 'PLAN.json', manifest, immutable=True)
    ledger = {'schemaVersion': 'zoop-daytime-acquisition-ledger-2', 'planSha256': sha(root / 'PLAN.json'),
              'startedAt': None, 'endedAt': None, 'plans': {}, 'held': {k: 0 for k in BUDGET_KEYS},
              'spent': {k: 0 for k in BUDGET_KEYS}, 'originReadyAt': {}, 'closedReason': None}
    atomic(root / 'LEDGER.json', ledger, immutable=True)
    publish_index(root, manifest, ledger)
    print(json.dumps({'prepared': True, 'planCount': len(plans), 'sourceCount': len(rows),
                      'index': str(root / 'INDEX.json'), 'retainedErrors': retained['errors']}))


def clean_env(fetch_values=None, set_id=None):
    result = {**{key: os.environ[key] for key in ('HOME', 'PATH', 'TMPDIR', 'LANG', 'LC_ALL') if key in os.environ},
              'PYTHONPATH': os.pathsep.join(str(REPO / part) for part in ('ai/pipeline/src', 'ai/worker/src')),
              'PYTHONDONTWRITEBYTECODE': '1'}
    if set_id:
        result['ZOOP_AI_PIPELINE_LIVE_SET_ID'] = set_id
        if fetch_values and fetch_values.get('DEEPSEEK_API_KEY'):
            result['DEEPSEEK_API_KEY'] = fetch_values['DEEPSEEK_API_KEY']
    return result


def validate_run_config(pin, root, stop_new):
    from zoop_ai_pipeline.live_funding import run_policy
    from zoop_ai_pipeline.private_processing import Actor
    if ref(pin['path']) != pin:
        raise ValueError('funding_config_pin_changed')
    config = load(pin['path'])
    try:
        run_policy(config)
    except ValueError:
        raise ValueError('collection_funding_config_mismatch') from None
    if (type(config['maxCalls']) is not int or not 1 <= config['maxCalls'] <= 100000
            or Path(config['root']).resolve() / 'collection' != root.resolve()
            or datetime.fromisoformat(config['admitUntil'].replace('Z', '+00:00')) != datetime.fromisoformat(stop_new)):
        raise ValueError('collection_funding_config_mismatch')
    if Actor.model_validate(config['processingActor']).wire() != config['processingActor']:
        raise ValueError('processing_actor_must_be_canonical')
    from zoop_ai_pipeline.live_funding import timestamp
    if not FINISH_RESERVE_SECONDS + 300 < (timestamp(config['finishBy']) - timestamp(config['admitUntil'])).total_seconds() <= 3600:
        raise ValueError('run_finish_window_invalid')
    return config


def attach_fallback(plan, root, options):
    from zoop_ai_pipeline.private_intake import Config
    from zoop_ai_pipeline.ingestion_contracts import digest
    normalized = Config.model_validate(plan['configTemplate']).wire()
    normalized.pop('fallback', None)
    set_id = 'acquisition:' + plan['id']
    native_requests = normalized['policy']['maxRequests']
    allowance = {'fetch': native_requests, 'search': 0}
    plan['ceilings']['requests'] = native_requests + allowance['fetch']
    proof = {'schemaVersion': 'zoop-acquisition-set-1', 'setId': set_id, 'sourceId': plan['sourceId'],
             'unitDigest': digest(normalized), 'allowance': allowance}
    proof_path = root / 'evidence' / (plan['id'] + '.admission.json')
    atomic(proof_path, proof, immutable=True)
    pin = ref(proof_path)
    plan['funding'] = {**proof, 'proof': pin}
    plan['configTemplate']['fallback'] = {
        'enabled': True, 'setId': set_id, 'sourceId': plan['sourceId'], 'approvalRef': options['approvalRef'],
        'budgetConfigPath': options['fundingConfig']['path'], 'budgetConfigSha256': options['fundingConfig']['sha256'],
        'setProofPath': pin['path'], 'setProofSha256': pin['sha256'],
        'allowedHosts': plan['configTemplate']['exactArticleHosts'], 'maxCalls': allowance['fetch']}


def acquisition_budget(root, manifest):
    from zoop_ai_pipeline.live_budget import Budget
    from zoop_ai_pipeline.live_funding import run_policy
    pin = manifest['options'].get('fundingConfig')
    if not pin:
        return None
    config = validate_run_config(pin, root, manifest['options']['stopNewWorkAt'])
    policy = run_policy(config)
    return Budget(Path(config['root']) / 'modelbudget', policy['totalMaxNanoUsd'], config['maxCalls'],
                  funding=policy, bucket_caps=policy['bucketMaxNanoUsd'], finish_by=config['finishBy'])


def read_runtime_key(path, name):
    """Only an explicit Main-configured file; never ambient provider credentials."""
    if name not in {'DEEPSEEK_API_KEY', 'OPENDART_API_KEY'}:
        raise ValueError('credential_name_not_authorized')
    if path is None:
        return {}
    values = {}
    seen = False
    with verified_path(path).open(encoding='utf-8') as stream:
        for line in stream:
            match = re.match(r"^\s*(?:export\s+)?(" + name + r")\s*=\s*(.*?)\s*$", line)
            if not match:
                continue
            if seen:
                raise ValueError('duplicate_fetch_key_configuration')
            seen = True
            value = match[2]
            if value[:1] in ("'", '"'):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError('fetch_key_literal_required')
                value = value[1:-1]
            if not value:
                continue
            if '\n' in value or '\r' in value or '${' in value or '$(' in value:
                raise ValueError('fetch_key_literal_required')
            values[name] = value
    return values


def plan_admission(plan):
    from zoop_ai_pipeline.ingestion_contracts import digest
    if plan.get('funding'):
        return plan['funding']
    return {'setId': 'acquisition:' + plan['id'],
            'unitDigest': digest({'kind': plan['kind'], 'config': plan['configTemplate']}), 'allowance': {}}


def finish_funding(budget, plan, record):
    if budget is None or not record.get('fundedSetId'):
        return
    from zoop_ai_pipeline.live_budget import BudgetError
    funding = plan_admission(plan)
    state = 'unknown' if record['status'] == 'unknown' else (
        'blocked' if record['status'] == 'error' or outcome(plan, record)['status'] == 'blocked' else 'completed')
    if state != 'unknown':
        try:
            budget.resume_set(funding['setId'], funding['unitDigest'])
        except BudgetError as exc:
            state = 'unknown'
            record.update(status='unknown', reasonCode=exc.code)
    budget.finish_set(funding['setId'], state)
    record['fundingOutcome'] = state


def child_command(kind, mode, config, exclusions):
    return [sys.executable, '-B', str(Path(__file__).resolve()), mode, '--kind', kind,
            '--config', str(config), '--exclusions', str(exclusions)]


def seed_native_continuation(collector, config, pins):
    for pin in pins.values():
        if ref(pin['path']) != pin:
            raise ValueError('native_predecessor_pin_mismatch')
    previous = load(pins['state']['path'])
    previous_config = load(pins['plan']['path'])['config']
    current = config.wire()
    if (any(previous_config[key] != current[key] for key in
            ('fromDay', 'throughDay', 'listingOrigin', 'articleOrigin', 'exactHosts', 'grant', 'rightsEvidence'))
            or {item['name'] for item in previous_config['channels']} != {item['name'] for item in current['channels']}
            or previous.get('unknownRequests') or previous.get('pendingRequest') or previous.get('pendingListing')):
        raise ValueError('native_predecessor_scope_or_outcome_invalid')
    base = collector.State

    class ContinuedState(base):
        def __init__(self, config, binding):
            if Path(config.state_dir).exists():
                raise ValueError('native_successor_namespace_already_exists')
            super().__init__(config, {**binding, 'predecessor': pins})
            try:
                self.data['blocked'] = list(previous['blocked'])
                self.data['delays'] = dict(previous['delays'])
                self.data['items'] = {identifier: {'candidate': copy.deepcopy(item['candidate']),
                                                   'outcome': 'pending', 'phase': 'planned'}
                                      for identifier, item in previous['items'].items() if native_unattempted(item)}
                self.data['candidateCount'] = len(self.data['items'])
                for name in self.data['channels']:
                    channel = copy.deepcopy(previous['channels'][name])
                    boundary = channel.get('reason') in NORMAL_ENDS - {'listing-end'}
                    channel.update(pages=0)
                    if boundary:
                        channel.update(done=False, reason=None)
                    self.data['channels'][name] = channel
                self.save()
            except BaseException:
                self.close()
                raise

    collector.State = ContinuedState


def child(kind, config_path, exclusion_path, *, validate=False):
    from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, canonical
    if kind == 'native':
        from zoop_ai_pipeline import korea_corpus as collector
        cls_name = 'DurableFetcher'
        config = collector.load_config(config_path)
    elif kind == 'private':
        from zoop_ai_pipeline import private_intake as collector
        cls_name = 'PrivateFetcher'
        config = collector.load_config(config_path)
    elif kind == 'official':
        from zoop_ai_pipeline import official_source_intake as collector
        cls_name = 'TrackedFetcher'
        config = collector.load_config(config_path)
    else:
        from zoop_ai_pipeline import hn_discovery as collector
        cls_name = '_JsonFetcher'
        wrapper = load(config_path)
        config = collector.Config.model_validate(wrapper['config'])
    exclusion = exclusion_sets(load(exclusion_path))
    if kind == 'native':
        native_exclusions = collector.exclusions

        def all_native_exclusions(current):
            return native_exclusions(current) | exclusion['newsIds']

        collector.exclusions = all_native_exclusions
    if validate:
        if kind == 'native':
            collector.load_evidence(config.rights_evidence)
            collector.exclusions(config)
        print(json.dumps({'valid': True, 'kind': kind}))
        return 0
    base = getattr(collector, cls_name)

    def scoped_denial(value, state=None):
        code = deny(value, exclusion)
        if (code == 'prior_url_excluded' and kind == 'private' and config.known_unsent is not None and state is not None):
            from zoop_ai_pipeline.ingestion_contracts import digest
            item = state.data['candidates'].get('private-news-' + digest([config.plan_id, value]))
            if item is not None and item.get('reusableNative', {}).get('reason') == 'fallback_admission_mismatch':
                return None
        if (code == 'prior_host_blocked' and kind == 'private' and config.fallback is not None and state is not None
                and urlsplit(value).hostname in collector.public_client403_hosts(state)):
            # This only reaches the native blocked-host guard. It cannot perform
            # another native GET, clear robots/access policy, or replay an attempted URL.
            return 'prior_url_excluded' if url_key(value) in exclusion['urls'] else None
        return code

    class PriorGuardFetcher(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._blocked.update(exclusion['blockedHosts'])
            for host, delay in exclusion['hostDelays'].items():
                self._delay[host] = max(self._delay.get(host, 0), delay)

        def fetch(self, value):
            if kind == 'native':
                code = ('set_request_budget' if self.requests >= self.policy.max_requests else
                        'set_byte_budget' if self.downloaded >= self.policy.max_total_bytes else
                        'set_time_budget' if time.monotonic() >= self.run_deadline else None)
                if code:
                    self.state.data['reason'] = code
                    self.state.save()
                    raise IngestionFailure(code)
            return super().fetch(value)

        def _guard(self, value):
            try:
                require_send_window(self.policy.timeout_seconds, os.environ.get(SEND_BEFORE_ENV))
            except ValueError as exc:
                raise IngestionFailure(str(exc)) from None
            code = scoped_denial(value, getattr(self, 'state', None))
            if code:
                raise IngestionFailure(code)
            return super()._guard(value)

    setattr(collector, cls_name, PriorGuardFetcher)
    if kind == 'private':
        original_selection = collector._selection

        def selection(state):
            for identifier in original_selection(state):
                item = state.data['candidates'][identifier]
                code = scoped_denial(item['url'], state)
                if code:
                    item.update(status='refused', code=code)
                    state.data['candidates'][identifier] = item
                    state.save()
                else:
                    yield identifier

        collector._selection = selection
    continuation_path = Path(config_path).with_suffix('.native-continuation.json')
    if kind == 'native' and continuation_path.exists():
        seed_native_continuation(collector, config, load(continuation_path))
    try:
        if kind == 'official':
            result = collector.run(config, runtime_key=os.environ.get('OPENDART_API_KEY') if config.source_id == 'opendart' else None)
        else:
            result = collector.run(config, Path(wrapper['stateDir'])) if kind == 'hn' else collector.run(config)
        if kind == 'hn':
            result = {key: value for key, value in result.items() if key not in ('candidates', 'dispositions', 'selectedStoryIds', 'config')}
            result['discovered'] = len(load(Path(wrapper['stateDir']) / 'SNAPSHOT.json')['snapshot']['candidates'])
        print(canonical({key: value for key, value in result.items() if key not in ('documents', 'dispositions', 'privateItems')}))
        return 0 if result['state'] == 'completed' else 2
    except IngestionFailure as exc:
        print(json.dumps({'state': 'refused', 'error': {'code': exc.code}}))
        return 2


def materialize(plan, exclusion, directory):
    config = copy.deepcopy(plan['configTemplate'])
    exclusion_path = directory / (plan['id'] + '.exclusions.json')
    atomic(exclusion_path, frozen_exclusions(exclusion), immutable=True)
    if plan['kind'] == 'native':
        native_path = directory / (plan['id'] + '.native-exclusions.json')
        # The unchanged worker wire accepts <=10,000 IDs. The child wrapper unions
        # the complete independently pinned exclusion set before listing admission.
        ids = sorted(exclusion['newsIds'])
        atomic(native_path, {'schemaVersion': 'zoop-korea-exclusions-1',
                             'newsIds': ids if len(ids) <= 10000 else []}, immutable=True)
        config['exclusionManifest'] = ref(native_path)
        if plan.get('nativePredecessor'):
            atomic(directory / (plan['id'] + '.native-continuation.json'), plan['nativePredecessor'], immutable=True)
    path = directory / (plan['id'] + '.json')
    atomic(path, config, immutable=True)
    return path, exclusion_path


def validate_manifest(root, manifest, ledger):
    if ledger['planSha256'] != sha(root / 'PLAN.json'):
        raise ValueError('immutable_plan_changed')
    for path, expected in manifest['sourcePins'].items():
        if sha(path) != expected:
            raise ValueError('source_pin_changed')
    for key in ('priorExclusions', 'reusedCorpus', 'rightsEvidence', 'routeResearch'):
        item = manifest.get(key)
        if item and ref(item['path']) != item:
            raise ValueError('evidence_pin_changed')
    for item in load(manifest['reusedCorpus']['path'])['priorStates']:
        if ref(item['path']) != item:
            raise ValueError('prior_state_changed')
    if manifest.get('replayPackages'):
        import collection_history
        collection_history.verify_replay_pins(manifest['replayPackages'])
    if manifest['options'].get('fundingConfig'):
        control = validate_run_config(manifest['options']['fundingConfig'], root, manifest['options']['stopNewWorkAt'])
        if manifest['options'].get('finishBy') != control['finishBy']:
            raise ValueError('collection_finish_pin_changed')
    for plan in all_plans(manifest, ledger):
        if plan.get('funding') and ref(plan['funding']['proof']['path']) != plan['funding']['proof']:
            raise ValueError('acquisition_admission_proof_changed')
    ids = [plan['id'] for plan in all_plans(manifest, ledger)]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_dispatch_identity')
    if any(plan['sourceId'] == 'gdelt-doc' or 'api.gdeltproject.org' in plan['hosts'] for plan in all_plans(manifest, ledger)):
        raise ValueError('blocked_provider_dispatch_forbidden')


def check(root):
    manifest, ledger = load(root / 'PLAN.json'), load(root / 'LEDGER.json')
    validate_manifest(root, manifest, ledger)
    directory = root / 'evidence' / ('offline-configs-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    exclusion = exclusion_sets(load(manifest['priorExclusions']['path']))
    results = []
    for plan in all_plans(manifest, ledger):
        config, exclusions = materialize(plan, exclusion, directory)
        proc = subprocess.run(child_command(plan['kind'], 'validate-child', config, exclusions),
                              env=clean_env(), capture_output=True, text=True, check=False)
        results.append({'planId': plan['id'], 'returnCode': proc.returncode, 'valid': proc.returncode == 0})
        if proc.returncode:
            atomic(root / 'evidence/CHECK.json', {'passed': False, 'results': results, 'stderr': proc.stderr})
            raise ValueError('child_config_invalid_' + plan['id'])
    result = {'passed': True, 'network': 'none', 'configCount': len(results), 'configs': results,
              'planSha256': ledger['planSha256']}
    atomic(root / 'evidence/CHECK.json', result)
    print(json.dumps({'passed': True, 'network': 'none', 'configCount': len(results)}))


def smoke(root):
    """Actual collector CLIs, all origins pre-denied; no external HTTP allowed."""
    manifest, ledger = load(root / 'PLAN.json'), load(root / 'LEDGER.json')
    directory = root / 'evidence' / ('offline-smoke-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    outcomes = []
    for kind in ('native', 'private', 'hn'):
        plan = copy.deepcopy(next(p for p in all_plans(manifest, ledger) if p['kind'] == kind))
        plan['id'] = 'offline-denied-' + kind
        plan['configTemplate']['stateDir'] = str(directory / (kind + '-state'))
        plan['configTemplate'].pop('fallback', None)
        if kind != 'hn':
            plan['configTemplate']['planId'] = plan['id']
        denied = exclusion_sets({'blockedHosts': plan['hosts']})
        config, exclusions = materialize(plan, denied, directory)
        proc = subprocess.run(child_command(kind, 'collect-child', config, exclusions), env=clean_env(),
                              capture_output=True, text=True, check=False)
        atomic(directory / (kind + '-process.json'), {'returnCode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr})
        summary = json.loads(proc.stdout)
        usage = summary.get('usage', {}) if kind == 'native' else summary
        requests = usage.get('requests' if kind == 'native' else 'sourceRequests')
        bytes_ = usage.get('bytes' if kind == 'native' else 'sourceBytes')
        if proc.returncode != 2 or requests != 0 or bytes_ != 0:
            raise ValueError('offline_cli_denial_failed_' + kind)
        outcomes.append({'kind': kind, 'requests': requests, 'bytes': bytes_, 'returnCode': proc.returncode})
    atomic(directory / 'SMOKE.json', {'passed': True, 'network': 'none', 'outcomes': outcomes})
    print(json.dumps({'passed': True, 'network': 'none', 'evidence': str(directory / 'SMOKE.json')}))


def outcome(plan, record):
    summary = record.get('summary') or record.get('checkpointSummary') or {}
    native = plan['kind'] == 'native'
    usage = summary.get('usage', {}) if native else summary
    counts = summary.get('counts', {})
    retained = record.get('committedRecords', counts.get('exported', 0) if native else summary.get('currentRetainedInWindow', summary.get('retainedInWindow', 0)))
    discovered = summary.get('candidateCount', 0) if native else summary.get('currentDiscoveredCandidates', summary.get('candidates', summary.get('discovered', 0)))
    reasons = [record.get('reasonCode'), summary.get('error', {}).get('code'),
               summary.get('reason') if native else summary.get('stopCode')]
    if summary.get('state') == 'prerequisite':
        reasons.append('source_prerequisite')
    if native:
        reasons += [value.get('reason') for value in summary.get('channels', {}).values() if value.get('reason') != 'listing-end']
    else:
        reasons += [key for key in summary.get('partitionDispositions', {}) if key not in ('done', 'pending')]
        reasons += [key for key in summary.get('candidateDispositions', {})
                    if key not in ('retained', 'pending') and not key.startswith('inherited:')]
        reasons += list(record.get('taskDispositions', {}))
    if summary.get('saturatedPartitions'):
        reasons.append('discovery_not_exhaustive')
    if record.get('status') == 'running':
        reasons.append('running_finite_set')
    reasons = sorted({reason for reason in reasons if reason})
    provider = summary.get('providerOutcomeCounts', {}) if plan['kind'] == 'private' else {}
    provider_requests = sum(provider.values())
    provider_bytes = summary.get('providerBytes', 0) if plan['kind'] == 'private' else 0
    unknown = usage.get('unknownRequests', 0) + provider.get('unknown', 0) + provider.get('invalid', 0)
    capped = any('cap' in reason or 'budget' in reason or reason in ('timeout', 'rate_limit') for reason in reasons)
    exhausted = (summary.get('state') == 'completed' and not capped and not unknown
                 and not summary.get('pendingPartitions', 0) and not summary.get('pendingCandidates', 0)
                 and not summary.get('saturatedPartitions', 0))
    if plan['kind'] == 'hn':
        exhausted = False  # a current feed sample cannot establish history exhaustion
    if record.get('status') in ('unknown', 'error') or unknown:
        state = 'partial'
    elif (summary.get('state') == 'prerequisite' or any(reason in BLOCKS for reason in reasons)) and not retained:
        state = 'blocked'
    elif record.get('status') == 'not_started':
        state = 'partial'
    elif not summary:
        state = 'supported'
    elif not exhausted and plan['kind'] != 'hn':
        state = 'partial'
    elif retained:
        state = 'prepared'
    elif plan['kind'] == 'hn' and discovered:
        state = 'discovered'
    else:
        state = 'empty'
    return {'status': state, 'reasonCodes': reasons, 'exhausted': exhausted, 'limited': capped,
            'fetchedCountBasis': record.get('fetchedCountBasis', 'retained-prepared-records-lower-bound'),
            'counts': {'discovered': discovered, 'fetched': record.get('fetchedArticles', retained), 'prepared': retained,
                       'analysisReady': 0, 'requests': usage.get('requests' if native else 'sourceRequests', 0) + provider_requests,
                       'bytes': usage.get('bytes' if native else 'sourceBytes', 0) + provider_bytes, 'unknown': unknown,
                       'pending': counts.get('pending', 0) if native else summary.get('pendingCandidates', 0)}}


def observation(plan, record, run_id=RUN_ID):
    coverage = outcome(plan, record)
    counts = coverage['counts']
    summary = record.get('summary') or {}
    native = plan['kind'] == 'native'
    dispositions = summary.get('candidateDispositions')
    refused = (summary.get('counts', {}).get('refused') if native else summary.get('refusedTasks') if plan['kind'] == 'official' else
               sum(value for key, value in dispositions.items() if key not in ('retained', 'pending', 'unknown') and not key.startswith('inherited:'))
               if isinstance(dispositions, dict) else None)
    state = 'unknown' if record['status'] == 'unknown' or counts['unknown'] else (
        'blocked' if coverage['status'] == 'blocked' else 'error' if record['status'] == 'error' else
        'refused' if coverage['status'] == 'partial' and not counts['prepared'] else
        'empty' if not counts['prepared'] and not counts['discovered'] else 'ok')
    return {'eventId': 'acquisition-' + plan['id'], 'runId': run_id, 'cohort': 'collection-' + plan['kind'],
            'phase': 'acquisition', 'unitId': plan['id'], 'sourceId': plan['sourceId'],
            'startUtc': record['startedAt'], 'endUtc': record['endedAt'], 'durationMs': record['durationMs'],
            'durationProvenance': 'cli_wall', 'status': state, 'reasonCode': next(iter(coverage['reasonCodes']), None),
            'freshness': plan['freshness'], 'counts': {'requests': counts['requests'], 'retained': counts['prepared'],
            'refused': refused, 'unknown': counts['unknown'], 'pending': counts['pending'],
            'duplicate': summary.get('duplicates' if native else 'exactTextDuplicateGroups'), 'excluded': summary.get('exclusions') if native else None},
            'bytes': {'input': counts['bytes'], 'output': None, 'retained': None},
            'artifacts': ['collection/logs/' + plan['id'] + '.stdout.json', 'collection/configs/' + plan['id'] + '.json']}


def item_freshness(items, reused, fresh_from, cache):
    old = {item['recordPath'] for item in reused['privateItems']}
    result = {}
    for item in items:
        path = item['recordPath']
        if path in old:
            result[path] = {'freshness': 'reused', 'publicationDay': None}
            continue
        key = (path, item['recordSha256'])
        if key not in cache:
            raw = verified_path(path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != item['recordSha256']:
                raise ValueError('freshness_record_pin_changed')
            day = json.loads(raw).get('publicationDay')
            try:
                valid = isinstance(day, str) and date.fromisoformat(day).isoformat() == day
            except ValueError:
                valid = False
            cache[key] = {'freshness': ('fresh' if day >= fresh_from else 'backfill') if valid else 'unknown',
                          'publicationDay': day if valid else None}
        result[path] = cache[key]
    return result


def matrix_coverage(manifest, ledger, native, private, reused, freshness=None):
    rows = copy.deepcopy(manifest['sourceMatrix'])
    old_native = {item['exportPath'] for item in reused['nativeItems']}
    old_private = {item['recordPath'] for item in reused['privateItems']}
    freshness = freshness or {}
    for row in rows:
        source = row.get('adapterSourceId', row['sourceId'])
        private_refs = [item for item in private if item['sourceId'] == source]
        native_refs = [item for item in native if (item['sourceId'] == source and
                       (row.get('channel') is None or item['sourceKind'] == row['channel'])) or
                       FOREIGN_ROWS.get(item['sourceId']) == row['sourceId']]
        plans = [plan for plan in all_plans(manifest, ledger) if plan['rowId'] == row['sourceId']]
        coverage = [{'planId': plan['id'], 'freshness': plan['freshness'],
                     'dispatchState': ledger['plans'].get(plan['id'], {}).get('status', 'not_started'),
                     'committedRecords': ledger['plans'].get(plan['id'], {}).get('committedRecords', 0),
                     'fromDay': plan['configTemplate'].get('fromDay'), 'throughDay': plan['configTemplate'].get('throughDay'),
                     **outcome(plan, ledger['plans'].get(plan['id'], {}))} for plan in plans]
        if not plans:
            options = manifest['options']
            for window_freshness, first, last in (
                ('fresh', options.get('freshFromDay'), options.get('throughDay')),
                ('backfill', options.get('fromDay'),
                 (date.fromisoformat(options['freshFromDay']) - timedelta(days=1)).isoformat()
                 if options.get('freshFromDay') else None),
            ):
                coverage.append({'planId': None, 'freshness': window_freshness, 'fromDay': first, 'throughDay': last,
                                 'status': row['status'], 'reasonCodes': [row['reasonCode']] if row.get('reasonCode') else [],
                                 'exhausted': False, 'limited': False,
                                 'counts': {key: 0 for key in ('discovered', 'fetched', 'prepared', 'analysisReady', 'requests', 'bytes', 'unknown', 'pending')}})
        row['coverage'] = coverage
        row['counts'] = {'discovered': sum(part['counts']['discovered'] for part in coverage),
                         'fetched': sum(part['counts']['fetched'] for part in coverage),
                         'prepared': len(private_refs) + len(native_refs), 'analysisReady': 0,
                         'newCollection': sum(item['recordPath'] not in old_private for item in private_refs)
                                          + sum(item['exportPath'] not in old_native for item in native_refs),
                         'reused': sum(item['recordPath'] in old_private for item in private_refs)
                                   + sum(item['exportPath'] in old_native for item in native_refs),
                         'requests': sum(part['counts']['requests'] for part in coverage),
                         'bytes': sum(part['counts']['bytes'] for part in coverage)}
        for category in ('fresh', 'backfill'):
            row['counts'][category] = sum(freshness.get(item['recordPath'], {}).get('freshness') == category for item in private_refs)
            row['counts'][category] += sum(item.get('freshness') == category for item in native_refs)
        row['counts']['unclassifiedNew'] = row['counts']['newCollection'] - row['counts']['fresh'] - row['counts']['backfill']
        states = {part['status'] for part in coverage
                  if not ledger['plans'].get(part['planId'], {}).get('continuationPlanId')}
        if row.get('admissionStatus') == 'blocked':
            row['status'] = 'blocked'
        elif plans:
            row['status'] = ('partial' if 'partial' in states or ('supported' in states and ledger['endedAt']) else
                             'blocked' if states == {'blocked'} else 'prepared' if row['counts']['prepared'] else
                             'discovered' if 'discovered' in states else 'empty' if states == {'empty'} else 'supported')
        elif row['counts']['reused'] and row['status'] != 'blocked':
            row['status'] = 'prepared'
        row['analysisReadiness'] = 'requires_separate_processing_authorization'
        row['fallbackEnabled'] = any(plan.get('funding') for plan in plans)
        row['fallbackPrerequisites'] = sorted({ledger['plans'][plan['id']]['fallbackPrerequisite']
            for plan in plans if ledger['plans'].get(plan['id'], {}).get('fallbackPrerequisite')})
        row['runtimePrerequisites'] = sorted({reason for plan in plans for reason in
            (ledger['plans'].get(plan['id'], {}).get('summary') or {}).get('prerequisites', [])})
        if not any(plan['id'] in ledger['plans'] for plan in plans):
            row['runtimePrerequisites'] += row.get('officialPrerequisites', [])
        row['backendCounts'] = {}
        for plan in plans:
            for backend, count in ledger['plans'].get(plan['id'], {}).get('backendCounts', {}).items():
                row['backendCounts'][backend] = row['backendCounts'].get(backend, 0) + count
        row['providerKnownCostNano'] = sum(ledger['plans'].get(plan['id'], {}).get('providerKnownCostNano', 0) for plan in plans)
        row['modelSend'] = row['publicUse'] = False
    return rows


def admission_matrix(manifest, ledger, adapters):
    """Keep the research roster's exact IDs; adapter/channel identities stay explicit."""
    if not manifest.get('researchSources'):
        return adapters
    by_id = {row['sourceId']: row for row in adapters}
    result = []
    options = manifest['options']
    for fact in manifest['researchSources']:
        identifier = SOURCE_ALIASES.get(fact['id'], fact['id'])
        ids = (['korea-' + channel for channel in ROUTES] if identifier == 'korea-portal' else
               ['eu-commission', 'eu-employment'] if identifier == 'eu-commission' else [identifier])
        selected = [by_id[key] for key in ids if key in by_id]
        if not selected:
            raise ValueError('source_admission_row_missing_' + fact['id'])
        plans = [plan for plan in all_plans(manifest, ledger) if plan['rowId'] in ids]
        dispatched = [ledger['plans'][plan['id']] for plan in plans
                      if ledger['plans'].get(plan['id'], {}).get('startedAt')]
        states = {row['status'] for row in selected}
        status = next(iter(states)) if len(states) == 1 else 'partial'
        reasons = {row['reasonCode'] for row in selected if row.get('reasonCode')}
        reasons.update(reason for row in selected for part in row['coverage'] for reason in part['reasonCodes'])
        prerequisites = {reason for row in selected for reason in [*row['fallbackPrerequisites'], *row.get('runtimePrerequisites', [])]}
        if any(row['fallbackEnabled'] for row in selected) and not dispatched:
            prerequisites.add('deepseek_key_setup_not_checked_before_launch')
        if not dispatched and not reasons:
            reasons.add('awaiting_launch' if not ledger['startedAt'] else 'not_started')
        elif not reasons:
            reasons.add('configured_window_empty' if status == 'empty' else 'committed_records_available' if status == 'prepared' else status)
        counts = {key: sum(row['counts'][key] for row in selected) for key in selected[0]['counts']}
        backends = {backend for row in selected for backend in row.get('backendCounts', {})}
        result.append({
            'sourceId': fact['id'], 'name': fact.get('name', fact['id']), 'roster': fact['roster'],
            'fromDay': options['fromDay'], 'throughDay': options['throughDay'],
            'adapterSourceIds': ids, 'status': status, 'attemptStatus': 'attempted' if dispatched else 'not-started',
            'dispatchCounts': {state: sum(ledger['plans'].get(plan['id'], {}).get('status', 'not_started') == state for plan in plans)
                               for state in ('not_started', 'reserved', 'running', 'finished', 'unknown', 'error')},
            'capability': [{'sourceId': row['sourceId'], 'admission': row.get('admissionStatus', row['status']),
                            'kind': row['kind'], 'body': row.get('capability', {}).get('bodyStatus', row.get('bodyAcquisition', 'item-gated'))}
                           for row in selected],
            'reasonCodes': sorted(reasons), 'prerequisites': sorted(prerequisites), 'counts': counts,
            'backendCounts': {backend: sum(row.get('backendCounts', {}).get(backend, 0) for row in selected) for backend in sorted(backends)},
            'providerKnownCostNano': sum(row.get('providerKnownCostNano', 0) for row in selected),
            'finiteSets': [{'setId': plan.get('funding', {}).get('setId', plan['id']),
                            'freshness': plan['freshness'], 'limits': plan['ceilings'],
                            'paidFetchAllowance': plan.get('funding', {}).get('allowance', {}).get('fetch', 0),
                            'state': ledger['plans'].get(plan['id'], {}).get('status', 'not_started')}
                           for plan in plans],
            'coverage': [part for row in selected for part in row['coverage']],
            'modelSend': False, 'publicUse': False,
        })
    return result


def publish_admission(root, manifest, matrix):
    counts = {}
    for row in matrix:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    value = {'schemaVersion': 'zoop-source-admission-1', 'runId': manifest['runId'], 'generatedAt': stamp(),
             'fromDay': manifest['options'].get('fromDay'), 'throughDay': manifest['options'].get('throughDay'),
             'sourceCount': len(matrix), 'statusCounts': counts, 'sources': matrix,
             'stopNewWorkAt': manifest['options']['stopNewWorkAt'], 'stopPolicy': 'close-admission-drain-finite-children'}
    atomic(root / 'SOURCE_ADMISSION.json', value)
    lines = ['# Source admission', '', f"Run: `{manifest['runId']}`. New-set admission stops at `{value['stopNewWorkAt']}`; admitted finite children drain.",
             '', 'Native/public access is checked per item. Configured routes are not proven history coverage. Reused records are not new collection.',
             'Collection never grants model-send or public redistribution. Analysis readiness is established separately by the processing bridge.',
             '', '| Source ID | Capability/status | Attempt | New | Reused | Reason / prerequisite |',
             '|---|---|---|---:|---:|---|']
    for row in matrix:
        reasons = '; '.join(row.get('reasonCodes', []) + row.get('prerequisites', [])).replace('|', '&#124;').replace('\n', ' ')
        lines.append(f"| {row['sourceId']} | {row['status']} | {row.get('attemptStatus', 'not-started')} | {row['counts']['newCollection']} | {row['counts']['reused']} | {reasons} |")
    atomic(root / 'SOURCE_ADMISSION.md', '\n'.join(lines) + '\n', text=True)


def publish_index(root, manifest, ledger, *, freshness_cache=None):
    if manifest.get('replayPackages'):
        import collection_history
        collection_history.verify_replay_pins(manifest['replayPackages'])
    reused = load(manifest['reusedCorpus']['path'])
    native, private = list(reused['nativeItems']), list(reused['privateItems'])
    observations, aggregates = [], []
    for plan in all_plans(manifest, ledger):
        record = ledger['plans'].get(plan['id'], {})
        if record.get('observation'):
            observations.append(record['observation'])
        if record.get('itemsRef'):
            items = load(record['itemsRef']['path'])
            native.extend(items['nativeItems'])
            private.extend(items['privateItems'])
        if plan['kind'] == 'private' and record:
            aggregates.append({'planId': plan['id'], 'stateDir': plan['configTemplate']['stateDir'],
                               'sourceId': plan['sourceId'], 'summary': record.get('summary'),
                               'rights': 'unconfirmed', 'modelSend': False, 'publicUse': False})
    native, private = unique_items(native, 'exportPath'), unique_items(private, 'recordPath')
    if manifest.get('replayPackages'):
        private = collection_history.merge_private(private)
    freshness = item_freshness(private, reused, manifest['options'].get('freshFromDay', '2026-10-28'),
                              freshness_cache if freshness_cache is not None else {})
    adapters = matrix_coverage(manifest, ledger, native, private, reused, freshness)
    matrix = admission_matrix(manifest, ledger, adapters)
    published_at, checkpoint_id = stamp(), 'collection-' + uuid.uuid4().hex
    value = {'schemaVersion': 'zoop-overnight-collection-index-1', 'runId': manifest['runId'], 'generatedAt': stamp(),
             'publishedAt': published_at, 'checkpointId': checkpoint_id, 'startedAt': ledger['startedAt'], 'endedAt': ledger['endedAt'],
             'checkpointConsistency': 'immutable-committed-files-plus-atomic-state-observation',
             'nativeItems': native, 'privateItems': private, 'private': aggregates, 'reusedCorpus': reused['reusedCorpus'],
             'itemFreshness': freshness,
             'retainedReferenceErrors': reused['errors'], 'sourceMatrix': matrix, 'adapterMatrix': adapters,
             'observations': observations, 'aggregate': {'caps': manifest['options']['caps'], 'reserved': ledger['held'], 'spent': ledger['spent']},
             'ledgerPath': str(root / 'LEDGER.json'), 'planPath': str(root / 'PLAN.json'),
             'status': 'finished' if ledger['endedAt'] else ('running' if ledger['startedAt'] else 'ready-not-launched'),
             'modelSend': False, 'publicUse': False, 'requestLatencyMs': None, 'durationProvenance': 'cli_wall'}
    atomic(root / 'INDEX.json', value)
    atomic(root / 'INDEX_CHECKPOINT.json', {'checkpointId': checkpoint_id, 'publishedAt': published_at,
                                          'index': ref(root / 'INDEX.json')})
    publish_admission(root, manifest, matrix)


class RunningChild:
    def __init__(self, plan, root, config, exclusions, *, env=None):
        self.output = root / 'logs' / (plan['id'] + '.stdout.json')
        self.stdout = open(self.output, 'xb')
        self.stderr = open(root / 'logs' / (plan['id'] + '.stderr.txt'), 'xb')
        try:
            self.process = subprocess.Popen(child_command(plan['kind'], 'collect-child', config, exclusions),
                                            env=env if env is not None else clean_env(), cwd=root, stdin=subprocess.DEVNULL,
                                            stdout=self.stdout, stderr=self.stderr, start_new_session=True)
        except BaseException:
            self.close()
            raise
        self.pid = self.process.pid

    def poll(self):
        return self.process.poll()

    def terminate(self):
        os.killpg(self.pid, signal.SIGTERM)
        try:
            self.process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(self.pid, signal.SIGKILL)
            self.process.wait(timeout=TERMINATION_GRACE_SECONDS)

    def result(self):
        self.close()
        try:
            return load(self.output)
        except (ValueError, OSError):
            return None

    def close(self):
        self.stdout.close()
        self.stderr.close()


def stop_reason(root, manifest, ledger, now, *, budget=None):
    if ledger['closedReason'] and ledger['closedReason'] != 'revision_checkpoint_drain':
        return ledger['closedReason']
    if (root / 'STOP').exists():
        return 'operator_soft_stop'
    if now >= datetime.fromisoformat(manifest['options']['stopNewWorkAt']):
        return 'stop_new_deadline'
    if budget is not None:
        from zoop_ai_pipeline.live_budget import BudgetError
        try:
            budget.check_admission()
        except BudgetError as exc:
            return exc.code
    return ledger['closedReason']


def available(ledger, plan, caps):
    return all(ledger['held'][key] + ledger['spent'][key] + plan['ceilings'][key] <= caps[key] for key in BUDGET_KEYS)


def measured_usage(plan, record):
    summary = record.get('summary') or {}
    usage = summary.get('usage', {}) if plan['kind'] == 'native' else summary
    required = ('requests', 'bytes') if plan['kind'] == 'native' else ('sourceRequests', 'sourceBytes')
    if (record['status'] != 'finished' or usage.get('unknownRequests', 0)
            or any(type(usage.get(key)) is not int or usage[key] < 0 for key in required)):
        return None
    provider = summary.get('providerOutcomeCounts', {}) if plan['kind'] == 'private' else {}
    provider_bytes = summary.get('providerBytes', 0) if plan['kind'] == 'private' else 0
    if (not isinstance(provider, dict) or any(type(value) is not int or value < 0 for value in provider.values())
            or type(provider_bytes) is not int or provider_bytes < 0 or provider.get('unknown', 0) or provider.get('invalid', 0)
            or summary.get('providerUnknownByteUpperBound', 0)):
        return None
    return {'requests': usage[required[0]] + sum(provider.values()), 'bytes': usage[required[1]] + provider_bytes}


def settle(ledger, plan, record):
    # Missing receipts/unknown outcomes retain their entire original reservation.
    usage = measured_usage(plan, record)
    if usage is None:
        return
    for key in BUDGET_KEYS:
        ledger['held'][key] -= plan['ceilings'][key]
        ledger['spent'][key] += usage[key]
    record['reservationSettled'] = True


def partial_summary(plan):
    path = Path(plan['configTemplate']['stateDir']) / 'STATE.json'
    raw = path.read_bytes()
    envelope = json.loads(raw)
    data = envelope.get('state', envelope)
    if plan['kind'] == 'official':
        return {'state': 'prerequisite' if data.get('prerequisites') else 'partial',
                'sourceRequests': data['requests'], 'sourceBytes': data['bytes'], 'unknownRequests': data['unknownRequests'],
                'retainedInWindow': len(data['records']), 'currentDiscoveredCandidates': len(data['candidates']),
                'pendingCandidates': sum(item['status'] == 'pending' for item in data['tasks'].values()),
                'stopCode': data.get('stopCode'), 'prerequisites': data.get('prerequisites', []),
                'observedStateSha256': hashlib.sha256(raw).hexdigest()}
    if plan['kind'] == 'native':
        counts = {status: sum(item['outcome'] == status for item in data['items'].values())
                  for status in ('exported', 'pending', 'failed', 'refused', 'unknown')}
        return {'state': 'partial', 'counts': counts, 'candidateCount': data['candidateCount'],
                'usage': {key: data[key] for key in ('requests', 'bytes', 'unknownRequests')},
                'reason': data['reason'], 'channels': data['channels'],
                'observedStateSha256': hashlib.sha256(raw).hexdigest()}
    if isinstance(data.get('candidates'), str):
        db = sqlite3.connect((path.parent / 'QUEUE.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=0.1)
        try:
            candidates = dict(db.execute('SELECT status,count(*) FROM candidates GROUP BY status'))
            tasks = dict(db.execute('SELECT status,count(*) FROM tasks GROUP BY status'))
            current_discovered = db.execute(
                "SELECT count(*) FROM candidates WHERE COALESCE(json_extract(value,'$.fromPredecessor'),0)=0").fetchone()[0]
        finally:
            db.close()
    else:
        candidates, tasks = {}, {}
        for target, values in ((candidates, data['candidates'].values()), (tasks, data['tasks'].values())):
            for item in values:
                target[item['status']] = target.get(item['status'], 0) + 1
        current_discovered = sum(not item.get('fromPredecessor', False) for item in data['candidates'].values())
    return {'state': 'partial', 'candidates': sum(candidates.values()), 'retainedInWindow': candidates.get('retained', 0),
            'currentDiscoveredCandidates': current_discovered,
            'pendingCandidates': candidates.get('pending', 0), 'pendingPartitions': tasks.get('pending', 0),
            'sourceRequests': data['requests'], 'sourceBytes': data['bytes'], 'unknownRequests': data['unknownRequests'],
            'providerBytes': data.get('providerBytes', 0), 'providerUnknownByteUpperBound': data.get('providerUnknownByteUpperBound', 0),
            'providerUnknownRequests': data.get('providerUnknownRequests', 0), 'pendingProviderRequest': data.get('pendingProviderRequest'),
            'stopCode': data.get('stopCode'), 'observedStateSha256': hashlib.sha256(raw).hexdigest()}


def index_finished(root, plan, record, *, cache=None, partial=False):
    state = Path(plan['configTemplate']['stateDir'])
    items = {'nativeItems': [], 'privateItems': []}
    if state.exists() and (state / 'PLAN.json').exists():
        if plan['kind'] == 'native':
            items['nativeItems'] = native_items(plan, cache)
        elif plan['kind'] == 'private':
            items['privateItems'] = private_items(state, cache)
            if (state / 'STATE.json').exists():
                envelope = load(state / 'STATE.json')
                data = envelope.get('state', envelope)
                record['fetchedArticles'], record['providerKnownCostNano'] = 0, 0
                record['backendCounts'] = {}
                record['providerOutcomeCounts'] = {}
                for attempt in state_rows(data, state, 'attempts'):
                    receipt = attempt.get('providerReceipt', {})
                    outcome_ = attempt.get('providerOutcome', receipt.get('outcome'))
                    if outcome_:
                        record['providerOutcomeCounts'][outcome_] = record['providerOutcomeCounts'].get(outcome_, 0) + 1
                    if attempt.get('kind') == 'article' and (attempt.get('response') or outcome_ == 'success'):
                        record['fetchedArticles'] += 1
                        backend = attempt.get('extractionBackend', 'native')
                        record['backendCounts'][backend] = record['backendCounts'].get(backend, 0) + 1
                    actual = attempt.get('providerActualNano', receipt.get('actualNano'))
                    if type(actual) is int:
                        record['providerKnownCostNano'] += actual
                record['fetchedCountBasis'] = 'recorded-native-or-provider-successful-article-responses'
        elif plan['kind'] == 'official':
            items['privateItems'] = official_items(state, cache)
            record['backendCounts'] = {'official-source': len(items['privateItems'])}
            data = load(state / 'STATE.json')['state']
            record['taskDispositions'] = {}
            for item in data['tasks'].values():
                if item['status'] in ('refused', 'unknown') and item.get('code'):
                    code = item['code']
                    record['taskDispositions'][code] = record['taskDispositions'].get(code, 0) + 1
    record['committedRecords'] = len(items['nativeItems']) + len(items['privateItems'])
    if partial:
        record['itemCheckpoint'] = record.get('itemCheckpoint', 0) + 1
        suffix = '.items-' + str(record['itemCheckpoint']) + '.json'
        if (state / 'STATE.json').exists() and plan['kind'] != 'hn':
            record['checkpointSummary'] = partial_summary(plan)
            record['checkpointSummary']['providerOutcomeCounts'] = record.get('providerOutcomeCounts', {})
    else:
        suffix = '.items.json'
    destination = root / 'evidence' / (plan['id'] + suffix)
    if destination.exists():
        if load(destination) != items:
            raise ValueError('immutable_item_index_conflict')
    else:
        atomic(destination, items, immutable=True)
    record['itemsRef'] = ref(destination)


def execute(root, manifest, ledger, *, launch=RunningChild, now=utc, sleep=time.sleep, disk_free=None,
            budget=None, fetch_values=None, dart_values=None):
    """Single-writer dispatcher. Dependency seams are external process, clock and disk."""
    disk_free = disk_free or (lambda: shutil.disk_usage(root).free)
    exclusion = exclusion_sets(load(manifest['priorExclusions']['path']))
    current = root / 'evidence/CURRENT_EXCLUSIONS.json'
    if current.exists():
        exclusion = exclusion_sets(load(current))
    active = {}
    item_caches = {}
    freshness_cache = {}
    checkpoint_at = now() + timedelta(seconds=manifest['options'].get('checkpointSeconds', 30))
    fatal = None
    finish_at = datetime.fromisoformat(manifest['options']['finishBy'].replace('Z', '+00:00')) if 'finishBy' in manifest['options'] else None
    terminate_at = finish_at - timedelta(seconds=FINISH_RESERVE_SECONDS + 2 * TERMINATION_GRACE_SECONDS * manifest['options']['concurrency']) if finish_at else None
    # A restart never launches a reserved identity twice. A still-running orphan
    # blocks overlapping origins; no PID is killed or treated as completed work.
    uncertain_hosts = set()
    for plan in all_plans(manifest, ledger):
        record = ledger['plans'].get(plan['id'])
        if record and record['status'] in ('reserved', 'running', 'unknown'):
            record.update(status='unknown', reasonCode='previous_dispatch_outcome_unknown',
                          endedAt=record.get('endedAt') or now().isoformat(), durationMs=record.get('durationMs', 0))
            uncertain_hosts.update(plan['hosts'])
            state = Path(plan['configTemplate']['stateDir']) / 'STATE.json'
            if state.exists():
                absorb_state(state, exclusion)
            if not record.get('itemsRef'):
                index_finished(root, plan, record)
            record['observation'] = observation(plan, record, manifest['runId'])
    ledger['startedAt'] = ledger['startedAt'] or now().isoformat()
    ledger['endedAt'] = None
    try:
        while True:
            changed = False
            if active and now() >= checkpoint_at:
                for plan, _, _ in active.values():
                    record = ledger['plans'][plan['id']]
                    try:
                        index_finished(root, plan, record, cache=item_caches.setdefault(plan['id'], {}), partial=True)
                        record.pop('checkpointError', None)
                    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                        record['checkpointError'] = type(exc).__name__
                checkpoint_at = now() + timedelta(seconds=manifest['options'].get('checkpointSeconds', 30))
                changed = True
            for identifier, (plan, handle, started) in list(active.items()):
                if terminate_at is not None and now() >= terminate_at and handle.poll() is None:
                    ledger['closedReason'] = 'finish_deadline'
                    ledger['plans'][identifier]['terminationReason'] = 'finish_deadline'
                    handle.terminate()
                code = handle.poll()
                if code is None:
                    continue
                record = ledger['plans'][identifier]
                record.update(status='unknown' if code < 0 or record.get('terminationReason') else 'finished', returnCode=code,
                              endedAt=now().isoformat(), durationMs=round((time.monotonic() - started) * 1000, 3), summary=handle.result())
                if record['summary'] is None:
                    record.update(status='unknown', reasonCode='child_receipt_missing')
                try:
                    state = Path(plan['configTemplate']['stateDir']) / 'STATE.json'
                    if state.exists():
                        absorb_state(state, exclusion, keep_unattempted=record['status'] == 'finished')
                    index_finished(root, plan, record)
                except (OSError, ValueError, KeyError) as exc:
                    record.update(status='unknown', reasonCode='retained_index_invalid_' + type(exc).__name__)
                if record['status'] == 'finished' and measured_usage(plan, record) is None:
                    record.update(status='unknown', reasonCode='child_usage_unsettled_no_retry')
                finish_funding(budget, plan, record)
                settle(ledger, plan, record)
                record['observation'] = observation(plan, record, manifest['runId'])
                if not stop_reason(root, manifest, ledger, now(), budget=budget):
                    try:
                        enqueue_continuation(root, manifest, ledger, plan, record)
                    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                        record['continuationError'] = type(exc).__name__
                        record['reasonCode'] = 'continuation_prerequisite_' + type(exc).__name__
                for host in plan['hosts']:
                    delay = max(2, exclusion['hostDelays'].get(host, 0))
                    ledger['originReadyAt'][host] = (now() + timedelta(seconds=delay)).isoformat()
                if record['status'] == 'unknown':
                    uncertain_hosts.update(plan['hosts'])
                del active[identifier]
                changed = True
            reason = stop_reason(root, manifest, ledger, now(), budget=budget)
            if budget is not None and reason in ('operator_soft_stop', 'stop_new_deadline', 'finish_deadline') and not ledger.get('fundingAdmissionClosed'):
                budget.close_admission(reason)
                ledger['fundingAdmissionClosed'] = True
            if reason:
                ledger['closedReason'] = reason
            busy = {host for plan, _, _ in active.values() for host in plan['hosts']}
            for plan in fair_plans(manifest, ledger):
                if plan['id'] in ledger['plans']:
                    continue
                reason = stop_reason(root, manifest, ledger, now(), budget=budget)
                skip = reason
                if terminate_at is not None and now() + timedelta(seconds=plan['ceilings']['seconds']) >= terminate_at:
                    skip = skip or 'finish_window_insufficient'
                if uncertain_hosts.intersection(plan['hosts']):
                    skip = skip or 'origin_has_unsettled_dispatch_no_retry'
                if skip:
                    ledger['plans'][plan['id']] = {'status': 'not_started', 'reasonCode': skip}
                    changed = True
                    continue
                if len(active) >= manifest['options']['concurrency']:
                    break
                if busy.intersection(plan['hosts']):
                    continue
                if any(now() < datetime.fromisoformat(ledger['originReadyAt'][host]) for host in plan['hosts'] if host in ledger['originReadyAt']):
                    continue
                if not available(ledger, plan, manifest['options']['caps']):
                    if active:
                        continue
                    ledger['plans'][plan['id']] = {'status': 'not_started', 'reasonCode': 'resource_budget_exhausted'}
                    changed = True
                    continue
                if disk_free() < manifest['options']['minFreeBytes'] + 2 * (ledger['held']['bytes'] + plan['ceilings']['bytes']):
                    ledger['closedReason'] = reason = 'disk_reserve_reached'
                    ledger['plans'][plan['id']] = {'status': 'not_started', 'reasonCode': reason}
                    changed = True
                    continue
                if (root / 'configs' / (plan['id'] + '.exclusions.json')).exists():
                    ledger['plans'][plan['id']] = {'status': 'not_started', 'reasonCode': 'incomplete_materialization_no_replay'}
                    changed = True
                    continue
                config, exclusions = materialize(plan, exclusion, root / 'configs')
                reason = stop_reason(root, manifest, ledger, now(), budget=budget)
                if reason:
                    ledger['plans'][plan['id']] = {'status': 'not_started', 'reasonCode': reason}
                    changed = True
                    continue
                record = {'status': 'reserved', 'startedAt': now().isoformat(), 'ceilings': plan['ceilings'],
                          'config': ref(config), 'exclusions': ref(exclusions)}
                ledger['plans'][plan['id']] = record
                for key in BUDGET_KEYS:
                    ledger['held'][key] += plan['ceilings'][key]
                atomic(root / 'LEDGER.json', ledger)
                try:
                    if budget is not None or plan.get('funding'):
                        from zoop_ai_pipeline.live_budget import BudgetError
                        funding = plan_admission(plan)
                        if budget is None:
                            raise ValueError('funded_collection_budget_required')
                        try:
                            budget.admit_set(funding['setId'], funding['unitDigest'], funding['allowance'])
                        except BudgetError as exc:
                            record.update(status='not_started', reasonCode=exc.code)
                            for key in BUDGET_KEYS:
                                ledger['held'][key] -= plan['ceilings'][key]
                            changed = True
                            continue
                        record['fundedSetId'] = funding['setId']
                        if plan.get('funding'):
                            record['fallbackPrerequisite'] = None if fetch_values and fetch_values.get('DEEPSEEK_API_KEY') else 'deepseek_api_key_missing'
                        atomic(root / 'LEDGER.json', ledger)
                    if plan.get('funding'):
                        child_env = clean_env(fetch_values, plan['funding']['setId'])
                        if terminate_at is not None:
                            child_env[SEND_BEFORE_ENV] = terminate_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                        handle = launch(plan, root, config, exclusions, env=child_env)
                    elif plan['kind'] == 'official':
                        env = clean_env()
                        if terminate_at is not None:
                            env[SEND_BEFORE_ENV] = terminate_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                        if plan['sourceId'] == 'opendart' and dart_values and dart_values.get('OPENDART_API_KEY'):
                            env['OPENDART_API_KEY'] = dart_values['OPENDART_API_KEY']
                        handle = launch(plan, root, config, exclusions, env=env)
                    else:
                        env = clean_env() if terminate_at is not None else None
                        if terminate_at is not None:
                            env[SEND_BEFORE_ENV] = terminate_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                        handle = launch(plan, root, config, exclusions, env=env)
                    record.update(status='running', pid=handle.pid)
                    active[plan['id']] = (plan, handle, time.monotonic())
                    busy.update(plan['hosts'])
                except OSError as exc:
                    record.update(status='error', reasonCode='child_spawn_' + type(exc).__name__, endedAt=now().isoformat(), durationMs=0)
                    finish_funding(budget, plan, record)
                    record['observation'] = observation(plan, record, manifest['runId'])
                    # Proven failure before Popen returns does not authorize relaunch.
                changed = True
            if changed:
                atomic(current, frozen_exclusions(exclusion))
                atomic(root / 'LEDGER.json', ledger)
                publish_index(root, manifest, ledger, freshness_cache=freshness_cache)
            pending = any(plan['id'] not in ledger['plans'] for plan in all_plans(manifest, ledger))
            if not active and not pending:
                break
            sleep(0.1)
    except BaseException as exc:
        fatal = exc
        ledger['closedReason'] = 'controller_failure_drain'
    finally:
        # Even controller exceptions/soft signals close admission, not child lifetimes.
        for plan, handle, started in active.values():
            while handle.poll() is None:
                if terminate_at is not None and now() >= terminate_at:
                    handle.terminate()
                    break
                sleep(0.1)
            record = ledger['plans'][plan['id']]
            record.update(status='unknown', reasonCode='controller_failure_after_dispatch',
                          endedAt=now().isoformat(), durationMs=round((time.monotonic() - started) * 1000, 3), summary=handle.result())
            try:
                index_finished(root, plan, record)
                finish_funding(budget, plan, record)
            except Exception as exc:
                record['reasonCode'] = 'drained_receipt_failure_' + type(exc).__name__
                fatal = fatal or exc
            record['observation'] = observation(plan, record, manifest['runId'])
        for plan in all_plans(manifest, ledger):
            if plan['id'] not in ledger['plans']:
                ledger['plans'][plan['id']] = {'status': 'not_started', 'reasonCode': ledger['closedReason'] or 'controller_ended'}
        ledger['endedAt'] = now().isoformat()
        atomic(root / 'LEDGER.json', ledger)
        publish_index(root, manifest, ledger, freshness_cache=freshness_cache)
    if fatal:
        raise fatal
    return ledger


def run(root, approval_ref, fetch_env=None, opendart_env=None):
    if not approval_ref:
        raise ValueError('main_launch_approval_required')
    lock_fd = os.open(root / '.controller.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    previous_handlers = {}
    try:
        manifest, ledger = load(root / 'PLAN.json'), load(root / 'LEDGER.json')
        validate_manifest(root, manifest, ledger)
        checked = load(root / 'evidence/CHECK.json')
        if not checked['passed'] or checked.get('planSha256') != ledger['planSha256']:
            raise ValueError('offline_check_required')
        ledger['approvalRef'] = approval_ref

        def stop(signum, frame):
            if signum == signal.SIGUSR1 and ledger['closedReason'] not in (None, 'revision_checkpoint_drain'):
                return
            ledger['closedReason'] = 'revision_checkpoint_drain' if signum == signal.SIGUSR1 else 'operator_soft_stop'

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
            previous_handlers[sig] = signal.signal(sig, stop)
        execute(root, manifest, ledger, budget=acquisition_budget(root, manifest),
                fetch_values=read_runtime_key(fetch_env, 'DEEPSEEK_API_KEY'),
                dart_values=read_runtime_key(opendart_env, 'OPENDART_API_KEY'))
        atomic(root / 'FINAL_INVENTORY.json', {'schemaVersion': 'zoop-daytime-acquisition-final-2',
               'finishedAt': stamp(), 'plan': ref(root / 'PLAN.json'), 'index': ref(root / 'INDEX.json'),
               'ledger': ref(root / 'LEDGER.json'), 'modelSend': False, 'publicUse': False})
        print(json.dumps({'finished': True, 'index': str(root / 'INDEX.json'), 'spent': ledger['spent'], 'held': ledger['held']}))
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        os.close(lock_fd)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'check', 'smoke', 'run', 'validate-child', 'collect-child'))
    parser.add_argument('--root', type=Path, help='Explicit new collection root; no historical default')
    parser.add_argument('--approval-ref')
    parser.add_argument('--routes', type=Path)
    parser.add_argument('--run-config', type=Path, help='Same zoop-private-run-4 config including funding and finishBy as the model controller')
    parser.add_argument('--enable-deepseek-fetch', action='store_true')
    parser.add_argument('--known-unsent-proof', type=Path, help='Frozen Actor proof; only exact zero-attempt retained-native continuations')
    parser.add_argument('--prior-collection', action='append', type=Path, default=[], help='Explicit drained collection root; retained inputs and all attempted/unknown URLs remain pinned')
    parser.add_argument('--replay-package', action='append', type=Path, default=[], help='Immutable retained-markdown replay INDEX.json; offline evidence, not a prior collection or new acquisition')
    parser.add_argument('--fetch-env', type=Path, help='Main-configured literal DEEPSEEK_API_KEY file; run only')
    parser.add_argument('--opendart-env', type=Path, help='Only a Main-provided OPENDART_API_KEY file; only the opendart child receives it')
    parser.add_argument('--sec-company')
    parser.add_argument('--sec-contact')
    parser.add_argument('--sec-cik', action='append', default=[])
    parser.add_argument('--dart-ticker', action='append', default=[])
    parser.add_argument('--kind', choices=('native', 'private', 'official', 'hn'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--exclusions', type=Path)
    parser.add_argument('--concurrency', type=int, default=0, help='0 derives available source slots from CPU, RAM and file-descriptor reserves')
    parser.add_argument('--max-requests', type=int, default=100_000)
    parser.add_argument('--max-bytes', type=int, default=16_000_000_000)
    parser.add_argument('--set-requests', type=int, default=2000)
    parser.add_argument('--set-bytes', type=int, default=160_000_000)
    parser.add_argument('--set-seconds', type=int, default=1800)
    parser.add_argument('--min-free-bytes', type=int, default=4_000_000_000)
    parser.add_argument('--checkpoint-seconds', type=int, default=30)
    parser.add_argument('--from-day')
    parser.add_argument('--fresh-from-day')
    parser.add_argument('--through-day')
    parser.add_argument('--stop-new-at')
    args = parser.parse_args(argv)
    if args.command in ('validate-child', 'collect-child'):
        return child(args.kind, args.config, args.exclusions, validate=args.command == 'validate-child')
    if args.root is None:
        parser.error('--root is required')
    root = args.root.absolute()
    if args.command == 'prepare':
        if not args.approval_ref:
            parser.error('--approval-ref is required for the frozen acquisition scope')
        if args.routes is None:
            parser.error('--routes must name the complete 58-source research manifest')
        if any(value is None for value in (args.from_day, args.fresh_from_day, args.through_day, args.stop_new_at)):
            parser.error('explicit --from-day, --fresh-from-day, --through-day and --stop-new-at are required')
        if (args.concurrency < 0 or not 20 <= args.set_seconds <= 3600 or
                not 2_000_000 <= args.set_bytes <= 198_000_000 or not 1 <= args.set_requests <= 20_000 or
                args.max_requests < 52 or args.max_bytes < 11_000_000 or args.min_free_bytes < 0 or args.checkpoint_seconds < 1):
            parser.error('resource configuration outside finite adapter limits')
        if not date.fromisoformat(args.from_day) <= date.fromisoformat(args.fresh_from_day) <= date.fromisoformat(args.through_day):
            parser.error('ordered calendar window required')
        if datetime.fromisoformat(args.stop_new_at).tzinfo is None:
            parser.error('stop-new-at requires timezone')
        options = {'approvalRef': args.approval_ref, 'concurrency': args.concurrency,
                   'caps': {'requests': args.max_requests, 'bytes': args.max_bytes}, 'setRequests': args.set_requests,
                   'checkpointSeconds': args.checkpoint_seconds,
                   'setBytes': args.set_bytes, 'setSeconds': args.set_seconds, 'minFreeBytes': args.min_free_bytes,
                   'fromDay': args.from_day, 'freshFromDay': args.fresh_from_day, 'throughDay': args.through_day,
                   'stopNewWorkAt': args.stop_new_at}
        options.update(secCompany=args.sec_company, secContact=args.sec_contact, secCiks=args.sec_cik, dartTickers=args.dart_ticker)
        if args.prior_collection:
            options['priorCollections'] = [str(path.absolute()) for path in args.prior_collection]
        if args.replay_package:
            options['replayPackages'] = [str(path.absolute()) for path in args.replay_package]
        if args.known_unsent_proof is not None:
            if not args.enable_deepseek_fetch:
                parser.error('--known-unsent-proof requires current funded Fetch admission')
            if not args.prior_collection:
                parser.error('--known-unsent-proof requires explicit --prior-collection history')
            options['knownUnsentProof'] = ref(args.known_unsent_proof)
        if args.enable_deepseek_fetch:
            if args.run_config is None:
                parser.error('--enable-deepseek-fetch requires --run-config')
            options['fundingConfig'] = ref(args.run_config)
            validate_run_config(options['fundingConfig'], root, options['stopNewWorkAt'])
        elif args.run_config is not None:
            parser.error('--run-config acquisition funding requires --enable-deepseek-fetch')
        prepare(root, options, args.routes)
    elif args.command == 'check':
        check(root)
    elif args.command == 'smoke':
        smoke(root)
    elif args.command == 'run':
        run(root, args.approval_ref, args.fetch_env, args.opendart_env)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
