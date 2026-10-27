"""Record content hashes after generating and visually checking both exports."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = ["docs/holdline.md", "docs/holdline.docx", "docs/holdline.pdf"]
manifest = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
(root / "docs/exports.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Document export hashes recorded.")
