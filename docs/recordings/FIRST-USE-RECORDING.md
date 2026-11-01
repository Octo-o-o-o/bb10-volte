# 完整首次使用教程与录制说明

成片：[first-use-narrated.mp4](first-use-narrated.mp4) · [审片页](first-use-review.html) · [字幕](first-use.srt) · [图文教程源码](../../website/src/guide.html) · [反馈说明](../FEEDBACK.md)

## 范围

面向首次使用者的 Windows 教程，9 步、约 3 分 39 秒、1440×960、30 fps。使用真实 Tk 产品界面和隔离模拟数据，没有连接、刷写或修改真实手机，不作为硬件验收证据。基于源码 `6ca9147` 加本次待发布的教程与反馈改动。已发布 r14 没有新反馈入口时，使用“更多 → 导出检查报告”。Mac 总体顺序相同，刷写提示不同，首次 Root 准备要求 macOS 14+。

没有找到可用豆包配置，按用户授权使用 Edge 晓晓女声 `zh-CN-XiaoxiaoNeural`，只发送公开教程文稿。项目适配脚本固定 `edge-tts==7.3.1`，不修改全局安装或 skill。图文和解说共用 [步骤数据](first-use.steps.json)，每步包含操作、成功标志和失败处理。

章节：准备与备份 → 连接手机 → 导入首次 Root 固件 → 准备个人镜像与确认刷写 → 验证 Root → 备份并安装三网适配 → 正常重启后复查 → 断开 USB 验收双向通话 → 导出反馈。

## 数据与画面

[场景脚本](../../scripts/recordings/launch-first-use.py) 加载真实窗口，替换设备后端，拒绝子进程启动和网络连接。[录制脚本](../../scripts/recordings/capture-first-use.py) 等待就绪标记，通过 `capture-native.py` 和 FFmpeg `gdigrab` 按窗口标题录制。产品窗口完整保留，字幕放在窗口下方的独立区域。

Root 导入与安装另录了真实按钮点击和模拟成功结果，保存在 `first-use-raw/root-actions.mp4`、`first-use-raw/install-actions.mp4`。点击由原生界面工具执行，不是截图动画。重录时启动 `root-import` / `install` 场景，在录制后点击“校验并导入固件” / “备份并安装三网适配”。仅操作隔离演示窗口。缺少点击素材时，合成脚本使用对应静态场景，不会伪造动作。

## 重录命令

在隔离 worktree 运行。需要 Windows、Python 3.14（含 Tk）、Node、FFmpeg/FFprobe、uvx 和 `repo-demo-recorder` skill。网站目录先运行 `npm ci` 准备 Playwright；合并和封面命令从网站目录运行，使 skill 能找到 Playwright。以下 PowerShell 从仓库根开始：

```powershell
$recorderSkill = Join-Path $env:USERPROFILE '.codex/skills/repo-demo-recorder'
$env:RECORDER_SKILL = $recorderSkill
node scripts/recordings/first-use.mjs capture
node scripts/recordings/first-use.mjs compose
node scripts/recordings/first-use.mjs guide
Push-Location website
node "$recorderSkill/scripts/assemble-segmented-video.mjs" --manifest ../docs/recordings/first-use-segments.json --out ../docs/recordings/first-use-assembled.mp4 --report ../docs/recordings/first-use-assemble-report.json --combined-report ../docs/recordings/first-use-report.json --segments-dir ../docs/recordings/first-use-assembled-segments --width 1440 --height 960 --fps 30 --theme training --transition-duration-ms 2400 --transition-fade-in-ms 180 --transition-fade-out-ms 380
Pop-Location
node scripts/recordings/first-use.mjs finish
Push-Location website
node "$recorderSkill/scripts/generate-video-cover.mjs" --video ../docs/recordings/first-use-narrated.mp4 --report ../docs/recordings/first-use-report.json --out ../docs/recordings/first-use-cover.png --candidates-dir ../docs/recordings/first-use-cover-candidates --width 1440 --height 960 --theme training --timestamp 174 --title 'BB10 VoLTE 首次使用' --subtitle '从连接手机到通话验收' --line '连接 · Root · 安装 · 重启 · 通话验收' --badge '9 个步骤 · 中文讲解'
Pop-Location
node "$recorderSkill/scripts/embed-video-cover.mjs" --video docs/recordings/first-use-narrated.mp4 --cover docs/recordings/first-use-cover.png --out docs/recordings/first-use-narrated.mp4 --intro-duration-ms 2000 --narration-report docs/recordings/first-use-narrated-narration-report.json --narration-vtt docs/recordings/first-use-narrated-narration.vtt --report docs/recordings/first-use-cover-embed-report.json
node scripts/recordings/first-use.mjs package
```

只重录某场景用 `python scripts/recordings/capture-first-use.py --scenes connect --seconds 6`。已有配音会复用；改画面保留配音用 `node scripts/recordings/first-use.mjs compose --rerender`。修改解说后在新输出工作区重建受影响分段，避免误用旧语音。`compose` 生成本机的 `first-use-segments.json`，这个临时绝对路径清单不公开，换机器后重新运行即可。

封面选择通话就绪页的录屏帧，展示最终目标，不代表新的实机通话证据。保留 2 秒可见片头和 attached picture。不要在未重新合成时重复嵌入封面，否则会叠加片头。

## 校验和审片

```powershell
node scripts/recordings/validate-first-use.mjs docs/recordings/first-use-report.json --video docs/recordings/first-use-narrated.mp4 --source-video docs/recordings/first-use-assembled.mp4 --narration-report docs/recordings/first-use-narrated-narration-report.json --require-audio --require-cover-art --expect-width 1440 --expect-height 960 --min-audio-max-db -18 --frame-review-max-frames 96 --write-media-report docs/recordings/first-use-media-report.json --write-frame-review docs/recordings/first-use-frame-review-final
node scripts/recordings/first-use.mjs package
node "$recorderSkill/scripts/generate-review-page.mjs" --report docs/recordings/first-use-report.json --video docs/recordings/first-use-narrated.mp4 --media-report docs/recordings/first-use-media-report.json --narration-report docs/recordings/first-use-narrated-narration-report.json --cover docs/recordings/first-use-cover.png --cover-candidates docs/recordings/first-use-cover-candidates --frame-review docs/recordings/first-use-frame-review-final --out docs/recordings/first-use-review.html
node scripts/recordings/first-use.mjs package
python tools/check_release.py
```

Windows FFmpeg 不支持图片 glob。校验适配只把 skill 的 contact sheet 枚举改为 concat 清单，保留所有门禁和采样时刻；上游结构改变时直接报错，要求重新审查。

本次结果：9 段、8 个 2.4 秒转场；最终 219.339 秒，时长偏差 0，音量峰值约 −5.9 dB；72 张解说边界抽帧。整片解码通过，`blackdetect` 未发现持续 0.2 秒以上黑屏。人工检查片头 0.5 秒、封面后首帧、所有转场及最后 30 秒，见 [补充审片图](first-use-manual-review/contact-sheet.png)。

字幕按句拆分后按字数分配实际语音时长，不是逐字对齐。原生 Tk 没有 HTTP/console，空 `pageErrors` 不能代替网站测试。已知非失败噪声：gdigrab 启动帧率估计提示、本机 Edge 环境的 sitecustomize/pip 提示；录制退出码和音频检查均通过。

`package` 只同步本地网站视频/封面、修正最终 report 的片头时间、移除报告中的本机路径、更新 SHA-256 公开清单，不会上传、部署、提交或推送。发布网站前运行 `npm test` 和 `npm run test:browser`；新反馈入口需要随下一版桌面安装包发布。
