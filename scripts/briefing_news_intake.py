"""Bounded news discovery -> unchanged native HTTP/ingestion -> shared briefing pool.

Uses the current pipeline's publisher adapters, not the historical PoC. Discovery
metadata is never a publication clock or a permission. Each enabled source needs
its own current authority; private collector defaults are not public licences.
No search provider, paid fallback, model request or member-specific acquisition.
"""
from __future__ import annotations

import copy
from datetime import datetime
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import briefing_replay as b
from briefing_usage import write_once

SCHEMA = 'briefing-news-sources-v1'
RESULT = 'briefing-news-collection-v1'
KST = ZoneInfo('Asia/Seoul')
OPERATIONS = {'read', 'store', 'quote-display', 'model-send'}
DENIALS = {'robots_denied', 'robots_malformed', 'robots_unavailable', 'http_401', 'http_403', 'http_429'}


def require(ok, reason):
    if not ok:
        raise ValueError('briefing_news_' + reason)


def private_path(path):
    path = Path(path)
    require(path.is_absolute() and not path.is_symlink() and path.is_file()
            and path.stat().st_mode & 0o077 == 0, 'private_registry_required')
    return path


def load_registry(cfg):
    """An absent source authorization is reported, never manufactured from a URL."""
    if not cfg.get('newsSourceRegistry'):
        return None
    path = private_path(cfg['newsSourceRegistry'])
    raw = path.read_bytes()
    require(len(raw) <= 1_000_000, 'registry_size')
    from zoop_ai_pipeline.private_intake import _json
    value = _json(raw)
    require(set(value) == {'schemaVersion', 'revision', 'sources'} and value['schemaVersion'] == SCHEMA
            and isinstance(value['revision'], str) and value['revision'].strip(), 'registry_schema')
    require(isinstance(value['sources'], list) and len(value['sources']) <= 8, 'source_limit')
    seen = set()
    for source in value['sources']:
        require(set(source) == {'sourceId', 'enabled', 'authorizationRef', 'grant', 'nativeProcessing', 'maxListingPages',
                               'maxArticleAttempts', 'maxDocuments'}, 'source_schema')
        require(source['sourceId'] not in seen and type(source['enabled']) is bool, 'duplicate_source')
        seen.add(source['sourceId'])
        profile(source['sourceId'])
        for key, ceiling in [('maxListingPages', 3), ('maxArticleAttempts', 12), ('maxDocuments', 4)]:
            require(type(source[key]) is int and 1 <= source[key] <= ceiling, 'source_limit')
        require(source['maxDocuments'] <= source['maxArticleAttempts'], 'source_limit')
        require(isinstance(source['authorizationRef'], str) and source['authorizationRef'].strip(), 'authorization')
        from zoop_ai_pipeline.ingestion_contracts import Grant
        grant = Grant.model_validate(source['grant'])
        require(grant.source_id == source['sourceId'], 'source_grant_identity')
        native = source['nativeProcessing']
        require(set(native) == {'profile', 'recipients', 'authorizationRef'}
                and native['profile'] == 'briefing-native-v2-standard'
                and isinstance(native['recipients'], list) and all(isinstance(r, str) for r in native['recipients'])
                and isinstance(native['authorizationRef'], str) and native['authorizationRef'].strip(), 'native_authorization')
    return value, b.digest(raw)


def profile(source_id):
    from zoop_ai_pipeline.news_sources import source_catalog, source_descriptor
    # Do not turn the private catalogue's unconfirmed rights into an access grant.
    rows = [r for r in source_catalog() if r['sourceId'] == source_id]
    require(len(rows) == 1 and rows[0]['adapter'] in ('native-archive', 'configured'), 'unsupported_source')
    row = rows[0]
    require(row.get('discoveryStatus') not in ('blocked-policy', 'blocked-http', 'blocked-provider-429')
            and row.get('bodyPolicy') != 'native-pdf-intake-required', 'blocked_source')
    return row, source_descriptor(source_id)


def authorized(source, now=None):
    grant = source['grant']
    current = now or datetime.now(KST)
    expires = datetime.fromisoformat(grant['expiresAt']) if grant.get('expiresAt') else None
    return (source['enabled'] and grant['enabled'] and grant['rights'] == 'known'
            and OPERATIONS <= set(grant['allowedOperations']) and bool(grant['evidence'])
            and 'openai' in grant['recipients']
            and {'briefing-outlook', 'semantic-verification'} <= set(grant['purposes'])
            and {'openai', 'typesafe-native'} <= set(source['nativeProcessing']['recipients'])
            and (expires is None or (expires.tzinfo is not None and expires > current)))


def current_source(cfg, source_id, registry_sha):
    current = load_registry(cfg)
    require(current is not None and current[1] == registry_sha, 'source_authority_changed')
    matches = [s for s in current[0]['sources'] if s['sourceId'] == source_id]
    require(len(matches) == 1 and authorized(matches[0]), 'source_not_authorized')
    return matches[0]


def policy():
    from zoop_ai_pipeline.collection_contracts import Policy
    return Policy.model_validate({'schemaVersion': 'zoop-collection-policy-1', 'userAgent': 'ZoopBriefing/1.0',
        'timeoutSeconds': 15, 'maxTotalSeconds': 300, 'maxRedirects': 0, 'maxRequests': 30,
        'maxResponseBytes': 5_000_000, 'maxTotalBytes': 30_000_000, 'minIntervalSeconds': 2,
        'allowedMediaTypes': ['text/html'], 'syntheticLoopback': False})


class DiscoveryPolicy:
    def __init__(self, base):
        self.base = base
        self.allowed_media_types = ['text/html', 'application/xml', 'text/xml', 'application/rss+xml', 'application/atom+xml']

    def __getattr__(self, key):
        return getattr(self.base, key)


def publication_in_window(value, round_, observed):
    require(bool(value), 'publication_missing')
    start, cutoff = (datetime.fromisoformat(round_[k]) for k in ('windowFrom', 'windowTo'))
    seen = datetime.fromisoformat(observed)
    require(start < seen <= cutoff, 'observed_outside_window')
    from zoop_ai_pipeline.private_intake import _publication
    original = _publication(value)
    require(original['precision'] in ('instant', 'day'), 'publication_timezone_missing')
    published = datetime.fromisoformat(value) if original['precision'] == 'instant' else datetime.fromisoformat(original['day'])
    if published.tzinfo is None:
        # Same contract as the existing native clock: a date-only article may
        # enter by its real first observation, never an invented release instant.
        # This does NOT prove a fresh announcement after the AM/PM boundary.
        require(start.astimezone(KST).date() <= published.date() <= min(cutoff.astimezone(KST).date(), seen.astimezone(KST).date()),
                'publication_outside_window')
        return 'first_observed'
    else:
        require(start < published <= cutoff and published <= seen, 'publication_outside_window')
        return 'published_at'


def retain(source, registry_sha, round_, root, response, companies=None):
    """The exact GET bytes supply both metadata and native evidence, without re-fetch."""
    from zoop_ai_pipeline.collection import Fetcher, collect as native_collect
    from zoop_ai_pipeline.collection_contracts import Request
    from zoop_ai_pipeline.ingestion import Ingestor, Store
    from zoop_ai_pipeline.ingestion_contracts import Authority, Run, Export
    from zoop_ai_pipeline.news_archives import article_metadata, validate_article_url
    source_id = source['sourceId']
    row_profile, descriptor = profile(source_id)
    require(authorized(source), 'source_not_authorized')
    validate_article_url(source_id, response.final_url, descriptor=descriptor)
    meta = article_metadata(source_id, response.body, response.final_url, descriptor=descriptor)
    eligibility = publication_in_window(meta.published_at, round_, response.fetched_at)
    from zoop_ai_pipeline.private_intake import _publication
    declared = _publication(meta.published_at)
    published_at = meta.published_at if declared['precision'] == 'instant' else declared['day']
    require(bool(meta.publisher) and (meta.canonical_url is None or meta.canonical_url == response.final_url), 'article_identity')
    if companies is not None:
        from zoop_ai_pipeline.ingestion_parsers import prepare
        from briefing_company_names import matches
        prepared = prepare(response.body, 'text/html', meta.article_xpath)
        require(bool(matches(prepared['text'], companies)), 'no_catalogued_company')
    identifier = 'news-' + b.digest(response.final_url.encode())[:40]
    item = root / 'items' / identifier
    item.mkdir(mode=0o700, parents=True, exist_ok=True)
    native = root / 'native'
    native.mkdir(mode=0o700, exist_ok=True)
    rights = {'sourceId': source_id, 'rightsBasis': 'explicit-current-source-authority',
        'registrySha256': registry_sha, 'authorizationRef': source['authorizationRef'],
        'grant': source['grant'], 'nativeProcessing': source['nativeProcessing'],
        'articleUrl': response.final_url, 'bodySha256': b.digest(response.body),
        'fetchedAt': response.fetched_at, 'publication': declared, 'eligibilityBasis': eligibility, 'rawRedistribution': False}
    write_once(item / 'rights.json', rights)
    grant = copy.deepcopy(source['grant'])
    grant.update(allowedOperations=['read', 'store', 'quote-display'], recipients=[], purposes=[])
    sources = {'schemaVersion': 'zoop-ingestion-s2-1', 'revision': round_['id'] + '-news-' + registry_sha[:12], 'sources': [{
        'sourceId': source_id, 'adapter': 'collected-http', 'inputRoot': str(native), 'allowedHosts': row_profile['articleHosts'],
        'scopes': [{'scopeId': identifier, 'selection': 'one source-authorized article; exact GET body and clocks',
                    'initialCursor': None, 'articleXPath': meta.article_xpath,
                    'timestampLimitations': ['Discovery dates are hints only; original publication precision and real GET observation retained.',
                        'Date-only publication uses real first observation, not proof that the announcement happened after this round started.']}],
        'grant': grant}]}
    write_once(item / 'sources.json', sources)
    request = Request.model_validate({'schemaVersion': 'zoop-collection-1', 'collectionId': identifier,
        'sourceId': source_id, 'scopeId': identifier, 'targets': [{'candidateId': identifier, 'url': response.final_url,
        'supplierDocumentId': identifier, 'title': meta.title, 'publisher': meta.publisher,
        'publishedAt': published_at, 'documentKind': 'news'}]})

    class Captured(Fetcher):
        def fetch(self, url):
            require(url == response.final_url, 'captured_identity')
            self.authority_guard()
            return response

    result = native_collect(item / 'sources.json', policy(), request,
        fetcher=Captured(policy(), row_profile['articleHosts']),
        validate_response=lambda _, body: require(b.digest(body.body) == rights['bodySha256'], 'body_pin'))
    require(result['state'] == 'complete', 'native_collection')
    write_once(item / 'collection-result.json', result)
    store = Store(item / 'ingestion')
    try:
        engine = Ingestor(store, Authority(item / 'sources.json'))
        ingested = engine.run(Run.model_validate({'schemaVersion': 'zoop-ingestion-s2-1', 'roundId': identifier,
            'sourceId': source_id, 'scopeId': identifier, 'window': None, 'checkpointRevision': 0,
            'fixtureManifestHash': result['manifest']['sha256'], 'cleanerVersion': 'exact-copy-1'}), Path(result['manifestPath']))
        ref = ingested['documentRefs'][0]
        exported = engine.export(Export.model_validate({'schemaVersion': 'zoop-ingestion-s2-1', 'roundId': identifier,
            'sourceId': source_id, **{k: ref[k] for k in ('page', 'ordinal', 'documentId', 'rawVersion', 'documentVersion')}}), require_store=True)
    finally:
        store.close()
    write_once(item / 'export.json', exported)
    row = {'sourceId': source_id, 'nativeItemRoot': str(item), 'candidate': {'newsId': identifier,
        'channel': row_profile['category'], 'title': meta.title, 'publisher': meta.publisher,
        'publicationDay': declared['day'], 'url': response.final_url},
        'documentId': ref['documentId'], 'documentVersion': ref['documentVersion'], 'fetchedAt': response.fetched_at,
        'nativeBodySha256': result['targets'][0]['bodySha256'], 'nativeReceiptSha256': result['targets'][0]['receiptSha256'], 'rights': rights}
    write_once(item / 'row.json', row)
    return row, exported, root


def collect(cfg, round_, parent, *, fetcher_factory=None, monotonic=time.monotonic):
    from zoop_ai_pipeline.collection import Fetcher
    from zoop_ai_pipeline.news_archives import initial_tasks, parse_listing, validate_article_url
    registry = load_registry(cfg)
    root = parent / 'news-sources'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    binding = {'roundId': round_['id'], 'windowFrom': round_['windowFrom'], 'windowTo': round_['windowTo'],
               'registrySha256': registry[1] if registry else None}
    done = root / 'result.json'
    if done.exists():
        result = json.loads(done.read_bytes())
        require(result['binding'] == binding, 'saved_collection_binding')
        entries = []
        for relative in result['items']:
            item = root / relative
            require(not item.is_symlink() and item.resolve().is_relative_to(root.resolve()), 'saved_item_path')
            for name, sha in result['itemPins'][relative].items():
                require(name in ('row.json', 'export.json', 'rights.json', 'sources.json', 'collection-result.json')
                        and b.digest((item / name).read_bytes()) == sha, 'saved_item_pin')
            row, exported = (json.loads((item / name).read_bytes()) for name in ('row.json', 'export.json'))
            publication_in_window(exported['observation']['publishedAt'], round_, row['fetchedAt'])
            original = Path(row['nativeItemRoot'])
            require(original == item and b.digest((root / 'native/collections' / row['candidate']['newsId'] / 'bodies' /
                (row['nativeBodySha256'] + '.bin')).read_bytes()) == row['nativeBodySha256'], 'saved_body_pin')
            current_source(cfg, row['sourceId'], binding['registrySha256'])
            entries.append((row, exported, root))
        return entries, result
    require(not (root / 'started.json').exists(), 'interrupted_acquisition_not_repeated')
    write_once(root / 'started.json', binding)
    items, coverage = [], []
    # One shared five-minute discovery allowance, not five minutes per member/source.
    deadline = min(monotonic() + 300, monotonic() + max(0, (datetime.fromisoformat(round_['windowTo']) - datetime.now(KST)).total_seconds() - 190))
    for source in registry[0]['sources'] if registry else []:
        source_id = source['sourceId']
        state = {'sourceId': source_id, 'status': 'disabled' if not source['enabled'] else 'rights_prerequisite',
                 'listingPages': 0, 'articleAttempts': 0, 'retained': 0, 'excluded': {}, 'complete': False}
        coverage.append(state)
        if not authorized(source):
            continue
        if monotonic() >= deadline:
            state['status'] = 'time_budget'
            continue
        row_profile, descriptor = profile(source_id)
        fetcher = (fetcher_factory or Fetcher)(DiscoveryPolicy(policy()), row_profile['articleHosts'])
        fetcher.authority_guard = lambda sid=source_id: current_source(cfg, sid, registry[1])
        fetcher.run_deadline = min(fetcher.run_deadline, deadline)
        queue = list(initial_tasks(source_id, round_['windowFrom'][:10], round_['windowTo'][:10], descriptor=descriptor))
        seen_tasks, candidates = set(), {}
        source_root = root / source_id
        source_root.mkdir(mode=0o700, exist_ok=True)
        state['status'] = 'partial'
        try:
            while queue and state['listingPages'] < source['maxListingPages']:
                task = queue.pop(0)
                if task.key in seen_tasks:
                    continue
                seen_tasks.add(task.key)
                state['listingPages'] += 1
                try:
                    response = fetcher.fetch(task.url)
                    label = 'listing-' + b.digest(task.url.encode())[:24]
                    b.write_once(source_root / (label + '.bin'), response.body)
                    write_once(source_root / (label + '.json'), {'url': response.final_url,
                        'bodySha256': b.digest(response.body), 'observedAt': response.fetched_at})
                    listing = parse_listing(source_id, task, response.body, response.final_url, descriptor=descriptor)
                except Exception as error:
                    code = getattr(error, 'code', 'listing_unavailable')
                    state['excluded'][code] = state['excluded'].get(code, 0) + 1
                    if code in DENIALS | {'timeout', 'request_budget', 'byte_budget'}:
                        state['status'] = code
                        break
                    state['status'] = 'listing_unavailable'
                    continue
                for candidate in listing.candidates:
                    validate_article_url(source_id, candidate.url, descriptor=descriptor)
                    candidates.setdefault(candidate.url, candidate)
                queue.extend(listing.next_tasks)
            # RSS time is used to order requests, never to create/replace source timestamps.
            if state['status'] in DENIALS | {'timeout', 'request_budget', 'byte_budget'}:
                continue
            companies = None
            if cfg.get('companyCatalogue'):
                catalogue = json.loads(Path(cfg['companyCatalogue']).read_bytes())
                companies = [{'companyId': c['company_id'], 'name': c['name'], 'aliases': c['aliases']}
                             for c in catalogue['companies']]
            from briefing_company_names import matches
            ordered = sorted(candidates.values(), key=lambda c: (bool(matches(c.title or '', companies or [])),
                c.published_at or c.archive_day or '', c.url), reverse=True)
            fetcher.policy = policy()
            for candidate in ordered[:source['maxArticleAttempts']]:
                state['articleAttempts'] += 1
                try:
                    response = fetcher.fetch(candidate.url)
                    row, _, _ = retain(source, registry[1], round_, root, response, companies)
                    items.append(str(Path(row['nativeItemRoot']).relative_to(root)))
                    state['retained'] += 1
                    if state['retained'] >= source['maxDocuments']:
                        break
                except Exception as error:
                    code = getattr(error, 'code', str(error))
                    # Stable codes only; provider bodies/URLs never enter public operational coverage.
                    code = code if isinstance(code, str) and code.replace('_', '').isalnum() and len(code) < 130 else 'article_unavailable'
                    state['excluded'][code] = state['excluded'].get(code, 0) + 1
                    if code in DENIALS or code in ('timeout', 'request_budget', 'byte_budget'):
                        state['status'] = code
                        break
        except Exception as error:
            code = getattr(error, 'code', None)
            state['status'] = code if code in DENIALS | {'timeout', 'request_budget', 'byte_budget'} else 'listing_unavailable'
        if state['retained'] and state['status'] == 'listing_unavailable':
            state['status'] = 'partial'
    unique_items = list(dict.fromkeys(items))
    pins = {item: {name: b.digest((root / item / name).read_bytes()) for name in
                  ('row.json', 'export.json', 'rights.json', 'sources.json', 'collection-result.json')} for item in unique_items}
    result = {'schemaVersion': RESULT, 'binding': binding, 'items': unique_items, 'itemPins': pins,
        'sources': coverage, 'status': 'partial' if registry else 'not_configured',
        'complete': False, 'modelCalls': 0, 'memberSpecificRequests': 0,
        'message': 'Bounded registered sources only; missing collection is not evidence of no market news.'}
    write_once(done, result)
    # The same immutable read path is used on first execution and resume.
    return collect(cfg, round_, parent, fetcher_factory=fetcher_factory, monotonic=monotonic)
