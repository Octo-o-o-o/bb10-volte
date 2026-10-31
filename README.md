# bb10-volte — 让黑莓 Q10、Q20、Passport 用上 VoLTE

<img src="assets/icon.png" width="96" alt="BB10 VoLTE">

**简体中文** | [English](README.en.md)

首次连接 Windows 或 Mac 安装一次；以后正常关机换卡、开机，手机自动适配移动、联通、电信，无需再次连接电脑刷机。继续使用自己的 SIM、号码、套餐和系统拨号器，在 LTE 下接打电话。

当前版本 **0.5.0-r8，实验版**。适用于已 Root 的 **Q10 SQN100-3、Q20 SQC100-2、Passport SQW100-4**，系统 **10.3.3.3216**。Passport 切入或离开电信入网策略时，可能需要再正常重启一次；程序会解释原因并提示重新检查。

[官网与下载](https://bb10-volte.octoooo.com/) · [使用指南](https://bb10-volte.octoooo.com/guide.html) · [Release](https://github.com/Octo-o-o-o/bb10-volte/releases/tag/v0.5.0-r8) · [更新日志](docs/UPDATELOG.md)

## 下载

官网默认使用 Cloudflare R2，无法访问 GitHub 也可下载。两处提供同版本、相同字节的文件；运行前核对完整 SHA-256。镜像提供独立线路，不保证所有地区和网络均可访问。

| 文件 | R2 直接下载 | GitHub 备用 |
| --- | --- | --- |
| Windows x64 EXE | [下载](https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-windows-x64.exe) | [下载](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/bb10-volte-0.5.0-r8-windows-x64.exe) |
| macOS universal DMG | [下载](https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-macos-universal.dmg) | [下载](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/bb10-volte-0.5.0-r8-macos-universal.dmg) |
| 完整源码 ZIP（含官网源码） | [下载](https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-experimental.zip) | [下载](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/bb10-volte-0.5.0-r8-experimental.zip) |
| SHA-256 校验码 | [查看](https://bb10-downloads.octoooo.com/v0.5.0-r8/SHA256SUMS.txt) | [查看](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/SHA256SUMS.txt) |

EXE / DMG 均内置 Python 和 Tk；Windows 同时内置 SSH/SCP，Mac 使用系统 SSH/SCP。Windows EXE 尚无 Authenticode 发布者签名。Mac 应用及 DMG 使用 Developer ID 签名、公证并附票；Intel 只核对包内架构，未在 Intel 实机运行。本轮 Mac 真实 USB 验收按机主安排暂缓。

## 当前验收

九个准确机型／运营商组合已通过功能验收。以下标注**每项实际测试的手机载荷版本**；三台现均安装 r8，不等于九项都用同一份 r8 重新测试。

| 机型 / OS 10.3.3.3216 | 移动 460-00 | 联通 460-01 | 电信 460-11 |
| --- | --- | --- | --- |
| Q10 SQN100-3 | 通过 · r7 | 通过 · r7 | 通过 · r8 |
| Q20 SQC100-2 | 通过 · r7 | 通过 · r8 | 通过 · r7 |
| Passport SQW100-4 | 通过 · r8 | 通过 · r7 | 通过 · r7 |

六项包含不连电脑换卡，另三项是安装后的初始卡基线。通话验收包括系统拨号器呼出／呼入、双方声音和 LTE；最后一轮三台的双向接通时长均由机主确认超过 35 秒，本机号码正确，Passport 移动名称正确。Q10 电信采用机主指定的最后一组成功通话；此前对端号码问题另记，本轮不判断首次呼出通过。

部分环形日志已轮转，机主确认的时长与完整保留的 SIP 计时分别记录。接回后的 LTE 快照不能代替全程连续采样。Q10 移动另有约 20 分钟持续驻网及双向通话记录。具体版本、证据与限制见[结构化验收矩阵](materials/unified-carrier-acceptance.json)。

r8 修复三款手机的当前 SIM 本机号码显示和换卡旧缓存恢复；入网策略及 IMS 引擎沿用 r7。Q10 联通号码修复另已验证。未覆盖其他变体、系统、MNC、ISIM、所有地区、漫游、长期待机及紧急呼叫；仍属实验版。

## 快速开始

### 使用方式

1. 先确认手机准确型号、系统、已开通 VoLTE 的有效 USIM（无 ISIM）、Root SSH 与可信连接材料。**自动适配安装不等于首次 Root。**
2. 打开 Windows EXE 或将 Mac 应用拖入“应用程序”后启动。USB 连接并解锁一台手机，进入“三网自动适配”。
3. 核对当前设备，点击“备份并安装自动适配”。程序保存、下载校验原始配置，再安装、回读和启用。
4. 按手机电源菜单正常重启，解锁后等待约 3–5 分钟，点击“已重启，重新检查”。Passport 如提示还需一次正常重启，按原因说明完成。只有本次开机的 SIM、原生 IMS 注册和 LTE 均确认后才显示成功。
5. 拔掉 USB，用系统拨号器呼出、呼入，各等**接通后的屏幕计时达到 00:35**，核对双向声音、全程 LTE、运营商与自己的号码。
6. 以后正常关机换卡，再开机自动适配。Passport 切入或离开电信时，先等约 5 分钟，再正常重启一次。热插卡不在已验收流程内。

升级已识别旧载荷时，先停止并恢复旧设置、正常重启清除旧组件，再安装启用新版并正常重启。保留原始备份和升级回执。未知文件、备份缺失、通话中或独立设置冲突会阻止写入。完整说明见[三网自动适配](docs/AUTO-CARRIERS.md)。

### 首次 Root 与连接

已 Root 且有可信 SSH 的手机无需重新刷机。Windows 提供 Q10 首次准备向导；macOS 14+ 提供原生实验入口。首次 Root 刷写会清空数据，必须备份并使用准确型号的固件，约需 15 GB 空间；未 Root 手机的实际首刷尚未完成验收。Q20、Passport 仍需各自匹配的 Root 方法，禁止刷入 Q10 镜像。

固件浏览器下载支持[极空间](https://t3.znas.cn/9jkbxczhAK4)及应用内百度网盘备用入口；下载后按机型校验导入，分享有效期以网页为准。它们与本页的 EXE/DMG 下载不同。见[首次使用](docs/FIRST-RUN.md)、[Mac 指南](docs/MACOS.md)和[连接说明](docs/GUI.md)。

### 源码运行与构建

```powershell
git clone https://github.com/Octo-o-o-o/bb10-volte.git
cd bb10-volte
python tools/check_release.py --check-git
python tools/gui.py
```

源码运行需要 Python 3.14（含 Tk）；完整 Root 准备使用该版本的 Zstandard 支持。原厂 `/radio/bin/ims_rrm` 不被覆盖，安装使用经过校验的独立副本；原生文件不匹配会停止。固定材料、上游来源与许可证见 [sources.json](materials/sources.json)及 [NOTICE](NOTICE.md)。

完整桌面回归 474 项，473 项通过、1 项跳过。软件测试、冻结包自检、签名公证与真实手机通话分开验收。源码发布使用显式文件清单和敏感信息扫描；私钥、原始通信日志、号码与设备标识不在公开资料中。官网源码与测试见 [website/README](website/README.md)。

[Windows 打包](docs/WINDOWS-EXE.md) · [macOS 打包](docs/MACOS.md) · [源码构建](docs/BUILD.md) · [统一流程](docs/AUTO-CARRIERS.md) · [贡献说明](CONTRIBUTING.md) · [MIT 许可证](LICENSE)

历史单运营商适配、社区证据和旧版限制保留在各文档与更新日志，不能用来替代上面的当前统一流程范围。欢迎在 [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues) 提交准确机型和脱敏结果；不要上传私钥、private 目录或原始号码日志。
