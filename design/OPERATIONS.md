# Operational Guide: Failure Modes & Scaling

## 1. Failure Scenarios

### A. Ingest Node Crash (The "Micro-Origin" Failure)
*Scenario*: A server hosting 4 cricket matches loses power.
1.  **Immediate Impact**: Viewers on those 4 streams see a freeze.
2.  **Detection**: Control Plane misses 3 heartbeats (10s).
3.  **Failover (Viewer Side)**:
    - Player receives `404 Not Found` or Timeout.
    - Player requests "Recovery URL" from API.
    - API returns the **S3 Backup URL** (delayed by ~5 mins).
    - **Result**: Viewers jump back 5 minutes but can continue watching the "Safe" recording.
4.  **Recovery (Streamer Side)**:
    - OBS/Encoder disconnects.
    - Streamer reconnects.
    - Dispatcher assigns a **new** healthy node.
    - Stream resumes live (New Live Event).

### B. Viral Stream (The "10k Viewer" Problem)
*Scenario*: A local match gets shared by a celebrity. Viewers spike from 50 to 10,000.
1.  **Impact**: The 1Gbps uplink on the Micro-Origin saturates (max ~200-300 viewers).
2.  **Detection**: Node metrics agent reports `NetOut > 800Mbps`.
3.  **Mitigation (Auto-Switch)**:
    - Control Plane updates the API response for *new* viewers: "Go to CDN".
    - Control Plane instructs Player (via SSE/WebSocket) to "Reload from CDN".
    - Traffic shifts from `node-04.platform.com` to `cdn.bunny.net`.
4.  **Cost**: We pay per GB for this event, but the stream stays up.

### C. Database Outage
*Scenario*: Primary Postgres fails.
1.  **Impact**: New streams cannot start. Existing streams continue (SRS/Nginx don't need DB for ongoing playback).
2.  **Mitigation**: Managed Database with Read Replica. Auto-failover (<60s).

---

## 2. Scaling Roadmap

### Phase 1: Pilot (0 - 500 Streams/Week)
- **Fleet**: 5 Bare Metal Servers.
- **Ops**: Manual deployment (Ansible).
- **Goal**: Validate stability of SRS + S3 Sync.

### Phase 2: Growth (500 - 2,000 Streams/Week)
- **Fleet**: 20 Servers.
- **Ops**: Kubernetes on Bare Metal (or Nomad) for easier management.
- **Feature**: Automated "Viral Stream" detection enabled.

### Phase 3: Target (8,000 Streams/Week)
- **Fleet**: 50+ Servers.
- **Ops**: Fully automated dispatcher.
- **Feature**: Multi-region/Geographic routing (Assign users to nearest node if we have nodes in multiple data centers).

---

## 3. Disaster Recovery (DR)

### "The Datacenter Fire"
If the entire Hetzner/OVH region goes dark:
1.  **Live Streams**: All cut.
2.  **Recovery**:
    - Spin up emergency capacity in AWS (EC2 Spot Instances).
    - *Costly*, but saves the event.
    - Update DNS to point to AWS.
3.  **VOD**: Safe in Wasabi/S3 (Different provider than compute).

---

## 4. Monitoring Checklist
*Tools: Prometheus (Node Exporter) + Grafana*

1.  **Bandwidth Utilization**: Alert at >800Mbps per node.
2.  **Disk Usage**: Alert at >80% (SRS segments filling up).
3.  **Stream Health**: Track `on_publish` vs `on_unpublish` to detect frequent disconnects (instability).
4.  **Upload Lag**: Monitor `last_s3_sync_time`. If >10 mins, alert (Backup broken).
