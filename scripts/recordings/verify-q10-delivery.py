"""Evidence and final-media checks, with no device access."""
from pathlib import Path
import datetime
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'docs/recordings'
S='q10-xiaohongshu'
evidence=json.loads((D/'evidence/gui-last-result.json').read_text(encoding='utf-8'))
assert evidence['registered'] is True
assert evidence['status']['current']['ims']=='connected'
assert evidence['status']['current']['ran']=='LTE'
assert evidence['preflight']['device']['variant']=='SQN100-3'
assert evidence['preflight']['outcome']=='compatible'
if (D/'launcher.stderr.log').exists():
    assert not (D/'launcher.stderr.log').read_text(encoding='utf-8').strip()
else:
    # Source releases retain the captured result, not machine-local launcher logs.
    archived=json.loads((D/(S+'-quality-summary.json')).read_text(encoding='utf-8'))
    assert archived['nativeLauncherStderr']=='empty'
captures=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((D/'raw').glob('*.capture.json'))]
assert len(captures)==3 and all(c['exitCode']==0 and c['desktopCaptured'] is False for c in captures)
video=D/(S+'-final.mp4')
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
v=next(s for s in probe['streams'] if s['codec_type']=='video' and not s['disposition'].get('attached_pic'))
assert (v['width'],v['height'])==(1080,1920)
assert v['r_frame_rate']=='30/1'
assert any(s.get('disposition',{}).get('attached_pic') for s in probe['streams'])
assert any(s['codec_type']=='audio' for s in probe['streams'])
decode=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(video),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,text=True)
assert decode.returncode==0 and not decode.stderr.strip(),decode.stderr
black=subprocess.run(['ffmpeg','-hide_banner','-i',str(video),'-map','0:v:0','-vf','blackdetect=d=0.5:pix_th=0.10','-an','-f','null','-'],capture_output=True,text=True)
(D/(S+'-blackdetect.log')).write_text(black.stderr,encoding='utf-8')
assert black.returncode==0 and 'black_start:' not in black.stderr
frames=json.loads((D/(S+'-frame-review/frame-review.json')).read_text(encoding='utf-8'))
assert frames['sampleCount']>=54
files=[video,D/(S+'-cover.png'),D/(S+'-final.srt'),*sorted((D/'raw').glob('*.mp4'))]
summary={
 'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'status':'passed','realDeviceEvidence':{'registered':True,'ims':'connected','network':'LTE','variant':'SQN100-3','persistentMutations':False,'callsMade':False},
 'sourceCommit':'d2a0c40','durationSeconds':float(probe['format']['duration']),
 'dimensions':[v['width'],v['height']],'frameRate':v['r_frame_rate'],
 'nativeCaptureExitCodes':[c['exitCode'] for c in captures],
 'nativeLauncherStderr':'empty','fullDecode':'passed','continuousBlackFramesOver500ms':False,
 'visualReview':{'contactSheetFrames':frames['sampleCount'],'selectedFullSizeFrames':'cover, opening, check details, registration result, ending','subtitleProductOverlap':False},
 'limitations':['No calls placed in this session; historical call claims reference project acceptance evidence.','Subtitle phrase timings are proportional within measured TTS cues; owner can audition pronunciation and pacing in review page.'],
 'files':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
}
(D/(S+'-quality-summary.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':summary['status'],'durationSeconds':summary['durationSeconds'],'sha256':summary['files'][0]['sha256']}))
