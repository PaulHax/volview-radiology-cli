"""Resolve Girder file ids and existing local paths for CLI image inputs.

Girder-backed inputs arrive as comma-separated file ids, with ``slicer_cli_web``
providing ``girderApiUrl`` and ``girderToken``. Existing local paths pass through
without a download or Girder credentials.
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

    Existing files are local paths, and tokens matching the Girder object-id
    shape are file ids to fetch. Anything else is rejected.
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
        raise ValueError("girderApiUrl is required to fetch input file ids")
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

    - ``value``: comma-separated Girder file ids or existing local paths.
    - ``api_url`` / ``token``: the injected ``girderApiUrl``/``girderToken``;
      only consulted when there is at least one id to fetch.
    - ``client``: an optional Girder client. A ``GirderClient`` is built from
      ``api_url``/``token`` when omitted.

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
        # The caller reads these files after this function returns, so retain
        # them until the CLI process exits.
        atexit.register(shutil.rmtree, dest_dir, ignore_errors=True)
    else:
        os.makedirs(dest_dir, exist_ok=True)

    fetched = [_download_one(client, file_id, dest_dir) for file_id in file_ids]
    return local_paths + fetched


def resolve_girder_credentials(args):
    """Pull ``girderApiUrl``/``girderToken`` off parsed CLI args, env fallback.

    ``slicer_cli_web`` injects them as ``args.girderApiUrl`` and
    ``args.girderToken``. Empty values use the corresponding environment
    variable.
    """
    api_url = getattr(args, "girderApiUrl", None) or os.environ.get("GIRDER_API_URL")
    token = getattr(args, "girderToken", None) or os.environ.get("GIRDER_TOKEN")
    return (api_url or None), (token or None)
