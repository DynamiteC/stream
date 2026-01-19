# Implementation Guide

## 1. System Overview
The system consists of three main codebases:
1.  **Ingest Node (SRS + Nginx + Python Sidecar)**: Deployed on the 50x Bare Metal fleet.
2.  **Control Plane (Go/Node API)**: Central authority.
3.  **Frontend (Video.js)**: Smart player.

---

## 2. Ingest Node Configuration

### A. SRS Configuration (`/etc/srs/srs.conf`)
We use SRS to ingest RTMP and output DASH directly.

```nginx
# SRS Configuration for RTMP -> DASH
listen              1935;
max_connections     1000;
daemon              off;
srs_log_tank        console;

http_server {
    enabled         on;
    listen          8080;
    dir             ./objs/nginx/html;
}

vhost __defaultVhost__ {
    # 1. Auth Hook
    http_hooks {
        enabled         on;
        on_publish      http://api.platform.com/v1/hooks/on_publish;
        on_unpublish    http://api.platform.com/v1/hooks/on_unpublish;
    }

    # 2. DASH Packetizer
    dash {
        enabled         on;
        dash_fragment   10;      # 10s segments
        dash_update_period 150;  # Update manifest every 150s
        dash_path       ./objs/nginx/html/live/[app]/[stream].mpd;
        dash_cleanup    on;      # Clean up old segments (Rolling window)
        dash_window     600;     # Keep last 10 minutes (DVR)
    }
}
```

### B. Nginx Delivery Config (`/etc/nginx/sites-available/live`)
Serves the DASH files with CORS and **Secure Link Authentication**.

```nginx
server {
    listen 80;
    server_name _;
    root /usr/local/srs/objs/nginx/html;

    # CORS for Web Player
    add_header Access-Control-Allow-Origin *;
    add_header Access-Control-Allow-Methods 'GET, HEAD, OPTIONS';

    location /live {
        # Security: Validates the ?token=MD5:EXPIRY query param
        secure_link $arg_token,$arg_expires;
        secure_link_md5 "$secure_link_expires$uri$remote_addr mysecretkey";

        if ($secure_link = "") { return 403; }
        if ($secure_link = "0") { return 410; }

        types {
            application/dash+xml mpd;
            video/iso.segment m4s;
        }
        # Cache DASH segments for 1 year (immutable)
        location ~ \.m4s$ {
            expires 1y;
            add_header Cache-Control "public, max-age=31536000";
        }
        # Cache Manifest for 5 seconds (Live)
        location ~ \.mpd$ {
            expires 5s;
            add_header Cache-Control "public, max-age=5";
        }
    }
}
```

### C. The "S3 Syncer" Sidecar (Python)
Runs as a systemd service. Checks for new segments and uploads.

```python
import os
import time
import boto3
from pathlib import Path

WATCH_DIR = "/usr/local/srs/objs/nginx/html/live"
BUCKET = "my-streaming-bucket"
# Upload every 5 minutes
INTERVAL = 300

s3 = boto3.client('s3', endpoint_url='https://s3.wasabisys.com')

def sync_loop():
    while True:
        print("Starting Sync...")
        for app_dir in Path(WATCH_DIR).iterdir():
            if not app_dir.is_dir(): continue

            for stream_dir in app_dir.iterdir(): # e.g. /live/app/stream/
                 # Find all .m4s segments
                 segments = list(stream_dir.glob("*.m4s"))
                 # Find manifest
                 manifest = stream_dir / "index.mpd"

                 # Upload Logic (Simplified)
                 for seg in segments:
                     # Check if uploaded recently (store state in Redis or local DB)
                     # if not uploaded:
                     #    s3.upload_file(str(seg), BUCKET, f"backup/{app_dir.name}/{seg.name}")
                     pass

        time.sleep(INTERVAL)

if __name__ == "__main__":
    sync_loop()
```

---

## 3. Security & Analytics Logic

### A. Signed URL Generation (Control Plane)
Before a player can watch, they request a token from the API.

```python
import hashlib
import time
import base64

SECRET = "mysecretkey"

def generate_signed_url(path, client_ip):
    # Expiry: 3 hours from now
    expires = int(time.time()) + 10800

    # String to Sign: expires + path + client_ip + secret
    # Matches Nginx secure_link_md5 "$secure_link_expires$uri$remote_addr mysecretkey";
    raw_str = f"{expires}{path}{client_ip} {SECRET}"

    # MD5 Hash -> Base64 (URL Safe)
    md5_hash = hashlib.md5(raw_str.encode('utf-8')).digest()
    token = base64.urlsafe_b64encode(md5_hash).decode('utf-8').replace('=', '')

    return f"https://node-01.platform.com{path}?token={token}&expires={expires}"
```

### B. TimescaleDB Schema (Metrics)
PostgreSQL with Timescale extension for storing billions of data points.

```sql
-- 1. Streams Table (Metadata)
CREATE TABLE streams (
    id SERIAL PRIMARY KEY,
    stream_key VARCHAR(64) UNIQUE NOT NULL,
    user_id INT NOT NULL,
    title VARCHAR(255),
    start_time TIMESTAMP DEFAULT NOW(),
    end_time TIMESTAMP,
    server_node VARCHAR(50) -- e.g. "node-04"
);

-- 2. Viewership Metrics (Hypertable)
CREATE TABLE stream_metrics (
    time TIMESTAMPTZ NOT NULL,
    stream_id INT NOT NULL,
    viewer_count INT NOT NULL,
    bandwidth_mbps DOUBLE PRECISION,
    UNIQUE (time, stream_id)
);

-- Convert to Hypertable (Partition by time)
SELECT create_hypertable('stream_metrics', 'time');

-- Query: Average Viewers per Stream (Last 1 Hour)
SELECT stream_id, AVG(viewer_count)
FROM stream_metrics
WHERE time > NOW() - INTERVAL '1 hour'
GROUP BY stream_id;
```

---

## 4. Dispatcher Logic (Control Plane)

**Goal**: Assign stream to `Node-X` where `CurrentStreams < MaxStreams`.

```go
// Go Pseudocode
func GetIngestNode(streamKey string) (string, error) {
    // 1. Check Redis for existing session
    if node, err := redis.Get("stream_node:" + streamKey); err == nil {
        return node, nil
    }

    // 2. Find best node
    nodes := db.GetActiveNodes()
    var bestNode Node
    minLoad := 9999

    for _, node := range nodes {
        load := redis.Get("node_load:" + node.ID) // e.g. "3" streams
        if load < minLoad && load < MAX_STREAMS_PER_NODE {
            bestNode = node
            minLoad = load
        }
    }

    // 3. Reserve spot
    redis.Incr("node_load:" + bestNode.ID)
    redis.Set("stream_node:" + streamKey, bestNode.IP)

    return "rtmp://" + bestNode.IP + "/live/" + streamKey, nil
}
```

---

## 5. Frontend Overlay (Client-Side)

Using `video.js` and a WebSocket for data.

```html
<div id="player-container" style="position: relative;">
    <video id="my-video" class="video-js"></video>

    <!-- Overlay Layer -->
    <div id="overlay" style="position: absolute; top: 10px; right: 10px; color: white; background: rgba(0,0,0,0.5); padding: 5px;">
        <span id="score">0 - 0</span>
    </div>
</div>

<script>
    var player = videojs('my-video');
    var ws = new WebSocket("wss://api.platform.com/score-stream/match-123");

    ws.onmessage = function(event) {
        var data = JSON.parse(event.data);
        // data = { teamA: 10, teamB: 5, time: "45:00" }
        document.getElementById("score").innerText = data.teamA + " - " + data.teamB;
    };
</script>
```
