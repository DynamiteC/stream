# Micro-Origin Node Setup

This repository contains the configuration and code to run a **Micro-Origin Node** for the live streaming platform.

## Prerequisites
- Docker & Docker Compose
- An OBS client (to push stream)
- A Video Player (VLC or Web) to watch

## Quick Start

1. **Configure Identity**
   Copy the example environment file and edit it.
   ```bash
   cp .env.example .env
   # Edit .env to set NODE_ID and AWS Credentials
   ```

2. **Start the Node**
   ```bash
   docker-compose up -d --build
   ```

3. **Push a Stream**
   Open OBS and stream to:
   - **Server**: `rtmp://localhost/live`
   - **Key**: `match1`

4. **Watch the Stream**
   Open VLC or a DASH Player and open:
   - URL: `http://localhost/live/live/match1.mpd`

## Architecture
- **SRS (Port 1935)**: Ingests RTMP, converts to DASH segments in shared volume.
- **Nginx (Port 80)**: Serves the DASH segments from the shared volume.
- **Sidecar**: Watches the volume and uploads backups to S3 (logs only in this demo).

## Logs
To see the sidecar backup activity:
```bash
docker-compose logs -f sidecar
```
