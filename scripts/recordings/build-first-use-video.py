"""Compose native takes with a separate instruction panel and Edge narration."""
import json
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'docs/recordings'
B = D / 'first-use-build'
B.mkdir(exist_ok=True)
STEPS = json.loads((D / 'first-use.steps.json').read_text(encoding='utf-8'))
SCENARIO = D / 'first-use.scenario.json'
FONT = 'C\\:/Windows/Fonts/msyh.ttc'
HINTS = [
    '准确型号与系统\n提前备份手机\n已有 Root 可跳过首刷',
    '旧文件夹 → 导入材料\n已有 Root → 重新授权\n从未 Root → 首次准备',
    '对应型号的完整固件\n不运行、不解压\n选择文件后校验导入',
    '导入后继续准备镜像\n核对机型与备份\n清空数据需再次确认',
    '完成手机首次设置\n打开 BlackBerry World\n回电脑重新检测 Root',
    '先检查当前设备\n再备份并安装\n保留原始配置备份',
    '手机电源菜单重启\n解锁并等待 3–5 分钟\n再检查本次开机状态',
    '拔掉 USB 后测试\n呼入、呼出各 00:35\n双向声音 + 全程 LTE',
    '说明卡住的步骤\n预览并保存 ZIP\n自行发送给开发者']


def run(args, name, cwd=ROOT):
    with (B / (name + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(list(map(str, args)), cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((B / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-3500:])
        raise RuntimeError(name + ' failed')


def duration(path):
    result = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                      '-of', 'default=nw=1:nk=1', str(path)], text=True)
    return float(result)


manifest = []
for index, step in enumerate(STEPS):
    name = f'{index+1:02d}-{step["id"]}'
    raw = D / 'first-use-raw' / (step['image'] + '.mp4')
    seek = []
    if step['id'] == 'root' and (D / 'first-use-raw/root-actions.mp4').exists():
        raw = D / 'first-use-raw/root-actions.mp4'
        seek = ['-ss', '9']
    elif step['id'] == 'install' and (D / 'first-use-raw/install-actions.mp4').exists():
        raw = D / 'first-use-raw/install-actions.mp4'
        seek = ['-ss', '8']
    video, narrated = B / (name + '.mp4'), B / (name + '-narrated.mp4')
    report_path = B / (name + '-report.json')
    seconds = round(max(16, len(step['narration']) / 4.7 + 1.6), 2)
    title = ['先备份\n再检查要求', '连接手机\n按已有材料选路', '首次 Root\n导入对应固件',
             '准备个人镜像\n再确认刷写', '完成手机设置\n重新验证 Root', '先检查设备\n备份并安装',
             '正常重启\n检查本次开机', '拔掉 USB\n验收双向通话', '卡住时\n保存反馈包'][index]
    for suffix, text in [('title', title), ('hints', HINTS[index]), ('number', f'{index+1:02d} / 09')]:
        (B / (name + '-' + suffix + '.txt')).write_text(text, encoding='utf-8', newline='\n')
    relative = lambda suffix: (B / (name + '-' + suffix + '.txt')).relative_to(ROOT).as_posix()
    graph = (f'[0:v]scale=1000:820:force_original_aspect_ratio=decrease,pad=1000:820:(ow-iw)/2:(oh-ih)/2:color=0xf1f5f9,'
             f'tpad=stop_mode=clone:stop_duration={seconds}[ui];'
             f'color=c=0x102033:s=1440x960:r=30:d={seconds}[bg];[bg][ui]overlay=28:58:shortest=1,'
             f"drawtext=fontfile='{FONT}':text='BB10 VoLTE':fontsize=24:fontcolor=0xd7e5f2:x=28:y=15,"
             f"drawtext=fontfile='{FONT}':textfile='{relative('number')}':fontsize=24:fontcolor=0x77d8bd:x=1070:y=110,"
             f"drawtext=fontfile='{FONT}':textfile='{relative('title')}':fontsize=32:line_spacing=12:fontcolor=white:x=1070:y=170,"
             'drawbox=x=1070:y=340:w=76:h=3:color=0x77d8bd:t=fill,'
             f"drawtext=fontfile='{FONT}':textfile='{relative('hints')}':fontsize=23:line_spacing=18:fontcolor=0xc3d0df:x=1070:y=386[out]")
    if '--rerender' in sys.argv and narrated.exists():
        actual = duration(narrated)
        graph = graph.replace(f'stop_duration={seconds}', f'stop_duration={actual}').replace(f':d={seconds}[bg]', f':d={actual}[bg]')
        refreshed = B / (name + '-refreshed.mp4')
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *seek, '-i', raw, '-i', narrated,
             '-filter_complex', graph, '-map', '[out]', '-map', '1:a:0', '-t', actual, '-c:a', 'copy',
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-r', '30', refreshed], name+'-rerender')
        refreshed.replace(narrated)
    if not narrated.exists():
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *seek, '-i', raw,
             '-filter_complex', graph, '-map', '[out]', '-t', seconds, '-an', '-c:v', 'libx264',
             '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-r', '30', video], name+'-render')
        report = {'scenario': 'first-use', 'title': step['title'], 'dataMode': 'mock', 'readonly': True,
                  'baseUrl': 'native:BB10-VoLTE', 'surface': 'native-desktop', 'audience': 'customer',
                  'durationMs': round(seconds*1000), 'pageErrors': [], 'consoleMessages': [], 'responseErrors': [],
                  'nativeScope': 'Real Tk UI with isolated demonstration backends; not device acceptance.',
                  'captions': [{'title': step['title'], 'body': step['action'], 'narration': step['narration'],
                                'startMs': 600, 'endMs': round(seconds*1000)-600}],
                  'steps': [{'label': step['id'], 'highlightVisible': False, 'overflow': 0,
                             'assertion': 'Dedicated mock window capture; no live device mutation'}]}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        run(['node', ROOT/'scripts/recordings/first-use-tts.mjs', '--video', video, '--report', report_path,
             '--out', narrated, '--scenario', SCENARIO, '--timing', 'report', '--max-padding-ms', '12000'], name+'-tts')
        narration = json.loads(narrated.with_name(narrated.stem+'-narration-report.json').read_text(encoding='utf-8'))
        cue = narration['cues'][0]
        report['captions'][0].update(startMs=cue['startMs'], endMs=cue['endMs'])
        report['durationMs'] = round(duration(narrated)*1000)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest.append({'video': str(narrated), 'report': str(report_path), 'title': step['title'],
                     'subtitle': f'{index+1:02d} / 09', 'line': '看清这一步，再继续下一步'})
    print('Narrated ' + name, flush=True)
(D / 'first-use-segments.json').write_text(json.dumps({'segments': manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
print('All 9 narrated segments ready', flush=True)
