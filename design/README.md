# Live Streaming Platform Design

**Target Scale:** 8,000 Streams/Week | **Budget:** <$4,000/Mo | **Latency:** ~12s

## Executive Summary
This architecture achieves the aggressive cost target ($0.001/GB effective) by avoiding standard Cloud CDNs for the bulk of traffic. Instead, it utilizes a fleet of unmetered **Bare Metal Micro-Origins**.

We utilize a **"Source-Passthrough"** strategy for live streaming to eliminate transcoding costs, and a **"Client-Side Overlay"** approach to handle graphics without server-side processing.

## Documentation Index

1.  [**Architecture Overview**](./ARCHITECTURE.md)
    *   The "Sharded Micro-Origin" concept.
    *   Data flow for Live, VOD, and Overlays.
    *   Tech Stack: SRS, Nginx, Python Sidecar, Video.js.

2.  [**Cost Analysis**](./COST_ANALYSIS.md)
    *   Detailed budget breakdown showing how we hit the <$4,000 limit.
    *   Comparison of Bare Metal vs. Cloud.
    *   Storage cost optimization with Wasabi/R2.

3.  [**Implementation Guide**](./IMPLEMENTATION.md)
    *   Configuration for SRS (Simple Realtime Server).
    *   Nginx Caching rules.
    *   **Python Code**: The S3 Backup Sidecar.
    *   **JavaScript Code**: The Client-Side Overlay player.

4.  [**Operations & Scaling**](./OPERATIONS.md)
    *   Handling "Viral Streams" (Overflow to CDN).
    *   Disaster Recovery (Node Failure).
    *   Monitoring Checklist.

## Quick Specs
*   **Ingest Protocol**: RTMP
*   **Delivery Protocol**: DASH (Live), HLS/DASH (VOD)
*   **Segment Duration**: 10 seconds
*   **Live Storage**: RAM/SSD Buffer (Edge)
*   **Backup Storage**: S3/Wasabi (Async 5-min batches)
*   **Transcoding**: None (Live Passthrough) / Optional (Post-Event)

## Critical Constraints Solved
*   **Bandwidth Cost**: Solved via fixed-price unmetered bare metal servers (Hetzner/OVH).
*   **Compute Cost**: Solved by removing live transcoding and moving overlays to the client.
*   **Fault Tolerance**: Solved by sharding streams (2-4 per server); one server crash only affects those specific matches.
