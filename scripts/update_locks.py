"""Regenerate runtime and development locks in a temporary clean environment."""

import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="holdline-locks-") as directory:
    env = Path(directory) / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(env)], check=True)
    python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(root / "requirements.in")], check=True
    )
    runtime = subprocess.check_output([str(python), "-m", "pip", "freeze"], text=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(root / "requirements-dev.in")], check=True
    )
    development = subprocess.check_output([str(python), "-m", "pip", "freeze"], text=True)
    (root / "requirements.lock.txt").write_text(runtime)
    (root / "requirements-dev.lock.txt").write_text(development)
print("Locks updated. Review the diff, then run the full checks.")
