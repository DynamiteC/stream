"""Shared fixtures for the sidecar test suite.

``main.py`` is a standalone script that reads its configuration from the
environment at import time and creates a few module-level globals (the S3
client, the thread pool, the ``uploaded_files`` dedup set). We load it once by
path and then reset the mutable state between tests so the cases stay isolated.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def main_mod():
    """Import ``main.py`` once for the whole session.

    DRY_RUN is forced on so the import never tries to build a real S3 client.
    Individual tests flip the relevant globals as needed.
    """
    os.environ.setdefault("DRY_RUN", "true")
    spec = importlib.util.spec_from_file_location(
        "sidecar_main", SIDECAR_DIR / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["sidecar_main"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sidecar(main_mod, tmp_path, monkeypatch):
    """A clean sidecar module pointed at an empty temp watch dir.

    Resets the cross-cycle ``uploaded_files`` set, points ``WATCH_DIR`` at an
    isolated temp directory, pins ``NODE_ID``, and neutralises ``time.sleep`` so
    the missing-directory path doesn't actually block.
    """
    main_mod.uploaded_files.clear()
    monkeypatch.setattr(main_mod, "WATCH_DIR", str(tmp_path))
    monkeypatch.setattr(main_mod, "NODE_ID", "test-node")
    monkeypatch.setattr(main_mod.time, "sleep", lambda *_a, **_k: None)
    return main_mod


def make_stream(watch_dir, app, stream_key, num_segments):
    """Create a manifest + ``num_segments`` segment files for a stream.

    Mirrors the SRS layout the sidecar expects:
    ``<watch_dir>/<app>/<stream_key>.mpd`` and ``<stream_key>-<seq>.m4s``.
    Returns the manifest Path and the list of segment Paths.
    """
    app_dir = Path(watch_dir) / app
    app_dir.mkdir(parents=True, exist_ok=True)

    manifest = app_dir / f"{stream_key}.mpd"
    manifest.write_text("<MPD/>")

    segments = []
    for seq in range(1, num_segments + 1):
        seg = app_dir / f"{stream_key}-{seq}.m4s"
        seg.write_bytes(b"segment-data")
        segments.append(seg)

    return manifest, segments
