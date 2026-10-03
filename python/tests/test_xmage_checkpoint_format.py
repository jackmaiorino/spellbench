"""Exercise the real export format without importing Torch or loading weights."""

import gzip
import importlib.util
import json
import stat
import zipfile
from contextlib import nullcontext
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    "checkpoint_format", Path(__file__).parents[2] / "integrations/xmage-models/checkpoint_format.py")
formats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(formats)
META = {"deck": "Standard-MonoU", "version": 2}


def export(path, metadata=META, extra=()):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata))
        archive.writestr("model.pt.gz", gzip.compress(b"opaque model bytes"))
        for name, data in extra:
            archive.writestr(name, data)


def test_original_export_layout_reads_gzip_weights_and_checks_association_without_extraction(tmp_path):
    path = tmp_path / "author.mz"
    export(path)
    with formats.checkpoint_stream(path, "magezero-mz", META) as (stream, metadata):
        assert metadata == META and stream.read() == b"opaque model bytes"
        stream.seek(7)
        assert stream.read(5) == b"model"
    assert list(tmp_path.iterdir()) == [path]
    for wrong in ({**META, "deck": "Other"}, {**META, "version": 3}):
        with pytest.raises(ValueError, match="does not match"):
            with formats.checkpoint_stream(path, "magezero-mz", wrong):
                pytest.fail("a different deck/version reached the weight loader")


@pytest.mark.parametrize("metadata", [None, {"deck": "Other"}, {**META, "version": True},
                                        {**META, "version": -1}, {**META, "deck": ""}])
def test_unpinned_or_invalid_export_metadata_is_refused(tmp_path, metadata):
    path = tmp_path / "author.mz"
    export(path)
    with pytest.raises(ValueError, match="deck name"):
        with formats.checkpoint_stream(path, "magezero-mz", metadata):
            pytest.fail("invalid association reached the weight loader")


@pytest.mark.parametrize("name", ["../escaped.pt", "unrequested.py", "metadata.json"])
def test_traversal_extra_and_duplicate_members_cannot_be_loaded(tmp_path, name):
    path = tmp_path / "author.mz"
    with pytest.warns(UserWarning) if name == "metadata.json" else nullcontext():
        export(path, extra=[(name, "unexpected")])
    with pytest.raises(ValueError, match="exactly"):
        with formats.checkpoint_stream(path, "magezero-mz", META):
            pytest.fail("invalid ZIP members reached the weight loader")
    assert list(tmp_path.iterdir()) == [path]


def test_oversized_metadata_duplicate_field_and_link_member_are_refused(tmp_path):
    path = tmp_path / "author.mz"
    link = zipfile.ZipInfo("model.pt.gz")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    for metadata, member, error in (
            (json.dumps({**META, "padding": "x" * 4096}), "model.pt.gz", "byte bound"),
            ('{"deck":"Standard-MonoU","deck":"Other","version":2}', "model.pt.gz", "duplicate"),
            (json.dumps(META), link, "ordinary")):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("metadata.json", metadata)
            archive.writestr(member, gzip.compress(b"opaque"))
        with pytest.raises(ValueError, match=error):
            with formats.checkpoint_stream(path, "magezero-mz", META):
                pytest.fail("invalid export reached the weight loader")


@pytest.mark.parametrize("checkpoint_format", ["torch", "torch-gzip"])
def test_raw_checkpoint_formats_preserve_bytes_and_do_not_accept_export_metadata(tmp_path, checkpoint_format):
    path = tmp_path / "checkpoint"
    data = b"opaque model bytes"
    path.write_bytes(gzip.compress(data) if checkpoint_format == "torch-gzip" else data)
    with formats.checkpoint_stream(path, checkpoint_format) as (stream, metadata):
        assert metadata is None and stream.read() == data
    with pytest.raises(ValueError, match="requires a MageZero"):
        with formats.checkpoint_stream(path, checkpoint_format, META):
            pytest.fail("bundle metadata was accepted for a raw checkpoint")
