"""Reproducible native-window takes of each fully rendered tutorial state."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--scenes', default='home,connect,root,root-import,root-prepared,root-verified,install,restart,ready,feedback')
parser.add_argument('--seconds', type=float, default=6)
args = parser.parse_args()
output = ROOT / 'docs/recordings/first-use-raw'
output.mkdir(parents=True, exist_ok=True)
images = ROOT / 'website/src/assets/tutorial'
images.mkdir(parents=True, exist_ok=True)
reports = []
for scene in args.scenes.split(','):
    if scene not in ('home', 'connect', 'root', 'root-import', 'root-prepared', 'root-verified', 'install', 'restart', 'ready', 'feedback'):
        raise ValueError('Unknown scene')
    marker = output / (scene + '.ready.json')
    if marker.exists():
        marker.unlink()
    with (output / (scene + '.stderr.txt')).open('w', encoding='utf-8') as errors:
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/recordings/launch-first-use.py'),
                                    '--scene', scene, '--ready-file', str(marker)],
                                   cwd=ROOT, stdout=subprocess.DEVNULL, stderr=errors,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 20
            while not marker.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Scene did not become ready: ' + scene)
                time.sleep(.1)
            video = output / (scene + '.mp4')
            subprocess.run([sys.executable, str(ROOT / 'scripts/recordings/capture-native.py'),
                '--title', 'BB10 Tutorial - ' + scene, '--seconds', str(args.seconds), '--out', str(video)], check=True)
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', '1', '-i', str(video),
                            '-frames:v', '1', str(images / (scene + '.png'))], check=True)
            reports.append(json.loads(marker.read_text(encoding='utf-8')))
            print('Captured ' + scene, flush=True)
        finally:
            process.terminate()
            process.wait(timeout=10)
(output / 'capture-report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
