#!/usr/bin/env node
// Rebuild the portrait edit from native recordings. Never connects to a phone.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
const skill=process.env.RECORDER_SKILL||path.join(os.homedir(),'.codex/skills/repo-demo-recorder');
const python=process.env.RECORDING_PYTHON||path.resolve('.recording-venv/Scripts/python.exe');
const stem='docs/recordings/q10-xiaohongshu';
function run(cmd,args){const r=spawnSync(cmd,args,{stdio:'inherit'});if(r.status!==0)process.exit(r.status||1);}
const node=(file,args)=>run(process.execPath,[file,...args]);
const tool=(name,args)=>node(path.join(skill,'scripts',name+'.mjs'),args);
run(python,['scripts/recordings/build-q10-video.py']);
if(process.argv.includes('--reuse-audio')){
  if(!existsSync('docs/recordings/build/narration.m4a')){
    // The public narrated video retains the audio; build caches are not shipped.
    if(!existsSync(stem+'-narrated.mp4'))throw new Error('Public narrated video missing');
    run('ffmpeg',['-hide_banner','-loglevel','error','-y','-i',stem+'-narrated.mp4','-vn','-c:a','copy','docs/recordings/build/narration.m4a']);
  }
  run('ffmpeg',['-hide_banner','-loglevel','error','-y','-i',stem+'.mp4','-i','docs/recordings/build/narration.m4a','-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart',stem+'-narrated.mp4']);
} else {
  node('scripts/recordings/tts-local.mjs',['--video',stem+'.mp4','--report',stem+'-report.json','--out',stem+'-narrated.mp4','--scenario',stem+'.scenario.json']);
}
run(python,['scripts/recordings/finish-q10-video.py','burn']);
tool('embed-video-cover',['--video',stem+'-captioned.mp4','--cover',stem+'-cover.png','--out',stem+'-final.mp4','--intro-duration-ms','2000','--narration-report',stem+'-final-narration-report.json','--narration-vtt',stem+'-final-narration.vtt','--report',stem+'-cover-embed-report.json']);
tool('validate-recording-report',[stem+'-report.json','--video',stem+'-final.mp4','--source-video',stem+'.mp4','--narration-report',stem+'-final-narration-report.json','--require-audio','--require-cover-art','--min-audio-max-db','-18','--expect-width','1080','--expect-height','1920','--write-media-report',stem+'-media-report.json']);
run(python,['scripts/recordings/finish-q10-video.py','review']);
run(python,['scripts/recordings/verify-q10-delivery.py']);
tool('generate-review-page',['--report',stem+'-report.json','--video',stem+'-final.mp4','--source-video',stem+'.mp4','--media-report',stem+'-media-report.json','--narration-report',stem+'-final-narration-report.json','--cover',stem+'-cover.png','--cover-candidates',stem+'-cover-candidates','--frame-review',stem+'-frame-review','--out',stem+'-review.html','--title','黑莓 Q10 · 小红书演示审片']);
