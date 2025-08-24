import os, time, json
import cv2
import numpy as np
import requests

BACKEND=os.getenv("BACKEND_URL","http://backend:8000")
API_KEY=os.getenv("API_KEY","changeme")
MODEL_PATH=os.getenv("AGENT_MODEL_PATH","")
CAMERA_ID=os.getenv("CAMERA_ID","cam_1")
VIDEO_PATH=os.getenv("VIDEO_PATH","/samples/demo.mp4")
TRACKER_IMPL=os.getenv("TRACKER_IMPL","centroid")  # centroid | ocsort_stub | your_plugin

def load_tracker():
    try:
        mod = __import__(f"tracker_plugins.{TRACKER_IMPL}", fromlist=['Tracker'])
        return mod.Tracker()
    except Exception as e:
        print("tracker load failed; using centroid:", e)
        from tracker_plugins.centroid import Tracker
        return Tracker()

def mock_person_boxes(frame, t):
  h,w = frame.shape[:2]
  boxes=[]
  for i in range(5):
    x = int((t*5 + i*60) % (w-60))
    y = 120 + int(40*np.sin((t+i)/10))
    boxes.append([x,y,x+40,y+80])
  return boxes

def to_norm(boxes, w, h):
  out=[]
  for b in boxes:
    x1,y1,x2,y2,*rest = b
    norm=[x1/w, y1/h, x2/w, y2/h]
    if rest: norm+=rest
    out.append(norm)
  return out

def main():
  cap = cv2.VideoCapture(VIDEO_PATH)
  if not cap.isOpened():
    print("Failed to open", VIDEO_PATH); return
  tracker = load_tracker()
  t=0
  while True:
    ok, frame = cap.read()
    if not ok:
      cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
    boxes = mock_person_boxes(frame, t)
    tracked = tracker.update(boxes)
    h,w = frame.shape[:2]
    payload = {"camera_id": CAMERA_ID, "ts": time.time(), "persons": to_norm(tracked, w, h)}
    try:
      requests.post(f"{BACKEND}/ingest/detections", json=payload, headers={"X-API-Key": API_KEY}, timeout=2)
    except Exception as e:
      print("post failed:", e)
    t += 1
    time.sleep(0.1)

if __name__ == "__main__":
  main()
