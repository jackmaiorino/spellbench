"""Input preparation must reject corrupt or oversized releases before execution."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    "xmage_release_assets", Path(__file__).parents[1] / "tools" / "xmage_release_assets.py")
assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assets)


def pinned(data: bytes, filename="model.pt.gz"):
    return {"id": "test-model", "filename": filename, "url": "https://example.invalid/model",
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def remote(data):
    return lambda request, timeout: io.BytesIO(data)


def test_fetch_preserves_verified_opaque_bytes_and_does_not_refetch(tmp_path):
    # Deliberately not a parseable checkpoint: fetching has no deserializer.
    data = b"opaque pickle bytes that the host must never load"
    item = pinned(data)
    storage = {"cap_bytes": 1024, "reserve_bytes": 0}
    result = assets.fetch(tmp_path, item, storage, opener=remote(data))
    assert result["sha256"] == item["sha256"]
    assert (tmp_path / item["filename"]).read_bytes() == data
    assert not list(tmp_path.glob("*.part"))
    def must_not_open(*args, **kwargs):
        pytest.fail("a verified release was downloaded again")
    assert assets.fetch(tmp_path, item, storage, opener=must_not_open) == result


@pytest.mark.parametrize("downloaded", [b"bad payload", b"good payloa", b"good payload EXTRA"])
def test_corrupt_truncated_and_oversized_downloads_are_retained_but_never_admitted(tmp_path, downloaded):
    item = pinned(b"good payload")
    with pytest.raises(ValueError):
        assets.fetch(tmp_path, item, {"cap_bytes": 1024, "reserve_bytes": 0}, opener=remote(downloaded))
    assert not (tmp_path / item["filename"]).exists()
    assert len(list(tmp_path.glob("*.part"))) == 1


def test_changed_existing_weight_is_refused_and_preserved(tmp_path):
    item = pinned(b"good weights")
    dest = tmp_path / item["filename"]
    dest.write_bytes(b"changed weights")
    with pytest.raises(ValueError, match="does not match"):
        assets.fetch(tmp_path, item, {"cap_bytes": 1024, "reserve_bytes": 0}, opener=remote(b"good weights"))
    assert dest.read_bytes() == b"changed weights"


@pytest.mark.parametrize("budget", [{"cap_bytes": 1, "reserve_bytes": 0},
                                     {"cap_bytes": 1024, "reserve_bytes": 2**80}])
def test_storage_refusal_happens_before_network_or_file_creation(tmp_path, budget):
    def must_not_open(*args, **kwargs):
        pytest.fail("storage refusal reached the network")
    with pytest.raises(ValueError):
        assets.fetch(tmp_path, pinned(b"model bytes"), budget, opener=must_not_open)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("filename", ["../model.pt", "a/b.pt", "a\\b.pt", "model.pt.", "C:weight.pt"])
def test_asset_name_cannot_escape_input_root(tmp_path, filename):
    with pytest.raises(ValueError, match="filename"):
        assets.fetch(tmp_path, pinned(b"model", filename), {"cap_bytes": 100, "reserve_bytes": 0})


def test_archive_report_finds_deck_associations_and_weights_without_extracting(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xmage/decks/Standard-MonoU.dck", "60 Island")
        z.writestr("xmage/models/Standard-MonoU/ver1/model.pt.gz", "opaque weights")
        z.writestr("xmage/lib/engine.jar", "opaque executable")
    item = pinned(path.read_bytes(), "bundle.zip")
    report = assets.archive_report(path, item)
    assert report["deck_files"] == ["xmage/decks/Standard-MonoU.dck"]
    assert report["weight_files"] == [{"path": "xmage/models/Standard-MonoU/ver1/model.pt.gz", "bytes": 14}]
    assert report["archive_files"] == 3
    assert list(tmp_path.iterdir()) == [path]


def test_archive_with_traversal_member_is_rejected_without_extracting(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("../escape.pt", "opaque")
    with pytest.raises(ValueError, match="non-relative"):
        assets.archive_report(path, pinned(path.read_bytes(), "bundle.zip"))
    assert list(tmp_path.iterdir()) == [path]


def test_pinned_github_blob_download_requests_raw_bytes(tmp_path):
    data = b"dim\t1024\nA\t0\tPass\n"
    item = pinned(data, "actions.tsv")
    item.update(url="https://api.github.com/repos/owner/repo/git/blobs/" + "a" * 40,
                transport="github-raw-blob")
    def fetch_raw(request, timeout):
        assert request.get_header("Accept") == "application/vnd.github.raw+json"
        return io.BytesIO(data)
    assert assets.fetch(tmp_path, item, {"cap_bytes": 1000, "reserve_bytes": 0}, opener=fetch_raw)["bytes"] == len(data)
    item["url"] = "https://example.invalid/changed-transport"
    with pytest.raises(ValueError, match="public Git blob"):
        assets.validate_asset(item)


def test_local_checkpoint_is_verified_opaquely_and_never_downloaded(tmp_path):
    data = b"private checkpoint bytes"
    item = pinned(data)
    item.pop("url")
    item.update(kind="checkpoint", transport="local-file", provenance="Jack's archived export")
    def must_not_open(*args, **kwargs):
        pytest.fail("a local checkpoint reached the network")
    with pytest.raises(ValueError, match="already be staged"):
        assets.fetch(tmp_path, item, {"cap_bytes": 100, "reserve_bytes": 0}, opener=must_not_open)
    (tmp_path / item["filename"]).write_bytes(data)
    assert assets.fetch(tmp_path, item, {"cap_bytes": 100, "reserve_bytes": 0},
                        opener=must_not_open)["sha256"] == item["sha256"]
    item.pop("provenance")
    with pytest.raises(ValueError, match="explicit provenance"):
        assets.validate_asset(item)
