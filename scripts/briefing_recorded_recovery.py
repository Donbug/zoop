"""Explicit, finite recovery of an unpublished slot from its already stored inputs.

No fetching, clock replacement, budget reset, terminal-attempt edit or unknown
request replay. The ordinary automatic poller never enters this command.
"""
import json
import os
import signal
from datetime import date, datetime, timedelta
from pathlib import Path
import briefing_native_intake as native
import briefing_priority_server as producer
from briefing_usage import write_once


def recover(cfg, edition, day):
    import psycopg
    from psycopg.rows import dict_row
    server = native.server
    now = datetime.now(server.KST)
    server.require(date.fromisoformat(day) == now.date(), 'recorded_recovery_today_only')
    authorization = os.environ.get('BRIEFING_RECORDED_RECOVERY_AUTHORIZATION', '')
    server.require(bool(authorization.strip()), 'recorded_recovery_authorization_required')
    rid = 'brf-' + day + '-' + edition
    os.environ['BRIEFING_RECORDED_RECOVERY_ROUND'] = rid
    with psycopg.connect(cfg['dsn'], autocommit=True, row_factory=dict_row) as conn:
        server.require(conn.execute("SELECT pg_try_advisory_lock(hashtext('zoop-briefing-server-v1')) AS owned").fetchone()['owned'], 'another_briefing_writer')
        job = conn.execute('SELECT * FROM briefing_common_schedule_jobs WHERE id=%s', (rid,)).fetchone()
        server.require(job is not None, 'recorded_recovery_existing_job_required')
        if server.published(conn, job):
            return {'roundId': rid, 'status': 'already_published', 'newModelCalls': 0}
        server.require(job['status'] == 'requires_recovery' and job['scheduled_at'] < now, 'recorded_recovery_unpublished_slot_required')
        saved = conn.execute('SELECT status,published_at FROM briefing_rounds WHERE id=%s', (rid,)).fetchone()
        server.require(saved is not None and saved['status'] == 'failed' and saved['published_at'] is None, 'recorded_recovery_failed_original_required')
        active = conn.execute("SELECT 1 FROM briefing_attempts WHERE round_id=%s AND status IN ('queued','running','verifying')", (rid,)).fetchone()
        server.require(active is None, 'recorded_recovery_active_attempt')
        unknown = conn.execute("SELECT 1 FROM ai_executions WHERE briefing_attempt_id IN (SELECT id FROM briefing_attempts WHERE round_id=%s) AND status IN ('unknown','running')", (rid,)).fetchone()
        server.require(unknown is None, 'recorded_recovery_unknown_send')
        recovery = Path(cfg['work']) / 'recoveries' / rid / native.b.digest(authorization.encode())[:16]
        recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
        server.require(not (recovery / 'started.json').exists(), 'recorded_recovery_already_started')
        r = {'id': rid, 'date': day, 'edition': edition, 'scheduledAt': job['scheduled_at'].isoformat(),
             'windowFrom': job['window_from'].isoformat(), 'windowTo': job['scheduled_at'].isoformat()}
        context = {**cfg, 'recordedOnly': True, 'recordedRecoveryAuthorization': authorization,
                   'recordedCollectionRoot': str(Path(cfg['work']) / 'native' / rid),
                   'recoveryDeadline': (now + timedelta(minutes=40)).isoformat()}
        # Preserve the failed job and all original terminal attempt snapshots.
        write_once(recovery / 'started.json', {'round': r, 'authorizationRef': authorization,
            'startedAt': native.b.now(), 'originalJobStatus': job['status'], 'originalFinishedAt': job['finished_at'].isoformat() if job['finished_at'] else None})
        def timeout(signum, frame):
            raise TimeoutError('finite_recorded_recovery_deadline')
        previous = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(45 * 60)
        stage = 'native'
        try:
            baseline = native.native_command(context, 'state', {}, recovery / 'baseline.request.json')
            ready = native.prepare(context, r)
            write_once(recovery / 'native-result.json', ready)
            server.require(ready.get('status') != 'withheld', 'recorded_recovery_candidates_withheld')
            native.register_authority(context, ready)
            incoming = native.native_command(context, 'import', ready, recovery / 'import.request.json')
            activated = native.native_command(context, 'activate', {'baseline': baseline, 'incoming': incoming}, recovery / 'activate.request.json')
            write_once(recovery / 'activated.json', activated)
            stage = 'generation'
            # The slot stays requires_recovery while held by this writer lock;
            # prepare must still see its original failed round. Publication is atomic.
            result = producer.produce({**context, 'expectedGraphVersion': activated['graphVersion']}, job)
            server.require(server.published(conn, job), 'recorded_recovery_publication_proof')
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='completed',finished_at=now() WHERE id=%s AND status='requires_recovery'", (rid,))
            write_once(recovery / 'completed.json', result)
            return result
        except BaseException:
            if server.published(conn, job):
                conn.execute("UPDATE briefing_common_schedule_jobs SET status='completed',finished_at=now() WHERE id=%s AND status='requires_recovery'", (rid,))
                return {'roundId': rid, 'status': 'published', 'recoveredFromStorage': True}
            write_once(recovery / 'failed.json', {'roundId': rid, 'stage': stage, 'failedAt': native.b.now(), 'status': 'requires_recovery'})
            latest = conn.execute('SELECT status FROM briefing_attempts WHERE round_id=%s ORDER BY attempt_no DESC LIMIT 1', (rid,)).fetchone()
            if latest is None or latest['status'] == 'completed':
                failure = recovery / 'failure'; failure.mkdir(mode=0o700, exist_ok=True)
                server.record_input_failure(context, r, failure, stage=stage, reason='recorded_recovery_failed')
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
