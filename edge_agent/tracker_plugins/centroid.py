from math import hypot
import numpy as np

class Tracker:
    def __init__(self, max_lost=10, dist_thresh=80.0):
        self.next_id = 1
        self.tracks = {}  # id -> (cx, cy, lost)
        self.max_lost = max_lost
        self.dist_thresh = dist_thresh

    def update(self, boxes):
        centers = [((x1+x2)/2.0, (y1+y2)/2.0) for x1,y1,x2,y2 in boxes]
        ids = list(self.tracks.keys())
        if not ids:
            for (cx,cy) in centers:
                tid = self.next_id; self.next_id += 1
                self.tracks[tid] = (cx,cy,0)
        else:
            costs = np.full((len(ids), len(centers)), np.inf, dtype=np.float32)
            for i, tid in enumerate(ids):
                cx, cy, _ = self.tracks[tid]
                for j, (ux,uy) in enumerate(centers):
                    costs[i,j] = hypot(cx-ux, cy-uy)
            assigned_tracks = set(); assigned_dets = set()
            for _ in range(min(len(ids), len(centers))):
                i,j = np.unravel_index(np.argmin(costs), costs.shape)
                if np.isinf(costs[i,j]) or costs[i,j] > self.dist_thresh: break
                assigned_tracks.add(ids[i]); assigned_dets.add(j)
                self.tracks[ids[i]] = (centers[j][0], centers[j][1], 0)
                costs[i,:] = np.inf; costs[:,j] = np.inf
            for j in range(len(centers)):
                if j in assigned_dets: continue
                tid = self.next_id; self.next_id += 1
                self.tracks[tid] = (centers[j][0], centers[j][1], 0)
            for tid in list(self.tracks.keys()):
                if tid not in assigned_tracks:
                    cx, cy, lost = self.tracks[tid]
                    self.tracks[tid] = (cx, cy, lost+1)
                if self.tracks[tid][2] > self.max_lost:
                    del self.tracks[tid]
        out=[]
        for tid,(cx,cy,_) in self.tracks.items():
            if centers:
                j = np.argmin([hypot(cx-ux, cy-uy) for (ux,uy) in centers])
                out.append(list(boxes[j]) + [tid])
        return out
