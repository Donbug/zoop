"""Package prototype source and a prebuilt web bundle, never runtime state."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

# Adding a new app or data directory is a reviewed change, not a recursive root copy.
TREES = {
    "prototype/web/src": {".ts", ".tsx", ".css", ".svg"},
    "prototype/web/scripts": {".mjs", ".js"},
    "prototype/web/public": {".svg", ".png", ".ico", ".woff", ".woff2", ".webmanifest"},
    "prototype/web/dist": {".html", ".js", ".css", ".svg", ".png", ".ico", ".woff", ".woff2", ".webmanifest"},
    "prototype/bff/src": {".py"},
    "ai/worker/src": {".py"},
    "ai/pipeline/src": {".py"},
}
FILES = (
    "prototype/README.md", "prototype/web/package.json", "prototype/web/pnpm-lock.yaml",
    "prototype/web/index.html", "prototype/web/tsconfig.json", "prototype/web/tsconfig.app.json",
    "prototype/web/tsconfig.node.json", "prototype/web/vite.config.ts", "prototype/web/DESIGN.md",
    "prototype/bff/pyproject.toml", "prototype/bff/uv.lock", "prototype/bff/README.md",
    "ai/README.md", "ai/worker/pyproject.toml", "ai/worker/uv.lock", "ai/worker/README.md",
    "ai/pipeline/pyproject.toml", "ai/pipeline/uv.lock", "ai/pipeline/README.md",
    "docs/api/openapi.yaml", "docs/api/ai-contract.schema.json", "docs/design/tokens.json",
)
REQUIRED = (
    "prototype/web/package.json", "prototype/web/pnpm-lock.yaml", "prototype/web/dist/index.html",
    "prototype/bff/pyproject.toml", "prototype/bff/uv.lock", "ai/worker/pyproject.toml", "ai/worker/uv.lock",
    "ai/pipeline/pyproject.toml", "ai/pipeline/uv.lock",
    "docs/api/openapi.yaml", "docs/api/ai-contract.schema.json", "docs/design/tokens.json",
)
FORBIDDEN_DIRS = {"var", "node_modules", "__pycache__", "recordings", "logs", "cache", "private", "fixtures"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key", ".p12", ".pyc", ".map"}


def denied(path: Path) -> bool:
    return (any(part.startswith(".") or part in FORBIDDEN_DIRS or part.startswith("var.") for part in path.parts)
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or path.name.lower() in {"credentials", "credentials.json", "id_rsa", "id_ed25519"})


def selected_files(root: Path) -> list[Path]:
    root = root.resolve()
    paths = set(FILES)
    for folder, suffixes in TREES.items():
        base = root / folder
        if not base.is_dir() or base.is_symlink():
            raise ValueError(f"required source/build directory missing or linked: {folder}")
        # Do not descend into excluded directories or follow directory symlinks.
        pending = [base]
        while pending:
            for child in pending.pop().iterdir():
                rel = child.relative_to(root)
                if denied(rel) or child.is_symlink():
                    continue
                if child.is_dir():
                    pending.append(child)
                elif child.is_file() and child.suffix.lower() in suffixes:
                    paths.add(rel.as_posix())
    selected = []
    for name in sorted(paths):
        rel = Path(name)
        path = root / rel
        if denied(rel) or any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
            continue
        if path.is_file():
            selected.append(rel)
    missing = set(REQUIRED) - {path.as_posix() for path in selected}
    if missing:
        raise ValueError("required allowlisted files missing: " + ", ".join(sorted(missing)))
    for folder in ("prototype/web/src", "prototype/bff/src", "ai/worker/src", "ai/pipeline/src"):
        if not any(path.as_posix().startswith(folder + "/") for path in selected):
            raise ValueError(f"source tree empty: {folder}")
    return selected


def package(root: Path, output: Path, commit: str, ci_run_id: str | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--commit requires a full lowercase 40-character Git commit SHA")
    root = root.resolve()
    output = output.resolve()
    if output == root or root in output.parents:
        raise ValueError("output must be outside the repository/source fixture")
    paths = selected_files(root)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"zoop-prototype-{commit}.zip"
    manifest = {"commit": commit, "ciRunId": ci_run_id, "kind": "source-and-web-build-not-deployment", "files": []}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for rel in paths:
            data = (root / rel).read_bytes()
            info = zipfile.ZipInfo(rel.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
            manifest["files"].append({"path": rel.as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksum = output / "SHA256SUMS"
    checksum.write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                for path in (archive, manifest_path)), encoding="ascii")
    return {"archive": str(archive), "files": len(paths), "checksum": str(checksum)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--ci-run-id")
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.output, args.commit, args.ci_run_id)))


if __name__ == "__main__":
    main()
