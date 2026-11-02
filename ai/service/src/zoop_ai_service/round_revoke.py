"""Revoke one exact round read grant while the owning service is stopped."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat

from .config import ConfigError, _absolute
from .ledger import ProcessLock
from .plan_verify import InstallError, decode, read_file


def revoke(root, owner, handoff_id, manifest_digest, bundle_digest):
    lock = ProcessLock(root, create=False)
    try:
        marker = decode(read_file(root / "rounds" / "binding.json", 65536, owned=True))
        if marker["schemaVersion"] != "zoop-ai-round-state-1":
            raise ValueError("round binding")
        path = root / "rounds" / "rounds.sqlite3"
        info = path.lstat()
        if os.path.realpath(path) != str(path) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("round store")
        with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            entry = db.execute("SELECT manifest_digest,bundle_digest FROM grants WHERE owner=? AND handoff_id=?", (owner, handoff_id)).fetchone()
            if entry != (manifest_digest, bundle_digest):
                raise ValueError("grant binding")
            db.execute("UPDATE grants SET active=0 WHERE owner=? AND handoff_id=?", (owner, handoff_id))
        return {"schemaVersion": "zoop-ai-round-grant-revocation-1", "handoffId": handoff_id, "state": "revoked"}
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state-dir", "principal", "handoff-id", "manifest-digest", "bundle-digest"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        result = revoke(_absolute(args.state_dir, "state-dir"), args.principal, args.handoff_id, args.manifest_digest, args.bundle_digest)
    except (ConfigError, InstallError, OSError, ValueError, KeyError, sqlite3.Error):
        print('{"error":"round_grant_revocation_refused"}')
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
