"""Capture one explicit native window, never the whole desktop."""
import argparse
import json
from pathlib import Path
import subprocess
import time
p = argparse.ArgumentParser()
p.add_argument('--title', default='BB10 VoLTE - Q10 Demo')
p.add_argument('--seconds', type=float, default=20)
p.add_argument('--out', required=True)
a = p.parse_args()
out = Path(a.out).resolve()
out.parent.mkdir(parents=True, exist_ok=True)
started = time.time()
command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', '-f', 'gdigrab',
           '-framerate', '30', '-draw_mouse', '1', '-i', 'title=' + a.title,
           '-t', str(a.seconds), '-an', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-pix_fmt', 'yuv420p', str(out)]
r = subprocess.run(command)
out.with_suffix('.capture.json').write_text(json.dumps({
    'source': 'native-window-gdigrab', 'title': a.title, 'startedUnix': started,
    'endedUnix': time.time(), 'exitCode': r.returncode, 'targetSeconds': a.seconds,
    'desktopCaptured': False, 'frameRate': 30
}, indent=2), encoding='utf-8')
raise SystemExit(r.returncode)
