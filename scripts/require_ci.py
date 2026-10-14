"""Require a successful CI push run for the exact artifact commit on main."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


REQUIRED_JOBS = {"public-config", "web", "app-web", "bff", "ai-worker", "ai-pipeline", "ai-service", "api", "required-ci"}


def select_run(payload: dict, sha: str, repository: str) -> dict:
    candidates = [run for run in payload.get("workflow_runs", [])
                  if run.get("head_sha") == sha and run.get("event") == "push"
                  and run.get("head_branch") == "main"
                  and run.get("path", "").split("@", 1)[0] == ".github/workflows/ci.yml"
                  and run.get("repository", {}).get("full_name") == repository]
    if not candidates:
        raise ValueError("No CI push run found for this exact main commit; run CI first.")
    # A previous successful attempt must not hide a newer failed/in-progress run.
    latest = max(candidates, key=lambda run: (run["id"], run.get("run_attempt", 1)))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("Latest CI push run for this commit has not completed successfully.")
    return latest


def require_jobs(jobs: list[dict]) -> None:
    observed = {job["name"]: job.get("conclusion") for job in jobs}
    if any(observed.get(name) != "success" for name in REQUIRED_JOBS):
        raise ValueError("CI job evidence missing or not successful: require public-config, web, app-web, bff, ai-worker, ai-pipeline, ai-service, api and required-ci.")


def get_json(path: str, token: str) -> dict:
    # Fixed GitHub origin and no redirects: never send authorization elsewhere.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    request = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "zoop-artifact-gate"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.URLError:
        raise ValueError("GitHub CI evidence read failed; check Actions: read permission and connectivity.") from None


def main() -> None:
    sha = os.environ.get("GITHUB_SHA", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not token:
        raise SystemExit("Require GitHub commit, repository and ephemeral Actions read token.")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Artifact workflow is restricted to main.")
    query = urllib.parse.urlencode({"head_sha": sha, "event": "push", "per_page": 100})
    payload = get_json(f"/repos/{repo}/actions/workflows/ci.yml/runs?{query}", token)
    try:
        run = select_run(payload, sha, repo)
        jobs = []
        for page in range(1, 11):
            result = get_json(f"/repos/{repo}/actions/runs/{run['id']}/attempts/{run.get('run_attempt', 1)}/jobs?per_page=100&page={page}", token)
            jobs.extend(result["jobs"])
            if len(jobs) >= result["total_count"]:
                break
        else:
            raise ValueError("Too many jobs to validate CI evidence safely.")
        require_jobs(jobs)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"ci-run-id={run['id']}\n")
    print(f"Exact-commit CI gate passed: run {run['id']} / {sha}")


if __name__ == "__main__":
    main()
