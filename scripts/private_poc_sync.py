"""CI-only credential scope: authenticate dependency fetch, then discard helper."""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


PROJECTS = ("prototype/bff", "ai/pipeline")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=PROJECTS, required=True)
    project = parser.parse_args(argv).project
    if not os.environ.get("POC_READ_TOKEN"):
        raise SystemExit("Missing POC_READ_TOKEN; private PoC installation cannot be skipped.")
    # No token in arguments, remote URLs, git config, logs, or persistent files.
    with tempfile.TemporaryDirectory(prefix="zoop-askpass-") as folder:
        helper = Path(folder) / "askpass.sh"
        helper.write_text('#!/bin/sh\ncase "$1" in\n  *Username*) printf "%s\\n" "x-access-token" ;;\n  *Password*) printf "%s\\n" "$POC_READ_TOKEN" ;;\n  *) exit 1 ;;\nesac\n', encoding="utf-8")
        helper.chmod(0o700)
        env = {**os.environ, "GIT_ASKPASS": str(helper), "GIT_TERMINAL_PROMPT": "0",
               "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": ""}
        # Authenticate the fixed dependency URL before uv, without echoing git stderr.
        preflight = subprocess.run(["git", "ls-remote", "https://github.com/Donbug/investmate-poc.git", "HEAD"],
                                   env=env, capture_output=True, timeout=30)
        if preflight.returncode or not preflight.stdout.strip():
            raise SystemExit("Private PoC read preflight failed. Check App installation/repository Contents: read permission.")
        return subprocess.run(["uv", "sync", "--project", project, "--frozen", "--group", "dev"], env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
