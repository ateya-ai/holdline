import hashlib
import json
import re
import zipfile
from pathlib import Path

from scripts.package_release import build

ROOT = Path(__file__).resolve().parents[1]


def test_archive_has_verified_sources_and_no_local_state(tmp_path):
    destination = build(tmp_path / "release.zip")
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        prefix = "holdline-2.0.0/"
        manifest = json.loads(archive.read(prefix + "RELEASE-MANIFEST.json"))
        assert prefix + "README.md" in names
        assert prefix + ".env.example" in names
        assert prefix + ".github/workflows/quality.yml" in names
        assert prefix + "docs/holdline.pdf" in names
        for name in names:
            assert not any(
                part in {".env", ".venv", ".run", ".git", "__pycache__", ".DS_Store"}
                for part in Path(name).parts
            )
            assert not name.endswith((".sqlite", ".dump", ".pyc"))
        for name, expected in manifest["files"].items():
            assert hashlib.sha256(archive.read(prefix + name)).hexdigest() == expected
    assert (
        destination.with_suffix(".zip.sha256")
        .read_text()
        .startswith(hashlib.sha256(destination.read_bytes()).hexdigest())
    )


def test_published_markdown_links_resolve():
    documents = (
        list(ROOT.glob("*.md"))
        + list((ROOT / "docs").glob("*.md"))
        + list((ROOT / "aws").glob("*.md"))
    )
    for document in documents:
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
            if target.startswith(("http://", "https://", "#")):
                continue
            path = target.split("#", 1)[0]
            assert (document.parent / path).exists(), f"{document.name}: {target}"
