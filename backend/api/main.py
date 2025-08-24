import os, time, asyncio, random
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from prometheus_client import Counter, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

from services.notifier import Notifier
from services.db import init_db, save_alert, get_alerts_db, save_zone, get_zone, DB_OK, save_homography, get_homography
from services.heatmap import HeatmapAggregator
from services.discovery import onvif_discover
from services.health import camera_health
from services.auth import require_write, maybe_require_oidc
from services.clipper import generate_clip_precise, upload_clip_and_gif

load_dotenv()

MODE = os.getenv("MODE", "mock")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
PROM_ENABLED = os.getenv("PROMETHEUS_ENABLED","true").lower() == "true"
ENABLE_NOTIFICATIONS = os.getenv("ENABLE_NOTIFICATIONS","true").lower() == "true"
HLS_OUTPUT_DIR = os.getenv("HLS_OUTPUT_DIR", "/app/hls")

app = FastAPI(title="Sentinel Vision AI API", version="0.7.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# Serve HLS
os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
app.mount("/hls", StaticFiles(directory=HLS_OUTPUT_DIR), name="hls")

# In-memory camera store
CAMERAS: Dict[str, Dict[str, Any]] = {}
ALERTS_CACHE: List[Dict[str, Any]] = []

# Models
class Camera(BaseModel):
    name: str
    rtsp_url: Optional[str] = None
    location: Optional[str] = None
    tags: Optional[List[str]] = None

class CameraOut(Camera):
    id: str

class Alert(BaseModel):
    type: str
    camera_id: str
    confidence: float
    message: str
    ts: float

class Zone(BaseModel):
    camera_id: str
    polygon: List[List[float]]

class HomographyIn(BaseModel):
    camera_id: str
    src: List[List[float]]
    dst: List[List[float]]

class DetectionIn(BaseModel):
    camera_id: str
    ts: float
    persons: List[List[float]]

# metrics
REG = CollectorRegistry()
ALERTS_TOTAL = Counter("alerts_total","Total alerts emitted",["type"], registry=REG)
WS_CLIENTS = Gauge("ws_clients","Active websocket clients", registry=REG)
LAST_ALERT_TS = Gauge("last_alert_ts","Unix timestamp of last alert", registry=REG)
PERSON_COUNT = Gauge("person_count","People count per camera", ["camera_id"], registry=REG)
DEDUPED_ALERTS = Counter("deduped_alerts_total","Alerts suppressed by dedupe", registry=REG)
CLIP_UPLOADS = Counter("clip_uploads_total","Clips uploaded", registry=REG)
CLIP_FAILURES = Counter("clip_failures_total","Clip creations that failed", registry=REG)
CORR_GROUPS = Counter("alert_correlation_groups_total","Correlation summaries posted", registry=REG)

@app.get("/metrics")
def metrics():
    if not PROM_ENABLED: return Response("metrics disabled", media_type="text/plain")
    return Response(content=generate_latest(REG), media_type=CONTENT_TYPE_LATEST)

notifier = Notifier(enabled=ENABLE_NOTIFICATIONS)
heatmaps = HeatmapAggregator()

# WebSocket manager
class ConnectionManager:
    def __init__(self) -> None: self.active: List[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.active.append(ws); WS_CLIENTS.set(len(self.active))
    def disconnect(self, ws: WebSocket):
        if ws in self.active: self.active.remove(ws); WS_CLIENTS.set(len(self.active))
    async def broadcast(self, data: Dict[str, Any]):
        alive = []
        for ws in self.active:
            try: await ws.send_json(data); alive.append(ws)
            except Exception: pass
        self.active = alive; WS_CLIENTS.set(len(self.active))

manager = ConnectionManager()

@app.on_event("startup")
async def on_startup():
    init_db()
    if MODE == "mock": asyncio.create_task(mock_alerts())

@app.get("/health")
def health():
    return {"status": "ok", "mode": MODE, "prometheus": PROM_ENABLED, "db": DB_OK()}

# --- Cameras ---
@app.get("/cameras", response_model=List[CameraOut])
def list_cameras():
    return [dict(id=k, **v) for k, v in CAMERAS.items()]

@app.post("/cameras", response_model=CameraOut, dependencies=[Depends(require_write)])
async def add_camera(cam: Camera, request: Request):
    await maybe_require_oidc(request)
    cam_id = f"cam_{len(CAMERAS)+1}"
    CAMERAS[cam_id] = cam.model_dump()
    return dict(id=cam_id, **cam.model_dump())

@app.get("/cameras/discover", dependencies=[Depends(require_write)])
async def discover(request: Request):
    await maybe_require_oidc(request)
    return {"devices": onvif_discover()}

@app.get("/cameras/health")
def cams_health():
    return camera_health(CAMERAS)

# --- Zones (ROI) ---
@app.get("/zones/{camera_id}", response_model=Optional[Zone])
def get_zone_api(camera_id: str):
    z = get_zone(camera_id)
    return z

@app.put("/zones/{camera_id}", dependencies=[Depends(require_write)])
async def put_zone_api(camera_id: str, zone: Zone, request: Request):
    await maybe_require_oidc(request)
    if zone.camera_id != camera_id:
        raise HTTPException(400, "camera_id mismatch")
    save_zone(zone.model_dump())
    return {"ok": True}

# --- Homography ---
@app.get("/calibration/{camera_id}")
def get_h_api(camera_id: str):
    return get_homography(camera_id) or {}

@app.put("/calibration/{camera_id}", dependencies=[Depends(require_write)])
async def put_h_api(camera_id: str, payload: HomographyIn, request: Request):
    await maybe_require_oidc(request)
    if payload.camera_id != camera_id: raise HTTPException(400, "camera_id mismatch")
    save_homography(payload.model_dump())
    return {"ok": True}

# --- Alerts ---
@app.get("/alerts", response_model=List[Alert])
def list_alerts(limit: int = 100):
    if DB_OK():
        return get_alerts_db(limit)
    return ALERTS_CACHE[-limit:]

@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await asyncio.sleep(60)
    except WebSocketDisconnect: manager.disconnect(ws)

# --- Ingest (from edge agent) ---
@app.post("/ingest/detections", dependencies=[Depends(require_write)])
async def ingest(d: DetectionIn, request: Request):
    await maybe_require_oidc(request)
    PERSON_COUNT.labels(d.camera_id).set(len(d.persons))
    heatmaps.add(d.camera_id, d.persons)
    return {"ok": True}

# --- Heatmap ---
@app.get("/analytics/heatmap/{camera_id}.png")
def heatmap_png(camera_id: str):
    png = heatmaps.to_png(camera_id)
    return Response(content=png, media_type="image/png")

# --- Mock alert generator (demonstrates notify + clip + correlation) ---
async def mock_alerts():
    types = ["gun","knife","intruder","loitering","fight","crowd","distance","distress_audio","fire","ppe","vehicle","fall","line_cross","zone_intrusion"]
    while True:
        await asyncio.sleep(3.0)
        if not CAMERAS:
            CAMERAS["cam_1"] = {"name": "Demo Cam 1", "rtsp_url": None, "location": "Demo"}
            CAMERAS["cam_2"] = {"name": "Demo Cam 2", "rtsp_url": None, "location": "Demo"}
        cam_id = random.choice(list(CAMERAS.keys()))
        a = Alert(type=random.choice(types), camera_id=cam_id, confidence=round(random.uniform(0.55,0.98),2), message="Auto-generated demo alert", ts=time.time())
        sent, thread_ts, corr_posted = notifier.maybe_send_with_blocks(a.model_dump())
        if not sent:
            DEDUPED_ALERTS.inc()
            continue
        if corr_posted:
            CORR_GROUPS.inc()
        ALERTS_CACHE.append(a.model_dump())
        ALERTS_TOTAL.labels(a.type).inc(); LAST_ALERT_TS.set(a.ts)
        save_alert(a.model_dump())
        await manager.broadcast({"event": "alert", "payload": a.model_dump()})
        # Clip + GIF
        try:
            clip_path = generate_clip_precise(camera_id=cam_id, seconds=6)
            if clip_path:
                urls = upload_clip_and_gif(camera_id=cam_id, clip_path=clip_path, seconds=6)
                notifier.post_thread_message_blocks(urls, thread_ts=thread_ts)
                CLIP_UPLOADS.inc()
        except Exception as e:
            print("clip failed:", e); CLIP_FAILURES.inc()
