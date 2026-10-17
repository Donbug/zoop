#!/usr/bin/env python3
"""Local-only TLS + basic-auth proof of `zoop-ai-graph preflight|init` against a REAL Neo4j 5 Community server, through the same Python driver and the same
installed CLI an operator runs. It is not an AWS, Fargate, RBAC or GraphDbStatus check, and it emulates nothing: every TLS verdict below is the real driver's,
against a real server that REQUIRES TLS on Bolt.

Two ways to run it (both fail, never skip, and both are loopback-only):

1. MANAGED (explicit flag): the script creates a throwaway private PKI, starts its OWN private containers from the digest-pinned official image (never pulling
   it, publishing only 127.0.0.1, secrets only through the environment), runs the stages below and removes exactly what it created:
       ZOOP_GRAPH_USER=neo4j ZOOP_GRAPH_PASSWORD=<random, >= 16 chars> ZOOP_GRAPH_AUTH=basic   (generated when absent)
       ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_tls_smoke.py --manage-containers [--stages cases,smoke,regression]
       ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_tls_smoke.py --cleanup RUN_ID   # exact containers by label+name; never anything else
   It refuses any docker endpoint that is not a local unix socket, never touches an existing container, and removes only the container IDs it created.
2. PROVIDED (you own the containers and certificates): a TLS-required Neo4j that is EMPTY, reachable as `localhost`, and public CA files:
       ZOOP_GRAPH_TLS_SMOKE_URI=bolt+s://localhost:<port>       ZOOP_GRAPH_TLS_SMOKE_CA=<public CA A pem, signs the server leaf (SAN DNS:localhost only)>
       ZOOP_GRAPH_TLS_SMOKE_WRONG_CA=<public pem of an unrelated CA B>     ZOOP_GRAPH_AUTH=basic ZOOP_GRAPH_USER=neo4j ZOOP_GRAPH_PASSWORD=<>= 16 chars>
       ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_tls_smoke.py [--stage cases|smoke|regression]
   `cases` needs an empty server and leaves it initialized; `smoke` and `regression` each need ANOTHER fresh empty server (they delegate to
   graph_projection_smoke.py / graph_projection_regression.py with SSL_CERT_FILE=<CA A> and the matching *_URI).

Stages: `cases` (the preflight/init matrix below), `smoke` (the full freeze/project/recover/read smoke over TLS) and `regression` (R1-R4 over TLS).

`cases`: server preconditions proven by an independent Python `ssl` handshake (CA A + `localhost` ok; CA B refused; `127.0.0.1` refused because the leaf has no
IP SAN; a plain Bolt preamble is not answered as Bolt); P1 preflight with the right CA, name and credentials -> eligible-empty-target with no ledger, no state
and Neo4j unchanged; N1-N8 each change exactly ONE variable against a server just proven healthy (no CA variable, wrong CA, name mismatch, plain Bolt to a
TLS-REQUIRED server, one wrong password, auth=none over TLS, unsafe URIs, foreign/symlinked/ownership state) and must be refused with the stable code and,
where it is decided before any connection, with no socket opened at all (each such child runs under a socket audit hook); I1 init binds exactly 10
constraints and 13 indexes, I2 the repeated init is identical and writes nothing, I3 a preflight afterwards refuses (it never adopts) and changes nothing.
Every command output is one JSON line with an empty stderr and no password, credential field, target host or path in it.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent
sys.path[:0] = [str(PIPELINE)]

from scripts.graph_projection_smoke import Raw, assert_no_credential_leak, guard_source  # noqa: E402
from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import source_checkout  # noqa: E402

SCHEMA = "zoop-graph-projection-1"
DATABASE = "neo4j"
INIT = {"schemaVersion": SCHEMA, "storeId": "zoop-dev-graph", "database": DATABASE}
# The declared Infra image: official Community 5.26.32, by the registry digest Main pulled. Never pulled by this script.
IMAGE_TAG = "neo4j:5.26.32"
IMAGE_DIGEST = "sha256:f1e52d4dc6da122468c4a3c1050a4f5e117f6d3268625237c34d49166f0d6082"
IMAGE = f"neo4j@{IMAGE_DIGEST}"
LABEL = "zoop.graph-tls-smoke"
CLAIM = "local Community 5.26 TLS + basic-auth proof of preflight/init only: no AWS, Fargate, RBAC, DNS, SSM or GraphDbStatus claim"
STAGES = ("cases", "smoke", "regression")
UNSAFE_URIS = ("bolt+ssc://localhost:{p}", "neo4j+s://localhost:{p}", "bolt+s://operator:secret@localhost:{p}", "bolt+s://localhost:{p}/neo4j",
               "bolt+s://localhost", "bolt://example.com:7687", "http://localhost:{p}")


class Failed(AssertionError):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise Failed(message)


# ---------------------------------------------------------------- the target and its public trust files ------------------------------

@dataclass
class Target:
    port: int
    ca: Path            # PUBLIC pem of CA A: signs the server leaf; handed to the CLI as SSL_CERT_FILE
    wrong_ca: Path      # PUBLIC pem of the unrelated CA B

    @property
    def uri(self) -> str:
        return f"bolt+s://localhost:{self.port}"

    @property
    def plain_uri(self) -> str:
        return f"bolt://127.0.0.1:{self.port}"

    @property
    def mismatch_uri(self) -> str:
        return f"bolt+s://127.0.0.1:{self.port}"


def public_pem(path: str | None, what: str) -> Path:
    """A regular, non-symlink file holding certificates only. A file with any private key in it is refused, so a key can never be handed over by mistake."""
    check(path, f"{what} is required")
    p = Path(path)
    check(p.is_absolute() and p.is_file() and not p.is_symlink(), f"{what} must be an absolute path to a regular file")
    data = p.read_text()
    check(data.lstrip().startswith("-----BEGIN CERTIFICATE-----") and "PRIVATE KEY" not in data, f"{what} must contain public certificates only")
    return p


def require_credentials() -> None:
    check(os.environ.get("ZOOP_GRAPH_AUTH") == "basic" and os.environ.get("ZOOP_GRAPH_USER") and len(os.environ.get("ZOOP_GRAPH_PASSWORD", "")) >= 16,
          "ZOOP_GRAPH_AUTH=basic, ZOOP_GRAPH_USER and a ZOOP_GRAPH_PASSWORD of at least 16 characters are required (from the environment, never argv)")


def provided_target() -> Target:
    uri = os.environ.get("ZOOP_GRAPH_TLS_SMOKE_URI", "")
    match = re.fullmatch(r"bolt\+s://localhost:([0-9]{1,5})", uri)
    check(match and 1 <= int(match.group(1)) <= 65535, "ZOOP_GRAPH_TLS_SMOKE_URI must be exactly bolt+s://localhost:<port> (loopback only; the leaf's SAN is DNS:localhost)")
    return Target(int(match.group(1)), public_pem(os.environ.get("ZOOP_GRAPH_TLS_SMOKE_CA"), "ZOOP_GRAPH_TLS_SMOKE_CA"),
                  public_pem(os.environ.get("ZOOP_GRAPH_TLS_SMOKE_WRONG_CA"), "ZOOP_GRAPH_TLS_SMOKE_WRONG_CA"))


# ---------------------------------------------------------------- independent server preconditions ------------------------------------

def handshake(port: int, cafile: Path, server_name: str, host: str = "127.0.0.1") -> dict:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname, context.verify_mode = True, ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=str(cafile))
    with socket.create_connection((host, port), timeout=5) as raw, context.wrap_socket(raw, server_hostname=server_name) as tls:
        return tls.getpeercert()


def refused(call) -> bool:
    try:
        call()
    except (ssl.SSLError, ssl.CertificateError):
        return True
    return False


def server_preconditions(t: Target, checks: list[str]) -> None:
    leaf = handshake(t.port, t.ca, "localhost")
    check(leaf.get("subjectAltName") == (("DNS", "localhost"),), f"the leaf must carry exactly SAN DNS:localhost, got {leaf.get('subjectAltName')}")
    check(refused(lambda: handshake(t.port, t.wrong_ca, "localhost")), "an unrelated CA must NOT verify the server")
    check(refused(lambda: handshake(t.port, t.ca, "127.0.0.1")), "the leaf has no IP SAN: connecting by 127.0.0.1 must fail name verification")
    with socket.create_connection(("127.0.0.1", t.port), timeout=5) as plain:
        plain.settimeout(5)
        plain.sendall(b"\x60\x60\xb0\x17" + b"\x00\x00\x05\x04" + b"\x00" * 12)   # Bolt preamble + a version proposal, in the clear
        try:
            answer = plain.recv(4)
        except (ConnectionError, TimeoutError, OSError):
            answer = b""
    check(not (len(answer) == 4 and answer[:2] == b"\x00\x00" and answer != b"\x00\x00\x00\x00"), "a TLS-REQUIRED server must not answer a plain Bolt handshake")
    checks.append("server preconditions (independent ssl handshake): CA A + localhost verified, SAN exactly DNS:localhost, CA B refused, 127.0.0.1 refused, plain Bolt not served")


# ---------------------------------------------------------------- the CLI under test ----------------------------------------------

def clean_env(ca: Path | None, *, auth: str | None = "basic", password: str | None = None, ownership: bool = True) -> dict[str, str]:
    """Exactly what an operator's command gets: PATH/HOME/LANG, the ZOOP_GRAPH_* trio and, only when given, SSL_CERT_FILE. No SSL_CERT_DIR, no proxy, no
    other secret is inherited."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if ownership:
        env.update(ownership_env())
    if auth:
        env["ZOOP_GRAPH_AUTH"] = auth
        if auth == "basic":
            env["ZOOP_GRAPH_USER"] = os.environ["ZOOP_GRAPH_USER"]
            env["ZOOP_GRAPH_PASSWORD"] = password if password is not None else os.environ["ZOOP_GRAPH_PASSWORD"]
    if ca:
        env["SSL_CERT_FILE"] = str(ca)
    return env


class Operator:
    def __init__(self, t: Target, work: Path):
        self.t, self.work, self.outputs = t, work, []

    def run(self, command: str, state: Path, *, uri: str | None, expected: int, ca: Path | None | str = "ca", auth: str | None = "basic", password: str | None = None,
            net: bool = True, ownership: bool = True, request: dict | None = None) -> dict:
        env = clean_env(self.t.ca if ca == "ca" else ca, auth=auth, password=password, ownership=ownership)
        program = guard_source(self.t.port if net else -1) + "runpy.run_module('zoop_ai_pipeline.graph_projection_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, command, "--state-dir", str(state)] + (["--graph-uri", uri] if uri is not None else [])
        child = subprocess.run(argv, input=json_bytes(request or INIT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=180)
        text = child.stdout.decode()
        self.outputs.append(text)
        check(child.returncode == expected, f"{command} {uri}: exit {child.returncode} (wanted {expected}): {text.strip()} {child.stderr.decode()[-400:]}")
        check(not child.stderr, f"{command}: stderr must be empty, got {child.stderr.decode()[-400:]}")
        check(text.endswith("\n") and text.count("\n") == 1, f"{command}: stdout must be exactly one JSON line")
        assert_no_credential_leak(text, DATABASE)
        for extra in (password, str(self.work), "localhost", f":{self.t.port}"):
            check(not extra or extra not in text, f"{command}: output leaks {extra!r}" if extra == password else f"{command}: output leaks a target or path")
        return json.loads(text)

    def refused(self, command: str, state: Path, code: str, **kw) -> dict:
        out = self.run(command, state, expected=2, **kw)
        check(out.get("schemaVersion") == SCHEMA and out.get("error", {}).get("code") == code, f"{command}: wanted {code}, got {out}")
        return out


def ledger_rows(state: Path) -> str:
    db = sqlite3.connect((state / "graph.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        return json.dumps([db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall() for table in ("meta", "versions", "attempts")])
    finally:
        db.close()


def tree_state(path: Path) -> dict:
    return {str(p): (stat.S_IMODE(p.lstat().st_mode), p.lstat().st_size, p.lstat().st_mtime_ns) for p in [path, *sorted(path.rglob("*"))]} if path.exists() else {}


def neo4j_state(raw: Raw) -> dict:
    return {"nodes": raw.count("MATCH (n) RETURN count(n) AS c"), "relationships": raw.count("MATCH ()-[r]->() RETURN count(r) AS c"),
            "constraints": sorted(r["name"] for r in raw.q("SHOW CONSTRAINTS YIELD name")),
            "indexes": sorted(r["name"] for r in raw.q("SHOW INDEXES YIELD name, type") if r["type"] != "LOOKUP")}


# ---------------------------------------------------------------- stage: cases ------------------------------------------------------

def stage_cases(t: Target) -> dict:
    require_credentials()
    checks: list[str] = []
    observed: dict = {}
    os.environ["SSL_CERT_FILE"] = str(t.ca)   # this process's own oracle driver; every CLI child gets its own explicit environment
    work = Path(tempfile.mkdtemp(prefix="zoop-graph-tls-ws-")).resolve()
    op = Operator(t, work)
    raw = Raw(t.uri, DATABASE)
    try:
        check(neo4j_state(raw) == {"nodes": 0, "relationships": 0, "constraints": [], "indexes": []}, "the server must be EMPTY and fresh: this smoke never wipes a database")
        pristine = neo4j_state(raw)
        server_preconditions(t, checks)
        state = work / "graph"

        def eligible(p: Path = state) -> dict:
            out = op.run("preflight", p, uri=t.uri, expected=0)
            card = out["preflight"]
            check(set(out) == {"schemaVersion", "preflight", "usage"} and out["usage"] == {"providerCalls": 0, "modelCalls": 0}, f"unexpected preflight shape {out}")
            check(set(card) == {"result", "ddlPermission", "tls", "ledger", "server", "database", "dbId", "counts", "schemaObjects"}, f"unexpected preflight fields {card}")
            check(card["result"] == "eligible-empty-target" and card["ddlPermission"] == "unverified" and card["tls"] == "verified" and card["ledger"] == "absent", card)
            check(card["server"] == {"agent": "Neo4j/5.26.32", "edition": "community"} and card["database"] == DATABASE and card["dbId"], card)
            check(card["counts"] == {"nodes": 0, "relationships": 0} and card["schemaObjects"] == {"constraints": 0, "indexes": 0}, card)
            return out

        # P1: the right CA, the right name, the right credentials: a candidate, with no ledger and Neo4j unchanged.
        first = eligible()
        check(not state.exists() and neo4j_state(raw) == pristine, "P1: preflight created state or changed Neo4j")
        observed["dbId"] = first["preflight"]["dbId"]
        empty = work / "empty-755"
        empty.mkdir(mode=0o755)
        empty.chmod(0o755)
        before = tree_state(empty)
        eligible(empty)
        check(tree_state(empty) == before and list(empty.iterdir()) == [], "P1b: preflight touched an existing empty directory")
        empty.rmdir()
        checks.append("P1 preflight over TLS (CA A, localhost, basic auth): eligible-empty-target, tls verified, community 5.26.32, ddlPermission unverified; no ledger/state, Neo4j unchanged")

        # N-cases: one variable at a time, each against a server just proven healthy.
        def single(name: str, code: str, **kw) -> dict:
            eligible()
            out = op.refused("preflight", state, code, uri=kw.pop("uri", t.uri), **kw)
            check(not state.exists() and neo4j_state(raw) == pristine, f"{name}: state or Neo4j changed")
            observed[name] = out["error"]
            return out

        single("N1 no SSL_CERT_FILE", "graph_unavailable", ca=None)
        single("N2 wrong CA", "graph_unavailable", ca=t.wrong_ca)
        single("N3 name mismatch", "graph_unavailable", uri=t.mismatch_uri)
        single("N4 plain Bolt to TLS-REQUIRED server", "graph_unavailable", uri=t.plain_uri, auth="basic")
        single("N5 one wrong password", "graph_auth_failed", password=secrets.token_urlsafe(18))
        single("N6 auth none over TLS", "graph_auth_unconfigured", auth="none", net=False)
        for index, template in enumerate(UNSAFE_URIS):
            single(f"N7.{index} unsafe URI", "graph_uri_invalid", uri=template.format(p=t.port), net=False)
        checks.append("N1-N7: no CA variable, wrong CA, hostname mismatch, plain Bolt to a TLS-REQUIRED server, one wrong password: refused (graph_unavailable / graph_unavailable / "
                      "graph_unavailable / graph_unavailable / graph_auth_failed); auth=none over TLS and 7 unsafe URIs refused with NO socket (audit hook); each against a healthy server")

        # N8: placement and ownership, decided before any connection.
        foreign = work / "foreign"
        foreign.mkdir()
        (foreign / "notes.txt").write_text("not ours")
        snapshot = tree_state(foreign)
        op.refused("preflight", foreign, "state_namespace_conflict", uri=t.uri, net=False)
        check(tree_state(foreign) == snapshot, "N8: a foreign directory was touched")
        real = work / "real"
        real.mkdir()
        (work / "link").symlink_to(real)
        op.refused("preflight", work / "link" / "state", "state_namespace_invalid", uri=t.uri, net=False)
        check(list(real.iterdir()) == [], "N8: a symlinked ancestor was followed")
        if source_checkout():
            checks.append("N8 foreign directory and symlinked ancestor refused untouched with no socket (state_ownership_unconfigured is only observable from an INSTALLED wheel: "
                          "this run is a source checkout, so that sub-case was not exercised)")
        else:
            op.refused("preflight", work / "owned-check", "state_ownership_unconfigured", uri=t.uri, net=False, ownership=False)
            checks.append("N8 foreign directory, symlinked ancestor and missing ownership variables (installed wheel) refused untouched with no socket")
        check(neo4j_state(raw) == pristine, "N8: Neo4j changed")

        # I1-I3: init binds, repeats unchanged, and a later preflight refuses without adopting anything.
        bound = op.run("init", state, uri=t.uri, expected=0)
        store = bound["store"]
        check(store["state"] == "bound" and store["storeId"] == INIT["storeId"] and store["database"] == DATABASE and store["dbId"] == observed["dbId"], bound)
        check(store["schemaObjects"] == {"constraints": 10, "indexes": 13} and store["server"] == {"agent": "Neo4j/5.26.32", "edition": "community"}, bound)
        after = neo4j_state(raw)
        check(after["nodes"] == 1 and after["relationships"] == 0 and len(after["constraints"]) == 10 and len(after["indexes"]) == 13, f"I1: unexpected Neo4j state {after}")
        check(sorted(p.name for p in state.iterdir()) == ["graph.lock", "graph.sqlite3"] and stat.S_IMODE(state.stat().st_mode) == 0o700
              and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in state.iterdir()), "I1: ledger layout or modes")
        rows = ledger_rows(state)
        again = op.run("init", state, uri=t.uri, expected=0)
        check(again == bound and ledger_rows(state) == rows and neo4j_state(raw) == after, "I2: the repeated init changed something")
        op.refused("preflight", state, "graph_store_already_bound", uri=t.uri, net=False)
        fresh_state = work / "second-ledger"
        op.refused("preflight", fresh_state, "graph_store_not_empty", uri=t.uri)
        check(not fresh_state.exists() and neo4j_state(raw) == after and ledger_rows(state) == rows, "I3: a refused preflight created state or changed something")
        checks.append("I1 init over TLS: bound, 10 constraints + 13 indexes, one ZgStore, ledger 0700/0600; I2 identical repeat, ledger rows and Neo4j unchanged; "
                      "I3 preflight afterwards refuses (graph_store_already_bound for the ledger, graph_store_not_empty for the database) and changes nothing")
        everything = "\n".join(op.outputs)
        check(os.environ["ZOOP_GRAPH_PASSWORD"] not in everything, "a password was echoed")
        checks.append(f"{len(op.outputs)} command outputs: each one JSON line, empty stderr, no password, no credential field, no target host or path; user name only as its legitimate constants")
        return {"status": "passed", "checks": checks, "observed": observed}
    finally:
        raw.close()
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- stages: the existing smoke and regression over TLS ----------------

def delegate(script: str, uri_var: str, t: Target) -> dict:
    require_credentials()
    env = clean_env(t.ca)
    env[uri_var] = t.uri
    child = subprocess.run([sys.executable, str(HERE / script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=3000)
    out, err = child.stdout.decode(), child.stderr.decode()
    check(os.environ["ZOOP_GRAPH_PASSWORD"] not in out + err, f"{script}: the password appeared in its output")
    check(child.returncode == 0, f"{script} exited {child.returncode}:\n{out[-3000:]}\n{err[-2000:]}")
    return {"status": "passed", "script": script, "stdoutTail": out[-600:]}


def run_stage(stage: str, t: Target) -> dict:
    if stage == "cases":
        return stage_cases(t)
    if stage == "smoke":
        return delegate("graph_projection_smoke.py", "ZOOP_GRAPH_SMOKE_URI", t)
    return delegate("graph_projection_regression.py", "ZOOP_GRAPH_REGRESSION_URI", t)


# ---------------------------------------------------------------- managed mode: own PKI and own containers --------------------------

def openssl(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)


def make_ca(directory: Path, name: str) -> tuple[Path, Path]:
    (directory / f"{name}.cnf").write_text(f"[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=zoop-graph-tls-smoke {name}\n"
                                           "[v3]\nbasicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n")
    openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", f"{name}.key", cwd=directory)
    openssl("req", "-x509", "-new", "-sha256", "-days", "2", "-key", f"{name}.key", "-config", f"{name}.cnf", "-out", f"{name}.pem", cwd=directory)
    return directory / f"{name}.pem", directory / f"{name}.key"


def make_pki(root: Path) -> tuple[Path, Path, Path]:
    """CA A, an unrelated CA B and a leaf signed by A with SAN DNS:localhost ONLY (no IP SAN), serverAuth, PKCS#8 key. CA private keys stay under
    `pki/` (never mounted); only the leaf key and certificate go into the server's read-only `/ssl/bolt`, whose mandatory trusted/ and revoked/ are empty."""
    pki = root / "pki"
    pki.mkdir(mode=0o700)
    ca_a, key_a = make_ca(pki, "ca-a")
    ca_b, _ = make_ca(pki, "ca-b")
    (pki / "leaf.cnf").write_text("[v3]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
                                  "subjectAltName=DNS:localhost\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n")
    (pki / "req.cnf").write_text("[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=localhost\n")
    openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", "leaf.key", cwd=pki)
    openssl("req", "-new", "-key", "leaf.key", "-config", "req.cnf", "-out", "leaf.csr", cwd=pki)
    openssl("x509", "-req", "-sha256", "-days", "2", "-in", "leaf.csr", "-CA", ca_a.name, "-CAkey", key_a.name, "-CAcreateserial", "-extfile", "leaf.cnf",
            "-extensions", "v3", "-out", "leaf.pem", cwd=pki)
    ssl_dir = root / "ssl"
    bolt = ssl_dir / "bolt"
    for directory in (ssl_dir, bolt, bolt / "trusted", bolt / "revoked"):
        directory.mkdir(mode=0o755, exist_ok=True)
        directory.chmod(0o755)
    shutil.copy(pki / "leaf.pem", bolt / "public.crt")
    shutil.copy(pki / "leaf.key", bolt / "private.key")
    (bolt / "private.key").chmod(0o644)   # the server user inside the container must read it; the whole tree is a 0700 throwaway root and is shredded on exit
    return ssl_dir, ca_a, ca_b


class Docker:
    def __init__(self, run: str):
        self.run, self.owned = run, []
        check(shutil.which("docker"), "docker is not installed")
        host = os.environ.get("DOCKER_HOST", "")
        check(not host or host.startswith("unix://"), "DOCKER_HOST must be a local unix socket")
        context = self.cmd("context", "show").strip()
        endpoint = self.cmd("context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}").strip()
        check(endpoint.startswith("unix://"), "refusing a docker context that is not a local unix socket")
        found = self.cmd("image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}", check_rc=False)
        check(IMAGE_DIGEST in found, f"{IMAGE_TAG} @ {IMAGE_DIGEST} is not present locally (this script never pulls; pull it explicitly first)")

    @staticmethod
    def cmd(*args: str, env: dict | None = None, check_rc: bool = True) -> str:
        child = subprocess.run(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env or os.environ.copy(), timeout=300)
        if check_rc and child.returncode:
            raise Failed(f"docker {args[0]} failed: {child.stderr.strip()[:400]}")
        return child.stdout if child.returncode == 0 else ""

    def start(self, role: str, ssl_dir: Path) -> tuple[str, int]:
        name = f"zoop-graph-tls-{self.run}-{role}"
        check(not self.cmd("ps", "-a", "-q", "--filter", f"name=^/{name}$").strip(), f"a container named {name} already exists: refusing to touch it")
        env = os.environ.copy()
        env["NEO4J_AUTH"] = f"{os.environ['ZOOP_GRAPH_USER']}/{os.environ['ZOOP_GRAPH_PASSWORD']}"   # passed by NAME below: never on any argv
        settings = {"NEO4J_server_bolt_tls__level": "REQUIRED", "NEO4J_dbms_ssl_policy_bolt_enabled": "true", "NEO4J_dbms_ssl_policy_bolt_base__directory": "/ssl/bolt",
                    "NEO4J_dbms_ssl_policy_bolt_client__auth": "NONE", "NEO4J_dbms_usage__report_enabled": "false", "NEO4J_server_memory_heap_initial__size": "384m",
                    "NEO4J_server_memory_heap_max__size": "512m", "NEO4J_server_memory_pagecache_size": "128m"}
        args = ["run", "-d", "--pull", "never", "--name", name, "--label", f"{LABEL}={self.run}", "--label", f"{LABEL}-role={role}", "--memory", "1536m",
                "-p", "127.0.0.1::7687", "--tmpfs", "/data", "--tmpfs", "/logs", "-v", f"{ssl_dir}:/ssl:ro", "-e", "NEO4J_AUTH"]
        for key, value in settings.items():
            args += ["-e", f"{key}={value}"]
        container = self.cmd(*args, IMAGE, env=env).strip()
        self.owned.append(container)
        label = self.cmd("inspect", container, "--format", f'{{{{index .Config.Labels "{LABEL}"}}}}').strip()
        check(label == self.run, "the started container does not carry this run's label")
        mapping = self.cmd("port", container, "7687/tcp").strip().splitlines()[0]
        host, _, port = mapping.rpartition(":")
        check(host == "127.0.0.1" and port.isdigit(), f"Bolt must be published on 127.0.0.1 only, got {mapping!r}")
        return container, int(port)

    def logs(self, container: str) -> str:
        text = self.cmd("logs", "--tail", "40", container, check_rc=False)
        return "\n".join(line for line in text.splitlines() if os.environ["ZOOP_GRAPH_PASSWORD"] not in line)

    def remove(self, container: str) -> None:
        label = self.cmd("inspect", container, "--format", f'{{{{index .Config.Labels "{LABEL}"}}}}', check_rc=False).strip()
        if label == self.run:   # exactly a container THIS run created, never anything else
            self.cmd("rm", "-f", "-v", container, check_rc=False)
        if container in self.owned:
            self.owned.remove(container)

    def remove_all(self) -> None:
        for container in list(self.owned):
            self.remove(container)


def cleanup_run(run: str) -> dict:
    """Targeted recovery of an interrupted managed run: only containers that carry BOTH this run's label and its exact name prefix."""
    check(re.fullmatch(r"[0-9a-f]{8}", run), "RUN_ID must be the 8 hex digits printed by the managed run")
    docker = Docker(run)
    removed = []
    for line in docker.cmd("ps", "-a", "--filter", f"label={LABEL}={run}", "--format", "{{.ID}} {{.Names}}").splitlines():
        container, _, name = line.partition(" ")
        if name.startswith(f"zoop-graph-tls-{run}-"):
            docker.owned.append(container)
            docker.remove(container)
            removed.append(name)
    return {"status": "cleaned", "runId": run, "removedContainers": removed}


def shred(root: Path) -> None:
    for key in root.rglob("*.key"):
        with contextlib.suppress(OSError):
            key.write_bytes(b"\0" * max(key.stat().st_size, 1))
    shutil.rmtree(root, ignore_errors=True)


def wait_ready(docker: Docker, container: str, t: Target) -> None:
    os.environ["SSL_CERT_FILE"] = str(t.ca)   # the readiness probe's own driver trusts CA A exactly as the CLI children are told to
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        state = docker.cmd("inspect", container, "--format", "{{.State.Status}}", check_rc=False).strip()
        if state != "running":
            raise Failed(f"the Neo4j container is {state or 'gone'}:\n{docker.logs(container)}")
        try:
            handshake(t.port, t.ca, "localhost")
            probe = Raw(t.uri, DATABASE)
            try:
                probe.q("RETURN 1 AS ok")
                return
            finally:
                probe.close()
        except Exception:  # noqa: BLE001 - not ready yet; the deadline decides
            time.sleep(2)
    raise Failed(f"Neo4j did not become ready within 240s:\n{docker.logs(container)}")


def managed(stages: list[str]) -> dict:
    run = uuid.uuid4().hex[:8]
    print(f"run id: {run} (interrupted? --cleanup {run})", file=sys.stderr)
    os.environ.setdefault("ZOOP_GRAPH_AUTH", "basic")
    os.environ.setdefault("ZOOP_GRAPH_USER", "neo4j")
    os.environ.setdefault("ZOOP_GRAPH_PASSWORD", secrets.token_urlsafe(24))
    check(os.environ["ZOOP_GRAPH_AUTH"] == "basic", "managed mode is basic-auth only")
    check(os.environ["ZOOP_GRAPH_USER"] == "neo4j", "a Community server's only user is neo4j")
    require_credentials()
    docker = Docker(run)
    root = Path(tempfile.mkdtemp(prefix="zoop-graph-tls-")).resolve()
    root.chmod(0o700)
    results: dict = {}
    try:
        ssl_dir, ca_a, ca_b = make_pki(root)
        for stage in stages:   # one FRESH empty server per stage: each stage needs, and may leave behind, its own state
            container, port = docker.start(stage, ssl_dir)
            try:
                target = Target(port, ca_a, ca_b)
                wait_ready(docker, container, target)
                results[stage] = run_stage(stage, target)
            finally:
                docker.remove(container)
        return {"status": "passed", "runId": run, "image": f"{IMAGE_TAG}@{IMAGE_DIGEST}", "stages": results, "claim": CLAIM,
                "cleanup": {"containersRemoved": True, "pkiShredded": True}}
    finally:
        docker.remove_all()
        shred(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manage-containers", action="store_true", help="create and remove this run's own private PKI and containers (explicit opt-in)")
    parser.add_argument("--stages", default=",".join(STAGES), help="managed mode: comma separated subset of " + ",".join(STAGES))
    parser.add_argument("--stage", choices=STAGES, default="cases", help="provided mode: the stage to run against ZOOP_GRAPH_TLS_SMOKE_URI")
    parser.add_argument("--cleanup", metavar="RUN_ID", help="remove the containers of an interrupted managed run, by exact label and name")
    args = parser.parse_args()
    if args.cleanup:
        print(json.dumps(cleanup_run(args.cleanup), indent=2))
        return 0
    if args.manage_containers:
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]
        check(stages and all(s in STAGES for s in stages), f"--stages must be a subset of {STAGES}")
        result = managed(stages)
    else:
        result = {"status": "passed", "stage": args.stage, "image": "provided by the operator", "result": run_stage(args.stage, provided_target()), "claim": CLAIM}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
