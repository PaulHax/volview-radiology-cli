"""Download front-end (v1 b3) tests -- run fully offline.

``girder_client`` is importable in the harness, but a fake client is injected so
no Girder server is needed. This covers the comma-split / id-vs-path
classification / fail-closed logic that turns the facade's forwarded
``inputVolume`` string into local paths for ``assemble``.
"""
import os

import pytest

from volview_cli_base import girder_input as gi


# --- pure helpers ---------------------------------------------------------

def test_parse_input_tokens_splits_trims_and_drops_empties():
    assert gi.parse_input_tokens("a, b ,,c ") == ["a", "b", "c"]
    assert gi.parse_input_tokens("") == []
    assert gi.parse_input_tokens(None) == []
    assert gi.parse_input_tokens("  ") == []


def test_looks_like_object_id():
    assert gi.looks_like_object_id("6600000000000000000000a1")
    assert gi.looks_like_object_id("aBcDeF0123456789aBcDeF01")
    assert not gi.looks_like_object_id("6600000000000000000000a1x")  # 25 chars
    assert not gi.looks_like_object_id("/tmp/foo.nrrd")
    assert not gi.looks_like_object_id("")
    assert not gi.looks_like_object_id(None)


def test_classify_tokens_splits_local_paths_from_ids(tmp_path):
    local = tmp_path / "vol.nrrd"
    local.write_bytes(b"x")
    fid = "6600000000000000000000a1"
    paths, ids = gi.classify_tokens([str(local), fid])
    assert paths == [str(local)]
    assert ids == [fid]


def test_classify_tokens_fails_closed_on_foreign_string():
    with pytest.raises(ValueError):
        gi.classify_tokens(["http://evil.example/x", ])


# --- orchestration with an injected fake client ---------------------------

class _FakeClient:
    """Mirrors the two girder_client methods the front-end uses."""

    def __init__(self, names=None):
        self._names = names or {}
        self.downloaded = []

    def getFile(self, file_id):
        return {"_id": file_id, "name": self._names.get(file_id, file_id + ".dcm")}

    def downloadFile(self, file_id, path):
        with open(path, "wb") as fh:
            fh.write(b"bytes-of-" + file_id.encode())
        self.downloaded.append((file_id, path))


def test_resolve_all_local_paths_needs_no_client(tmp_path):
    a = tmp_path / "a.nrrd"
    b = tmp_path / "b.nrrd"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    value = "%s,%s" % (a, b)
    out = gi.resolve_inputs_to_local_paths(value)  # no client, no api_url
    assert out == [str(a), str(b)]


def test_resolve_fetches_ids_via_client(tmp_path):
    ids = ["6600000000000000000000a1", "6600000000000000000000a2",
           "6600000000000000000000a3"]
    value = ",".join(ids)  # the facade's comma-joined shape
    client = _FakeClient()
    dest = tmp_path / "dl"
    out = gi.resolve_inputs_to_local_paths(value, client=client, dest_dir=str(dest))
    assert len(out) == 3
    for p in out:
        assert os.path.exists(p)
    # every id was fetched exactly once
    assert sorted(fid for fid, _ in client.downloaded) == sorted(ids)


def test_resolve_mixed_local_and_ids(tmp_path):
    local = tmp_path / "seg.nrrd"
    local.write_bytes(b"seg")
    fid = "6600000000000000000000b9"
    value = "%s,%s" % (local, fid)
    client = _FakeClient()
    out = gi.resolve_inputs_to_local_paths(
        value, client=client, dest_dir=str(tmp_path / "dl")
    )
    assert out[0] == str(local)   # local-first ordering
    assert len(out) == 2
    assert client.downloaded and client.downloaded[0][0] == fid


def test_resolve_single_id(tmp_path):
    fid = "6600000000000000000000c7"
    client = _FakeClient()
    out = gi.resolve_inputs_to_local_paths(
        fid, client=client, dest_dir=str(tmp_path / "dl")
    )
    assert len(out) == 1 and os.path.exists(out[0])


def test_resolve_empty_value_fails_closed():
    with pytest.raises(ValueError):
        gi.resolve_inputs_to_local_paths("")


def test_resolve_foreign_token_fails_closed():
    with pytest.raises(ValueError):
        gi.resolve_inputs_to_local_paths("not-an-id-and-not-a-path")


def test_resolve_ids_without_api_url_fails_closed():
    # An id to fetch but no injected client and no api_url -> refuse, don't guess.
    with pytest.raises(ValueError):
        gi.resolve_inputs_to_local_paths("6600000000000000000000d1")


# --- credential extraction ------------------------------------------------

class _Args:
    pass


def test_resolve_girder_credentials_from_args():
    args = _Args()
    args.girderApiUrl = "http://girder:8080/api/v1"
    args.girderToken = "tok-abc"
    url, tok = gi.resolve_girder_credentials(args)
    assert url == "http://girder:8080/api/v1"
    assert tok == "tok-abc"


def test_resolve_girder_credentials_empty_string_is_absent(monkeypatch):
    monkeypatch.delenv("GIRDER_API_URL", raising=False)
    monkeypatch.delenv("GIRDER_TOKEN", raising=False)
    args = _Args()
    args.girderApiUrl = ""   # the XML default when slicer_cli_web didn't inject
    args.girderToken = ""
    url, tok = gi.resolve_girder_credentials(args)
    assert url is None and tok is None


def test_resolve_girder_credentials_env_fallback(monkeypatch):
    monkeypatch.setenv("GIRDER_API_URL", "http://env-girder/api/v1")
    monkeypatch.setenv("GIRDER_TOKEN", "env-tok")
    url, tok = gi.resolve_girder_credentials(_Args())
    assert url == "http://env-girder/api/v1"
    assert tok == "env-tok"
