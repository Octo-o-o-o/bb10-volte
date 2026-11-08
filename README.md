# bb10-volte — 让 Q10、Q20、Passport、P’9983 用上 VoLTE

**桌面 r42 · 手机原生版 0.1.0.43。** Q10、Q20、Passport、P’9983 的目录后缀都开放移动、联通、电信入口。实测可用、测试中（已开放、尚未实测）和实测有问题分开显示；这些标签不再拦住启用。当地频段、SIM 和运营商网络仍会影响结果。

SQC100-1 与 P’9983 SQK100-1 已有机主三网通过反馈。SQK100-2 有官方型号记录，尚未实测。SQW100-2 的量产身份还没核实，用“—”标记，不把它写成不存在或只是频段受限。启用仍需要有效 Root、OS 10.3.3.3216、匹配的原生文件、当前 SIM 和可恢复备份。

[完整适配表](docs/COMPATIBILITY.md) · [逐台手动进度](docs/INTAKE-MANUAL-PROGRESS.md) · [本版说明](docs/RELEASE-r42.md)

## 本版更新

1. 四大家族的型号入口一起开放，P’9983 纳入同一套流程。实测进度按完整后缀记录，开放使用不等于每个后缀都通过了全部项目。
2. 开机后如果需要激活、换卡后还要处理，或连接失败，应用会给出更明确的提示。
3. 连接稳定时减少重复检查和写入。没有测量过整机省电百分比，也不表示后台完全不占资源。
4. 修复已经定位的问题：错误代理导致网页打不开，短信确认关联造成的重复收信，以及部分换卡后残留的短信忙状态。不能据此认为所有网络都不会再重复收信。

仍存在的问题：部分电信短信已经送到对方，本机却继续显示“发送中”，下一条可能因此排队。已经送达的不要反复重发。如果你有解决办法，欢迎提 [Pull Request](https://github.com/Octo-o-o-o/bb10-volte/pulls) 或在 [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues) 里说明。合入后会在项目里致谢。

## 使用方式

还没有 Root：用 Windows 或 Mac 版按引导做完整准备。刷写会清空手机，先备份照片、联系人和文件，并核对固件与加载器身份。

已经 Root：安装手机版 BAR，在手机里检查、备份并开启。装好以后，日常使用不必再连电脑。

重启后先解锁，等到 Root 生效，再给注册留几分钟。只在应用提示时再重启，不必固定连着重启三次。换卡前正常关机，换好后开机；如果提示要写入新的运营商配置，再按提示重启。Passport 切入或离开电信时，若提示还要正常重启一次，按提示做。通常不用重装。

用电脑操作时，按提示打开开发模式。只用手机版时，必须已经 Root。这两项没做到，启用会失败。电脑认不到手机时，先换一根能传数据的线和另一个 USB 口，再看驱动。官方连接软件也连不上，只说明连接本身有问题，不一定就是这根线坏了。

## 下载

| 电脑 | 系统要求 |
| --- | --- |
| Windows | **Windows 10 / Windows 11，64 位（x64）** |
| Mac · Apple 芯片 | **macOS 11 Big Sur 或更新版本** |
| Mac · Intel | **macOS 10.15 Catalina 或更新版本** |

**不支持 Windows 7、Windows 8 / 8.1 或 32 位 Windows。** Mac 通用 DMG 包含 Apple 芯片与 Intel 两种架构；**首次 Root 准备另需 macOS 14 或更新版本**。

上述 Mac 运行下限已按当前发布包内的原生程序和运行库核对，不代表旧版 macOS 或 Intel 已实机验证。Windows 11 x64 已完成打包与启动验证，Windows 10 x64 尚待实机验证；Mac 当前已在 Apple 芯片上运行，Intel 尚未实机验证。详见 [Windows 版说明](docs/WINDOWS-EXE.md)和 [Mac 版说明](docs/MACOS.md)。

官网默认使用 Cloudflare R2，无法访问 GitHub 也可下载。两处提供同版本、相同字节的文件；运行前核对完整 SHA-256。镜像提供独立线路，不保证所有地区和网络均可访问。

| 文件 | R2 直接下载 | GitHub 备用 |
| --- | --- | --- |
| Windows x64 EXE | [下载](https://bb10-downloads.octoooo.com/v0.5.0-r42/bb10-volte-0.5.0-r42-windows-x64.exe) | [下载](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r42/bb10-volte-0.5.0-r42-windows-x64.exe) |
| macOS universal DMG | [下载](https://bb10-downloads.octoooo.com/v0.5.0-r42/bb10-volte-0.5.0-r42-macos-universal.dmg) | [下载](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r42/bb10-volte-0.5.0-r42-macos-universal.dmg) |
| 完整源码 ZIP（含官网源码） | [下载](https://bb10-downloads.octoooo.com/v0.5.0-r42/bb10-volte-0.5.0-r42-experimental.zip) | [下载](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r42/bb10-volte-0.5.0-r42-experimental.zip) |
| SHA-256 校验码 | [查看](https://bb10-downloads.octoooo.com/v0.5.0-r42/SHA256SUMS.txt) | [查看](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r42/SHA256SUMS.txt) |

EXE / DMG 均内置 Python 和 Tk；Windows 同时内置 SSH/SCP，Mac 使用系统 SSH/SCP。Windows EXE 尚无 Authenticode 发布者签名。Mac 应用及 DMG 使用 Developer ID 签名、公证并附票；Intel 只核对包内架构，未在 Intel 实机运行。r14 已增加 Mac／Q20 首次 Root，以及 Q20／联通与 Passport／移动短信和短时双向通话实测。

## Windows 界面

`0.5.0-r14` 已增加[低版本 OS 升级与型号匹配](docs/FIRMWARE-UPGRADE.md)、手机授权命令前置检查及配套操作说明。升级会清空手机数据，须单独确认；旧系统真机升级闭环尚待验收。上述下载已包含这些新增流程。

![Windows 版三网自动适配界面](website/src/assets/windows-setup.jpg)

真实程序界面，使用脱敏演示状态截图；它展示安装、重启后重新检查和完成入口，不作为实机测试证据。Windows 和 Mac 使用同一套自动适配流程。

## 快速开始

下面的编号步骤是桌面引导安装。手机已经 Root 时，按上面的[使用方式](#使用方式)安装 BAR 即可。

### 桌面引导安装

1. 先确认手机准确型号、系统、已开通 VoLTE 的有效 USIM（无 ISIM）、Root SSH 与可信连接材料。**自动适配安装不等于首次 Root。**
2. 打开 Windows EXE 或将 Mac 应用拖入“应用程序”后启动。USB 连接并解锁一台手机，进入“三网自动适配”。
3. 核对当前设备，点击“备份并安装自动适配”。程序保存、下载校验原始配置，再安装、回读和启用。
4. 按手机电源菜单正常重启，解锁后等待约 3–5 分钟，点击“已重启，重新检查”。Passport 如提示还需一次正常重启，按原因说明完成。只有本次开机的 SIM、原生 IMS 注册和 LTE 均确认后才显示成功。
5. 拔掉 USB，用系统拨号器呼出、呼入，各等**接通后的屏幕计时达到 00:35**，核对双向声音、全程 LTE、运营商与自己的号码。
6. 以后正常关机换卡，再开机自动适配。Passport 切入或离开电信时，先等约 5 分钟，再正常重启一次。热插卡不在已验收流程内。

升级已识别旧载荷时，先停止并恢复旧设置、正常重启清除旧组件，再安装启用新版并正常重启。保留原始备份和升级回执。未知文件、备份缺失、通话中或独立设置冲突会阻止写入。完整说明见[三网自动适配](docs/AUTO-CARRIERS.md)。

### 首次 Root 与连接

已 Root 且有可信 SSH 的手机无需重新刷机。`0.5.0-r14` 已接入 Q10、Classic（Q20）、Passport（Q30）的自动 Root 准备和分阶段刷写。请按准确硬件型号选择对应固件；首次刷写会清空数据。Windows 三款固件的离线构建与校验已通过。r14 已完成 Windows／Passport SQW100-4 与 Apple 芯片 Mac／Q20 SQC100-2 的首次 Root、新密钥 UID 0、首次安装及正常菜单重启自动启动；原生阶段使用验收入口执行，完整 GUI 首次使用、Q10 首刷及 Intel USB 刷写尚未验收。准备至少 15 GB 空间。导入后点击“自动准备 Root 镜像”，完成后再确认刷写，见[首次使用](docs/FIRST-RUN.md)。

固件浏览器下载支持[极空间](https://t3.znas.cn/9jkbxczhAK4)及应用内百度网盘备用入口；下载后按机型校验导入，分享有效期以网页为准。它们与本页的 EXE/DMG 下载不同。见[首次使用](docs/FIRST-RUN.md)、[Mac 指南](docs/MACOS.md)和[连接说明](docs/GUI.md)。

### 源码运行与构建

```powershell
git clone https://github.com/Octo-o-o-o/bb10-volte.git
cd bb10-volte
python tools/check_release.py --check-git
python tools/gui.py
```

源码运行需要 Python 3.14（含 Tk）；完整 Root 准备使用该版本的 Zstandard 支持。原厂 `/radio/bin/ims_rrm` 不被覆盖，安装使用经过校验的独立副本；原生文件不匹配会停止。固定材料、上游来源与许可证见 [sources.json](materials/sources.json)及 [NOTICE](NOTICE.md)。

软件测试、冻结包自检、签名公证与真实手机通话分开验收。源码发布使用显式文件清单和敏感信息扫描；私钥、原始通信日志、号码与设备标识不在公开资料中。官网源码与测试见 [website/README](website/README.md)。

[Windows 打包](docs/WINDOWS-EXE.md) · [macOS 打包](docs/MACOS.md) · [源码构建](docs/BUILD.md) · [统一流程](docs/AUTO-CARRIERS.md) · [贡献说明](CONTRIBUTING.md) · [MIT 许可证](LICENSE)

历史单运营商适配、社区证据和旧版限制保留在各文档与更新日志，不能用来替代上面的当前统一流程范围。欢迎在 [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues) 提交准确机型和脱敏结果；不要上传私钥、private 目录或原始号码日志。

## 分享与支持

安装并确认注册后，完成页提供中英文“分享给好友”、GitHub Star 和可选咖啡打赏。分享只复制文案与官网链接，由你自行发送；支付宝、微信均支持 ¥9.90 / ¥19.90 / ¥29.90 / 自定义金额，是否打赏不影响任何功能。详情见[完成与支持](docs/SUPPORT.md)。

开源包只包含程序、脱敏材料及明确的公共资源；不包含 SSH 私钥、原始设备日志、个人号码、原始收款截图或原厂固件。公开收款码使用 OctoLab 图标，保留原付款去向；扫码后请在支付应用中核对收款人和金额。

<sub>[项目官网](https://bb10-volte.octoooo.com/) · [OctoLab 出品](https://octoooo.com/) · [联系开发者](mailto:octoooo@octoooo.com)</sub>
