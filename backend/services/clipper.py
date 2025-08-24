import os, subprocess, time, uuid, tempfile, re
from .s3 import upload_file

HLS_DIR = os.getenv("HLS_OUTPUT_DIR","/app/hls")

def _read_playlist(camera_id: str):
    pl = os.path.join(HLS_DIR, camera_id, "index.m3u8")
    if not os.path.exists(pl): return None, None, []
    lines = open(pl, 'r', encoding='utf-8').read().splitlines()
    target = 2
    segs = []
    for i,l in enumerate(lines):
        if l.startswith('#EXT-X-TARGETDURATION:'):
            target = int(float(l.split(':')[1]))
        if l.startswith('#EXTINF:'):
            dur = float(l.split(':')[1].rstrip(','))
            uri = lines[i+1].strip()
            if not uri.startswith('http'):
                uri = os.path.join(HLS_DIR, camera_id, uri)
            segs.append((dur, uri))
    return pl, target, segs

def generate_clip_precise(camera_id: str, seconds: int = 6) -> str | None:
    pl, target, segs = _read_playlist(camera_id)
    if not segs: return None
    # take last N segs totaling at least seconds
    total = 0.0
    selected = []
    for dur, uri in reversed(segs):
        selected.insert(0, (dur, uri))
        total += dur
        if total >= seconds: break
    # concat to .ts then remux to mp4
    with tempfile.TemporaryDirectory() as td:
        concat_path = os.path.join(td, "files.txt")
        with open(concat_path, 'w', encoding='utf-8') as f:
            for _,uri in selected:
                # ffmpeg concat demuxer requires escaped paths
                f.write(f"file '{uri}'\n")
        out_ts = os.path.join(td, "out.ts")
        out_mp4 = f"/tmp/clip_{uuid.uuid4().hex}.mp4"
        try:
            subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",concat_path,"-c","copy",out_ts], check=True)
            subprocess.run(["ffmpeg","-y","-loglevel","error","-i",out_ts,"-c","copy",out_mp4], check=True)
            return out_mp4
        except Exception as e:
            # fallback: stream cut
            out_mp4 = f"/tmp/clip_{uuid.uuid4().hex}.mp4"
            try:
                subprocess.run(["ffmpeg","-y","-loglevel","error","-i",pl,"-t",str(seconds),"-c","copy",out_mp4], check=True)
                return out_mp4
            except Exception as e2:
                print("fallback clip failed:", e2)
                return None

def _generate_gif(in_mp4: str, seconds: int = 6) -> str | None:
    out_gif = in_mp4.replace(".mp4",".gif")
    try:
        subprocess.run(["ffmpeg","-y","-loglevel","error","-i",in_mp4,"-t",str(seconds),
                        "-vf","fps=8,scale=480:-1:flags=lanczos", out_gif], check=True)
        return out_gif
    except Exception as e:
        print("gif gen failed:", e)
        return None

def upload_clip_and_gif(camera_id: str, clip_path: str, seconds: int = 6):
    key_mp4 = f"{camera_id}/{int(time.time())}.mp4"
    url_mp4 = upload_file(clip_path, key_mp4)
    gif_path = _generate_gif(clip_path, seconds=seconds)
    url_gif = None
    if gif_path:
        key_gif = key_mp4.replace(".mp4",".gif")
        url_gif = upload_file(gif_path, key_gif)
    try:
        os.remove(clip_path)
        if gif_path: os.remove(gif_path)
    except: pass
    return {"mp4": url_mp4, "gif": url_gif}
