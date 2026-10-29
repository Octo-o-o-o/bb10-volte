# 黑莓 Q10 小红书演示录制说明

成片：`q10-xiaohongshu-final.mp4`，75.4 秒，1080×1920，30 fps，H.264 / AAC。包含中文旁白、烧录字幕、独立 SRT / VTT、真实截图封面和本地审片页。

## 内容与授权

- 目标观众：小红书上的黑莓用户和旧设备爱好者。
- 固定提交 `d2a0c40`，桌面版本 0.3.3-r1；手机已有服务版本为 0.3.2。录制不代表新版本安装验收。
- 数据模式：`production + allowProduction + readonly`。机主明确同意使用已连接 Q10 的真实状态并脱敏，只做连接、兼容性检查和状态查询。
- 设备：Q10 SQN100-3 / BB10 10.3.3.3216 / 中国联通 460-01。实际回读 `registered=true`、IMS connected、200 OK、LTE。脱敏证据：`evidence/gui-last-result.json`。
- 本次没有拨号、安装、刷机、停止或重启服务。手机本来已 Root 且已安装服务；视频不是从零刷机教程，也不是本次通话实测。
- 预检向随机临时目录上传诊断脚本，完成后清理，不改持久业务配置。沿用严格主机校验与现有私钥；交付材料没有私钥、手机号、IMSI、IMEI、ICCID 或个人账户内容。
- 双向短通话、全程 4G 的表述引用已有 `materials/startup-latency-2026-10-28.json` 和 README 验收表，不扩大到其他设备与运营商。

## 叙事和画面

先展示启用结果，再演示连接、检查详情和状态查询，最后说明实测范围与 Root 备份要求。素材是原生 Tk 窗口录屏，不是网页仿制或模拟状态。连接和查询等待做了剪短；结尾用真实已完成结果的冻结帧停留。两次章节转场各 2.2 秒，片头封面 2 秒。

完整窗口使用 contain 排版，标题、解释与字幕均在截图外侧。候选封面及选择理由在 `q10-xiaohongshu-cover-candidates/`。MP4 内嵌 attached_pic，同时保留可见封面片头。

## 重新录制原生素材

本次创建独立 worktree，固定版本后启动专用实例，没有改产品源码。`launch-q10-demo.py` 只增加录制窗口标题、尺寸、只读动作保护和脱敏结果落盘。

```powershell
python scripts/recordings/launch-q10-demo.py --ssh-config <本人现有可信配置绝对路径> --host q10-root
python scripts/recordings/capture-native.py --seconds 55 --out docs/recordings/raw/01-connect.mp4
python scripts/recordings/capture-native.py --title '检查详情' --seconds 22 --out docs/recordings/raw/02-checks.mp4
python scripts/recordings/capture-native.py --seconds 45 --out docs/recordings/raw/03-status.mp4
```

用 Windows Computer Use 选择唯一的 `BB10 VoLTE - Q10 Demo` 窗口。每次观察后单独执行操作并刷新截图：第一段点击“连接手机”等真实结果；第二段打开“检查详情”，停留后滚到 IMS 信息；第三段回首页点击“查看状态”等真实结果。capture JSON 保存开始时间与退出码。只录指定窗口，不录桌面或其他应用。重录后根据实际等待长度调整 `build-q10-video.py` 的 CHAPTERS 裁切时间，不能盲用本次时间点。

## 从现有素材重建

需要 Node.js、Python 3.14、FFmpeg/FFprobe 和 repo-demo-recorder skill。本次验证了 Pillow 13.0.0、edge-tts 7.3.1。

```powershell
python -m venv .recording-venv
.\.recording-venv\Scripts\python.exe -m pip install pillow==13.0.0 edge-tts==7.3.1
node scripts/recordings/q10-xiaohongshu.mjs --reuse-audio
```

`--reuse-audio` 使用本次保留配音；源码包没有构建缓存时，从随包的 narrated MP4 提取音轨，不发送文本到在线服务，只适用于解说稿与时间轴未改变的情况。省略会重新合成旁白。在线合成仅向 Microsoft Edge TTS 发送本视频的公开解说。可用 `RECORDING_PYTHON` 与 `RECORDER_SKILL` 指定环境与技能位置。

全局 uvx 的旧 edge-tts 7.2.8 曾返回 HTTP 403。`tts-local.mjs` 复用技能的 TTS、时间轴与补帧实现，只将执行器换为已验证的任务环境 edge-tts 7.3.1。未改全局技能，也未关闭 TLS 校验。

## 验证与已知边界

已运行录制脚本语法检查、原生录制退出码检查、真实设备结果断言、全片解码、音视频与封面门禁、黑屏检查，并抽查最终时间轴的 54 张帧。报告为 `q10-xiaohongshu-media-report.json`，审片页为 `q10-xiaohongshu-review.html`。

主 runner 内含技能 validate 命令，要求音轨、封面、1080×1920、峰值高于 -18 dB。本机用 Pillow 生成 contact sheet，避免 FFmpeg image2 glob 在 Windows 的兼容问题；抽帧使用最终旁白时间轴。

浏览器 pageErrors/HTTP/console 不适用于 Tk；这些空数组不是浏览器测试结论。原生启动 stderr 为空。FFmpeg 初始 `not enough frames to estimate rate` 为已解释的采集提示，成片以 30 fps 编码并完成全片解码。字幕句内时间按实测配音时长分配，不是逐字人工校时；发布前可在审片页试听个人偏好的读音与节奏。

原始三段、脚本、场景、含配音的成片、字幕、封面、审片帧和脱敏报告随源码保留，并由 `materials/recording-files.json` 显式列出与校验。构建缓存及本机运行日志仅保留本地。录制发生在旧版本，不代表 r5 的手机实测；本次随 r5 纳入 Git 和 Release，没有上传小红书。
