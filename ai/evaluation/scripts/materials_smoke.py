"""Actual CLI material conversion smoke, not a model benchmark.

Run from the repository root: python3 -B ai/evaluation/scripts/materials_smoke.py
All fixture mutations are confined to TemporaryDirectory; the adapter is read-only.
"""
from __future__ import annotations

import argparse
import gettext
import hashlib
import json
import locale  # Preload gettext's stdlib locale support before the command audit.
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DEFAULT_MATERIALS = ROOT / "corpus" / "external-pilot-v1"
FILES = ("klue-re.inputs.json", "klue-re.gold.json", "tatqa.inputs.json", "tatqa.gold.json")
STDLIB = Path(os.__file__).parent


class CommandEnvironment(Mapping):
    """Deny application lookups; observe only proven argparse stdlib call chains.

    No underlying environment values are ever read. Allowed lookups behave as an
    absent key, matching run_cli's empty subprocess environment.
    """

    def __init__(self, effects: dict, observations: dict) -> None:
        self.effects = effects
        self.observations = observations

    @staticmethod
    def _display_caller(key, frame) -> str | None:
        if frame.f_code is Mapping.get.__code__:
            frame = frame.f_back
        if key in ("COLUMNS", "LINES"):
            if (frame.f_code is shutil.get_terminal_size.__code__ and frame.f_back is not None
                    and frame.f_back.f_code is argparse.HelpFormatter.__init__.__code__):
                return "shutil.get_terminal_size <- argparse.HelpFormatter.__init__"
        if key in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG") and frame.f_code is gettext.find.__code__:
            frame = frame.f_back
            locale_codes = {gettext.translation.__code__, gettext.dgettext.__code__, gettext.gettext.__code__,
                            gettext.dngettext.__code__, gettext.ngettext.__code__}
            while frame is not None and frame.f_code in locale_codes:
                frame = frame.f_back
            if frame is not None and frame.f_globals is vars(argparse):
                return "gettext.find <- gettext translation <- argparse"
        if key in ("PYTHON_COLORS", "NO_COLOR", "FORCE_COLOR", "TERM"):
            colorize = sys.modules.get("_colorize")
            can_colorize = getattr(colorize, "can_colorize", None)
            set_color = getattr(argparse.HelpFormatter, "_set_color", None)
            if (can_colorize is not None and set_color is not None
                    and frame.f_code in can_colorize.__code__.co_consts
                    and frame.f_code.co_name == "_safe_getenv"
                    and frame.f_back is not None and frame.f_back.f_code is can_colorize.__code__
                    and frame.f_back.f_back is not None and frame.f_back.f_back.f_code is set_color.__code__):
                return "_colorize._safe_getenv <- can_colorize <- argparse.HelpFormatter._set_color"
        return None

    def __getitem__(self, key):
        caller = self._display_caller(key, sys._getframe(1))
        if caller is not None:
            observation = (key, caller)
            self.observations[observation] = self.observations.get(observation, 0) + 1
            raise KeyError(key)
        self.effects["environmentReads"] += 1
        raise AssertionError("material CLI read application environment")

    def __iter__(self):
        self.effects["environmentReads"] += 1
        raise AssertionError("material CLI enumerated the environment")

    def __len__(self):
        self.effects["environmentReads"] += 1
        raise AssertionError("material CLI inspected the environment")


def copy_materials(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", *FILES):
        shutil.copyfile(DEFAULT_MATERIALS / name, target / name)


def replace_file(target: Path, name: str, document=None, *, raw: bytes | None = None) -> None:
    """Synthetic fixture mutation with honest integrity metadata, never repository writes."""
    if raw is None:
        raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    (target / name).write_bytes(raw)
    manifest = json.loads((target / "manifest.json").read_text("utf-8"))
    for item in manifest["files"]:
        if item["path"] == name:
            item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def run_cli(*argv: str, audited: bool = True) -> subprocess.CompletedProcess:
    command = ([sys.executable, "-B", str(Path(__file__).resolve()), "--audit-cli"] if audited
               else [sys.executable, "-B", "-m", "zoop_eval"])
    return subprocess.run([*command, *argv], cwd=ROOT, env={}, capture_output=True, text=True, timeout=30, check=False)


def audited_entrypoint(argv: list[str]) -> int:
    """Execute the real module entry point with fail-closed side-effect guards."""
    materials = DEFAULT_MATERIALS
    dataset = None
    for index, arg in enumerate(argv):
        if arg == "--materials" and index + 1 < len(argv):
            materials = Path(argv[index + 1])
        elif arg.startswith("--materials="):
            materials = Path(arg.split("=", 1)[1])
        elif arg == "--dataset" and index + 1 < len(argv):
            dataset = argv[index + 1]
        elif arg.startswith("--dataset="):
            dataset = arg.split("=", 1)[1]
    materials = materials.absolute()
    allowed = {str(materials), "manifest.json"}
    if argv[0] == "materials-inputs":
        allowed.add(f"{dataset}.inputs.json")
    else:
        allowed.update(FILES)
    opened = []
    effects = {"networkAttempts": 0, "writeAttempts": 0, "environmentReads": 0, "processAttempts": 0}
    environment_observations = {}
    active = True

    def audit(event: str, args: tuple) -> None:
        if not active:
            return
        if event.startswith("socket."):
            effects["networkAttempts"] += 1
            raise AssertionError("material CLI attempted networking")
        if event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.fork"):
            effects["processAttempts"] += 1
            raise AssertionError("material CLI attempted a child process")
        if event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link", "os.symlink", "os.chmod", "os.truncate", "os.putenv", "os.unsetenv"):
            effects["writeAttempts"] += 1
            raise AssertionError("material CLI attempted mutation")
        if event == "open":
            path, mode, flags = args
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                effects["writeAttempts"] += 1
                raise AssertionError("material CLI attempted a file write")
            if isinstance(path, int):
                return
            path = os.fsdecode(path)
            # Audit starts before application imports. Only Python modules from
            # this package/stdlib are import reads, never corpus or .env files.
            module_path = Path(path)
            if module_path.is_absolute() and module_path.suffix in (".py", ".pyc"):
                if module_path.is_relative_to(ROOT / "zoop_eval"):
                    return
                if module_path.is_relative_to(STDLIB) and "site-packages" not in module_path.parts:
                    return
            opened.append(path)
            if path not in allowed:
                raise AssertionError("material CLI attempted an unselected file read")

    old_environment, old_bytes = os.environ, os.environb
    os.environ = os.environb = CommandEnvironment(effects, environment_observations)
    sys.argv = ["zoop_eval", *argv]
    sys.addaudithook(audit)
    try:
        try:
            runpy.run_module("zoop_eval", run_name="__main__")
        except SystemExit as exc:
            code = exc.code
        else:
            code = 0
    finally:
        active = False
        os.environ, os.environb = old_environment, old_bytes
    print(json.dumps({"audit": effects, "opened": opened,
                      "allowedEnvironmentReads": [{"key": key, "caller": caller, "count": count}
                                                  for (key, caller), count in environment_observations.items()]}), file=sys.stderr)
    return code


def expect(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def checked(*argv: str, code: int = 0) -> dict:
    result = run_cli(*argv)
    expect(result.returncode == code, f"CLI status: {result.returncode}: {result.stderr}")
    doc = json.loads(result.stdout)
    audit = json.loads(result.stderr)
    expect(not any(audit["audit"].values()), "unexpected side effects")
    expect(doc["ok"] is (code == 0), "structured outcome")
    return doc


def main() -> int:
    direct = run_cli("materials-validate", audited=False)
    expect(direct.returncode == 0 and not direct.stderr, "python -m zoop_eval materials-validate")
    validation = checked("materials-validate")
    expect(validation["counts"] == {"klue-re": {"records": 20, "entitySpansChecked": 40},
                                    "tatqa": {"contexts": 5, "questions": 30}}, "collected counts")
    for dataset, count in (("klue-re", 20), ("tatqa", 30)):
        inputs = run_cli("materials-inputs", "--dataset", dataset)
        expect(inputs.returncode == 0, inputs.stderr)
        gold = checked("materials-gold", "--dataset", dataset)
        expect(len(gold["cases"]) == count, "gold count")
        expect(gold["inputsSha256"] == hashlib.sha256(inputs.stdout.rstrip("\n").encode("utf-8")).hexdigest(), "exact canonical binding")
        expect(inputs.stdout == run_cli("materials-inputs", "--dataset", dataset).stdout, "stable input bytes")
    with tempfile.TemporaryDirectory(prefix="zoop-material-smoke-") as temporary:
        target = Path(temporary)
        copy_materials(target)
        for dataset in ("klue-re", "tatqa"):
            (target / f"{dataset}.gold.json").unlink()
        for dataset in ("klue-re", "tatqa"):
            checked("materials-inputs", "--materials", str(target), "--dataset", dataset)
        checked("materials-validate", "--materials", str(target), code=2)
        copy_materials(target)
        data = json.loads((target / "klue-re.gold.json").read_text("utf-8"))
        data["records"][0]["label"] = True
        replace_file(target, "klue-re.gold.json", data)
        checked("materials-gold", "--materials", str(target), "--dataset", "klue-re", code=2)
        copy_materials(target)
        data = json.loads((target / "tatqa.gold.json").read_text("utf-8"))
        data["records"][0]["questions"][0]["rel_paragraphs"] = ["999"]
        replace_file(target, "tatqa.gold.json", data)
        checked("materials-validate", "--materials", str(target), code=2)
        copy_materials(target)
        data = json.loads((target / "tatqa.inputs.json").read_text("utf-8"))
        data["records"][0]["questions"][0]["answer"] = "forbidden annotation"
        replace_file(target, "tatqa.inputs.json", data)
        checked("materials-inputs", "--materials", str(target), "--dataset", "tatqa", code=2)
    print(json.dumps({"status": "passed", "counts": validation["counts"],
                      "proofScope": "Real collected files and synthetic invalid variants through the actual CLI; conversion/identity/integrity only, not accuracy. Audit starts before application imports, after Python/stdlib bootstrap. argparse locale/display lookups and temporary fixture writes are outside the application credential/model-config and read-only boundaries.",
                      "checks": ["canonical deterministic input/gold binding", "gold absent and no gold open attempts",
                                 "forged label type rejection", "orphan paragraph rejection", "annotation key rejection"],
                      "networkCalls": 0, "modelCalls": 0, "applicationEnvironmentReads": 0,
                      "repositoryWrites": 0, "qualityMeasurements": 0}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--audit-cli":
        sys.exit(audited_entrypoint(sys.argv[2:]))
    sys.exit(main())
