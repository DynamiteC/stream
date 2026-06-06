"""Unit tests for the S3 backup sidecar (``main.py``).

Coverage focuses on the non-obvious logic that has historically hidden bugs:
the prefix matching used to associate segments with a manifest, the
cross-cycle dedup set, DRY_RUN gating, and graceful handling of a missing
watch directory.
"""

from unittest.mock import MagicMock

import pytest

from conftest import make_stream


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


def test_upload_file_dry_run_skips_s3(sidecar, monkeypatch):
    """In DRY_RUN mode no S3 call is made even if a client is configured."""
    s3 = MagicMock()
    monkeypatch.setattr(sidecar, "DRY_RUN", True)
    monkeypatch.setattr(sidecar, "s3", s3)

    sidecar.upload_file("/data/live/live/match1.mpd", "backups/n/live/match1.mpd")

    s3.upload_file.assert_not_called()


def test_upload_file_real_calls_s3(sidecar, monkeypatch):
    """With DRY_RUN off, the file is uploaded with the expected arguments."""
    s3 = MagicMock()
    monkeypatch.setattr(sidecar, "DRY_RUN", False)
    monkeypatch.setattr(sidecar, "s3", s3)
    monkeypatch.setattr(sidecar, "BUCKET", "test-bucket")

    sidecar.upload_file("/data/live/live/match1.mpd", "backups/n/match1.mpd")

    s3.upload_file.assert_called_once_with(
        "/data/live/live/match1.mpd", "test-bucket", "backups/n/match1.mpd"
    )


def test_upload_file_no_client_is_noop(sidecar, monkeypatch):
    """When the S3 client failed to initialise, upload is a safe no-op."""
    monkeypatch.setattr(sidecar, "DRY_RUN", False)
    monkeypatch.setattr(sidecar, "s3", None)

    # Should not raise.
    sidecar.upload_file("/data/live/live/match1.mpd", "backups/n/match1.mpd")


def test_upload_file_swallows_exceptions(sidecar, monkeypatch):
    """A failing upload must not crash the sync loop."""
    s3 = MagicMock()
    s3.upload_file.side_effect = RuntimeError("network down")
    monkeypatch.setattr(sidecar, "DRY_RUN", False)
    monkeypatch.setattr(sidecar, "s3", s3)

    # Should not raise despite the S3 error.
    sidecar.upload_file("/data/live/live/match1.mpd", "backups/n/match1.mpd")


# ---------------------------------------------------------------------------
# run_sync_cycle: orchestration
#
# We replace upload_file with a thread-safe recorder so we can assert exactly
# which (local_path, s3_key) pairs were submitted, without touching S3.
# ---------------------------------------------------------------------------


@pytest.fixture
def recorder(sidecar, monkeypatch):
    import threading

    lock = threading.Lock()
    calls = []

    def _record(local_path, s3_key):
        with lock:
            calls.append((str(local_path), s3_key))

    monkeypatch.setattr(sidecar, "upload_file", _record)
    return calls


def s3_keys(calls):
    return {key for _local, key in calls}


def test_missing_watch_dir_is_graceful(sidecar, recorder, monkeypatch):
    """A not-yet-created watch dir must not raise and must upload nothing."""
    monkeypatch.setattr(sidecar, "WATCH_DIR", "/nonexistent/path/xyz")

    sidecar.run_sync_cycle()

    assert recorder == []


def test_empty_watch_dir_uploads_nothing(sidecar, recorder):
    sidecar.run_sync_cycle()
    assert recorder == []


def test_uploads_manifest_and_all_segments(sidecar, recorder):
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=3)

    sidecar.run_sync_cycle()

    keys = s3_keys(recorder)
    assert keys == {
        "backups/test-node/live/match1/match1.mpd",
        "backups/test-node/live/match1/match1-1.m4s",
        "backups/test-node/live/match1/match1-2.m4s",
        "backups/test-node/live/match1/match1-3.m4s",
    }


def test_segments_deduplicated_across_cycles(sidecar, recorder):
    """Segments upload once; the manifest re-uploads every cycle (it mutates)."""
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=2)

    sidecar.run_sync_cycle()
    recorder.clear()

    # Second cycle with the same files on disk.
    sidecar.run_sync_cycle()

    keys = s3_keys(recorder)
    # Manifest is always re-uploaded; segments are not.
    assert keys == {"backups/test-node/live/match1/match1.mpd"}


def test_new_segment_uploaded_on_later_cycle(sidecar, recorder):
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=2)
    sidecar.run_sync_cycle()
    recorder.clear()

    # A new segment appears in the next cycle.
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=3)
    sidecar.run_sync_cycle()

    assert "backups/test-node/live/match1/match1-3.m4s" in s3_keys(recorder)
    assert "backups/test-node/live/match1/match1-1.m4s" not in s3_keys(recorder)


def test_prefix_collision_does_not_leak_segments(sidecar, recorder):
    """A manifest must only claim its own segments.

    ``match1`` and ``match10`` share a textual prefix; the ``stream_key-``
    separator must keep their segments correctly partitioned.
    """
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=2)
    make_stream(sidecar.WATCH_DIR, "live", "match10", num_segments=2)

    sidecar.run_sync_cycle()

    keys = s3_keys(recorder)
    # match1 owns only its two segments.
    assert "backups/test-node/live/match1/match1-1.m4s" in keys
    assert "backups/test-node/live/match1/match1-2.m4s" in keys
    # match10's segments are filed under match10, never under match1.
    assert "backups/test-node/live/match1/match10-1.m4s" not in keys
    assert "backups/test-node/live/match10/match10-1.m4s" in keys
    assert "backups/test-node/live/match10/match10-2.m4s" in keys


def test_multiple_apps_are_isolated(sidecar, recorder):
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=1)
    make_stream(sidecar.WATCH_DIR, "replay", "match1", num_segments=1)

    sidecar.run_sync_cycle()

    keys = s3_keys(recorder)
    assert "backups/test-node/live/match1/match1-1.m4s" in keys
    assert "backups/test-node/replay/match1/match1-1.m4s" in keys


# ---------------------------------------------------------------------------
# HLS (.m3u8 / .ts) backup
# ---------------------------------------------------------------------------


def test_uploads_hls_manifest_and_segments(sidecar, recorder):
    make_stream(
        sidecar.WATCH_DIR,
        "live",
        "match1",
        num_segments=3,
        manifest_ext=".m3u8",
        segment_ext=".ts",
    )

    sidecar.run_sync_cycle()

    assert s3_keys(recorder) == {
        "backups/test-node/live/match1/match1.m3u8",
        "backups/test-node/live/match1/match1-1.ts",
        "backups/test-node/live/match1/match1-2.ts",
        "backups/test-node/live/match1/match1-3.ts",
    }


def test_dash_and_hls_coexist_without_cross_claiming(sidecar, recorder):
    """A DASH and HLS manifest for the same stream each own only their format.

    The .mpd manifest must claim only .m4s segments and the .m3u8 manifest only
    .ts segments, even though all four files share the ``match1-`` prefix.
    """
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=2)  # DASH
    make_stream(
        sidecar.WATCH_DIR,
        "live",
        "match1",
        num_segments=2,
        manifest_ext=".m3u8",
        segment_ext=".ts",
    )

    sidecar.run_sync_cycle()

    assert s3_keys(recorder) == {
        "backups/test-node/live/match1/match1.mpd",
        "backups/test-node/live/match1/match1-1.m4s",
        "backups/test-node/live/match1/match1-2.m4s",
        "backups/test-node/live/match1/match1.m3u8",
        "backups/test-node/live/match1/match1-1.ts",
        "backups/test-node/live/match1/match1-2.ts",
    }


def test_hls_segments_deduplicated_across_cycles(sidecar, recorder):
    make_stream(
        sidecar.WATCH_DIR,
        "live",
        "match1",
        num_segments=2,
        manifest_ext=".m3u8",
        segment_ext=".ts",
    )

    sidecar.run_sync_cycle()
    recorder.clear()
    sidecar.run_sync_cycle()

    # Only the manifest re-uploads; .ts segments are deduped like .m4s.
    assert s3_keys(recorder) == {"backups/test-node/live/match1/match1.m3u8"}


def test_non_directory_entries_ignored(sidecar, recorder):
    """Stray files at the watch-dir root are skipped (only app dirs scanned)."""
    from pathlib import Path

    Path(sidecar.WATCH_DIR, "stray.txt").write_text("noise")
    make_stream(sidecar.WATCH_DIR, "live", "match1", num_segments=1)

    sidecar.run_sync_cycle()

    assert s3_keys(recorder) == {
        "backups/test-node/live/match1/match1.mpd",
        "backups/test-node/live/match1/match1-1.m4s",
    }


def test_uploaded_set_pruned_when_segment_deleted(sidecar, recorder):
    """Deleted segments are evicted from the dedup set so it can't grow forever."""
    _manifest, segments = make_stream(
        sidecar.WATCH_DIR, "live", "match1", num_segments=2
    )
    sidecar.run_sync_cycle()
    assert str(segments[0]) in sidecar.uploaded_files

    segments[0].unlink()
    sidecar.run_sync_cycle()

    assert str(segments[0]) not in sidecar.uploaded_files
    assert str(segments[1]) in sidecar.uploaded_files
