"""Run packaging against throwaway synthetic input; never inspect a real .env."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import package_artifacts as artifacts
import private_poc_sync
import repo_checks
import require_ci

SHA = "a" * 40
REPO = "example/zoop"
CI_JOBS = {
    "public-config", "web", "app-web", "ai-worker", "ai-pipeline-tests", "ai-pipeline-smoke",
    "ai-pipeline", "ai-service", "ai-container", "api-container", "api-tests", "api-graph-smoke",
    "api", "required-ci",
}


def fixture(root: Path) -> None:
    for name in artifacts.REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic allowed input\n", encoding="utf-8")
    for folder in artifacts.TREES:
        (root / folder).mkdir(parents=True, exist_ok=True)
    for name in ("prototype/web/src/main.tsx", "prototype/bff/src/app.py", "ai/worker/src/worker.py", "ai/pipeline/src/pipeline.py"):
        (root / name).write_text("synthetic source\n", encoding="utf-8")
    (root / "prototype/web/dist/assets").mkdir()
    (root / "prototype/web/dist/assets/app.js").write_text("synthetic bundle\n")
    (root / "prototype/web/dist/assets/font.woff2").write_bytes(b"synthetic font")
    for name in (
        ".env", "prototype/bff/.env", "ai/worker/.env.local", "ai/pipeline/.env.local", "prototype/web/dist/.env",
        "prototype/web/dist/assets/.env.production", "prototype/bff/var/members.sqlite",
        "ai/worker/src/var/jobs.db", "ai/pipeline/var/ingestion.sqlite3", "prototype/web/src/private/recording.ts",
        "prototype/web/dist/logs/session.js", "prototype/web/dist/assets/server.key",
        "prototype/web/dist/assets/trace.log", "prototype/web/dist/assets/app.js.map",
        "prototype/web/src/node_modules/cache.ts", "prototype/bff/src/__pycache__/app.pyc",
        "prototype/web/src/recordings/private.ts", "docs/recordings/private.json",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic forbidden payload; not actual user data\n", encoding="utf-8")


class PackagingTests(unittest.TestCase):
    def test_real_cli_zip_and_checksum_exclude_secret_filenames(self):
        with tempfile.TemporaryDirectory(prefix="zoop-package-test-") as folder:
            root, output = Path(folder) / "fixture", Path(folder) / "artifact"
            fixture(root)
            result = subprocess.run([sys.executable, str(SCRIPTS / "package_artifacts.py"), "--root", str(root),
                                     "--output", str(output), "--commit", SHA, "--ci-run-id", "42"],
                                    capture_output=True, text=True, check=True)
            archive = Path(json.loads(result.stdout)["archive"])
            with zipfile.ZipFile(archive) as bundle:
                entries = bundle.namelist()
                self.assertEqual(bundle.testzip(), None)
                self.assertIn("prototype/web/dist/index.html", entries)
                self.assertIn("prototype/web/dist/assets/font.woff2", entries)
                self.assertIn("prototype/bff/src/app.py", entries)
                self.assertIn("ai/worker/src/worker.py", entries)
                self.assertIn("ai/pipeline/src/pipeline.py", entries)
                self.assertFalse(any(artifacts.denied(Path(name)) for name in entries))
                self.assertFalse(any(".env" in name or "node_modules" in name or "recordings" in name for name in entries))
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["commit"], SHA)
                self.assertEqual(manifest["ciRunId"], "42")
                self.assertEqual({item["path"] for item in manifest["files"]}, set(entries))
                for item in manifest["files"]:
                    self.assertEqual(hashlib.sha256(bundle.read(item["path"])).hexdigest(), item["sha256"])
            for line in (output / "SHA256SUMS").read_text().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            print(f"Synthetic artifact proof: {len(entries)} ZIP entries; .env/state/recordings/logs/cache/key exclusions passed; checksums matched.")

    def test_symlinks_are_not_read_or_packaged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "fixture"
            fixture(root)
            secret = Path(folder) / "synthetic-private.txt"
            secret.write_text("synthetic secret input")
            (root / "prototype/web/src/leak.ts").symlink_to(secret)
            (root / "prototype/web/src/linked").symlink_to(secret.parent, target_is_directory=True)
            selected = [path.as_posix() for path in artifacts.selected_files(root)]
            self.assertNotIn("prototype/web/src/leak.ts", selected)
            self.assertFalse(any("/linked/" in name for name in selected))

    def test_missing_build_fails_instead_of_empty_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "fixture"
            fixture(root)
            (root / "prototype/web/dist/index.html").unlink()
            with self.assertRaisesRegex(ValueError, "required allowlisted files missing"):
                artifacts.package(root, Path(folder) / "output", SHA)

    def test_output_inside_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "outside"):
                artifacts.package(Path(folder), Path(folder) / "artifact", SHA)

    def test_invalid_sha_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "40-character"):
            artifacts.package(Path("."), Path("/tmp"), "main")

    def test_zip_is_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "fixture"
            fixture(root)
            first = artifacts.package(root, Path(folder) / "first", SHA)
            second = artifacts.package(root, Path(folder) / "second", SHA)
            self.assertEqual(Path(first["archive"]).read_bytes(), Path(second["archive"]).read_bytes())


class CiGateTests(unittest.TestCase):
    def run_record(self, **changes):
        return {"id": 7, "run_attempt": 1, "head_sha": SHA, "head_branch": "main", "event": "push",
                "path": ".github/workflows/ci.yml", "repository": {"full_name": REPO},
                "status": "completed", "conclusion": "success", **changes}

    def test_same_commit_push_passes(self):
        run = self.run_record()
        self.assertEqual(require_ci.select_run({"workflow_runs": [run]}, SHA, REPO), run)
        require_ci.require_jobs([{"name": name, "conclusion": "success"} for name in CI_JOBS])

    def test_other_commit_pr_branch_repo_and_workflow_do_not_pass(self):
        for changes in ({"head_sha": "b" * 40}, {"event": "pull_request"}, {"head_branch": "feature"},
                        {"repository": {"full_name": "elsewhere/zoop"}}, {"path": ".github/workflows/other.yml"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "No CI push run"):
                require_ci.select_run({"workflow_runs": [self.run_record(**changes)]}, SHA, REPO)

    def test_latest_failure_cannot_hide_behind_previous_success(self):
        for status, conclusion in (("completed", "failure"), ("in_progress", None), ("completed", "skipped")):
            with self.subTest(status=status, conclusion=conclusion), self.assertRaisesRegex(ValueError, "Latest CI"):
                require_ci.select_run({"workflow_runs": [self.run_record(), self.run_record(id=8, status=status, conclusion=conclusion)]}, SHA, REPO)
            with self.subTest(attempt=2, status=status), self.assertRaisesRegex(ValueError, "Latest CI"):
                require_ci.select_run({"workflow_runs": [self.run_record(),
                    self.run_record(run_attempt=2, status=status, conclusion=conclusion)]}, SHA, REPO)

    def test_missing_or_unsuccessful_job_fails_for_every_required_job(self):
        self.assertEqual(require_ci.REQUIRED_JOBS, CI_JOBS)
        for required in sorted(CI_JOBS):
            for conclusion in ("skipped", "failure", "cancelled", None):
                with self.subTest(job=required, conclusion=conclusion), self.assertRaisesRegex(ValueError, "CI job evidence"):
                    require_ci.require_jobs([{"name": name, "conclusion": conclusion if name == required else "success"}
                                             for name in CI_JOBS])
            with self.subTest(missing=required), self.assertRaisesRegex(ValueError, "CI job evidence"):
                require_ci.require_jobs([{"name": name, "conclusion": "success"} for name in CI_JOBS - {required}])
        with self.assertRaisesRegex(ValueError, "CI job evidence"):
            require_ci.require_jobs([])

    def invoke_gate(self, responses, **environment):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "output"
            output.touch()
            env = {"GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA, "GITHUB_REPOSITORY": REPO,
                   "GH_TOKEN": "synthetic-fixture", "GITHUB_OUTPUT": str(output), **environment}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(require_ci.urllib.request, "build_opener") as opener, \
                    redirect_stdout(io.StringIO()):
                opener.return_value.open.side_effect = [io.StringIO(json.dumps(response)) for response in responses]
                error = None
                try:
                    require_ci.main()
                except SystemExit as failure:
                    error = str(failure)
                urls = [call.args[0].full_url for call in opener.return_value.open.call_args_list]
            return error, output.read_text(), urls

    def test_entrypoint_reads_exact_commit_and_attempt_paginated_jobs(self):
        jobs = [{"name": name, "conclusion": "success"} for name in sorted(CI_JOBS)]
        error, output, urls = self.invoke_gate([
            {"workflow_runs": [self.run_record(run_attempt=3)]},
            {"jobs": jobs[:7], "total_count": 14},
            {"jobs": jobs[7:], "total_count": 14},
        ])
        self.assertIsNone(error)
        self.assertEqual(output, "ci-run-id=7\nci-run-attempt=3\n")
        self.assertEqual(urls, [
            f"https://api.github.com/repos/{REPO}/actions/workflows/ci.yml/runs?head_sha={SHA}&event=push&per_page=100",
            f"https://api.github.com/repos/{REPO}/actions/runs/7/attempts/3/jobs?per_page=100&page=1",
            f"https://api.github.com/repos/{REPO}/actions/runs/7/attempts/3/jobs?per_page=100&page=2",
        ])

    def test_entrypoint_rejects_wrong_ref_before_reading_ci(self):
        for ref in ("refs/heads/feature", "refs/tags/main", "refs/pull/7/merge", ""):
            with self.subTest(ref=ref):
                error, output, urls = self.invoke_gate([], GITHUB_REF=ref)
                self.assertEqual(error, "Artifact workflow is restricted to main.")
                self.assertEqual(output, "")
                self.assertEqual(urls, [])

    def test_entrypoint_refuses_wrong_sha_missing_runs_and_failed_latest_attempt(self):
        for runs, message in (
            ([], "No CI push run"),
            ([self.run_record(head_sha="b" * 40)], "No CI push run"),
            ([self.run_record(), self.run_record(run_attempt=2, conclusion="failure")], "Latest CI"),
        ):
            with self.subTest(runs=runs):
                error, output, urls = self.invoke_gate([{"workflow_runs": runs}])
                self.assertIn(message, error)
                self.assertEqual(output, "")
                self.assertEqual(len(urls), 1)

    def test_entrypoint_refuses_missing_skipped_or_failed_ai_container(self):
        for conclusion in ("missing", "skipped", "failure"):
            jobs = [{"name": name, "conclusion": conclusion if name == "ai-container" else "success"}
                    for name in CI_JOBS if name != "ai-container" or conclusion != "missing"]
            with self.subTest(conclusion=conclusion):
                error, output, _ = self.invoke_gate([
                    {"workflow_runs": [self.run_record()]}, {"jobs": jobs, "total_count": len(jobs)},
                ])
                self.assertIn("CI job evidence", error)
                self.assertEqual(output, "")


class ImagePublicationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {
            kind: repo_checks.yaml_load(SCRIPTS.parent / f".github/workflows/deploy-{kind}-dev.yml")
            for kind in ("api", "ai")
        }

    def run_shell(self, script, env):
        return subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                              env={"PATH": os.defpath, **env}, capture_output=True, text=True)

    def test_required_ci_executes_every_prerequisite_result(self):
        workflow = repo_checks.yaml_load(SCRIPTS.parent / ".github/workflows/ci.yml")
        required = workflow["jobs"]["required-ci"]
        self.assertEqual(set(workflow["jobs"]), CI_JOBS)
        self.assertEqual(set(required["needs"]), CI_JOBS - {"required-ci"})
        self.assertEqual(required["if"], "always()")
        step = required["steps"][0]
        results = {}
        for variable, expression in step["env"].items():
            match = re.fullmatch(r"\$\{\{ needs\.([a-z-]+)\.result \}\}", expression)
            self.assertIsNotNone(match)
            results[match[1]] = variable
        self.assertEqual(set(results), CI_JOBS - {"required-ci"})
        env = {variable: "success" for variable in results.values()}
        self.assertEqual(self.run_shell(step["run"], env).returncode, 0)
        for job, variable in results.items():
            for conclusion in ("failure", "skipped", "cancelled", ""):
                with self.subTest(job=job, conclusion=conclusion):
                    result = self.run_shell(step["run"], {**env, variable: conclusion})
                    self.assertNotEqual(result.returncode, 0)

    def test_main_and_exact_commit_ci_gate_precede_both_aws_roles(self):
        for kind, workflow in self.workflows.items():
            with self.subTest(kind=kind):
                self.assertEqual(workflow["permissions"], {"contents": "read", "actions": "read", "id-token": "write"})
                operation = workflow["on"]["workflow_dispatch"]["inputs"]["operation"]
                self.assertEqual(operation["default"], "stage-image")
                self.assertEqual(operation["options"], ["stage-image", "deploy"])
                steps = workflow["jobs"]["deploy"]["steps"]
                ref_gate = steps[0]
                self.assertEqual(ref_gate["env"], {"RELEASE_REF": "${{ github.ref }}"})
                for ref in ("refs/heads/main", "refs/heads/feature", "refs/tags/main"):
                    result = self.run_shell(ref_gate["run"], {"RELEASE_REF": ref})
                    self.assertEqual(result.returncode == 0, ref == "refs/heads/main", result.stderr)
                checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
                self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")
                gate = next(step for step in steps if step.get("id") == "ci")
                self.assertEqual(gate["run"], "python scripts/require_ci.py")
                self.assertEqual(gate["env"], {"GH_TOKEN": "${{ github.token }}"})
                for guard in (ref_gate, gate):
                    self.assertIsNone(guard.get("if"))
                    self.assertEqual(guard.get("continue-on-error", "false"), "false")
                self.assertLess(steps.index(checkout), steps.index(gate))
                credentials = [step for step in steps if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")]
                self.assertEqual(len(credentials), 2)
                for step, operation_name, role in zip(credentials, ("stage-image", "deploy"),
                                                     ("AWS_IMAGE_STAGE_ROLE_ARN", "AWS_DEPLOY_ROLE_ARN")):
                    self.assertLess(steps.index(gate), steps.index(step))
                    self.assertEqual(step["if"], "${{ inputs.operation == '" + operation_name + "' }}")
                    self.assertEqual(step["with"]["role-to-assume"], "${{ vars." + role + " }}")
                for step in steps:
                    if "task-definition" in step.get("uses", "") or step.get("name") == "Download current task definition":
                        self.assertEqual(step["if"], "${{ inputs.operation == 'deploy' }}")

    def test_image_build_publishes_run_specific_tag_digest_and_commit_receipt(self):
        for kind, workflow in self.workflows.items():
            steps = workflow["jobs"]["deploy"]["steps"]
            build = next(step for step in steps if step.get("id") == "build-image")
            self.assertEqual(build["env"]["IMAGE_COMMIT"], "${{ github.sha }}")
            self.assertEqual(build["env"]["IMAGE_TAG"], "${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}")
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                output, calls, summary = root / "output", root / "calls", root / "summary"
                output.touch()
                digest = "sha256:" + "d" * 64
                tag = SHA + "-91-2"
                image = f"registry.example/zoop-{kind}"
                env = {"ECR_REGISTRY": "registry.example", "ECR_REPOSITORY": f"zoop-{kind}",
                       "IMAGE_COMMIT": SHA, "IMAGE_TAG": tag, "GITHUB_OUTPUT": str(output),
                       "CALLS": str(calls), "DIGEST": digest}
                commands = """
                docker() { printf 'docker %s\\n' "$*" >> "$CALLS"; }
                aws() { printf 'aws %s\\n' "$*" >> "$CALLS"; printf '%s\\n' "$DIGEST"; }
                """
                result = self.run_shell(commands + build["run"], env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls.read_text().splitlines(), [
                    f"docker build --file {kind}/Dockerfile --label org.opencontainers.image.revision={SHA} --tag {image}:{tag} {kind}",
                    f"docker push {image}:{tag}",
                    f"aws ecr describe-images --repository-name zoop-{kind} --image-ids imageTag={tag} --query imageDetails[0].imageDigest --output text",
                ])
                self.assertEqual(output.read_text(), f"image={image}@{digest}\ntagged-image={image}:{tag}\ncommit={SHA}\n")
                receipt = next(step for step in steps if step.get("name") == "Write workflow summary")
                values = {
                    "inputs.operation": "stage-image", "steps.build-image.outputs.image": f"{image}@{digest}",
                    "steps.build-image.outputs.tagged-image": f"{image}:{tag}", "steps.build-image.outputs.commit": SHA,
                    "steps.ci.outputs.ci-run-id": "7", "steps.ci.outputs.ci-run-attempt": "3",
                }
                receipt_env = {name: values[expression.removeprefix("${{ ").removesuffix(" }}")]
                               for name, expression in receipt["env"].items()}
                result = self.run_shell(receipt["run"], {**receipt_env, "GITHUB_RUN_ID": "91",
                    "GITHUB_RUN_ATTEMPT": "2", "GITHUB_STEP_SUMMARY": str(summary)})
                self.assertEqual(result.returncode, 0, result.stderr)
                for line in (f"- Main commit: `{SHA}`", "- CI run / attempt: `7` / `3`",
                             "- Image workflow run / attempt: `91` / `2`", f"- Image: `{image}@{digest}`"):
                    self.assertIn(line, summary.read_text())

    def test_image_build_failure_does_not_publish_a_digest(self):
        for kind, workflow in self.workflows.items():
            build = next(step for step in workflow["jobs"]["deploy"]["steps"] if step.get("id") == "build-image")
            for failing_command in ("build", "push"):
                with self.subTest(kind=kind, failing_command=failing_command), tempfile.TemporaryDirectory() as folder:
                    output = Path(folder) / "output"
                    output.touch()
                    result = self.run_shell("""
                        docker() { if [ "$1" = "$FAIL_COMMAND" ]; then return 17; fi; }
                        aws() { exit 99; }
                        """ + build["run"], {
                        "ECR_REGISTRY": "registry.example", "ECR_REPOSITORY": f"zoop-{kind}",
                        "IMAGE_TAG": SHA + "-91-2", "IMAGE_COMMIT": SHA,
                        "GITHUB_OUTPUT": str(output), "FAIL_COMMAND": failing_command,
                    })
                    self.assertEqual(result.returncode, 17, result.stderr)
                    self.assertEqual(output.read_text(), "")


class EvaluationVerificationGateTests(unittest.TestCase):
    def installed_cli(self, root: Path) -> Path:
        cli = root / "ai/worker/.venv/bin/zoop-ai"
        cli.parent.mkdir(parents=True)
        cli.write_text("synthetic installed CLI marker; never executed\n", encoding="utf-8")
        cli.chmod(0o700)
        return cli

    def test_subprocess_environment_excludes_provider_proxy_and_python_overrides(self):
        observed = []

        def probe_environment(command, *, cwd, env):
            result = subprocess.run(
                [sys.executable, "-I", "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
                env=env, capture_output=True, text=True, check=True,
            )
            observed.append(json.loads(result.stdout))

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.installed_cli(root)
            inherited = {"PATH": "/usr/bin:/bin", "HOME": folder, "LANG": "C.UTF-8",
                         "PYTHONPATH": "/synthetic/untrusted", "ZOOP_AI_LIVE_ENABLED": "1",
                         "TYPESAFE_BASE_URL": "https://example.invalid", "HTTPS_PROXY": "https://example.invalid"}
            with patch.object(repo_checks, "ROOT", root), patch.dict(os.environ, inherited, clear=True), \
                    patch.object(repo_checks, "run", side_effect=probe_environment), redirect_stdout(io.StringIO()):
                repo_checks.evaluation_verification()
            self.assertTrue(observed)
            for child_env in observed:
                for forbidden in ("PYTHONPATH", "ZOOP_AI_LIVE_ENABLED", "TYPESAFE_BASE_URL", "HTTPS_PROXY"):
                    self.assertNotIn(forbidden, child_env)
                self.assertEqual(child_env["HOME"], folder)
                self.assertEqual(child_env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_missing_or_nonexecutable_cli_fails_without_running_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(repo_checks, "ROOT", root), patch.object(repo_checks, "run") as run:
                with self.assertRaisesRegex(ValueError, "make worker-install"):
                    repo_checks.evaluation_verification()
                cli = self.installed_cli(root)
                cli.chmod(0o600)
                with self.assertRaisesRegex(ValueError, "make worker-install"):
                    repo_checks.evaluation_verification()
                run.assert_not_called()

    def test_smoke_failure_stops_before_gold_reading_evaluation_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.installed_cli(root)
            with patch.object(repo_checks, "ROOT", root), \
                    patch.object(repo_checks, "run", side_effect=subprocess.CalledProcessError(1, "smoke")) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    repo_checks.evaluation_verification()
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][-1], "smoke")


class SecretAndCredentialTests(unittest.TestCase):
    def test_secret_filenames_detected_without_contents(self):
        for name in (".env", "app/.env.production", "app/state.sqlite", "app/private.pem"):
            self.assertIsNotNone(repo_checks.secret_problem(Path(name)))
        self.assertIsNone(repo_checks.secret_problem(Path("app/.env.example")))

    def test_secret_signatures_use_only_synthetic_bytes(self):
        signature = b"ghp_" + b"a" * 36
        self.assertIsNotNone(repo_checks.secret_problem(Path("config.txt"), signature))
        self.assertIsNone(repo_checks.secret_problem(Path("config.txt"), b"API_TOKEN=example"))
        self.assertIsNotNone(repo_checks.secret_problem(Path("config.txt"), b"sk-proj-" + b"a" * 40))

    def test_public_url_slugs_are_not_api_key_signatures(self):
        urls = (b"https://example.invalid/samsung-sk-company-" + b"a" * 80,
                b"https://example.invalid/sayari-risk-" + b"a" * 40 + b".png")
        for url in urls:
            self.assertIsNone(repo_checks.secret_problem(Path("references.md"), url))

    def test_untracked_source_is_scanned_without_reading_ignored_env(self):
        with tempfile.TemporaryDirectory(prefix="zoop-secret-gate-test-") as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text(".env\n", encoding="utf-8")
            (root / "tracked.txt").write_text("safe synthetic input\n", encoding="utf-8")
            # Only the throwaway repository is staged; the project index is untouched.
            subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=root, check=True)
            synthetic_token = "ghp_" + "a" * 36
            (root / ".env").write_text(synthetic_token, encoding="utf-8")
            new_source = root / "new-source.py"
            new_source.write_text(synthetic_token, encoding="utf-8")
            errors, output = io.StringIO(), io.StringIO()
            with patch.object(repo_checks, "ROOT", root), redirect_stderr(errors), redirect_stdout(output):
                with self.assertRaisesRegex(ValueError, "Secret gate failed"):
                    repo_checks.secrets()
                self.assertIn("new-source.py", errors.getvalue())
                self.assertNotIn(synthetic_token, errors.getvalue())
                self.assertNotIn(".env:", errors.getvalue())
                new_source.write_text("safe untracked source\n", encoding="utf-8")
                repo_checks.secrets()
            self.assertIn("tracked and nonignored untracked files passed", output.getvalue())

    def test_missing_private_token_fails_without_network(self):
        for project in private_poc_sync.PROJECTS:
            with self.subTest(project=project), patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(SystemExit, "cannot be skipped"):
                private_poc_sync.main(["--project", project])

    def test_private_sync_rejects_every_project_but_the_bff_including_the_now_native_pipeline(self):
        for project in ("ai/worker", "ai/pipeline"):
            with self.subTest(project=project), patch.dict(os.environ, {"POC_READ_TOKEN": "synthetic-fixture"}, clear=True), self.assertRaises(SystemExit) as raised:
                private_poc_sync.main(["--project", project])
            self.assertEqual(raised.exception.code, 2)

    def test_private_preflight_fails_closed_and_cleans_askpass(self):
        observed = []
        def reject(command, **kwargs):
            helper = Path(kwargs["env"]["GIT_ASKPASS"])
            observed.append(helper)
            subprocess.run(["bash", "-n", str(helper)], check=True)
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"synthetic denied")
        real_run = subprocess.run
        def intercepted(command, **kwargs):
            if command[0] == "bash":
                return real_run(command, **kwargs)
            return reject(command, **kwargs)
        with patch.dict(os.environ, {"POC_READ_TOKEN": "synthetic-fixture"}, clear=True), patch.object(private_poc_sync.subprocess, "run", side_effect=intercepted):
            with self.assertRaisesRegex(SystemExit, "read preflight failed"):
                private_poc_sync.main(["--project", "prototype/bff"])
        self.assertTrue(observed)
        self.assertTrue(all(not helper.exists() for helper in observed))

    def test_pr_title_convention(self):
        self.assertTrue(repo_checks.TITLE.fullmatch("feat(web): 기업 문서 조회"))
        self.assertTrue(repo_checks.TITLE.fullmatch("fix(api)!: change contract"))
        self.assertIsNone(repo_checks.TITLE.fullmatch("new feature"))
        self.assertIsNone(repo_checks.TITLE.fullmatch("feat(unknown): change"))


if __name__ == "__main__":
    unittest.main()
