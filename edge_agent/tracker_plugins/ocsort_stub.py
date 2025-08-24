# Stub wrapper; replace with real OC-SORT import when installed.
# Must provide class Tracker with update(boxes_px)->[x1,y1,x2,y2,track_id]
class Tracker:
    def __init__(self, *args, **kwargs):
        pass
    def update(self, boxes):
        # passthrough with fake IDs
        return [b+[i+1] for i,b in enumerate(boxes)]
