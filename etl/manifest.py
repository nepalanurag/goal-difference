"""Content-hash manifest for the pipeline's key inputs (phase 9.5).

Lightweight alternative to full DVC for data versioning: the key pipeline
inputs get stable sha1 IDs written to data/MANIFEST.json, so any fitted
model can be traced back to the exact input bytes that produced it.
Immutable IDs, never "latest".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import settings

# Key pipeline inputs, in stable order. These are the files a refit stands
# on; the manifest is written after extract and read by fit.
MANIFEST_INPUTS: tuple[str, ...] = (
    *(f"data/fixtures_{league}.csv" for league in settings.league_order),
    "data/european_fixtures.jsonl",
)

MANIFEST_PATH: Path = settings.data_dir / "MANIFEST.json"


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest() -> dict:
    """Hash the key inputs and write data/MANIFEST.json. Returns the manifest."""
    entries = []
    for rel in MANIFEST_INPUTS:
        path = settings.repo_root / rel
        entries.append(
            {
                "path": rel,
                "sha1": sha1_file(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {"inputs": entries}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify_manifest() -> list[str]:
    """Re-hash the inputs and compare against data/MANIFEST.json.

    Returns a list of human-readable problems; an empty list means the
    working tree matches the recorded snapshot.
    """
    manifest = json.loads(MANIFEST_PATH.read_text())
    recorded = {e["path"]: e["sha1"] for e in manifest.get("inputs", [])}
    problems: list[str] = []
    for rel in MANIFEST_INPUTS:
        path = settings.repo_root / rel
        if not path.exists():
            problems.append(f"{rel}: file missing")
            continue
        actual = sha1_file(path)
        expected = recorded.get(rel)
        if expected is None:
            problems.append(f"{rel}: not recorded in MANIFEST.json")
        elif expected != actual:
            problems.append(
                f"{rel}: sha1 mismatch "
                f"(manifest {expected[:12]}, disk {actual[:12]})"
            )
    return problems


if __name__ == "__main__":
    manifest = write_manifest()
    print(f"wrote {MANIFEST_PATH} ({len(manifest['inputs'])} inputs)")
    for problem in verify_manifest():
        print("MISMATCH:", problem)
