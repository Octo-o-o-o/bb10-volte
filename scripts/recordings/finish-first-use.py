"""Synchronize final narration and burn one subtitle layer outside the UI."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'docs/recordings'
assembly = json.loads((D/'first-use-assemble-report.json').read_text(encoding='utf-8'))
cues = []
for segment in assembly['segments']:
    video = Path(segment['video'])
    report = json.loads(video.with_name(video.stem+'-narration-report.json').read_text(encoding='utf-8'))
    for source in report['cues']:
        cue = deepcopy(source)
        for key in ('startMs', 'endMs', 'windowEndMs', 'sourceStartMs', 'sourceEndMs', 'sourceWindowStartMs', 'sourceWindowEndMs'):
            if key in cue:
                cue[key] += segment['startMs']
        cue['index'] = len(cues)+1
        cues.append(cue)
milliseconds = round(assembly['output']['durationSeconds']*1000)
narration = {'engine': 'edge-tts', 'language': 'zh-CN', 'voice': 'zh-CN-XiaoxiaoNeural',
             'padMode': 'freeze', 'timeline': {'sourceDurationMs': milliseconds,
             'outputDurationMs': milliseconds, 'expectedDurationMs': milliseconds,
             'totalPaddingMs': sum(c.get('paddingMs', 0) for c in cues)}, 'cues': cues}
(D/'first-use-narrated-narration-report.json').write_text(json.dumps(narration,ensure_ascii=False,indent=2), encoding='utf-8')


def stamp(value, separator=','):
    milliseconds = round(value)
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}'


subtitles = []
for cue in cues:
    phrases = [p.strip() for p in re.split(r'(?<=[。！？；])', cue['text']) if p.strip()]
    lines = []
    for phrase in phrases:
        while len(phrase) > 42:
            split = phrase.rfind('，', 15, 42)+1
            if split < 16:
                split = 36
            lines.append(phrase[:split])
            phrase = phrase[split:]
        if phrase:
            lines.append(phrase)
    total = sum(len(line) for line in lines)
    end = cue['startMs'] + cue['audioDurationMs']
    cursor = cue['startMs']
    for line in lines:
        next_cursor = cursor + (end-cue['startMs'])*len(line)/total
        subtitles.append({'startMs':round(cursor),'endMs':round(next_cursor),'text':line})
        cursor = next_cursor


def srt(offset=0):
    return '\n\n'.join(f'{i+1}\n{stamp(c["startMs"]+offset)} --> {stamp(c["endMs"]+offset)}\n{c["text"]}' for i,c in enumerate(subtitles))+'\n'


(D/'first-use-subtitles.srt').write_text(srt(), encoding='utf-8', newline='\n')
(D/'first-use.srt').write_text(srt(2000), encoding='utf-8', newline='\n')
ass = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1440
PlayResY: 960
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,27,&H00FFFFFF,&H00FFFFFF,&H00102033,&H00102033,0,0,0,0,100,100,0,0,1,1,0,2,24,24,22,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
for item in subtitles:
    start, end = stamp(item['startMs'], '.')[:-1], stamp(item['endMs'], '.')[:-1]
    ass += f'Dialogue: 0,{start},{end},Default,,0,0,0,,{item["text"]}\n'
(D/'first-use-subtitles.ass').write_text(ass,encoding='utf-8',newline='\n')
(D/'first-use-narrated-narration.vtt').write_text('WEBVTT\n\n'+'\n\n'.join(
    f'{i+1}\n{stamp(c["startMs"], ".")} --> {stamp(c["endMs"], ".")}\n{c["text"]}' for i,c in enumerate(subtitles))+'\n',encoding='utf-8',newline='\n')
report_path = D/'first-use-report.json'
report = json.loads(report_path.read_text(encoding='utf-8'))
report.update(title='BB10 VoLTE：完整首次使用',scenario='first-use',durationMs=milliseconds,
              dataMode='mock',sourceCommit='6ca9147',
              narrative={'avoidVisibleTerms':['fixture','renderer-only','dev warning']},
              qualityGates={'maxOverflow':0},
              caveats=['Windows mock-backed native UI; not hardware acceptance.',
                       'Feedback is an unreleased desktop change; current r14 uses Export check report.',
                       'Native Tk has no browser HTTP/page console. Empty browser error arrays are not browser QA.',
                       'FFmpeg gdigrab startup rate-estimation warning; capture exit codes were zero.',
                       'Edge client emitted a nonfatal local sitecustomize/pip warning; audio was generated and measured.'])
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
command = ['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(D/'first-use-assembled.mp4'),
           '-vf', 'ass=docs/recordings/first-use-subtitles.ass',
           '-map','0:v:0','-map','0:a:0','-c:v','libx264','-preset','veryfast','-crf','21','-c:a','copy',
           '-movflags','+faststart',str(D/'first-use-narrated.mp4')]
subprocess.run(command,cwd=ROOT,check=True)
print(json.dumps({'durationMs':milliseconds,'subtitleCues':len(subtitles),'narrationCues':len(cues)}))
