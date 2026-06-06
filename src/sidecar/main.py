import os
import time
import logging
import boto3
import bisect
import threading
from pathlib import Path
from botocore.exceptions import NoCredentialsError
from concurrent.futures import ThreadPoolExecutor

# Config
STOP_EVENT = threading.Event()
NODE_ID = os.getenv("NODE_ID", "node-unknown")
WATCH_DIR = "/data/live"
BUCKET = os.getenv("S3_BUCKET", "my-bucket")
ENDPOINT = os.getenv("S3_ENDPOINT", "https://s3.example.com")
INTERVAL = int(os.getenv("SYNC_INTERVAL", "30"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Sidecar")

# S3 Client
s3 = None
if not DRY_RUN:
    try:
        s3 = boto3.client(
            's3',
            endpoint_url=ENDPOINT,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
    except Exception as e:
        logger.error(f"Failed to init S3 client: {e}")

import concurrent.futures

uploaded_files = set()

# Global ThreadPoolExecutor to avoid instantiation overhead in loop
executor = ThreadPoolExecutor(max_workers=10)

def upload_file(local_path, s3_key):
    """Upload a file to S3.

    Returns True when the file is safely backed up (or intentionally skipped in
    DRY_RUN), and False when the upload failed and should be retried on a later
    cycle. The caller uses this to decide whether to record the file as
    uploaded.
    """
    try:
        if DRY_RUN:
            logger.info(f"[DRY_RUN] Uploading {local_path} -> {s3_key}")
            return True

        if not s3:
            logger.error(f"S3 client unavailable; cannot upload {local_path}")
            return False

        logger.info(f"Uploading {local_path} -> {s3_key}")
        s3.upload_file(str(local_path), BUCKET, s3_key)
        return True
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return False

def run_sync_cycle():
    try:
        # Structure: SRS outputs to /data/live/[app]/[stream].mpd
        # Standard config: [app] is usually "live"
        # So files are at: /data/live/live/streamkey.mpd

        root = Path(WATCH_DIR)
        if not root.exists():
            logger.warning(f"Watch dir {WATCH_DIR} does not exist yet.")
            time.sleep(5)
            return


        current_cycle_files = set()

        # Prune uploaded_files set to only include files that currently exist
        # This prevents the set from growing indefinitely. Covers both DASH
        # (.m4s) and HLS (.ts) segments so HLS entries aren't dropped and then
        # needlessly re-uploaded each cycle.
        existing_files = {str(p) for p in root.glob("**/*.m4s")}
        existing_files |= {str(p) for p in root.glob("**/*.ts")}
        uploaded_files.intersection_update(existing_files)

        futures = []
        # (segment_path, future) pairs so we can record a segment as uploaded
        # only after its upload has actually succeeded.
        segment_futures = []

        # Map each manifest type to the segment extension it owns. SRS emits
        # DASH (.mpd + .m4s) and HLS (.m3u8 + .ts); a manifest must only claim
        # segments of its own packaging format.
        MANIFEST_SEGMENT_EXT = {".mpd": ".m4s", ".m3u8": ".ts"}

        for app_dir in root.iterdir():
            if not app_dir.is_dir(): continue

            app_name = app_dir.name

            # Optimize: Read directory once and separate files to avoid O(N^2) scanning
            manifests = []
            # Segments are kept in separate buckets per extension so DASH and
            # HLS sort/search independently.
            segments_by_ext = {ext: [] for ext in MANIFEST_SEGMENT_EXT.values()}
            with os.scandir(app_dir) as it:
                for entry in it:
                    if entry.name.endswith('.mpd') or entry.name.endswith('.m3u8'):
                        manifests.append(Path(entry.path))
                    elif entry.name.endswith('.m4s'):
                        p = Path(entry.path)
                        segments_by_ext['.m4s'].append(p)
                        current_cycle_files.add(str(p))
                    elif entry.name.endswith('.ts'):
                        p = Path(entry.path)
                        segments_by_ext['.ts'].append(p)
                        current_cycle_files.add(str(p))

            # Sort each bucket by name to enable binary search, and pre-compute
            # the parallel list of names bisect operates on.
            sorted_segments = {}
            for ext, segs in segments_by_ext.items():
                segs.sort(key=lambda x: x.name)
                sorted_segments[ext] = (segs, [s.name for s in segs])

            # 1. Find Manifests to identify active streams
            for manifest in manifests:
                stream_key = manifest.stem # filename without extension

                # Upload Manifest
                s3_key_manifest = f"backups/{NODE_ID}/{app_name}/{stream_key}/{manifest.name}"
                futures.append(executor.submit(upload_file, manifest, s3_key_manifest))

                # 2. Find related segments for this stream, scoped to the
                # packaging format of this manifest.
                # SRS names them: [stream]-[seq].m4s (DASH) / [stream]-[seq].ts (HLS)
                segments, segment_names = sorted_segments[MANIFEST_SEGMENT_EXT[manifest.suffix]]
                prefix = f"{stream_key}-"

                # Use bisect to find the start index of segments matching the prefix
                start_idx = bisect.bisect_left(segment_names, prefix)

                # Iterate from the start index and stop when prefix no longer matches
                for i in range(start_idx, len(segments)):
                    segment = segments[i]
                    if not segment.name.startswith(prefix):
                        break

                    if str(segment) in uploaded_files:
                        continue

                    s3_key_seg = f"backups/{NODE_ID}/{app_name}/{stream_key}/{segment.name}"
                    fut = executor.submit(upload_file, segment, s3_key_seg)
                    futures.append(fut)
                    segment_futures.append((str(segment), fut))

        # Wait for all uploads in this cycle to finish
        if futures:
            concurrent.futures.wait(futures)

        # Mark segments as uploaded only after a successful upload, so a
        # transient S3 failure is retried on the next cycle instead of being
        # silently skipped forever.
        for seg_path, fut in segment_futures:
            try:
                if fut.result():
                    uploaded_files.add(seg_path)
            except Exception as e:
                # upload_file swallows its own errors and returns False, so this
                # is purely defensive; a raised error means "not uploaded".
                logger.error(f"Upload task errored for {seg_path}: {e}")

        # Prune uploaded_files set to only include files that currently exist
        uploaded_files.intersection_update(current_cycle_files)

    except Exception as e:
        logger.error(f"Error in loop: {e}")

def sync_loop():
    logger.info(f"Sidecar started for Node: {NODE_ID}. Watching {WATCH_DIR} (DRY_RUN={DRY_RUN})")

    while not STOP_EVENT.is_set():
        run_sync_cycle()
        STOP_EVENT.wait(INTERVAL)

if __name__ == "__main__":
    sync_loop()
