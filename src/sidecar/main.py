import os
import time
import logging
import boto3
from pathlib import Path
from botocore.exceptions import NoCredentialsError

# Config
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

uploaded_files = set()

def upload_file(local_path, s3_key):
    try:
        if DRY_RUN:
            logger.info(f"[DRY_RUN] Uploading {local_path} -> {s3_key}")
            return

        if s3:
            logger.info(f"Uploading {local_path} -> {s3_key}")
            s3.upload_file(str(local_path), BUCKET, s3_key)
    except Exception as e:
        logger.error(f"Upload failed: {e}")

def sync_loop():
    logger.info(f"Sidecar started for Node: {NODE_ID}. Watching {WATCH_DIR} (DRY_RUN={DRY_RUN})")

    while True:
        try:
            # Structure: SRS outputs to /data/live/[app]/[stream].mpd
            # Standard config: [app] is usually "live"
            # So files are at: /data/live/live/streamkey.mpd

            root = Path(WATCH_DIR)
            if not root.exists():
                logger.warning(f"Watch dir {WATCH_DIR} does not exist yet.")
                time.sleep(5)
                continue

            # Prune uploaded_files set to only include files that currently exist
            # This prevents the set from growing indefinitely.
            existing_files = {str(p) for p in root.glob("**/*.m4s")}
            uploaded_files.intersection_update(existing_files)

            for app_dir in root.iterdir():
                if not app_dir.is_dir(): continue

                app_name = app_dir.name

                # Iterate FILES in the app directory (e.g. /data/live/live/*.m4s)
                # SRS DASH structure: [stream].mpd and [stream]-[seq].m4s are in the same folder

                # 1. Find Manifests to identify active streams
                for manifest in app_dir.glob("*.mpd"):
                    stream_key = manifest.stem # filename without extension

                    # Upload Manifest
                    s3_key_mpd = f"backups/{NODE_ID}/{app_name}/{stream_key}/{manifest.name}"
                    upload_file(manifest, s3_key_mpd)

                    # 2. Find related segments for this stream
                    # SRS usually names them: [stream]-[seq].m4s
                    # We can use glob with the stream_key prefix
                    for segment in app_dir.glob(f"{stream_key}-*.m4s"):
                        if str(segment) in uploaded_files:
                            continue

                        s3_key_seg = f"backups/{NODE_ID}/{app_name}/{stream_key}/{segment.name}"
                        upload_file(segment, s3_key_seg)
                        uploaded_files.add(str(segment))

        except Exception as e:
            logger.error(f"Error in loop: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    sync_loop()
