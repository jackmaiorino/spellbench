"""Fetch pinned public Java inputs and the action vocabulary for CI checks.

No checkpoints, private files or engine bundles are fetched. The 32 MiB input
cap and 1 GiB free-space reserve apply to the ephemeral CI input directory.
Local qualification retains the release manifest's existing storage limits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from xmage_release_assets import fetch, prepare_root


class NoTokenRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        if request.has_header("Authorization"):
            raise urllib.error.HTTPError(request.full_url, code,
                                         "authenticated blob request redirected", headers, fp)
        return super().redirect_request(request, fp, code, message, headers, new_url)


def input_opener(token: str | None, *, public_opener=urllib.request.urlopen, github_opener=None):
    """Use the CI token for exact public Git blobs and refuse token redirects."""
    if github_opener is None:
        github_opener = urllib.request.build_opener(NoTokenRedirect()).open
    blob = re.compile(r"https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/git/blobs/[a-f0-9]{40}")

    def open_input(request, *, timeout):
        if token and blob.fullmatch(request.full_url):
            request.add_header("Authorization", "Bearer " + token)
            return github_opener(request, timeout=timeout)
        return public_opener(request, timeout=timeout)

    return open_input


def public_inputs(assets):
    encoder = {"draftzero-exp1-" + name for name in
               ("actionencoder", "featuremap", "features", "labeledstate", "stateencoder")}
    encoder |= {"magezero-v02-" + name for name in
                ("actionencoder", "featuremap", "features", "labeledstate", "stateencoder")}
    required = encoder | {"draftzero-exp1-actions"}
    selected = [asset for asset in assets if asset["id"] in required
                or asset["id"].startswith(("draftzero-exp1-search-", "magezero-v02-search-", "draftzero-gnn-src-"))]
    if required - {asset["id"] for asset in selected} or any(
            asset["kind"] != "source-code"
            and not (asset["id"] == "draftzero-exp1-search-commonsmath3" and asset["kind"] == "build-dependency")
            and not (asset["id"] == "draftzero-exp1-actions" and asset["kind"] == "action-vocabulary")
            for asset in selected):
        raise ValueError("CI inputs must be pinned public sources, build dependency and action vocabulary")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parents[2] / "engines/xmage/releases.json"
    raw = manifest.read_bytes()
    selected = public_inputs(json.loads(raw)["assets"])
    root = prepare_root(args.root)
    storage = {"cap_bytes": 32 * 1024**2, "reserve_bytes": 1024**3}
    opener = input_opener(os.environ.get("SPELLBENCH_CI_GITHUB_TOKEN"))
    receipts = [fetch(root, asset, storage, opener=opener) for asset in selected]
    report = {"schema": "spellbench-draftzero-ci-inputs/v1",
              "input_manifest_sha256": hashlib.sha256(raw).hexdigest(),
              "assets": receipts, "storage": storage,
              "scope": "public source compilation and callback correctness; no checkpoints or qualification"}
    with (root / "CI-INPUTS.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"inputs": len(receipts), "bytes": sum(asset["bytes"] for asset in receipts)}))


if __name__ == "__main__":
    main()
