# Architecture Design: Distributed Micro-Origin Streaming Platform

## 1. High-Level Concept: "The Sharded Micro-Origin"

Instead of a monolithic cluster, the system uses a fleet of cost-effective **Micro-Origin Nodes**. Each node is responsible for the full lifecycle of a small number of streams (e.g., 2-4 concurrent cricket matches). This minimizes the "blast radius" of a failure—if one server crashes, only those specific matches are affected, not the entire platform.

### Core Philosophy
- **Decentralized Ingest**: Streams are intelligently routed to the least-loaded node.
- **Source-Quality Live**: No server-side transcoding for live. We pass through the source quality (e.g., 1080p/720p) to keep latency low and compute costs near zero.
- **Client-Side Intelligence**: The web player handles overlays (graphics) and failover logic.
- **Hybrid Storage**: Hot content lives in RAM/SSD on the edge; Safe content lives in S3.

---

## 2. Component Architecture

### A. The Control Plane (Central Brain)
*Hosted on a reliable cloud provider (e.g., AWS, DigitalOcean, Hetzner Cloud).*
- **API Server (Go/Node.js)**:
  - Authenticates users and streamers.
  - **The Dispatcher**: Assigns an incoming stream to a specific Micro-Origin Node based on load/health.
- **Database (PostgreSQL)**: Stores stream metadata, user info, and active node status.
- **State Store (Redis)**: Tracks real-time active streams and node heartbeats.

### B. The Micro-Origin Nodes (The Workers)
*Hosted on Bare Metal or High-Bandwidth VPS (e.g., Hetzner AX line, OVH).*
- **Ingest Engine (SRS - Simple Realtime Server)**:
  - Accepts RTMP push.
  - Slices stream into DASH Segments (10s duration).
  - Maintains a sliding window "Hot Cache" (e.g., last 2 minutes).
- **Delivery Server (Nginx)**:
  - Serves DASH manifests (`.mpd`) and segments (`.m4s`) directly to viewers.
  - Handles CORS and basic token validation.
- **The "S3 Syncer" (Sidecar Agent)**:
  - Monitors the segment directory.
  - Every 5 minutes (or on segment completion), uploads batches of segments to S3.
  - Ensures data is durable.

### C. The Frontend (Client)
- **Player (Video.js / Dash.js)**:
  - Connects to Control Plane to get the active Stream URL.
  - **Overlay Engine**: Fetches match data (Score, Timer) via WebSocket/SSE and renders HTML/CSS overlays on top of the `<video>` element.
  - **Failover Logic**: If the Micro-Origin returns 404/500, the player asks the Control Plane for a backup URL (e.g., S3 VOD or Backup Node).

---

## 3. Data Flow Diagrams

### Live Stream Workflow
1. **Assignment**: Camera/Encoder requests ingest URL. Dispatcher selects `Node-04` (low load).
2. **Ingest**: Camera pushes RTMP to `rtmp://node-04.platform.com/live/{key}`.
3. **Packaging**: SRS on `Node-04` transmuxes RTMP -> DASH (10s chunks).
4. **Hot Serve**:
   - Viewers 1-200 connect directly to `https://node-04.platform.com/live/{key}.mpd`.
   - Latency: ~12-15s (10s segment + buffer).
5. **Backup**: `S3 Syncer` on `Node-04` uploads chunks to `s3://bucket/archive/{key}/` every 5 mins.

### VOD / Post-Match Workflow
1. **Completion**: Stream ends. SRS triggers `on_unpublish` hook.
2. **Final Sync**: `S3 Syncer` pushes remaining segments and a "VOD Manifest" to S3.
3. **Processing (Optional)**: If transcode is needed for VOD (e.g., 360p mobile version), a separate worker pulls from S3, transcodes, and re-uploads.
4. **Playback**: Users watch the replay served via CloudFront (pointing to S3).

### Viral Stream Workflow (Overflow)
*If a stream exceeds node capacity (e.g., >500 viewers)*
1. **Detection**: `Node-04` reports high CPU/Bandwidth to Control Plane.
2. **Switch**: Control Plane updates the "Active Stream URL" to point to a CDN (e.g., BunnyCDN/CloudFront).
3. **Pull**: CDN pulls the stream from `Node-04` and caches it globally.
4. **Scale**: Unlimited viewers can now watch via CDN.

---

## 4. Tech Stack Selection

| Component | Technology | Reasoning |
| :--- | :--- | :--- |
| **Ingest/Packetizer** | **SRS (Simple Realtime Server)** | Extremely efficient, low latency, native DASH support, easy HTTP callbacks. Better performance than Nginx-RTMP. |
| **Web Server** | **Nginx** | Battle-tested for static file serving (DASH chunks), caching, and SSL termination. |
| **Database** | **PostgreSQL + TimescaleDB** | Robust metadata + efficient time-series storage for analytics (view counts, bandwidth). |
| **Object Storage** | **AWS S3 (or R2/Wasabi)** | Durable, infinite storage. Tiers allow cost optimization (Standard -> Glacier). |
| **CDN (Overflow)** | **BunnyCDN** (Volume) | significantly cheaper than CloudFront ($0.01/GB vs $0.08/GB) for viral offload. |
| **Compute** | **Hetzner AX / OVH** | Unmetered/High-bandwidth bare metal. Essential for the "0.001/GB" budget goal. |

---

## 5. Overlay Implementation (Client-Side)

Instead of burning pixels on the server (expensive, high latency):
1. **Data Source**: A scoring admin panel pushes updates (e.g., "Score: 10-2") to the Control Plane.
2. **Distribution**: Control Plane pushes this data via **Server-Sent Events (SSE)** or **WebSocket** to all connected clients on that stream channel.
3. **Rendering**: The web page has a transparent `<div>` absolutely positioned over the `<video>`. JavaScript updates the text/graphics in real-time.
4. **Sync**: Timestamps in the data stream match the video clock to ensure the score updates exactly when the event happens (optional advanced sync).

## 6. S3 Backup Strategy (The "5-Minute" Rule)

To balance safety and cost:
- We do **not** upload every segment immediately (too many PUT requests).
- **The Logic**:
    - Accumulate segments in a local `/tmp/buffer` folder.
    - Every 5 minutes, the `S3 Syncer` script runs.
    - It uploads all new `.m4s` files.
    - It updates the backup `.mpd` on S3.
- **Risk**: If a server explodes completely, we lose the last <5 minutes of data. This is an acceptable tradeoff for the cost savings on 8000 streams.
