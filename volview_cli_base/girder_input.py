"""Girder download front-end -- the v1 = b3 feeding layer (D10 point 3).

This is the *thin, backend-specific* layer that sits in front of the pure
``assemble`` core. The facade forwards a bound input's value as a comma-joined
string of Girder **file ids** (``processing.py`` ``_translateValuesToSlicerParams``)
and ``slicer_cli_web`` injects ``girderApiUrl``/``girderToken``; this module
comma-splits that value, fetches each id over the Girder REST API with
``girder_client``, and hands the local paths to ``assemble``. The CLI sees ids
+ a token, never a URL.

**v1 -> v2 containment.** Under Option C a small ``slicer_cli_web`` fan-out
bind-mounts the files and the CLI receives **local paths** instead of ids; this
whole module is then deleted and ``assemble`` is unchanged. To make that swap a
pure deletion -- and to be robust to whatever ``slicer_cli_web`` actually hands
the ``<image>`` input -- ``resolve_inputs_to_local_paths`` treats each token
that is already an existing local path as local (no fetch) and only fetches the
tokens that are Girder object ids. A fully-local input needs no token at all.
"""

import atexit
import os
import re
import shutil
import tempfile

# A Girder object id is a 24-char hex MongoDB ObjectId. Anything that is neither
# an existing local path nor this shape is refused (fail closed) -- the CLI
# never dereferences an arbitrary string.
_OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def looks_like_object_id(token):
    return bool(_OBJECT_ID_RE.match(token or ""))


def parse_input_tokens(value):
    """Comma-split a bound input value into trimmed, non-empty tokens.

    Order is advisory only -- ``assemble`` re-sorts DICOM by metadata -- so this
    does no sorting and makes no ordering promise.
    """
    if value is None:
        return []
    return [token.strip() for token in str(value).split(",") if token.strip()]


def classify_tokens(tokens, exists=os.path.exists):
    """Split tokens into ``(local_paths, file_ids)``.

    A token that is already an existing file is local (the v2/localized case); a
    token matching the Girder object-id shape is a file id to fetch (v1 = b3).
    Anything else fails closed. ``exists`` is injectable for tests.
    """
    local_paths = []
    file_ids = []
    unknown = []
    for token in tokens:
        if exists(token):
            local_paths.append(token)
        elif looks_like_object_id(token):
            file_ids.append(token)
        else:
            unknown.append(token)
    if unknown:
        raise ValueError(
            "input token is neither a local path nor a Girder file id: %r"
            % (unknown,)
        )
    return local_paths, file_ids


def _make_client(api_url, token):
    if not api_url:
        raise ValueError(
            "girderApiUrl is required to fetch input file ids (v1 b3 feeding)"
        )
    import girder_client

    client = girder_client.GirderClient(apiUrl=api_url)
    if token:
        client.setToken(token)
    return client


def _download_one(client, file_id, dest_dir):
    """Download a single Girder file, preserving its name (prefixed by id for
    uniqueness). DICOM ordering is by header, so the on-disk name is cosmetic.
    """
    name = file_id
    try:
        info = client.getFile(file_id)
        name = (info or {}).get("name") or file_id
    except Exception:
        # No metadata -> fall back to the id as the name; the download below is
        # the operation that actually matters.
        pass
    local_path = os.path.join(dest_dir, "%s__%s" % (file_id, name))
    client.downloadFile(file_id, local_path)
    return local_path


def resolve_inputs_to_local_paths(
    value, api_url=None, token=None, dest_dir=None, client=None
):
    """Resolve a bound input's wire value to a list of local file paths.

    - ``value``: the comma-joined ``inputVolume`` string the facade forwarded
      (N Girder file ids for a series; a single id for an L1 volume). Already-
      local paths are passed through untouched (v2/localized robustness).
    - ``api_url`` / ``token``: the injected ``girderApiUrl``/``girderToken``;
      only consulted when there is at least one id to fetch.
    - ``client``: an injected girder client (tests); a real ``GirderClient`` is
      built from ``api_url``/``token`` when omitted.

    Returns local paths in ``local-first, then fetched`` order -- advisory only.
    """
    tokens = parse_input_tokens(value)
    if not tokens:
        raise ValueError("no input files in value %r" % (value,))

    local_paths, file_ids = classify_tokens(tokens)
    if not file_ids:
        return local_paths

    if client is None:
        client = _make_client(api_url, token)
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="volview-input-")
        # Scope the scratch dir to the CLI *process*, not this function: the
        # caller reads the fetched files after we return, so we cannot delete on
        # function exit. Register removal at interpreter shutdown (runs on a
        # clean exit AND after an unhandled error propagates), which is the CLI
        # run boundary.
        atexit.register(shutil.rmtree, dest_dir, ignore_errors=True)
    else:
        os.makedirs(dest_dir, exist_ok=True)

    fetched = [_download_one(client, file_id, dest_dir) for file_id in file_ids]
    return local_paths + fetched


def resolve_girder_credentials(args):
    """Pull ``girderApiUrl``/``girderToken`` off parsed CLI args, env fallback.

    ``slicer_cli_web`` injects the two as ``<string>`` params declared in the
    CLI XML (the HistomicsTK ``example-girder-requests`` convention), so they
    arrive as ``args.girderApiUrl``/``args.girderToken``. Empty strings (the
    XML default when not injected) are treated as absent; the env vars are a
    standalone/testing fallback.
    """
    api_url = getattr(args, "girderApiUrl", None) or os.environ.get("GIRDER_API_URL")
    token = getattr(args, "girderToken", None) or os.environ.get("GIRDER_TOKEN")
    return (api_url or None), (token or None)
