"""Create a source-only release with a content manifest; never copy local state."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.0.0"
FILES = [
    ".dockerignore",
    ".env.example",
    ".gitignore",
    ".python-version",
    "README.md",
    "PLAN.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "requirements.in",
    "requirements.txt",
    "requirements.lock.txt",
    "requirements-dev.in",
    "requirements-dev.lock.txt",
    "requirements-infra.txt",
    "requirements-docs.txt",
    "pyproject.toml",
    "pytest.ini",
    "run.py",
    "Dockerfile",
    "docker-compose.yml",
    "compose.stack.yml",
    "compose.production.yml",
    "Caddyfile",
]
DIRECTORIES = [
    "holdline",
    "app",
    "specialists",
    "mcp_tools",
    "data",
    "skills",
    "tests",
    "scripts",
    "docs",
    "aws",
    "certs",
    ".github",
]
EXCLUDED = {"__pycache__", ".DS_Store", ".pytest_cache", ".ruff_cache", ".env", ".venv", ".run"}


def source_files():
    paths = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file())
    for path in sorted(set(paths)):
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED for part in relative.parts) or path.suffix in {
            ".pyc",
            ".pyo",
            ".sqlite",
            ".dump",
        }:
            continue
        if relative.name.startswith(".env") and str(relative) != ".env.example":
            continue
        if path.is_symlink():
            raise ValueError("release sources must not be symlinks: " + str(relative))
        if not path.is_file():
            raise FileNotFoundError("release source missing: " + str(relative))
        yield path


def build(destination: Path | None = None):
    destination = destination or ROOT / "dist" / ("holdline-" + VERSION + ".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = list(source_files())
    manifest = {
        "version": VERSION,
        "files": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
    }
    prefix = "holdline-" + VERSION + "/"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, prefix + str(path.relative_to(ROOT)))
        archive.writestr(prefix + "RELEASE-MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(checksum + "  " + destination.name + "\n")
    print("Release created:", destination)
    print("Source files:", len(files))
    return destination


if __name__ == "__main__":
    build()
