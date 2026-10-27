import subprocess
import sys
from pathlib import Path


def test_setup_is_portable_and_preserves_custom_credentials(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts/setup.py"
    script.write_text((root / "scripts/setup.py").read_text())
    (tmp_path / ".env.example").write_text((root / ".env.example").read_text())
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    first = (tmp_path / ".env").read_text()
    assert "replace-with-" not in first
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    assert (tmp_path / ".env").read_text() == first
    (tmp_path / ".env").write_text("HOLD_LINE_TOKEN=custom-preserved-token\n")
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    assert "HOLD_LINE_TOKEN=custom-preserved-token" in (tmp_path / ".env").read_text()
    assert "POSTGRES_PASSWORD=" in (tmp_path / ".env").read_text()
