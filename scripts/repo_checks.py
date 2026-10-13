"""Root command discovery and offline repository checks. No application startup."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = (
    ("web", "prototype/web", "React/Vite prototype", "pnpm install --frozen-lockfile", "pnpm typecheck; pnpm test; pnpm build"),
    ("bff", "prototype/bff", "FastAPI prototype (private pinned PoC)", "uv sync --frozen --group dev", "uv run --no-sync python -m pytest; uv build"),
    ("ai-worker", "ai/worker", "S1 Python CLI JSON worker (public dependencies only, not an HTTP service)", "uv sync --frozen --group dev", ".venv/bin/python -m pytest tests; uv build"),
    ("ai-service", "ai/service", "S1 internal loopback HTTP transport to the installed zoop-ai CLI (public dependencies only; local preparation, not deployed)", "uv sync --frozen --group dev", ".venv/bin/python -m pytest tests; scripts/service_smoke.py; scripts/export_openapi.py --check; uv build"),
    ("ai-pipeline", "ai/pipeline", "S2-1/S2-2/S3 offline CLI processes and the S4 read-only dependents report (private pinned PoC)", "uv sync --frozen --group dev", ".venv/bin/python -m pytest tests; scripts/*_smoke.py; uv build"),
    ("api", "api", "Spring Boot 4.1.1 / Java 21 app backend foundation plus the internal S1 AI transport client (no auth or domain endpoints yet; needs JDK 21)", "JAVA_HOME=<JDK 21>; ./api/gradlew -p api --version", "make api-test api-build; make service-install api-ai-smoke"),
    ("contracts", "docs/api", "Language-neutral target contract", "existing PyYAML/OpenAPI validator", "make contracts-check docs-check"),
)
HELP = """Polyglot monorepo: app code stays in its current directories.
Discovery: make help | projects | available-checks
Public/offline: make config-check | contracts-check | docs-check | tokens-check | secret-check | tooling-test | public-check
Web only: make web-install | web-typecheck | web-test | web-build
BFF only: make bff-install | bff-test | bff-build
Worker only: make worker-install | worker-test | worker-schema-check | worker-build
Pipeline only (private PoC): make pipeline-install | pipeline-test | pipeline-smoke | pipeline-build
Service only (internal HTTP over the S1 CLI, public deps): make service-install | service-test | service-smoke | service-openapi-check | service-build
Service + installed pipeline (S2 extraction jobs and S3 relation jobs; needs both make pipeline-install and make service-install, fails without them): make service-pipeline-test | service-pipeline-smoke
API only (Spring Boot, JDK 21): make api-test | api-build | api-ai-smoke (api-ai-smoke also needs make service-install; real Java -> ai/service -> zoop-ai replay gate)
Worker fixture drift: make worker-contracts-check (installed BFF Python)
BFF/web type drift: make bff-types-check (installed BFF Python + web tool)
Artifacts: make package-artifacts COMMIT=<40-char-sha> ARTIFACT_DIR=<outside-repo>
Override tools with PYTHON=, UV=, PNPM=. No root JS workspace; the Java app lives in api/ with its own pinned Gradle wrapper.
Install targets fetch dependencies. Tests do not request live data/model access.
See CONTRIBUTING.md and docs/development/github-setup.md for prerequisites.
"""
TITLE = re.compile(r"(?:feat|fix|docs|chore|refactor|test|build|ci|perf|revert)\((?:web|api|ai|contracts|docs|infra)\)!?: \S(?:.*\S)?$")
ACTION_PINS = {
    "actions/checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
    "actions/create-github-app-token": "fee1f7d63c2ff003460e3d139729b119787bc349",
    "astral-sh/setup-uv": "d0cc045d04ccac9d8b7881df0226f9e82c39688e",
    "pnpm/action-setup": "b906affcce14559ad1aafd4ab0e942779e9f58b1",
}
# Curated from action.yml at the pinned revisions. actionlint is a separate CI gate.
ACTION_INPUTS = {
    "actions/checkout": {"ref", "persist-credentials"},
    "actions/setup-node": {"node-version"},
    "actions/setup-python": {"python-version"},
    "actions/upload-artifact": {"name", "path", "if-no-files-found", "retention-days"},
    "actions/create-github-app-token": {"app-id", "private-key", "owner", "repositories", "permission-contents"},
    "astral-sh/setup-uv": {"enable-cache"},
    "pnpm/action-setup": {"version", "run_install", "package_json_file"},
}


def run(command: list[str], cwd: Path = ROOT, **kwargs) -> None:
    subprocess.run(command, cwd=cwd, check=True, **kwargs)


def available() -> None:
    for executable in ("python3", "make", "bash", "node", "pnpm", "uv", "git", "go", "actionlint"):
        print(f"tool {executable}: {shutil.which(executable) or 'not installed'}")
    for module in ("yaml", "openpyxl", "openapi_spec_validator", "pytest"):
        print(f"python module {module}: {'available' if importlib.util.find_spec(module) else 'not in this interpreter'}")
    for name, folder, _, _, _ in PROJECTS:
        print(f"project {name}: {'present' if (ROOT / folder).is_dir() else 'missing'} ({folder})")
    print("Discovery only; missing tools are not a passed check. See bootstrap commands in the setup guide.")


def yaml_load(path: Path):
    import yaml
    # BaseLoader preserves GitHub's YAML 1.2 'on' key, unlike YAML 1.1 bool parsing.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def config() -> None:
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        document = yaml_load(path)
        if not document.get("name") or not document.get("on") or not document.get("jobs"):
            raise ValueError(f"workflow fields missing: {path.name}")
        if set(document["on"]) - {"push", "pull_request", "workflow_dispatch"}:
            raise ValueError("Unreviewed workflow trigger; never use pull_request_target or workflow_run checkout.")
        if document.get("permissions", {}).get("contents") != "read":
            raise ValueError("Require explicit contents: read permissions.")
        for job in document["jobs"].values():
            if "timeout-minutes" not in job:
                raise ValueError("Require a finite job timeout.")
            for step in job.get("steps", []):
                if "uses" in step:
                    action, revision = step["uses"].rsplit("@", 1)
                    if ACTION_PINS.get(action) != revision:
                        raise ValueError(f"Unverified action revision: {action}")
                    if set(step.get("with", {})) - ACTION_INPUTS[action]:
                        raise ValueError(f"Unverified action input: {action}")
                    if action == "actions/checkout" and step.get("with", {}).get("persist-credentials") != "false":
                        raise ValueError("Do not persist checkout credentials.")
                if "run" in step:
                    shell = re.sub(r"\$\{\{.*?\}\}", "expression", step["run"], flags=re.S)
                    subprocess.run(["bash", "-n"], input=shell, text=True, check=True)
    for path in sorted((ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml")):
        form = yaml_load(path)
        if path.name == "config.yml":
            if form.get("blank_issues_enabled") not in {"true", "false"}:
                raise ValueError("Invalid issue config.")
            continue
        if not form.get("name") or not form.get("description") or not isinstance(form.get("body"), list):
            raise ValueError(f"Invalid issue form: {path.name}")
        ids = set()
        for field in form["body"]:
            kind = field.get("type")
            if kind not in {"markdown", "input", "textarea", "dropdown", "checkboxes"}:
                raise ValueError("Invalid issue field type.")
            attrs = field.get("attributes", {})
            if kind == "markdown":
                if not attrs.get("value"):
                    raise ValueError("Markdown field requires value.")
            elif not field.get("id") or field["id"] in ids or not attrs.get("label"):
                raise ValueError("Issue fields need unique ids and labels.")
            ids.add(field.get("id"))
            if kind in {"dropdown", "checkboxes"} and not attrs.get("options"):
                raise ValueError("Choice fields need options.")
        if form.get("assignees"):
            raise ValueError("Do not assign unresolved owners automatically.")
    if not (ROOT / ".github/pull_request_template.md").is_file():
        raise ValueError("PR template missing.")
    print("Workflow YAML, curated pinned action inputs, issue-form fields and Bash syntax: passed.")


def contracts() -> None:
    import yaml
    from openapi_spec_validator import validate
    from jsonschema.validators import validator_for
    from jsonschema import FormatChecker
    contract = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text())
    validate(contract)
    internal = ROOT / "docs/api/internal-ai-openapi.json"
    internal_spec = json.loads(internal.read_text(encoding="utf-8"))
    # The S1 wire schemas are referenced from ai-contract.schema.json, so validation needs the document's own location.
    validate(internal_spec, base_uri=internal.as_uri())
    if yaml.safe_load((ROOT / "docs/api/internal-ai-openapi.yaml").read_text(encoding="utf-8")) != internal_spec:
        raise ValueError("Internal AI OpenAPI: YAML and JSON differ; regenerate with ai/service/scripts/export_openapi.py (make service-openapi-check).")
    paths = sorted((ROOT / "docs/api").rglob("*.json"))
    paths += [ROOT / "prototype/web/package.json", ROOT / "docs/design/tokens.json",
              ROOT / "docs/screen-plan/captures/slide-index.json"]
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        # A token document's $schema identifies its format; it is not a schema definition.
        if path.name.endswith(".schema.json"):
            validator = validator_for(value, default=None)
            if validator is None:
                raise ValueError(f"Unsupported JSON Schema dialect: {path.relative_to(ROOT)}")
            validator.check_schema(value)
    schema = json.loads((ROOT / "docs/api/ai-contract.schema.json").read_text(encoding="utf-8"))
    validator = validator_for(schema, default=None)
    if validator is None:
        raise ValueError("Unsupported AI contract schema dialect.")
    answers = {"document-summary": "SummaryAnswer", "document-sentiment": "SentimentAnswer",
               "semantic-verification": "VerificationAnswer", "briefing-outlook": "OutlookAnswer"}
    records_checked = 0
    for name in ("synthetic-document", "synthetic-outlook"):
        fixture = ROOT / "ai/worker/fixtures/contracts" / name
        records = [("Submit", value) for value in json.loads((fixture / "jobs.json").read_text())["jobs"]]
        records += [("SourceGrant", value) for value in json.loads((fixture / "grants.json").read_text())["grants"]]
        records += [(answers[value["stage"]], value["response"])
                    for value in json.loads((fixture / "replay.json").read_text())["responses"]]
        for definition, value in records:
            validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"},
                      format_checker=FormatChecker()).validate(value)
            records_checked += 1
    for path in (*ROOT.glob("prototype/*/pyproject.toml"), *ROOT.glob("ai/*/pyproject.toml")):
        tomllib.loads(path.read_text(encoding="utf-8"))
    print(f"OpenAPI (public target + internal AI transport, YAML equals JSON), {len(paths)} JSON documents/schemas, {records_checked} portable fixture records with format checks, app TOML: passed.")


def copy_file(root: Path, target: Path, relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or any(part.startswith(".env") for part in path.parts):
        raise ValueError("Unsafe generated-document input path.")
    source = root / path
    if source.is_symlink():
        raise ValueError("Do not copy linked document inputs.")
    destination = target / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def workbook_values(path: Path) -> dict:
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        return {sheet.title: list(sheet.values) for sheet in workbook}
    finally:
        workbook.close()


def docs() -> None:
    import yaml
    catalog = yaml.safe_load((ROOT / "docs/system/catalog.yaml").read_text())
    links = yaml.safe_load((ROOT / "docs/system/links.yaml").read_text())
    with tempfile.TemporaryDirectory(prefix="zoop-doc-check-") as folder:
        target = Path(folder)
        inputs = set(catalog["fingerprints"]) | {
            "docs/system/build.py", "docs/system/import_sources.py", "docs/system/catalog.yaml", "docs/system/links.yaml",
            links["apiContract"], links["authority"]["source"],
            "docs/system/out/bff-openapi.json", "docs/system/out/bff-observation.json",
        }
        for relative in sorted(inputs):
            copy_file(ROOT, target, relative)
        # The generator checks code-location existence only. Symlinks preserve that
        # fact without copying application data, .env, state, or private recordings.
        for item in links.get("implementationLocations", []):
            for location in item.get("codeLocations", []):
                relative = location.split(":", 1)[0]
                source = ROOT / relative
                destination = target / relative
                if source.exists() and not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.symlink_to(source)
        sources = catalog["sources"]
        run([sys.executable, "docs/system/import_sources.py", "--spec-dir", sources["specDir"],
             "--wbs-dir", sources["wbsDir"], "--requirements-dir", sources["requirementsDir"],
             "--screens", sources["screens"], "--gap", sources["gap"]], cwd=target)
        generated = yaml.safe_load((target / "docs/system/catalog.yaml").read_text())
        if generated != catalog:
            raise ValueError("Generated catalog drift: run documented import_sources.py command.")
        run([sys.executable, "docs/system/build.py"], cwd=target)
        checks = json.loads((target / "docs/system/out/checks.json").read_text())
        if checks["severityCounts"].get("error", 0) or checks["xlsxReadback"]["status"] != "passed":
            errors = [item for item in checks["findings"] if item["severity"] == "error"]
            labels = ", ".join(sorted({item["code"] for item in errors}))
            raise ValueError(f"Document hard errors: {len(errors)} ({labels}); XLSX readback: {checks['xlsxReadback']['status']}. Original outputs unchanged.")
        count = 0
        for base in ("docs/system/out", "docs/api/out"):
            for result in sorted((target / base).rglob("*")):
                if not result.is_file() or result.name in {"bff-openapi.json", "bff-observation.json"}:
                    continue
                relative = result.relative_to(target)
                original = ROOT / relative
                if not original.is_file():
                    raise ValueError(f"Generated document missing: {relative}")
                same = (workbook_values(result) == workbook_values(original) if result.suffix == ".xlsx"
                        else result.read_bytes() == original.read_bytes())
                if not same:
                    raise ValueError(f"Generated document drift: {relative}; regenerate, do not edit output.")
                count += 1
        owned_patterns = ("screen-*.md", "feature-*.md", "api-differences/*.json")
        for pattern in owned_patterns:
            originals = {path.relative_to(ROOT) for path in (ROOT / "docs/system/out").glob(pattern)}
            results = {path.relative_to(target) for path in (target / "docs/system/out").glob(pattern)}
            if originals != results:
                raise ValueError(f"Stale generated documents: {pattern}")
        print(f"Catalog/generated drift: {count} outputs passed; hard errors 0; XLSX cells equal. Original warnings/differences preserved.")


def tokens() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-token-check-") as folder:
        target = Path(folder)
        for name in ("docs/design/tokens.json", "prototype/web/scripts/build-tokens.mjs"):
            copy_file(ROOT, target, name)
        run(["node", "prototype/web/scripts/build-tokens.mjs"], cwd=target)
        for name in ("prototype/web/src/styles/tokens.css", "prototype/web/src/styles/tokens.generated.ts"):
            if (target / name).read_bytes() != (ROOT / name).read_bytes():
                raise ValueError(f"Generated token drift: {name}; run pnpm tokens.")
    print("Generated token drift: passed (worktree unchanged).")


def worker_schema() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-worker-schema-") as folder:
        target = Path(folder)
        script = "ai/worker/scripts/export_schema.py"
        copy_file(ROOT, target, script)
        env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
        run([sys.executable, script], cwd=target, env=env)
        relative = Path("docs/api/ai-contract.schema.json")
        outputs = {result.relative_to(target) for result in (target / "docs/api").rglob("*") if result.is_file()}
        if outputs != {relative}:
            raise ValueError("Worker schema exporter output set changed: " + ", ".join(sorted(map(str, outputs))))
        if (target / relative).read_bytes() != (ROOT / relative).read_bytes():
            raise ValueError(f"Generated worker contract drift: {relative}")
    print("Worker generated S1 schema: exact output and content drift passed (worktree unchanged).")


def worker_contracts() -> None:
    """BFF-owned fixture exporter; needs the installed BFF environment (zoop_bff, pinned PoC, test-only zoop_ai)."""
    with tempfile.TemporaryDirectory(prefix="zoop-worker-contracts-") as folder:
        target = Path(folder)
        script = "prototype/bff/scripts/export_contracts.py"
        copy_file(ROOT, target, script)
        env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
        run([sys.executable, script], cwd=target, env=env)
        fixtures = Path("ai/worker/fixtures/contracts")
        expected = {fixtures / group / filename
                    for group in ("synthetic-document", "synthetic-outlook")
                    for filename in ("jobs.json", "grants.json", "replay.json", "snapshot.json")}
        outputs = {result.relative_to(target) for result in (target / fixtures).rglob("*") if result.is_file()}
        outputs |= {result.relative_to(target) for result in (target / "docs").rglob("*") if result.is_file()}
        if outputs != expected:
            missing = ", ".join(str(path) for path in sorted(expected - outputs))
            unexpected = ", ".join(str(path) for path in sorted(outputs - expected))
            raise ValueError(f"Worker fixture exporter output set changed; missing: {missing or 'none'}; unexpected: {unexpected or 'none'}")
        for relative in sorted(expected):
            original = ROOT / relative
            if not original.is_file() or (target / relative).read_bytes() != original.read_bytes():
                raise ValueError(f"Generated worker contract drift: {relative}")
    print("Worker portable document/outlook fixtures: exact output set and content drift passed (worktree unchanged).")


def bff_types() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-bff-types-") as folder:
        target = Path(folder)
        schema = target / "openapi.json"
        generated = target / "schema.d.ts"
        env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
        env["PYTHONPATH"] = str(ROOT / "prototype/bff/src")
        export = (
            "import json,sys; from pathlib import Path; "
            "from zoop_bff.app import create_app; from zoop_bff.config import Settings; "
            "state=Path(sys.argv[1]); "
            "app=create_app(Settings(state_dir=state,snapshot_path=Path(sys.argv[2]),"
            "company_catalog=None,quote_provider='off',metrics_enabled=False,"
            "briefing_scheduler=False,poc_sandbox=state/'sandbox')); "
            "Path(sys.argv[3]).write_text(json.dumps(app.openapi()),encoding='utf-8')"
        )
        run([sys.executable, "-c", export, str(target / "state"),
             str(ROOT / "prototype/bff/fixtures/poc-synthetic-inspect.json"), str(schema)],
            cwd=target, env=env)
        run([os.environ.get("PNPM", "pnpm"), "--dir", "prototype/web", "exec",
             "openapi-typescript", str(schema), "-o", str(generated)], env=env)
        if generated.read_bytes() != (ROOT / "prototype/web/src/api/schema.d.ts").read_bytes():
            raise ValueError("BFF-generated web type drift: regenerate schema.d.ts from the fresh BFF; target OpenAPI is not its source.")
    print("BFF-generated web types: drift check passed (isolated synthetic state; no server/network data).")


SECRET_PATTERNS = (
    re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,})"),
    re.compile(rb"(?<![A-Za-z0-9_-])(?:sk-[A-Za-z0-9]{48}|sk-proj-[A-Za-z0-9_-]{32,}|sk-ant-api03-[A-Za-z0-9_-]{32,})(?![A-Za-z0-9_-])"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)


def secret_problem(relative: Path, data: bytes | None = None) -> str | None:
    if any(part == ".env" or part.startswith(".env.") and part != ".env.example" for part in relative.parts):
        return "tracked environment file (content not read)"
    if relative.suffix.lower() in {".key", ".pem", ".p12", ".db", ".sqlite", ".sqlite3"}:
        return "tracked credential/runtime database (content not read)"
    if data is not None and any(pattern.search(data) for pattern in SECRET_PATTERNS):
        return "credential signature (value redacted)"
    return None


def secrets() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    )
    names = sorted({Path(os.fsdecode(name)) for name in result.stdout.split(b"\0") if name})
    if not names:
        raise ValueError("No repository files: secret gate requires a nonempty Git checkout.")
    findings = []
    count = 0
    for relative in names:
        path = ROOT / relative
        problem = secret_problem(relative)
        if problem:
            findings.append((relative, problem))
            continue  # Never open actual .env/keys/databases, even to scan them.
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".pptx", ".xlsx", ".woff", ".woff2", ".zip", ".mp4"}:
            continue
        problem = secret_problem(relative, path.read_bytes())
        count += 1
        if problem:
            findings.append((relative, problem))
    if findings:
        for relative, problem in findings:
            print(f"{relative}: {problem}", file=sys.stderr)
        raise ValueError("Secret gate failed. Remove/rotate credentials; never paste values in issues or logs.")
    print(f"Repository-file secret signatures: {count} tracked and nonignored untracked files passed. Not a comprehensive security audit or history scan.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["help", "projects", "available", "config", "contracts", "worker-schema", "worker-contracts", "bff-types", "docs", "tokens", "secrets", "public", "pr-title"])
    command = parser.parse_args().command
    try:
        if command == "help":
            print(HELP, end="")
        elif command == "projects":
            for name, folder, description, install, checks in PROJECTS:
                print(f"{name}: {folder}\n  {description}\n  bootstrap (in app): {install}\n  commands: {checks}")
        elif command == "public":
            for check in (config, contracts, docs, tokens, secrets):
                check()
        elif command == "pr-title":
            if not TITLE.fullmatch(os.environ.get("PR_TITLE", "")):
                raise ValueError("PR title must use Conventional Commits: type(web|api|ai|contracts|docs|infra): summary")
            print("PR title convention: passed.")
        else:
            {"available": available, "config": config, "contracts": contracts, "worker-schema": worker_schema, "worker-contracts": worker_contracts, "bff-types": bff_types, "docs": docs, "tokens": tokens, "secrets": secrets}[command]()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
