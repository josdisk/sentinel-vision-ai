import os, time, requests
from typing import Dict, Any, Tuple, Optional

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK","").strip()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN","").strip()
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID","").strip()
ALERT_DEDUPE_SECONDS = int(os.getenv("ALERT_DEDUPE_SECONDS","60"))
ALERT_CORRELATE_SECONDS = int(os.getenv("ALERT_CORRELATE_SECONDS","60"))
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID","").strip()
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN","").strip()
TWILIO_FROM = os.getenv("TWILIO_FROM","").strip()
ALERT_SMS_TO = os.getenv("ALERT_SMS_TO","").strip()

class Notifier:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.last_sent = {}     # (cam,type) -> ts
        self.threads = {}       # (cam,type) -> ts_id
        self.corr = {}          # type -> { first_ts, cams:set }

    def _should_send(self, alert: Dict[str,Any]) -> bool:
        key = (alert["camera_id"], alert["type"])
        last = self.last_sent.get(key, 0)
        if alert["ts"] - last < ALERT_DEDUPE_SECONDS:
            return False
        self.last_sent[key] = alert["ts"]
        return True

    def maybe_send_with_blocks(self, alert: Dict[str,Any]) -> Tuple[bool, Optional[str], bool]:
        if not self.enabled:
            return (True, None, False)
        # correlation accumulation
        c = self.corr.get(alert["type"])
        now = alert["ts"]
        if not c or now - c["first_ts"] > ALERT_CORRELATE_SECONDS:
            c = {"first_ts": now, "cams": set()}
        c["cams"].add(alert["camera_id"])
        self.corr[alert["type"]] = c
        corr_posted = False

        if not self._should_send(alert):
            # If in same correlation window, and we have a thread, append small update
            thread_ts = self.threads.get((alert["camera_id"], alert["type"]))
            if thread_ts:
                self.post_thread_message(f"Another `{alert['type']}` detected on {alert['camera_id']}.", thread_ts=thread_ts)
            return (False, self.threads.get((alert["camera_id"], alert["type"])), False)

        # Build blocks
        blocks = [
            {"type":"section","text":{"type":"mrkdwn","text":f"*{alert['type'].upper()}* detected on *{alert['camera_id']}*"}},
            {"type":"context","elements":[{"type":"mrkdwn","text":f"Confidence: `{alert['confidence']}` · Time: `{int(alert['ts'])}`"}]}
        ]
        thread_ts = self._post_blocks(blocks)
        if thread_ts:
            self.threads[(alert["camera_id"], alert["type"])] = thread_ts

        # If multiple cameras saw same type within window, post a summary
        c = self.corr.get(alert["type"])
        if c and len(c["cams"]) > 1:
            cams_list = ", ".join(sorted(c["cams"]))
            self.post_thread_message(f"*Correlation:* `{alert['type']}` also seen on: {cams_list}", thread_ts=thread_ts)
            corr_posted = True

        self._sms(alert)
        return (True, thread_ts, corr_posted)

    def post_thread_message(self, text: str, thread_ts: Optional[str] = None):
        if SLACK_BOT_TOKEN and SLACK_CHANNEL_ID and thread_ts:
            try:
                requests.post("https://slack.com/api/chat.postMessage",
                              headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                              data={"channel": SLACK_CHANNEL_ID, "text": text, "thread_ts": thread_ts}, timeout=5)
            except Exception as e:
                print("Slack thread post failed:", e)
        elif SLACK_WEBHOOK:
            try:
                requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=5)
            except Exception as e:
                print("Slack webhook thread fallback failed:", e)

    def post_thread_message_blocks(self, urls: Dict[str,str|None], thread_ts: Optional[str] = None):
        mp4 = urls.get("mp4"); gif = urls.get("gif")
        text = mp4 or gif or ""
        if SLACK_BOT_TOKEN and SLACK_CHANNEL_ID and thread_ts:
            blocks = [{"type":"section","text":{"type":"mrkdwn","text":"*Event clip ready*"}}]
            if gif:
                blocks.append({"type":"image","image_url": gif, "alt_text":"clip"})
            if mp4:
                blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"<{mp4}|Download MP4>"}})
            try:
                requests.post("https://slack.com/api/chat.postMessage",
                              headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}","Content-Type":"application/json"},
                              json={"channel": SLACK_CHANNEL_ID, "blocks": blocks, "thread_ts": thread_ts}, timeout=5)
            except Exception as e:
                print("Slack blocks thread post failed:", e)
        else:
            self.post_thread_message(f"Clip: {text}", thread_ts=thread_ts)

    def _post_blocks(self, blocks) -> Optional[str]:
        if SLACK_BOT_TOKEN and SLACK_CHANNEL_ID:
            try:
                r = requests.post("https://slack.com/api/chat.postMessage",
                                  headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}","Content-Type":"application/json"},
                                  json={"channel": SLACK_CHANNEL_ID, "blocks": blocks}, timeout=5)
                data = r.json()
                if data.get("ok"):
                    return data.get("ts")
            except Exception as e:
                print("Slack bot post failed:", e)
        if SLACK_WEBHOOK:
            try:
                requests.post(SLACK_WEBHOOK, json={"blocks": blocks}, timeout=5)
            except Exception as e:
                print("Slack webhook failed:", e)
        return None

    def _sms(self, alert: Dict[str,Any]):
        if TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and ALERT_SMS_TO:
            try:
                auth = (TWILIO_SID, TWILIO_TOKEN)
                data = {"From": TWILIO_FROM, "To": ALERT_SMS_TO, "Body": f"{alert['type']} at {alert['camera_id']}"}
                url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
                requests.post(url, data=data, auth=auth, timeout=5)
            except Exception as e:
                print("Twilio notify failed:", e)
