"""Build the broker child from a snapshot containing public Python sources only."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="spellbench-llm:local")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output manifest already exists")
    root = Path(__file__).resolve().parents[2]
    source = root / "python/spellbench"
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="spellbench-llm-image-") as folder:
        context = Path(folder)
        for path in sorted(source.rglob("*.py")):
            if path.is_symlink():
                raise ValueError("image sources must not be symlinks")
            name = path.relative_to(source)
            content = path.read_bytes()
            digest.update(name.as_posix().encode() + b"\0" + content + b"\0")
            target = context / "spellbench" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        dockerfile = root / "integrations/llm-sandbox/Dockerfile"
        shutil.copyfile(dockerfile, context / "Dockerfile")
        subprocess.run(["docker", "build", "--tag", args.tag, str(context)], check=True)
    image = subprocess.check_output(["docker", "image", "inspect", args.tag, "--format", "{{.Id}}"], text=True).strip()
    manifest = {"kind": "llm-container-image", "image_id": image, "package_sha256": digest.hexdigest(),
                "dockerfile_sha256": hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "projected_bytes": 250_000_000, "storage_cap_bytes": 500_000_000,
                "mounts": "public image sources only; no repository, logs or credentials"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
