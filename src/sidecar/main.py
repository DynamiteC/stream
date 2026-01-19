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
ENDPOINT = os.getenv("S3_ENDPOINT", "https://s3.wasabisys.com")
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
            # Structure: /data/live/[app]/[stream]/...
            # Example: /data/live/live/match1/
            root = Path(WATCH_DIR)
            if not root.exists():
                logger.warning(f"Watch dir {WATCH_DIR} does not exist yet.")
                time.sleep(5)
                continue

            for app_dir in root.iterdir():
                if not app_dir.is_dir(): continue

                for stream_dir in app_dir.iterdir():
                    if not stream_dir.is_dir(): continue

                    stream_key = stream_dir.name
                    # S3 Path: backups/{node_id}/{app}/{stream}/{filename}
                    # We include app_dir.name to be safe

                    # Upload Segments (.m4s)
                    for file_path in stream_dir.glob("*.m4s"):
                        if str(file_path) in uploaded_files:
                            continue

                        s3_key = f"backups/{NODE_ID}/{app_dir.name}/{stream_key}/{file_path.name}"
                        upload_file(file_path, s3_key)
                        uploaded_files.add(str(file_path))

                    # Upload Manifest (.mpd) - Always update
                    # SRS usually names it [stream].mpd, but we use glob to be sure
                    for manifest in stream_dir.glob("*.mpd"):
                        s3_key = f"backups/{NODE_ID}/{app_dir.name}/{stream_key}/{manifest.name}"
                        upload_file(manifest, s3_key)

        except Exception as e:
            logger.error(f"Error in loop: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    sync_loop()
