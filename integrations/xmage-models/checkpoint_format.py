"""Read checkpoint bytes without extracting files or deserializing model objects."""

from __future__ import annotations

import gzip
import json
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path


def validate_export_metadata(metadata: object) -> dict:
    if (not isinstance(metadata, dict) or set(metadata) != {"deck", "version"}
            or not isinstance(metadata["deck"], str) or not metadata["deck"].strip()
            or len(metadata["deck"]) > 128
            or type(metadata["version"]) is not int or metadata["version"] < 0):
        raise ValueError("MageZero export needs a deck name and nonnegative integer version")
    return metadata


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("MageZero export metadata has a duplicate field")
        result[key] = value
    return result


@contextmanager
def checkpoint_stream(path: Path, checkpoint_format: str, expected_export: dict | None = None):
    """Yield a seekable stream and verified export metadata inside the container.

    The caller still uses torch.load(weights_only=True). ZIP members remain
    streams; metadata never supplies an extraction path or a model filename.
    """
    if checkpoint_format in ("torch", "torch-gzip"):
        if expected_export is not None:
            raise ValueError("export metadata requires a MageZero .mz bundle")
        opener = gzip.open if checkpoint_format == "torch-gzip" else open
        with opener(path, "rb") as stream:
            yield stream, None
        return
    if checkpoint_format != "magezero-mz":
        raise ValueError("unsupported checkpoint format")
    validate_export_metadata(expected_export)
    with zipfile.ZipFile(path) as archive:
        items = archive.infolist()
        if (len(items) != 2
                or {item.filename for item in items} != {"metadata.json", "model.pt.gz"}):
            raise ValueError("MageZero .mz bundle must contain exactly metadata.json and model.pt.gz")
        for item in items:
            mode = item.external_attr >> 16
            if (item.is_dir() or item.flag_bits & 1
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                    or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError("MageZero .mz members must be ordinary unencrypted files")
        info = archive.getinfo("metadata.json")
        if not 0 < info.file_size <= 4096:
            raise ValueError("MageZero export metadata exceeds its byte bound")
        metadata = validate_export_metadata(json.loads(
            archive.read(info).decode("utf-8"), object_pairs_hook=unique_object))
        if metadata != expected_export:
            raise ValueError("MageZero export deck/version does not match its pinned association")
        weights = archive.getinfo("model.pt.gz")
        if not 0 < weights.file_size <= 1024**3:
            raise ValueError("MageZero export weight member exceeds its byte bound")
        with archive.open(weights) as member, gzip.GzipFile(fileobj=member, mode="rb") as stream:
            yield stream, metadata
