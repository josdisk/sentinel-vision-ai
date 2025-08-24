# Sentinel Vision AI — v7

**What’s new in v7**
- **Precise HLS clip stitching**: parses the camera playlist, stitches the most recent `.ts` segments to an MP4 for an exact time window (fallback to stream trim), plus optional **GIF preview**.
- **Slack blocks + correlation**: rich Slack messages with per‑alert blocks; de‑dup remains, and we also **correlate** same‑type alerts across cameras within a time window and post a summary in the thread.
- **S3 lifecycle**: MinIO bucket now configured with a lifecycle policy to expire clips (default 7 days) in dev.
- **Prometheus**: new `alert_correlation_groups_total` counter; Grafana updated.
- **Tracker interface**: edge tracker can be swapped to **OC‑SORT/ByteTrack** if you install the libs; centroid tracker remains default.

Everything else from v6 stays: edge agent, heatmaps, OIDC/Auth, homography, Grafana/Alertmanager, MinIO clips, etc.

## Run
```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build
```
Then visit UI, API docs, Metrics, and MinIO console as in v6.

## Optional: use a different tracker
Implement `update(boxes_px)` returning `[x1,y1,x2,y2,track_id]` and place it under `edge_agent/tracker_plugins/your_tracker.py`, set `TRACKER_IMPL=your_tracker` in the agent env.
