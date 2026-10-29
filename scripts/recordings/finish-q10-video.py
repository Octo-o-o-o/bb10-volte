"""Burn readable subtitles outside the product UI; normalize narration."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'docs/recordings'
STEM='q10-xiaohongshu'

def stamp(ms,kind='ass'):
    value=round(ms/(10 if kind=='ass' else 1))
    unit=100 if kind=='ass' else 1000
    frac=value%unit
    seconds=value//unit
    h,m,s=seconds//3600,(seconds//60)%60,seconds%60
    if kind=='ass':return f'{h}:{m:02}:{s:02}.{frac:02}'
    return f'{h:02}:{m:02}:{s:02}.{frac:03}'

def wrap(text):
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',48)
    lines=[]
    line=''
    for c in text:
        if font.getlength(line+c)>924:
            lines.append(line)
            line=''
        line+=c
    if line:lines.append(line)
    if len(lines)>2:raise ValueError('Subtitle too tall: '+text)
    return '\\N'.join(lines)

def burn():
    source=json.loads((D/(STEM+'-narrated-narration-report.json')).read_text(encoding='utf-8'))
    ass=['[Script Info]','ScriptType: v4.00+','PlayResX: 1080','PlayResY: 1920','WrapStyle: 2','ScaledBorderAndShadow: yes','',
         '[V4+ Styles]',
         'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding',
         'Style: Default,Microsoft YaHei,48,&H002D2717,&H002D2717,&H00EBF1F3,&H00EBF1F3,0,0,0,0,100,100,0,0,1,0,0,2,72,72,230,1','',
         '[Events]','Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text']
    refined=[]
    for cue in source['cues']:
        text=cue['text'].replace('四 G','4G')
        phrases=[t.strip('，。？！； ') for t in re.split('[，。？！；]',text) if t.strip()]
        i=0
        while i<len(phrases):
            if len(phrases[i])<5 and len(phrases)>1:
                if i+1<len(phrases):
                    phrases[i:i+2]=[phrases[i]+'，'+phrases[i+1]]
                else:
                    phrases[i-1:i+1]=[phrases[i-1]+'，'+phrases[i]]
                    i-=1
            i+=1
        weights=[len(t) for t in phrases]
        total=sum(weights)
        span=cue['audioDurationMs']
        start=cue['startMs']
        cumulative=0
        for phrase,weight in zip(phrases,weights):
            st=start+round(span*cumulative/total)
            cumulative+=weight
            en=start+round(span*cumulative/total)
            ass.append(f'Dialogue: 0,{stamp(st)},{stamp(en)},Default,,0,0,0,,{wrap(phrase)}')
            refined.append({'startMs':st,'endMs':en,'text':phrase})
    (D/'build/subtitles.ass').write_text('\n'.join(ass)+'\n',encoding='utf-8-sig')
    vtt=['WEBVTT','']
    for cue in refined:
        vtt.extend([f"{stamp(cue['startMs'],'vtt')} --> {stamp(cue['endMs'],'vtt')}",cue['text'],''])
    (D/(STEM+'-final-narration.vtt')).write_text('\n'.join(vtt),encoding='utf-8')
    (D/(STEM+'-subtitle-report.json')).write_text(json.dumps({'source':'measured TTS cue durations; phrase timing proportional within each cue','cues':refined,'safeArea':{'left':72,'right':72,'bottom':230},'coverIntroMs':2000},ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(D/(STEM+'-narrated-narration-report.json'),D/(STEM+'-final-narration-report.json'))
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(D/(STEM+'-narrated.mp4')),
                    '-vf','ass=docs/recordings/build/subtitles.ass','-af','loudnorm=I=-16:TP=-3:LRA=9',
                    '-c:v','libx264','-preset','slow','-crf','18','-pix_fmt','yuv420p','-r','30',
                    '-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',str(D/(STEM+'-captioned.mp4'))],cwd=ROOT,check=True)

def review():
    final=D/(STEM+'-final.mp4')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(final)]))
    duration=float(probe['format']['duration'])
    report=json.loads((D/(STEM+'-final-narration-report.json')).read_text(encoding='utf-8'))
    folder=D/(STEM+'-frame-review')
    folder.mkdir(exist_ok=True)
    times=[0.5,2.1,3,4]+[round(i*duration/14,3) for i in range(1,14)]+[duration-1]
    for cue in report['cues']:
        for bound in ['startMs','endMs']:
            for offset in [-0.1,0.1]:
                times.append(max(0,min(duration-0.05,cue[bound]/1000+offset)))
    # Map chapter transitions through TTS padding and the real cover intro.
    for source_time in [22,24.2,52.2,54.4]:
        shift=sum(c.get('paddingMs',0) for c in report['cues'] if c.get('sourceWindowEndMs',1e9)<=source_time*1000)
        mapped=2+source_time+shift/1000
        times.extend([mapped-0.1,mapped+0.1])
    times=sorted(set(round(t,3) for t in times))
    samples=[]
    thumbs=[]
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22)
    for i,t in enumerate(times):
        output=folder/f'{i:03}-{t:.3f}s.png'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(t),'-i',str(final),'-frames:v','1',str(output)],check=True)
        im=Image.open(output).convert('RGB').resize((216,384))
        thumb=Image.new('RGB',(232,424),'#FFFFFF')
        thumb.paste(im,(8,32))
        ImageDraw.Draw(thumb).text((9,4),f'{t:.2f}s',font=font,fill='#17272D')
        thumbs.append(thumb)
        samples.append({'atMs':round(t*1000),'file':str(output.relative_to(ROOT)).replace('\\','/')})
    columns=8
    rows=(len(thumbs)+columns-1)//columns
    sheet=Image.new('RGB',(columns*232,rows*424),'#E6E6E6')
    for i,thumb in enumerate(thumbs):sheet.paste(thumb,((i%columns)*232,(i//columns)*424))
    sheet.save(folder/'contact-sheet.png')
    (folder/'frame-review.json').write_text(json.dumps({'cueSource':'final adjusted narration report and mapped chapter transitions','sampleCount':len(samples),'samples':samples},ensure_ascii=False,indent=2),encoding='utf-8')
    # Export a standard SRT with the final, shifted timeline.
    vtt=(D/(STEM+'-final-narration.vtt')).read_text(encoding='utf-8')
    blocks=[b for b in vtt.split('\n\n') if '-->' in b]
    srt=[]
    for i,b in enumerate(blocks):
        lines=b.strip().splitlines()
        timestamp=next(k for k,line in enumerate(lines) if '-->' in line)
        srt.append(str(i+1)+'\n'+lines[timestamp].replace('.',',')+'\n'+'\n'.join(lines[timestamp+1:]))
    (D/(STEM+'-final.srt')).write_text('\n\n'.join(srt)+'\n',encoding='utf-8-sig')
    print(json.dumps({'durationSeconds':duration,'reviewFrames':len(samples)},ensure_ascii=False))

p=argparse.ArgumentParser()
p.add_argument('stage',choices=['burn','review'])
a=p.parse_args()
burn() if a.stage=='burn' else review()
