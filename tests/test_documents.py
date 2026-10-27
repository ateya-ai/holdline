import hashlib
import json
from pathlib import Path


def test_document_exports_match_recorded_source():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "docs/exports.json").read_text())
    assert set(manifest) == {"docs/holdline.md", "docs/holdline.docx", "docs/holdline.pdf"}
    for name, expected in manifest.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, (
            "Regenerate and review the design exports before recording new hashes"
        )
    assert (root / "docs/holdline.pdf").read_bytes().startswith(b"%PDF-")
