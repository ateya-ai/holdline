"""Verify the source archive and optionally install and check its clean copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--run-checks", action="store_true")
    args = parser.parse_args()
    prefix = "holdline-2.0.0/"
    with zipfile.ZipFile(args.archive) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive entries")
        for name in names:
            path = PurePosixPath(name)
            if not name.startswith(prefix) or path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe archive path")
            if any(
                part in {".git", ".env", ".venv", ".run", "__pycache__", ".DS_Store"}
                for part in path.parts
            ):
                raise ValueError("local state included in release")
        manifest = json.loads(archive.read(prefix + "RELEASE-MANIFEST.json"))
        expected = {prefix + name for name in manifest["files"]} | {
            prefix + "RELEASE-MANIFEST.json"
        }
        if set(names) != expected:
            raise ValueError("manifest and archive differ")
        for name, expected_hash in manifest["files"].items():
            if hashlib.sha256(archive.read(prefix + name)).hexdigest() != expected_hash:
                raise ValueError("source digest mismatch: " + name)
        print("Manifest verified:", len(manifest["files"]), "source files")
        if args.run_checks:
            with tempfile.TemporaryDirectory(prefix="holdline-clean-release-") as directory:
                archive.extractall(directory)
                root = Path(directory) / prefix.rstrip("/")
                environment = Path(directory) / "venv"
                subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
                python = environment / "bin/python"
                subprocess.run(
                    [
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "-r",
                        str(root / "requirements-dev.lock.txt"),
                    ],
                    check=True,
                )
                env = os.environ.copy()
                env["HOLD_LINE_LOAD_DOTENV"] = "false"
                commands = [
                    [str(python), "-m", "pip", "check"],
                    [str(python), "-m", "ruff", "check", "."],
                    [str(python), "-m", "ruff", "format", "--check", "."],
                    [str(python), "-m", "pytest", "-ra"],
                    [str(python), "scripts/setup.py"],
                    [str(python), "scripts/integration.py"],
                    [str(python), "scripts/check_supervisor.py"],
                ]
                for command in commands:
                    subprocess.run(command, cwd=root, env=env, check=True)
    print("Release verification passed.")


if __name__ == "__main__":
    main()
