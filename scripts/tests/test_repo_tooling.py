"""Run packaging against throwaway synthetic input; never inspect a real .env."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
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
        require_ci.require_jobs([{"name": name, "conclusion": "success"} for name in require_ci.REQUIRED_JOBS])

    def test_other_commit_pr_branch_repo_and_workflow_do_not_pass(self):
        for changes in ({"head_sha": "b" * 40}, {"event": "pull_request"}, {"head_branch": "feature"},
                        {"repository": {"full_name": "elsewhere/zoop"}}, {"path": ".github/workflows/other.yml"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "No CI push run"):
                require_ci.select_run({"workflow_runs": [self.run_record(**changes)]}, SHA, REPO)

    def test_latest_failure_cannot_hide_behind_previous_success(self):
        for status, conclusion in (("completed", "failure"), ("in_progress", None), ("completed", "skipped")):
            with self.subTest(status=status, conclusion=conclusion), self.assertRaisesRegex(ValueError, "Latest CI"):
                require_ci.select_run({"workflow_runs": [self.run_record(), self.run_record(id=8, status=status, conclusion=conclusion)]}, SHA, REPO)

    def test_missing_or_skipped_job_fails_for_every_required_job(self):
        self.assertIn("ai-pipeline", require_ci.REQUIRED_JOBS)
        self.assertIn("ai-pipeline-tests", require_ci.REQUIRED_JOBS)
        self.assertIn("ai-pipeline-smoke", require_ci.REQUIRED_JOBS)
        self.assertNotIn("ai-pipeline-public", require_ci.REQUIRED_JOBS)
        self.assertIn("ai-worker", require_ci.REQUIRED_JOBS)
        self.assertIn("ai-service", require_ci.REQUIRED_JOBS)
        self.assertIn("api", require_ci.REQUIRED_JOBS)
        self.assertIn("api-tests", require_ci.REQUIRED_JOBS)
        self.assertIn("api-graph-smoke", require_ci.REQUIRED_JOBS)
        self.assertIn("api-container", require_ci.REQUIRED_JOBS)
        self.assertIn("app-web", require_ci.REQUIRED_JOBS)
        self.assertEqual(len(require_ci.REQUIRED_JOBS), 14)
        for skipped in sorted(require_ci.REQUIRED_JOBS):
            with self.subTest(skipped=skipped), self.assertRaisesRegex(ValueError, "CI job evidence"):
                require_ci.require_jobs([{"name": name, "conclusion": "skipped" if name == skipped else "success"}
                                         for name in require_ci.REQUIRED_JOBS])
            with self.subTest(missing=skipped), self.assertRaisesRegex(ValueError, "CI job evidence"):
                require_ci.require_jobs([{"name": name, "conclusion": "success"} for name in require_ci.REQUIRED_JOBS - {skipped}])
        with self.assertRaisesRegex(ValueError, "CI job evidence"):
            require_ci.require_jobs([])


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
