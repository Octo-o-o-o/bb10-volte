"""Rebuild the portrait edit from verified native recordings. No device access."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'docs/recordings'
B = D / 'build'
B.mkdir(exist_ok=True)
FONT = 'C:/Windows/Fonts/msyh.ttc'
BOLD = 'C:/Windows/Fonts/msyhbd.ttc'
BG, INK, BLUE, MUTED = '#F3F1EB', '#17272D', '#174FD5', '#647378'

def run(args):
    subprocess.run(args, check=True)

def ff(args):
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y'] + list(map(str, args)))

def txt(draw, xy, text, size=36, color=INK, bold=False):
    draw.text(xy, text, font=ImageFont.truetype(BOLD if bold else FONT, size), fill=color)

CHAPTERS = [
  {'id':'opening','eyebrow':'旧机新用  /  BLACKBERRY','title':['让老黑莓','重新用上 4G 通话'],'tag':'BB10 VoLTE · Q10 真机连接',
   'info':['原生 IMS · 系统拨号器 · 自己的 SIM 卡','这次先看：连接 → 检查 → 查询状态'],
   'clips':[('01-connect.mp4',39,9)],'duration':9},
  {'id':'connect','eyebrow':'01  /  连上你的黑莓','title':['插上数据线','点击「连接手机」'],'tag':'手机解锁后，验证已有 Root 连接',
   'info':['自动识别 Q10、系统版本和运营商','录制中的等待已剪短'],
   'clips':[('01-connect.mp4',8,5),('01-connect.mp4',25,8)],'duration':13},
  {'id':'transition-check','transition':True,'eyebrow':'下一步  /  确认适配条件','title':['连接成功之后','逐项看检查结果'],'tag':'先确认系统、SIM 和网络是否匹配',
   'info':['每一步都有检查结论'], 'still':'checks.png','duration':2.2},
  {'id':'checks','eyebrow':'02  /  查看完整检查','title':['能不能用','让检查结果说话'],'tag':'系统 · Root · 原生文件 · SIM · 4G 网络',
   'info':['已检查 15 项：14 项通过','1 项是当前服务运行状态'],
   'clips':[('02-checks.mp4',2,14)],'duration':14},
  {'id':'status','eyebrow':'03  /  刷新服务状态','title':['查看注册结果','确认当前网络'],'tag':'已有服务，点击「查看状态」',
   'info':['本机回读：IMS connected · LTE','注册通过之后，还需实际通话验收'],
   'clips':[('03-status.mp4',14,7),('03-status.mp4',40,7)],'duration':14},
  {'id':'transition-scope','transition':True,'eyebrow':'使用之前  /  看清实测范围','title':['这台 Q10 已验证','其他组合逐台确认'],'tag':'机型、系统与运营商都要匹配',
   'info':['不把单台实测当作通用承诺'], 'still':'status.png','duration':2.2},
  {'id':'scope','eyebrow':'实测范围  /  如实说明','title':['Q10 SQN100-3','北京中国联通'],'tag':'系统：BB10 10.3.3.3216',
   'info':['项目已有双向短通话、全程 4G 记录','其他机型与运营商仍需验证'],
   'clips':[('03-status.mp4',40,10)],'duration':10},
  {'id':'closing','eyebrow':'开源项目  /  BB10 VoLTE','title':['让老黑莓','继续用起来'],'tag':'从一次兼容性检查开始',
   'info':['首次使用需要 Root，刷写前务必备份','GitHub：Octo-o-o-o / bb10-volte'],
   'clips':[('03-status.mp4',40,9)],'duration':9}
]

# Absolute times refer to the edited source, before the 2-second cover intro.
CUES = [
 (0.35,8.8,'让老黑莓重新用上 4G 通话','这台黑莓 Q10，已经用上原生四 G 通话。今天用真机，看看这个开源工具怎么用。'),
 (9.2,15.3,'连接并解锁手机','手机用数据线连上电脑，解锁后，点击连接手机。'),
 (15.3,21.85,'自动识别并验证已有连接','工具会识别型号、系统和运营商，并验证已有的 Root 连接。'),
 (24.4,31.5,'逐项检查适配条件','打开检查详情，系统版本、原生文件、SIM 卡和四 G 网络，逐项核对。'),
 (31.5,38.0,'先检查，再决定下一步','这台手机已经安装服务，所以还有一项显示为预期的运行状态。'),
 (38.45,45.0,'查看已安装的服务','返回首页，点击查看状态，就能读取手机当前的注册结果。'),
 (45.0,52.0,'IMS 注册与 LTE 网络正常','这里可以看到，服务注册正常，网络保持 LTE。接下来仍要完成实际通话验收。'),
 (54.6,64.25,'准确说明实测范围','项目已有这台 Q10 的双向短通话实测。验证范围是北京联通、这个机型和系统版本，其他组合仍需验证。'),
 (64.6,73.3,'首次 Root 前务必备份','首次使用需要 Root，刷写前务必备份。想让老黑莓继续用起来，可以从兼容性检查开始。')
]

def background(ch, index):
    im = Image.new('RGB',(1080,1920),BG)
    d = ImageDraw.Draw(im)
    d.rectangle((64,73,112,81), fill=BLUE)
    txt(d,(134,58),ch['eyebrow'],27,MUTED)
    for i,line in enumerate(ch['title']):
        txt(d,(62,160+i*111),line,78,BLUE if i else INK,True)
    txt(d,(64,432),ch['tag'],32,MUTED)
    d.line((64,499,1016,499),fill='#CCD3D2',width=2)
    for i,line in enumerate(ch['info']):
        txt(d,(64,1376+i*58),line,32,INK if i==0 else MUTED,i==0)
    d.line((64,1750,1016,1750), fill='#CCD3D2', width=2)
    d.line((64,1750,64+int(952*(index+1)/len(CHAPTERS)),1750),fill=BLUE,width=5)
    txt(d,(64,1780),'BB10 VoLTE  /  真机连接 · 只读演示',27,MUTED)
    txt(d,(64,1823),'Q10 SQN100-3  ·  2026.10',23,MUTED)
    return im

def make_cover():
    coverdir=D/'q10-xiaohongshu-cover-candidates'
    coverdir.mkdir(exist_ok=True)
    choices=[('connected.png','重新用上 4G 通话'),('checks.png','先检查，再上手'),('status.png','查看真实注册结果')]
    thumbs=[]
    for i,(source,subtitle) in enumerate(choices):
        ch=dict(CHAPTERS[0], title=['黑莓 Q10',subtitle],info=['连接 → 检查 → 查看状态','真机操作演示 · 已有 Root 与已安装服务'])
        im=background(ch,0)
        frame=Image.open(D/'evidence'/source).convert('RGB')
        frame.thumbnail((976,820),Image.Resampling.LANCZOS)
        im.paste(frame,((1080-frame.width)//2,560+(820-frame.height)//2))
        dr=ImageDraw.Draw(im)
        txt(dr,(64,1570),'BB10 VoLTE',58,BLUE,True)
        txt(dr,(64,1650),'老设备，继续用。',38,INK)
        im.save(coverdir/f'candidate-{i+1}.png')
        small=im.resize((324,576))
        thumbs.append(small)
        if i==0: im.save(D/'q10-xiaohongshu-cover.png')
    sheet=Image.new('RGB',(1012,640),'#FFFFFF')
    for i,im in enumerate(thumbs):
        sheet.paste(im,(10+i*334,44))
        txt(ImageDraw.Draw(sheet),(12+i*334,8),f'候选 {i+1}',22)
    sheet.save(coverdir/'contact-sheet.png')
    (coverdir/'selection.json').write_text(json.dumps({'selected':'candidate-1.png','source':'evidence/connected.png','reason':'真实 Q10 连接画面，产品完整可辨，直接展示 4G 通话服务已启用；标题置于截图外侧。'},ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--art-only',action='store_true')
    a=p.parse_args()
    ff(['-ss',44,'-i',D/'raw/03-status.mp4','-frames:v',1,D/'evidence/status.png'])
    cursor=0
    for index,ch in enumerate(CHAPTERS):
        ch['startMs']=round(cursor*1000)
        ch['endMs']=round((cursor+ch['duration'])*1000)
        cursor+=ch['duration']
        background(ch,index).save(B/(ch['id']+'-background.png'))
    make_cover()
    report={
      'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'scenario':'q10-xiaohongshu','title':'黑莓 Q10：连接、检查与 VoLTE 状态',
      'baseUrl':'native:BB10-VoLTE','sourceCommit':'d2a0c40',
      'dataMode':'production','allowProduction':True,'readonly':True,
      'audience':'小红书公开观众','surface':'portrait-video-of-native-desktop',
      'durationMs':round(cursor*1000),'chapters':CHAPTERS,
      'demoData':{'source':'connected owner-authorized Q10','privacy':'Only sanitized product UI; no phone numbers, device IDs, keys or account data'},
      'captions':[{'title':title,'body':text,'narration':text,'startMs':round(start*1000),'endMs':round(end*1000)} for start,end,title,text in CUES],
      'narration':{'enabled':True,'engine':'edge-tts','voice':'zh-CN-YunyangNeural'},
      'steps':[{'label':'native-connect-and-preflight','url':'native:main','highlightVisible':False,'overflow':0,'assertion':'Real GUI showed Q10 SQN100-3, OS 10.3.3.3216 and 4G service enabled'},
               {'label':'native-check-details','url':'native:checks','highlightVisible':False,'overflow':0,'assertion':'15 checks: 14 passed, 1 expected running state'},
               {'label':'native-status-refresh','url':'native:main','highlightVisible':False,'overflow':0,'assertion':'registered=true, IMS connected, LTE; native GUI says call acceptance pending'}],
      'consoleMessages':[],'pageErrors':[],'responseErrors':[],
      'nativeNotes':['Browser console/page/HTTP checks do not apply to this Tk application. Native launcher stderr inspected separately.',
                     'ffmpeg gdigrab initial not-enough-frames warning is input probing only; decoded output verified.',
                     'No calls made, no flashing, installation, service restart, configuration mutation or publication.',
                     'Read-only preflight uploads temporary diagnostic files using the existing trusted connection and cleans them afterward.',
                     'Editorial cuts shorten connection and status waiting; no results simulated.'],
      'evidence':'evidence/gui-last-result.json',
      'qualityGates':{'maxOverflow':0,'allowedConsoleErrors':[],'allowedResponseErrors':[]}
    }
    (D/'q10-xiaohongshu-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    scenario={k:report[k] for k in ['scenario','title','sourceCommit','dataMode','allowProduction','readonly','audience','surface']}
    scenario.update({'recording':{'method':'ffmpeg-gdigrab-window','videoSize':{'width':1080,'height':1920},'fps':30},
                     'narration':{'enabled':True,'engine':'edge-tts','voice':'zh-CN-YunyangNeural','language':'zh-CN','edgeRate':'+5%','mix':'replace','timing':'report','padMode':'freeze','maxPaddingMs':6000},
                     'chapters':CHAPTERS,'captions':report['captions']})
    (D/'q10-xiaohongshu.scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.art_only:return
    rendered=[]
    for i,ch in enumerate(CHAPTERS):
        if ch.get('transition'):
            source=D/'evidence'/ch['still']
            inputs=['-loop','1','-i',source]
        else:
            pieces=[]
            for j,(name,start,duration) in enumerate(ch['clips']):
                piece=B/f"{ch['id']}-{j}.mp4"
                ff(['-ss',start,'-i',D/'raw'/name,'-vf','tpad=stop_mode=clone:stop_duration=20','-t',duration,'-an','-c:v','libx264','-crf','17','-preset','veryfast','-pix_fmt','yuv420p',piece])
                pieces.append(piece)
            concat=B/(ch['id']+'-concat.txt')
            concat.write_text('\n'.join("file '"+str(p).replace('\\','/')+"'" for p in pieces),encoding='utf-8')
            source=B/(ch['id']+'-source.mp4')
            ff(['-f','concat','-safe','0','-i',concat,'-c','copy',source])
            inputs=['-i',source]
        out=B/(ch['id']+'.mp4')
        filtergraph='[0:v]scale=976:820:force_original_aspect_ratio=decrease,setsar=1[ui];[1:v][ui]overlay=(W-w)/2:560+(820-h)/2:shortest=1,format=yuv420p[out]'
        if ch.get('transition'):
            filtergraph=filtergraph.replace(',format=yuv420p[out]',',fade=t=in:st=0:d=0.18,fade=t=out:st=1.82:d=0.38,format=yuv420p[out]')
        ff(inputs+['-loop','1','-i',B/(ch['id']+'-background.png'),'-filter_complex',filtergraph,'-map','[out]','-t',ch['duration'],'-r','30','-an','-c:v','libx264','-preset','veryfast','-crf','18',out])
        rendered.append(out)
        print('Rendered',ch['id'],flush=True)
    concat=B/'final-concat.txt'
    concat.write_text('\n'.join("file '"+str(p).replace('\\','/')+"'" for p in rendered),encoding='utf-8')
    ff(['-f','concat','-safe','0','-i',concat,'-c','copy','-movflags','+faststart',D/'q10-xiaohongshu.mp4'])
    print('Portrait source complete:',cursor,'seconds',flush=True)

if __name__=='__main__':main()
