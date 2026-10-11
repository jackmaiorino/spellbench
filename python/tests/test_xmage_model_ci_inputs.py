from __future__ import annotations

import sys
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from xmage_model_ci_inputs import NoTokenRedirect, input_opener, public_inputs

BLOB = "https://api.github.com/repos/example/model/git/blobs/" + "a" * 40


def test_public_callback_inputs_include_pinned_vocab_without_any_checkpoints():
    assets = json.loads((Path(__file__).parents[2] / "engines/xmage/releases.json").read_text())["assets"]
    selected = public_inputs(assets)
    vocabulary = [asset for asset in selected if asset["id"] == "draftzero-exp1-actions"]
    assert len(vocabulary) == 1 and vocabulary[0]["filename"] == "FDN_SPG.tsv"
    assert vocabulary[0]["sha256"] == "16faa169baa03eafd3e36490b40c3cbabf1a902e7c227eff69646be1c09afee9"
    assert all(asset["kind"] in ("source-code", "build-dependency", "action-vocabulary") for asset in selected)
    assert sum(asset["bytes"] for asset in selected) < 32 * 1024**2
    with pytest.raises(ValueError, match="action vocabulary"):
        public_inputs([asset for asset in assets if asset["id"] != "draftzero-exp1-actions"])
    with pytest.raises(ValueError, match="action vocabulary"):
        public_inputs(assets + [{"id": "draftzero-exp1-search-unreviewed-weights", "kind": "checkpoint"}])


def test_pinned_blob_receives_read_token_only_in_authenticated_opener():
    calls = []

    def public(request, *, timeout):
        raise AssertionError("pinned blob must use the authenticated opener")

    def authenticated(request, *, timeout):
        calls.append((request.full_url, request.get_header("Authorization"), timeout))
        return "response"

    request = urllib.request.Request(BLOB)
    assert input_opener("test-token", public_opener=public, github_opener=authenticated)(request, timeout=60) == "response"
    assert calls == [(BLOB, "Bearer test-token", 60)]


@pytest.mark.parametrize("url", [
    "https://repo.maven.apache.org/maven2/org/example/library.jar",
    "https://api.github.com/repos/example/model/releases/assets/123",
    "https://api.github.com/repos/example/model/git/blobs/main",
    BLOB + "?redirect=https://example.org",
    BLOB.replace("api.github.com", "api.github.com.example.org"),
])
def test_other_input_urls_never_receive_ci_token(url):
    calls = []

    def public(request, *, timeout):
        calls.append((request.full_url, request.get_header("Authorization")))
        return "response"

    def authenticated(request, *, timeout):
        raise AssertionError("non-blob input must not use the token opener")

    request = urllib.request.Request(url)
    assert input_opener("test-token", public_opener=public, github_opener=authenticated)(request, timeout=60) == "response"
    assert calls == [(url, None)]


def test_missing_ci_token_preserves_public_blob_fetch():
    def public(request, *, timeout):
        assert request.full_url == BLOB and request.get_header("Authorization") is None
        return "response"

    def authenticated(request, *, timeout):
        raise AssertionError("missing token must not use the token opener")

    assert input_opener(None, public_opener=public, github_opener=authenticated)(
        urllib.request.Request(BLOB), timeout=60) == "response"


def test_authenticated_redirect_refuses_before_forwarding_token():
    request = urllib.request.Request(BLOB, headers={"Authorization": "Bearer test-token"})
    with pytest.raises(urllib.error.HTTPError, match="authenticated blob request redirected") as error:
        NoTokenRedirect().redirect_request(request, None, 302, "Found", {}, "https://example.org/receive")
    assert "test-token" not in str(error.value)
