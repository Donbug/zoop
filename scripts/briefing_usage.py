"""Content-free JDBC ledger adapter for a single, explicitly claimed producer attempt.

The Java command owns DB writes; this module never copies prompts/results into the
ledger. A failed ledger write stops further spending. No implicit network retry.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import select
import threading
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_once(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('ledger_event_identity_conflict')
        return
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class CommandPipe:
    def __init__(self, command):
        if not isinstance(command, list) or not command or any(not isinstance(s, str) for s in command):
            raise ValueError('ledger_command_array_required')
        # stdout contains only protocol JSON. Inherited stderr must not include credentials/provider bodies.
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        self.lock = threading.Lock()

    def send(self, value):
        with self.lock:
            self.process.stdin.write(json.dumps(value, separators=(',', ':'))+'\n')
            self.process.stdin.flush()
            if not select.select([self.process.stdout], [], [], 60)[0]:
                raise ValueError('ledger_pipe_timeout')
            line = self.process.stdout.readline(65538)
            if not line or len(line) > 65536:
                raise ValueError('ledger_pipe_unavailable')
            result = json.loads(line)
            if result.get('ok') is not True:
                # Only bounded codes from the command, never SQL/connection/provider exceptions.
                code = result.get('code', 'ledger_rejected')
                raise ValueError(code if isinstance(code, str) and code.replace('_', '').isalnum() else 'ledger_rejected')
            return result

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.process.stdout.close()


class UsageSession:
    def __init__(self, pipe, claim, directory, *, estimate=None, heartbeat_seconds=30):
        self.pipe, self.claim = pipe, claim
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
            raise ValueError('private_ledger_directory_required')
        self.estimate, self.interval = estimate, heartbeat_seconds
        self.owner = None
        self.unit = None
        self.stage = None
        self.failed = None
        self.stop = threading.Event()
        self.thread = None
        self.outcome = 'available'
        self.terminal = False
        self.lock_file = self.directory/'.owner.lock'
        self.feature = 'briefing' if claim['purpose'] == 'generation' else 'briefing-outlook'

    def send(self, op, **fields):
        if self.failed is not None:
            raise ValueError('ledger_heartbeat_failed')
        owner = {} if self.owner is None else {k:self.owner[k] for k in ('attemptId', 'ownerToken')}
        return self.pipe.send({'op':op, **owner, **fields})

    def __enter__(self):
        fd=os.open(self.lock_file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        try:
            return self._enter()
        except BaseException:
            self.lock_file.unlink()
            raise

    def _enter(self):
        self.owner = self.pipe.send({'op':'claim', **self.claim})
        if self.owner.get('reused') and not (self.directory/'attempt.json').exists():
            raise ValueError('attempt_owned_by_another_output')
        if self.owner['status'] not in ('queued', 'running', 'verifying'):
            if self.owner['status'] != 'completed':
                raise ValueError('attempt_already_finished_use_saved_result_or_new_request_key')
            self.terminal = True
        write_once(self.directory/'attempt.json', {k:self.owner[k] for k in ('attemptId','ownerToken','roundId','attemptNo')})
        if self.interval and not self.terminal:
            self.thread = threading.Thread(target=self._heartbeat, daemon=True)
            self.thread.start()
        return self

    def _heartbeat(self):
        while not self.stop.wait(self.interval):
            try:
                self.send('heartbeat')
            except Exception:
                self.failed = True
                return

    def retry(self, number):
        self.unit = None if number == 0 else 'repair-'+str(number)

    def replay(self, stage, call):
        self.stage = stage
        self.send('local', eventId=call, stage=stage, feature=self.feature, mode='replay')

    def save_only(self, event, callback):
        self.stage = 'save_only'
        result = callback()  # The existing saved result is restored; no model/transport is involved.
        self.send('local', eventId=event, stage='save_only', feature=self.feature, mode='save_only')
        return result

    def invoke(self, stage, encoded, transport):
        self.stage = stage
        request = json.loads(encoded)
        call = digest(encoded)
        started=self.send('model_start', callId=call, stage=stage, feature=self.feature, provider='openai',
                  model=request['model'], promptVersion=self.claim['purpose']+'-'+digest(request['instructions'].encode())[:16],
                  retryUnit=self.unit, reasoningEffort=request.get('reasoning',{}).get('effort'))
        if started.get('created') is not True:
            raise ValueError('existing_ai_attempt_requires_reconciliation')
        try:
            status, raw = transport(encoded)
        except BaseException:
            receipt = self._receipt(call, 'unknown', None, None, None, None, 'transport_unknown', None)
            self._finish(receipt)
            raise
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                value = {}
        except (ValueError, UnicodeError):
            value = {}
        usage = value.get('usage') if isinstance(value.get('usage'), dict) else {}
        tokens = lambda key: usage.get(key) if type(usage.get(key)) is int and usage[key] >= 0 else None
        state = 'succeeded' if status == 200 and value.get('status') == 'completed' else \
                'cancelled' if status == 200 and value.get('status') == 'cancelled' else \
                'failed' if status >= 400 or value.get('status') in ('failed', 'incomplete') else 'unknown'
        model = value.get('model') if isinstance(value.get('model'), str) else None
        provider_error = value.get('error') if isinstance(value.get('error'), dict) else {}
        error = provider_error.get('code')
        if not isinstance(error, str) or not re.fullmatch('[a-z_]{1,80}',error):
            error = 'provider_'+state
        receipt = self._receipt(call, state, True, tokens('input_tokens'), tokens('output_tokens'),
                                digest(raw), None if state == 'succeeded' else error, model)
        try:
            path=self.directory.parent/'calls'/(call+'.response.json')
            if path.exists():
                if path.read_bytes()!=raw: raise ValueError('provider_response_identity_conflict')
            else:
                with path.open('xb') as stream:
                    os.chmod(path,0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        finally:
            self._finish(receipt)
        return status, raw

    def _receipt(self, call, state, sent, input_tokens, output_tokens, response_sha, error, model):
        return {'callId':call, 'status':state, 'transmissionConfirmed':sent, 'inputTokens':input_tokens,
                'outputTokens':output_tokens, 'finishedAt':now(), 'responseSha256':response_sha, 'errorCode':error,
                'reportedModel':model, 'estimate':self.estimate if input_tokens is not None and output_tokens is not None else None}

    def _finish(self, receipt):
        # Write ahead of the DB receipt acknowledgement, so save/reconcile does not need another provider call.
        path = self.directory/(receipt['callId']+'-'+digest(json.dumps(receipt, sort_keys=True).encode())+'.receipt.json')
        try:
            write_once(path, receipt)
        finally:
            self.send('model_finish', **receipt)

    def __exit__(self, kind, value, traceback):
        try:
            return self._exit(kind,value,traceback)
        finally:
            self.lock_file.unlink()

    def _exit(self, kind, value, traceback):
        if self.terminal:
            return False
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
        try:
            self.send('finish', outcome=self.outcome if kind is None else 'cancelled' if kind is KeyboardInterrupt else 'failed',
                      failureStage=None if kind is None and self.outcome == 'available' else self.stage,
                      failureReason=None if kind is None and self.outcome == 'available' else 'quality_withheld' if kind is None else 'producer_failed')
        except Exception:
            if kind is None:
                raise
        return False


@contextlib.contextmanager
def recorded(client, session):
    previous = getattr(client, 'usage', None)
    if previous is not None:
        raise ValueError('client_already_recorded')
    with session:
        client.usage = session
        try:
            yield session
        finally:
            client.usage = previous


def reconcile(directory, pipe):
    """Re-ingest saved metadata only, under the original owner/AI IDs. Never dispatch or close an attempt."""
    directory = Path(directory).resolve()
    if not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError('private_ledger_directory_required')
    lock = directory/'.owner.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        owner = json.loads((directory/'attempt.json').read_bytes())
        if set(owner) != {'attemptId','ownerToken','roundId','attemptNo'}:
            raise ValueError('reconciliation_owner_contract')
        groups = {}
        fields = {'callId','status','transmissionConfirmed','inputTokens','outputTokens','finishedAt',
                  'responseSha256','errorCode','reportedModel','estimate'}
        for path in sorted(directory.glob('*.receipt.json')):
            if path.is_symlink() or path.stat().st_size > 65536:
                raise ValueError('reconciliation_receipt_file')
            receipt = json.loads(path.read_bytes())
            if set(receipt) != fields or receipt['status'] not in ('succeeded','failed','cancelled','unknown'):
                raise ValueError('reconciliation_receipt_contract')
            expected = receipt['callId']+'-'+digest(json.dumps(receipt, sort_keys=True).encode())+'.receipt.json'
            if path.name != expected:
                raise ValueError('reconciliation_receipt_digest')
            groups.setdefault(receipt['callId'], []).append(receipt)
        selected = []
        for receipts in groups.values():
            final = [r for r in receipts if r['status'] != 'unknown']
            if len(final) > 1:
                raise ValueError('reconciliation_conflicting_final_receipts')
            selected.append(final[0] if final else max(receipts, key=lambda r:r['finishedAt']))
        for receipt in selected:
            pipe.send({'op':'model_finish', 'attemptId':owner['attemptId'],
                       'ownerToken':owner['ownerToken'], **receipt})
        return {'status':'RECONCILED', 'receipts':len(selected), 'newModelCalls':0}
    finally:
        lock.unlink()
