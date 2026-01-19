# Cost Analysis & Capacity Planning

## 1. Traffic Modeling

### Assumptions
- **Streams**: 8,000 per week.
- **Duration**: 2 hours per stream.
- **Bitrate**: 4 Mbps (Source Quality 1080p/720p average).
- **Concurrency Scenario**:
  - **Interpretation A (Aggressive)**: 100 *Concurrent* Viewers.
    - Peak Bandwidth: 500 streams * 100 viewers * 4 Mbps = **200 Gbps**.
  - **Interpretation B (Realistic)**: 100 *Unique* Viewers, 20 min avg watch time.
    - Concurrent = `100 * (20/120)` = ~17 viewers/stream.
    - Peak Bandwidth: 500 streams * 17 viewers * 4 Mbps = **34 Gbps**.

**Budget Verdict**: To fit the **$4,000** limit, we must design for **Interpretation B** (34 Gbps). If traffic hits 200 Gbps, the bandwidth bill alone would exceed $4k on almost any provider except bare-metal bulk deals.

---

## 2. Infrastructure Costs (The "Micro-Origin" Fleet)

We need to sustain ~35 Gbps of egress.
Standard Cloud (AWS/GCP) cost: 35 Gbps * 730h * $0.08/GB = **Bankruptcy**.
**Solution**: Unmetered Bare Metal (Hetzner/OVH/Leaseweb).

### The "Worker" Node Spec
- **Hardware**: Entry-level Dedicated or High-End VPS.
  - CPU: 4-8 vCPU (Enough for SRS packetizing, no transcoding).
  - RAM: 16GB (RAM Buffer for Hot Cache).
  - Network: **1 Gbps Unmetered**.
- **Unit Cost**: ~$40 - $50 / month.
- **Capacity per Node**:
  - Safe limit: 700 Mbps egress (keep overhead).
  - 4 Mbps streams supportable: ~175 viewers total per server.
  - At 17 viewers/stream, one server handles ~10 concurrent streams.

### Fleet Size Calculation
- **Peak Load**: 34 Gbps.
- **Nodes Needed**: 34 Gbps / 0.7 Gbps = **49 Servers**.
- **Cost**: 49 * $45 = **$2,205 / month**.

---

## 3. Storage Costs (S3 / R2 / Wasabi)

### Volume Generated
- 8,000 streams * 2 hrs * 1.8 GB/hr = **28.8 TB / week**.
- **Monthly Ingest**: ~115 TB.

### Retention Strategy (Cost Critical)
- **Policy**: Delete recordings after 7 days (unless flagged "Keep").
- **Active Storage**: ~30 TB constant usage.

### Provider Comparison
- **AWS S3 Standard**: $0.023/GB * 30,000 = $690/month (plus egress fees!).
- **Cloudflare R2**: $0.015/GB * 30,000 = $450/month (Zero Egress).
- **Wasabi**: $0.0069/GB * 30,000 = **$207/month** (Zero Egress).

**Selection**: **Wasabi or R2**. Let's budget **$250** for storage + API requests.

---

## 4. Control Plane & Misc

- **Control Server**: 1x Reliable Cloud Instance (AWS t3.medium or DigitalOcean).
  - Cost: **$40/month**.
- **Database (Managed)**: 1x Managed Postgres/Timescale.
  - Cost: **$100/month**.
- **Load Balancer / DNS**: Cloudflare Free/Pro.
  - Cost: **$20/month**.

---

## 5. Total Budget Rollup

| Item | Qty | Unit Cost | Total | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Micro-Origin Fleet** | 50 | $45 | **$2,250** | Hetzner AX41 or similar |
| **Storage (Wasabi)** | 30TB | $0.006/GB | **$250** | 7-day retention |
| **Control Plane** | 1 | $150 | **$150** | API + DB |
| **Spare/Buffer** | - | - | **$350** | Unexpected overages |
| **TOTAL** | | | **$3,000** | **Under $4,000 Cap** |

---

## 6. Scaling Triggers (The "Viral" Danger)

If a single stream goes viral (>500 concurrent viewers):
- It **will** saturate the 1Gbps link of its host node.
- **Mitigation**: The "Dispatcher" detects >400 viewers and switches the DNS/Manifest to **BunnyCDN** (Volume Tier).
- **Cost Impact**:
  - 1 Viral Event: 2,000 viewers * 2 hours * 1.8GB = 7,200 GB.
  - BunnyCDN cost ($0.01/GB): **$72**.
  - **Verdict**: We can afford ~10-15 major "viral events" per month within the remaining $1,000 buffer.

## 7. Operational Efficiency
- **Transcoding**: $0 (Source Passthrough).
- **Egress**: Flat rate (Server rental).
- **Storage**: Capped by 7-day lifecycle.

This model is the **only** way to hit the $4,000 target with 300TB+ of traffic.
