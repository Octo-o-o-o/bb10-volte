"""Build the bilingual illustrated walkthrough from the recording step source."""
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
steps = json.loads((ROOT / 'docs/recordings/first-use.steps.json').read_text(encoding='utf-8'))
START, END = '<!-- first-use:start -->', '<!-- first-use:end -->'
for language in ('zh', 'en'):
    en = language == 'en'
    relative = '../' if en else ''
    title = 'Follow the illustrated walkthrough' if en else '跟着截图，一步一步完成'
    notice = 'Windows interface with demonstration data, recorded from r14 plus feedback. r15 includes feedback and adds early variant checks; follow the current app when wording differs. This explains operation and is not hardware acceptance evidence. Automatic setup covers only the accepted variants; other variants should use the candidate guide below. Mac follows the same overall steps; first Root preparation requires macOS 14+.' if en else '以下使用 Windows 真实程序界面与演示数据，录制基于 r14 加反馈功能；r15 已包含反馈入口，并新增型号前置检查，个别提示以当前程序为准。图文和视频用于操作讲解，不作为真实刷写或通话验收证据。自动流程仅适用已验证后缀；其他后缀先看下方候选试测说明。Mac 操作顺序相同，首次 Root 准备需 macOS 14+。'
    parts = [START, f'<section class="chapter guide-section" id="walkthrough" aria-labelledby="walkthrough-title">',
             f'<p class="eyebrow">STEP BY STEP · 01—09</p><h2 id="walkthrough-title">{title}</h2>',
             f'<p class="guide-note">{notice}</p>',
             '<nav class="tutorial-jump" aria-label="' + ('Tutorial steps' if en else '选择你卡住的步骤') + '">']
    for n, step in enumerate(steps, 1):
        parts.append(f'<a href="#walkthrough-{step["id"]}">{n:02d} · {escape(step["enTitle" if en else "title"])}</a>')
    parts.extend(['</nav>', '<div class="tutorial-video">',
        f'<video controls playsinline preload="metadata" poster="{relative}assets/tutorial/first-use-cover.png" aria-label="' +
        ('Chinese narrated first-use tutorial' if en else '完整首次使用视频教程，中文女声与字幕') + '">',
        f'<source src="{relative}assets/tutorial/first-use.mp4" type="video/mp4">',
        ('Your browser cannot play this video.' if en else '浏览器暂不支持播放，可下载视频观看。') + '</video>',
        f'<p><a href="{relative}assets/tutorial/first-use.mp4" download>' + ('Download tutorial video' if en else '下载完整教程视频') + '</a> · ' +
        ('Chinese narration and captions. Pause at any step.' if en else '中文女声 · 中文字幕 · 可随时暂停对照操作') + '</p></div></section>'])
    for n, step in enumerate(steps, 1):
        parts.append(f'<section class="chapter guide-section tutorial-step" id="walkthrough-{step["id"]}" aria-labelledby="tutorial-title-{n}">')
        if step['id'] == 'install':
            parts.append('<span id="walkthrough-preflight"></span>')
        parts.extend([f'<p class="eyebrow">{n:02d} / 09</p>',
            f'<h2 id="tutorial-title-{n}">{escape(step["enTitle" if en else "title"])}</h2>',
            f'<p>{escape(step["enText" if en else "text"])}</p>',
            f'<p><strong>{"Do this:" if en else "这样做："}</strong> {escape(step["enAction" if en else "action"])}</p>'])
        image = 'root-import' if step['id'] == 'root' else step['image']
        image_url = relative + 'assets/tutorial/' + image + '.png'
        parts.append(f'<figure class="guide-shot tutorial-shot"><a href="{image_url}" target="_blank" rel="noopener noreferrer"><img src="{image_url}" loading="lazy" width="1000" height="820" alt="{escape(step["enTitle" if en else "title"], quote=True)}"></a><figcaption>' +
            ('Actual Windows interface with demonstration data. Click to view the complete screenshot.' if en else '真实 Windows 界面，使用演示数据；点击可查看完整大图。') + '</figcaption></figure>')
        parts.extend([f'<div class="tutorial-result"><strong>{"You should see:" if en else "成功标志："}</strong> {escape(step["enExpected" if en else "expected"])}</div>',
            f'<details class="tutorial-help"><summary>{"Stuck at this step?" if en else "卡在这一步？"}</summary><p>{escape(step["enStuck" if en else "stuck"])}</p><p><a href="#walkthrough-feedback">' +
            ('How to save feedback' if en else '查看如何保存反馈包') + '</a></p></details>', '</section>'])
    extras = [
        ('drivers', 'Windows USB drivers', 'Windows 驱动',
         'Use First use and connection help → Windows drivers only if the computer does not detect the phone or USB network. Normal application use does not need administrator rights.',
         '只有电脑未识别手机或 USB 网络未就绪时，才进入“首次使用与连接帮助 → Windows 驱动”。日常使用不需要管理员权限；驱动安装会另行提示。'),
        ('firmware', 'Older OS: upgrade first', '旧系统：先升级再 Root',
         'Select System upgrade and follow the model-bound stages, backup requirements and separate wipe confirmations. Never apply another model’s firmware. Return to Root verification after the target OS is confirmed.',
         '选择“系统升级 / 继续升级记录”，按准确机型分阶段操作，遵守备份要求和每次清空确认。不要跨机型刷写。确认达到目标系统后，再继续 Root 与连接验证。'),
        ('pair', 'Already rooted, but connection files are missing', '已有 Root，但连接材料丢失',
         'Choose Authorize again from the phone. It requires an already working Root terminal. Follow each transfer and phone-command prompt, then verify phone identity and actual Root access. It does not root an unrooted phone.',
         '选择“没有旧文件，从手机重新授权”。这条路径需要手机已有有效 Root 终端；依次按提示准备授权文件、转移到手机、执行完整授权命令，再验证手机身份和实际 Root。它不能替未 Root 的手机完成 Root。')]
    for anchor, en_title, zh_title, en_text, zh_text in extras:
        parts.append(f'<section class="chapter guide-section" id="walkthrough-{anchor}"><h2>{en_title if en else zh_title}</h2><p>{en_text if en else zh_text}</p><a href="#walkthrough-feedback">' +
                     ('Save feedback from this step' if en else '在这一步保存反馈') + '</a></section>')
    parts.append(END)
    path = ROOT / ('website/src/en/guide.html' if en else 'website/src/guide.html')
    html = path.read_text(encoding='utf-8')
    if START in html:
        before, tail = html.split(START, 1)
        _, after = tail.split(END, 1)
        html = before + '\n'.join(parts) + after
    else:
        marker = '<div class="guide-content">'
        assert marker in html
        html = html.replace(marker, marker + '\n' + '\n'.join(parts), 1)
        nav = '<ol>'
        html = html.replace(nav, nav + '<li><a href="#walkthrough">' + ('Illustrated tutorial & video' if en else '图文步骤与视频') + '</a></li>', 1)
    path.write_text(html, encoding='utf-8', newline='\n')
print('Built Chinese and English tutorial sections')
