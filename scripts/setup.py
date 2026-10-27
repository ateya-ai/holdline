"""Create missing local credentials and replace only published placeholder values."""

import os
import secrets
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
text = target.read_text() if target.exists() else (root / ".env.example").read_text()
placeholders = {
    "",
    "replace-with-a-random-token",
    "replace-with-a-random-password",
    "local-dev-only",
}
lines = text.splitlines()
changed = not target.exists()
for key in ["HOLD_LINE_TOKEN", "POSTGRES_PASSWORD"]:
    index = next((i for i, line in enumerate(lines) if line.strip().startswith(key + "=")), None)
    if index is None:
        lines.append(key + "=" + secrets.token_urlsafe(32))
        changed = True
    elif lines[index].split("=", 1)[1].strip().strip('"').strip("'") in placeholders:
        lines[index] = key + "=" + secrets.token_urlsafe(32)
        changed = True
if changed:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=root, prefix=".env-", delete=False
    ) as stream:
        stream.write("\n".join(lines) + "\n")
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    os.replace(temporary, target)
    print("Local credentials configured; existing custom values preserved. Keep .env private.")
else:
    print(".env already has custom local credentials; preserved it.")
