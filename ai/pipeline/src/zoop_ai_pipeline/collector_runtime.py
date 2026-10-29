"""Container controller: one writer per state tree, supervised workers, consistent checkpoints, bounded SIGTERM shutdown."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import collector_checkpoint as cp
from .collector_s3 import open_store, parse_uri

EXIT_OK, EXIT_CONFIG, EXIT_BUSY, EXIT_CHECKPOINT, EXIT_PATH = 0, 2, 3, 4, 5
EXIT_RESTORE, EXIT_NO_CONTROLLER, EXIT_REQUEST = 6, 7, 8

DEFAULT_STATE_ROOT = "/var/lib/zoop-collector"
DEFAULT_CONFIG_DIR = "/etc/zoop-collector"
KINDS = {"private": "PRIVATE", "korea": "KOREA", "official": "OFFICIAL"}
SECRET_FOR = {"official": ("OPENDART_API_KEY",)}
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ConfigError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def log(event: str, **fields) -> None:
    print(json.dumps({"ts": cp.utc_now(), "event": event, **fields}, sort_keys=True), file=sys.stderr, flush=True)


@dataclass(frozen=True)
class PathSpec:
    name: str
    config_path: Path
    s3_uri: str | None
    sha256: str | None

    @property
    def state_dir_name(self) -> str:
        return self.name


@dataclass(frozen=True)
class Settings:
    run_id: str
    s3_uri: str | None
    state_root: Path
    config_dir: Path
    checkpoint_interval: float
    drain_seconds: float
    final_seconds: float
    stop_timeout: float
    reserve_seconds: float
    pause_timeout: float
    recover_seconds: float
    restore: str
    image: dict
    paths: dict[str, PathSpec]

    @property
    def control_dir(self) -> Path:
        return self.state_root / "control"

    @property
    def staging_dir(self) -> Path:
        return self.state_root / "checkpoints"

    def state_dir(self, name: str) -> Path:
        return self.state_root / name

    def stop_budget(self) -> float:
        return self.drain_seconds + self.recover_seconds + self.final_seconds + self.reserve_seconds


def _number(env: dict, key: str, default: float, *, minimum: float) -> float:
    raw = env.get(key)
    try:
        value = float(default if raw in (None, "") else raw)
    except ValueError:
        raise ConfigError("setting_invalid", key) from None
    if value < minimum:
        raise ConfigError("setting_invalid", key)
    return value


def settings_from_env(env: dict | None = None, *, require_run: bool = True) -> Settings:
    env = dict(os.environ if env is None else env)
    run_id = env.get("ZOOP_COLLECTOR_RUN_ID", "")
    if require_run or run_id:
        try:
            cp.run_prefix("x", run_id)
        except cp.CheckpointError:
            raise ConfigError("run_id_invalid", "ZOOP_COLLECTOR_RUN_ID") from None
    s3_uri = env.get("ZOOP_COLLECTOR_S3_URI") or None
    if s3_uri is not None:
        try:
            parse_uri(s3_uri)
        except cp.CheckpointError:
            raise ConfigError("setting_invalid", "ZOOP_COLLECTOR_S3_URI") from None
    config_dir = Path(env.get("ZOOP_COLLECTOR_CONFIG_DIR", DEFAULT_CONFIG_DIR))
    state_root = Path(env.get("ZOOP_COLLECTOR_STATE_ROOT", DEFAULT_STATE_ROOT))
    for value in (config_dir, state_root):
        if not value.is_absolute() or str(value) != os.path.abspath(value):
            raise ConfigError("setting_invalid", "absolute canonical directory required")
    paths = {}
    for name, prefix in KINDS.items():
        raw = env.get(f"{prefix}_CONFIG")
        if not raw:
            continue
        sha = env.get(f"{prefix}_CONFIG_SHA256") or None
        if sha is not None and not _SHA.fullmatch(sha):
            raise ConfigError("setting_invalid", f"{prefix}_CONFIG_SHA256")
        uri = env.get(f"{prefix}_CONFIG_S3_URI") or None
        if uri is not None:
            if sha is None:
                raise ConfigError("config_pin_required", f"{prefix}_CONFIG_SHA256")
            try:
                parse_uri(uri)
            except cp.CheckpointError:
                raise ConfigError("setting_invalid", f"{prefix}_CONFIG_S3_URI") from None
        path = Path(raw)
        if not path.is_absolute() or str(path) != os.path.abspath(path):
            raise ConfigError("setting_invalid", f"{prefix}_CONFIG")
        paths[name] = PathSpec(name, path, uri, sha)
    settings = Settings(
        run_id=run_id, s3_uri=s3_uri, state_root=state_root, config_dir=config_dir,
        checkpoint_interval=_number(env, "ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS", 900, minimum=0),
        drain_seconds=_number(env, "ZOOP_COLLECTOR_DRAIN_SECONDS", 40, minimum=1),
        final_seconds=_number(env, "ZOOP_COLLECTOR_FINAL_SECONDS", 50, minimum=1),
        stop_timeout=_number(env, "ZOOP_COLLECTOR_STOP_TIMEOUT_SECONDS", 120, minimum=1),
        reserve_seconds=_number(env, "ZOOP_COLLECTOR_RESERVE_SECONDS", 15, minimum=0),
        pause_timeout=_number(env, "ZOOP_COLLECTOR_PAUSE_TIMEOUT_SECONDS", 120, minimum=1),
        recover_seconds=_number(env, "ZOOP_COLLECTOR_RECOVER_SECONDS", 10, minimum=1),
        restore=env.get("ZOOP_COLLECTOR_RESTORE") or "auto",
        image={"gitCommit": env.get("ZOOP_COLLECTOR_IMAGE_REVISION") or None, "package": "zoop-ai-pipeline"},
        paths=paths)
    if settings.restore != "auto" and not re.fullmatch(r"\d{1,6}-[0-9a-f]{12}", settings.restore):
        raise ConfigError("setting_invalid", "ZOOP_COLLECTOR_RESTORE")
    if settings.stop_budget() > settings.stop_timeout:
        raise ConfigError("stop_budget_exceeds_timeout",
                          f"drain+recover+final+reserve={settings.stop_budget():g}s > {settings.stop_timeout:g}s")
    return settings


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fetch_pinned(store_for, uri: str, destination: Path, sha256: str, config_dir: Path) -> None:
    if destination.parent != config_dir:
        raise ConfigError("config_path_not_fixed", str(destination))
    bucket, key = parse_uri(uri)
    raw = store_for(bucket).get_bytes(key)
    if raw is None:
        raise ConfigError("config_object_missing", uri)
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ConfigError("config_sha256_mismatch", uri)
    try:
        _atomic_write(destination, raw, 0o444)
    except OSError as exc:
        raise ConfigError("config_unwritable", str(destination)) from exc


def _pinned_file(path: Path, sha256: str | None) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError:
        raise ConfigError("config_missing", str(path)) from None
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        raise ConfigError("config_sha256_mismatch", str(path))
    return raw


def load_path_config(name: str, path: Path):
    from pydantic import ValidationError
    from .ingestion_contracts import IngestionFailure
    try:
        if name == "private":
            from .private_intake import load_config
        elif name == "korea":
            from .korea_corpus import load_config
        else:
            from .official_source_intake import load_config
        return load_config(path)
    except IngestionFailure as exc:
        raise ConfigError("config_invalid", exc.code) from None
    except (OSError, ValueError, ValidationError, TypeError, KeyError):
        raise ConfigError("config_invalid", name) from None


def supply_configs(settings: Settings, env: dict, store_for) -> dict:
    """Fetch (S3, sha256-pinned) or read (mounted file) each configuration, validate it, and return the parsed configs."""
    configs = {}
    for name, spec in settings.paths.items():
        if spec.s3_uri is not None:
            _fetch_pinned(store_for, spec.s3_uri, spec.config_path, spec.sha256, settings.config_dir)
        _pinned_file(spec.config_path, spec.sha256)
        config = load_path_config(name, spec.config_path)
        expected = settings.state_dir(name)
        if Path(config.state_dir) != expected:
            raise ConfigError("state_dir_not_fixed", f"{name}: stateDir must be {expected}")
        if name == "private" and (config.fallback or config.predecessor or config.known_unsent):
            raise ConfigError("config_unsupported", "private: fallback, predecessor and knownUnsent are not supported in the container")
        if name == "official" and config.predecessor:
            raise ConfigError("config_unsupported", "official: predecessor is not supported in the container")
        if name == "official":
            for secret in SECRET_FOR["official"] if config.source_id == "opendart" else ():
                if not env.get(secret):
                    raise ConfigError("secret_missing", secret)
        if name == "korea":
            for field, key in (("rights_evidence", "KOREA_RIGHTS_EVIDENCE_S3_URI"), ("exclusion_manifest", "KOREA_EXCLUSIONS_S3_URI")):
                evidence = getattr(config, field)
                uri = env.get(key) or None
                if uri is not None:
                    _fetch_pinned(store_for, uri, Path(evidence.path), evidence.sha256, settings.config_dir)
                _pinned_file(Path(evidence.path), evidence.sha256)
        configs[name] = config
    if not configs:
        raise ConfigError("no_collection_path", "set at least one of PRIVATE_CONFIG, KOREA_CONFIG, OFFICIAL_CONFIG")
    return configs


class Worker:
    """One collection path in its own process group, controlled over a command pipe and an event pipe."""

    def __init__(self, settings: Settings, name: str, env: dict, *, recover_only: bool = False):
        self.name, self.recover_only = name, recover_only
        self.events: queue.Queue = queue.Queue()
        self.result: dict | None = None
        self.acked: set[str] = set()
        self.killed = False
        read_fd, write_fd = os.pipe()
        child_env = {key: env[key] for key in ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "SSL_CERT_FILE", "ZOOP_STATE_DIR",
                                               "ZOOP_AI_WORKER_STATE_DIR", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE")
                     if key in env}
        child_env.update({key: value for key, value in env.items() if key.startswith("ZOOP_COLLECTOR_")})
        child_env.update({f"{prefix}_CONFIG": str(settings.paths[kind].config_path)
                          for kind, prefix in KINDS.items() if kind in settings.paths})
        for key in ("KOREA_RIGHTS_EVIDENCE_S3_URI", "KOREA_EXCLUSIONS_S3_URI"):
            child_env.pop(key, None)
        for secret in SECRET_FOR.get(name, ()):
            if secret in env:
                child_env[secret] = env[secret]
        child_env["ZOOP_COLLECTOR_EVENT_FD"] = str(write_fd)
        command = [sys.executable, "-B", "-m", "zoop_ai_pipeline.collector_cli", "worker", name]
        if recover_only:
            command.append("--stopped")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=sys.stderr, stderr=sys.stderr, env=child_env,
                                        pass_fds=(write_fd,), start_new_session=True)
        os.close(write_fd)
        self._reader = threading.Thread(target=self._read, args=(read_fd,), daemon=True)
        self._reader.start()

    def _read(self, descriptor: int) -> None:
        with os.fdopen(descriptor, "r", encoding="utf-8") as lines:
            for line in lines:
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    log("worker_event_invalid", worker=self.name)
        self.events.put(None)

    def send(self, line: str) -> None:
        try:
            self.process.stdin.write((line + "\n").encode())
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def poll(self) -> int | None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event is None:
                continue
            if event.get("event") == "paused":
                self.acked.add(event["nonce"])
            elif event.get("event") == "result":
                self.result = event
        return self.process.poll()

    def signal_group(self, number: int) -> None:
        try:
            os.killpg(self.process.pid, number)
        except (ProcessLookupError, PermissionError):
            pass

    def stop(self) -> None:
        self.send("STOP")
        self.signal_group(signal.SIGTERM)

    def kill(self) -> None:
        self.killed = True
        self.signal_group(signal.SIGKILL)

    def reap(self, timeout: float) -> int | None:
        try:
            code = self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            return None
        self._reader.join(1)
        self.poll()
        return code


class Controller:
    def __init__(self, settings: Settings, env: dict, store, prefix: str):
        self.settings, self.env, self.store = settings, env, store
        self.prefix = cp.run_prefix(prefix, settings.run_id) if store is not None else ""
        self.workers: dict[str, Worker] = {}
        self.configs: dict = {}
        self.seq = 0
        self.previous: dict | None = None
        self.last_checkpoint: dict | None = None
        self.checkpoint_failures = 0
        self.stop_at: float | None = None
        self.phase = "starting"
        self.wake = threading.Event()
        self.lock_fd: int | None = None
        self.started = cp.utc_now()
        self.shutdown: dict[str, str] = {}

    # -- lifecycle ---------------------------------------------------------------------------------

    def acquire_lock(self) -> bool:
        self.settings.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock_fd = os.open(self.settings.state_root / "controller.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        for directory, mode in ((self.settings.control_dir, 0o755), (self.settings.control_dir / "requests", 0o1777),
                                (self.settings.control_dir / "responses", 0o755)):
            directory.mkdir(mode=mode, exist_ok=True)
            os.chmod(directory, mode)
        if self.settings.staging_dir.exists():
            shutil.rmtree(self.settings.staging_dir)
        self.settings.staging_dir.mkdir(mode=0o700)
        return True

    def on_signal(self, number, _frame) -> None:
        if self.stop_at is None:
            self.stop_at = time.monotonic()
            log("stop_requested", signal=signal.Signals(number).name)
        self.wake.set()

    def state_dirs(self) -> dict[str, Path]:
        return {name: self.settings.state_dir(name) for name in self.configs if self.settings.state_dir(name).is_dir()}

    def restore_if_needed(self) -> None:
        occupied = [name for name in self.configs if self.settings.state_dir(name).exists() and any(self.settings.state_dir(name).iterdir())]
        selector = "latest" if self.settings.restore == "auto" else self.settings.restore
        wanted = cp.find_checkpoint(self.store, self.prefix, self.settings.run_id, selector)
        pointer = cp.read_pointer(self.store, self.prefix, self.settings.run_id)
        if pointer is not None:
            self.last_checkpoint = pointer
            self.previous = cp.find_checkpoint(self.store, self.prefix, self.settings.run_id, "latest")[0]
            self.seq = pointer["seq"]
        if occupied:
            log("state_present", paths=occupied, restore="skipped")
        elif wanted is not None:
            manifest = wanted[0]
            check_restorable(manifest, self.settings, {n: spec.config_path for n, spec in self.settings.paths.items()})
            started = time.monotonic()
            cp.restore(self.store, self.prefix, self.settings.run_id, self.settings.state_root, selector=selector)
            log("restored", seq=manifest["seq"], checkpointId=manifest["checkpointId"], seconds=round(time.monotonic() - started, 2))
        elif self.settings.restore != "auto":
            raise ConfigError("checkpoint_not_found", self.settings.restore)

    def start_workers(self) -> None:
        for name in self.configs:
            self.workers[name] = Worker(self.settings, name, self.env)
            log("worker_started", worker=name, pid=self.workers[name].process.pid)

    def live(self) -> list[Worker]:
        return [worker for worker in self.workers.values() if worker.poll() is None]

    # -- checkpoints -------------------------------------------------------------------------------

    def pause_all(self, timeout: float) -> None:
        nonce = uuid.uuid4().hex
        waiting = self.live()
        for worker in waiting:
            worker.send(f"PAUSE {nonce}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.stop_at is None:
            if all(worker.poll() is not None or nonce in worker.acked for worker in waiting):
                return
            time.sleep(0.05)
        for worker in waiting:
            worker.send("RESUME")
        if self.stop_at is not None:
            raise cp.CheckpointError("controller_stopping")
        raise cp.CheckpointError("pause_timeout", f"{timeout:g}s")

    def checkpoint(self, kind: str, *, deadline: float | None = None) -> dict:
        seq, identifier = self.seq + 1, cp.new_checkpoint_id()
        staging = self.settings.staging_dir / f"{seq:06d}-{identifier}"
        quiescent = kind == "final"
        started = time.monotonic()
        if not quiescent:
            if self.stop_at is not None:
                raise cp.CheckpointError("controller_stopping")
            self.pause_all(self.settings.pause_timeout)
        try:
            tables = cp.capture(self.state_dirs(), staging)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            if not quiescent:
                for worker in self.live():
                    worker.send("RESUME")
        paused = time.monotonic() - started
        try:
            paths = [{"name": name, "stateDir": str(self.settings.state_dir(name)),
                      "configSha256": hashlib.sha256(self.settings.paths[name].config_path.read_bytes()).hexdigest(),
                      "unknownOutcomes": cp.count_unknown(name, staging),
                      "shutdown": self.shutdown.get(name, "running" if name in self.workers and self.workers[name].poll() is None else "exited")}
                     for name in self.state_dirs()]
            previous = ({"seq": self.previous["seq"], "checkpointId": self.previous["checkpointId"],
                         "manifestSha256": self.last_checkpoint["manifestSha256"]} if self.previous and self.last_checkpoint else None)
            manifest = cp.build_manifest(run_id=self.settings.run_id, checkpoint_id=identifier, seq=seq, kind=kind, tables=tables,
                                         paths=paths, unknown=sum(item["unknownOutcomes"] for item in paths), previous=previous,
                                         image=self.settings.image)
            pointer = cp.publish(self.store, self.prefix, staging, manifest, self.previous, deadline=deadline)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self.seq, self.previous, self.last_checkpoint = seq, manifest, pointer
        result = {"seq": seq, "checkpointId": identifier, "kind": kind, "files": len(manifest["files"]),
                  "bytes": sum(item["bytes"] for item in manifest["files"]), "unknownOutcomes": manifest["unknownOutcomes"],
                  "manifestKey": pointer["manifestKey"], "pausedSeconds": round(paused, 2),
                  "seconds": round(time.monotonic() - started, 2)}
        log("checkpoint_uploaded", **result)
        return result

    def attempt_checkpoint(self, kind: str) -> dict:
        try:
            result = self.checkpoint(kind)
            self.checkpoint_failures = 0
            return {"ok": True, "checkpoint": result}
        except cp.CheckpointError as exc:
            if exc.code == "controller_stopping":
                return {"ok": False, "error": exc.code}
            self.checkpoint_failures += 1
            log("checkpoint_failed", kind=kind, code=exc.code, detail=str(exc), consecutive=self.checkpoint_failures)
            return {"ok": False, "error": exc.code, "detail": str(exc)}

    def serve_requests(self) -> None:
        requests = self.settings.control_dir / "requests"
        for path in sorted(requests.glob("*.json")):
            try:
                request = json.loads(path.read_bytes())
                identifier = request["id"]
                if not re.fullmatch(r"[0-9a-f]{32}", identifier) or request["kind"] != "checkpoint":
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError):
                path.unlink(missing_ok=True)
                continue
            response = (self.attempt_checkpoint("requested") if self.stop_at is None
                        else {"ok": False, "error": "controller_stopping"})
            _atomic_write(self.settings.control_dir / "responses" / f"{identifier}.json",
                          json.dumps({"id": identifier, **response}, sort_keys=True).encode(), 0o644)
            path.unlink(missing_ok=True)

    def write_status(self) -> None:
        status = {"schemaVersion": "zoop-collector-status-1", "runId": self.settings.run_id, "pid": os.getpid(),
                  "startedAt": self.started, "updatedAt": cp.utc_now(), "phase": self.phase,
                  "workers": {name: {"pid": worker.process.pid, "exitCode": worker.process.poll(),
                                     "result": worker.result and {k: v for k, v in worker.result.items() if k != "event"}}
                              for name, worker in self.workers.items()},
                  "lastCheckpoint": self.last_checkpoint and {"seq": self.last_checkpoint["seq"],
                                                              "checkpointId": self.last_checkpoint["checkpointId"],
                                                              "manifestKey": self.last_checkpoint["manifestKey"],
                                                              "updatedAt": self.last_checkpoint["updatedAt"]},
                  "checkpointFailures": self.checkpoint_failures}
        _atomic_write(self.settings.control_dir / "status.json", json.dumps(status, sort_keys=True, indent=2).encode(), 0o644)

    # -- main loop and shutdown --------------------------------------------------------------------

    def supervise(self) -> None:
        interval = self.settings.checkpoint_interval
        next_checkpoint = time.monotonic() + interval if interval else None
        next_status = 0.0
        self.phase = "running"
        while self.stop_at is None and self.live():
            self.serve_requests()
            now = time.monotonic()
            if next_checkpoint is not None and now >= next_checkpoint and self.stop_at is None:
                self.attempt_checkpoint("periodic")
                next_checkpoint = time.monotonic() + interval
            if now >= next_status:
                self.write_status()
                next_status = now + 2
            self.wake.wait(0.2)

    def drain(self, deadline: float) -> list[Worker]:
        """Stop admission, wait until `deadline`, then kill whatever is still running. Returns the killed workers."""
        for worker in self.live():
            worker.stop()
        while self.live() and time.monotonic() < deadline:
            time.sleep(0.05)
        killed = self.live()
        for worker in killed:
            log("drain_deadline_exceeded", worker=worker.name)
            worker.kill()
        for worker in self.workers.values():
            worker.reap(5)
        return killed

    def recover(self, killed: list[Worker]) -> None:
        """A killed worker left a pending request or attempt; a stop-at-birth worker records it as unknown and exits."""
        for worker in killed:
            self.shutdown[worker.name] = "killed-unrecovered"
            recovery = Worker(self.settings, worker.name, self.env, recover_only=True)
            code = recovery.reap(self.settings.recover_seconds)
            if code is None:
                recovery.kill()
                recovery.reap(5)
                log("recovery_failed", worker=worker.name, reason="timeout")
            elif code != 0:
                log("recovery_failed", worker=worker.name, exitCode=code)
            else:
                self.shutdown[worker.name] = "killed-marked-unknown"
                log("recovered", worker=worker.name)

    def finish(self) -> int:
        self.phase = "stopping"
        began = self.stop_at if self.stop_at is not None else time.monotonic()
        if self.stop_at is not None:
            killed = self.drain(began + self.settings.drain_seconds)
            self.recover(killed)
            deadline = began + self.settings.stop_timeout - self.settings.reserve_seconds
        else:
            for worker in self.workers.values():
                worker.reap(5)
            deadline = None
        self.write_status()
        try:
            self.checkpoint("final", deadline=deadline)
            final_ok = True
        except cp.CheckpointError as exc:
            log("final_checkpoint_failed", code=exc.code, detail=str(exc))
            final_ok = False
        failed = [name for name, worker in self.workers.items()
                  if self.shutdown.get(name) == "killed-unrecovered"
                  or (worker.process.returncode not in (0, None) and not worker.killed)
                  or (worker.result or {}).get("state") == "refused"]
        for name in failed:
            log("path_failed", worker=name, exitCode=self.workers[name].process.returncode,
                result=self.workers[name].result)
        self.phase = "stopped"
        self.write_status()
        if not final_ok:
            return EXIT_CHECKPOINT
        return EXIT_PATH if failed else EXIT_OK


def check_restorable(manifest: dict, settings: Settings, config_paths: dict) -> None:
    """A checkpoint resumes only the paths and plans it was taken for, at the same absolute state directories."""
    for entry in manifest["paths"]:
        name = entry["name"]
        if name not in settings.paths:
            raise ConfigError("restore_path_not_configured", name)
        if entry["stateDir"] != str(settings.state_dir(name)):
            raise ConfigError("restore_state_dir_mismatch", f"{name}: {entry['stateDir']}")
        if entry["configSha256"] != hashlib.sha256(Path(config_paths[name]).read_bytes()).hexdigest():
            raise ConfigError("restore_config_changed", name)


def s3_store(bucket: str):
    from .collector_s3 import S3Store
    return S3Store(bucket)


def run(env: dict | None = None, *, store_factory=s3_store) -> int:
    env = dict(os.environ if env is None else env)
    try:
        settings = settings_from_env(env)
        if settings.s3_uri is None:
            raise ConfigError("setting_missing", "ZOOP_COLLECTOR_S3_URI")
    except ConfigError as exc:
        log("config_refused", code=exc.code, detail=str(exc))
        return EXIT_CONFIG
    stores: dict = {}

    def store_for(bucket: str):
        if bucket not in stores:
            stores[bucket] = store_factory(bucket)
        return stores[bucket]

    bucket, prefix = parse_uri(settings.s3_uri)
    controller = Controller(settings, env, store_for(bucket), prefix)
    if not controller.acquire_lock():
        log("controller_busy", stateRoot=str(settings.state_root))
        return EXIT_BUSY
    previous = {number: signal.signal(number, controller.on_signal) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        controller.configs = supply_configs(settings, env, store_for)
        controller.restore_if_needed()
        log("controller_started", runId=settings.run_id, paths=sorted(controller.configs), seq=controller.seq,
            stopBudgetSeconds=settings.stop_budget())
        controller.start_workers()
        controller.supervise()
        return controller.finish()
    except ConfigError as exc:
        log("config_refused", code=exc.code, detail=str(exc))
        return EXIT_CONFIG
    except cp.CheckpointError as exc:
        log("restore_failed", code=exc.code, detail=str(exc))
        return EXIT_RESTORE
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        os.close(controller.lock_fd)
