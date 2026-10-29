# bb10-volte Windows EXE

[English](WINDOWS-EXE.en.md) · [GUI 操作](GUI.md) · [macOS / DMG](MACOS.md)

下载 `bb10-volte-0.3.3-r1-windows-x64.exe`，双击即可启动。Python、Tcl/Tk、SSH/SCP、运营商模板、固定手机端载荷、操作指南与第三方许可均已内置。不需要在测试者电脑安装 Python、OpenSSH、Git 或 Codex。EXE 为单文件便携版，启动时会解压到系统临时目录，正常退出后清理；启动和正常使用不需要管理员权限；首次驱动安装会单独请求 Windows UAC。

目标为 Windows 10 / 11 x64，实际打包与启动验证在 Windows 11 x64 上完成。当前 EXE 未做 Windows Authenticode 签名；发布页同时提供 SHA-256。Apple 开发者证书不能用来签 Windows EXE。

## 发给测试者

1. 从公开的 [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases) 下载 EXE 和对应 `.exe.sha256`，也可直接传送这两个文件。
2. 已 Root 手机使用自己的可信连接；首次准备可进入“首次使用”，自动获取工具、驱动和 Q10 Root 材料。Q20 / Q30 首次 Root 必须使用匹配机型的方法。见[首次使用](FIRST-RUN.md)。
3. 打开 EXE，点击“检查设备”自动查找已有个人配置；也可主动导入。默认 `bb10-root` 与旧 `q10-root` 都支持，别名不限定手机型号。
4. 选择运营商模板或编辑配置，然后运行预检。Q20 / Q30 显示“未实测适配 · 可实验试用”，需勾选试用且通过所有技术检查。
5. 预检通过并确认备份后，安装、回读、启动、观察注册。最后用手机系统拨号器做真实呼入、呼出和声音验收。

OS 仍要求 **10.3.3.3216**，原生文件哈希、ARM32、SIM 类型、APN 和原厂配置检查不放宽。Q20 / Q30 未完成实机适配验收，不能刷 Q10 Root 镜像。

## 离线边界

**电脑无需接入互联网即可运行已经准备好的 EXE 和手机服务流程；首次 Root / 驱动向导仅在用户主动进入并确认时获取缺失材料。** 手机注册 IMS 与实际通话需要运营商网络。

| 阶段 / 材料 | EXE 内置 | 什么时候需要获取 |
| --- | --- | --- |
| Python 3.14.9、Tcl/Tk 9.0.4、SSH/SCP、crypto DLL | 是 | 启动不下载，不依赖系统 Python / SSH |
| 固定手机端脚本、辅助模块、JSON 模板、指南 | 是 | 运行不下载；固件原生文件在手机上校验 |
| 黑莓 Windows USB 驱动 | 否 | 向导自动下载、解包与校验，确认后通过 UAC 安装；也可预先缓存 |
| AutoRoot v4、对应机型固件、首次 Root 所需库和工具 | 否 | Windows Q10 向导自动获取和准备；首次下载需要互联网，缓存完整后可离线准备 |
| 每台手机的私钥、SSH 配置、主机信任记录 | 否 | 为设备单独生成并验证；不是从网上下载共用密钥 |
| 开通 VoLTE 的 SIM / LTE / IMS 网络 | 不适用 | 注册和通话需要运营商服务，不能在飞行模式下验收 |
| 账号、在线激活、付费校验、遥测、自动更新、AI API | 无 | 没有这些运行依赖 |

正常业务使用 SSH/SCP 到所选手机，并可读取直接 USB 地址的匿名机型发现信息。首次准备按固定清单下载 HTTPS 材料。自定义 `ssh_config` 可自行指定网络主机、代理或跳板，这会改变连接路径；准备步骤只运行已核验的固定工具与本项目脚本。操作系统本身的证书、杀毒或信誉查询不属于本程序逻辑，因此不承诺整台 Windows 电脑零网络流量。

首次准备的固定下载来源和散列见 [sources.json](../materials/sources.json)、[usb-drivers.json](../materials/usb-drivers.json)。Q10 的材料包括 AutoRoot v4、原版固件、libusb、LZO、7-Zip、固定 Git for Windows / OpenSSL 文件及 USB 驱动；Q20 / Q30 的对应固件仍由适配者核实。**没有一种材料必须在每次运行时重新在线下载**；可以预先获取、校验后离线传递。

## 保存位置与升级

EXE 的私有日志和临时请求使用 `%LOCALAPPDATA%\bb10-volte\private`，不写进临时解包目录或 EXE 所在目录。用户导入、导出的 JSON 配置使用自己选择的位置。升级时退出旧程序再换新版 EXE，个人 SSH 文件和用户目录中的记录保留。源码运行时仍使用项目内 `private/`。

“版本与开源许可”显示打包版本和完整第三方许可；“使用与恢复指南”读取包内文档。程序不检测更新，维护者以新文件交付版本。

## 打包与检查

维护者在 Windows x64 上安装 Python **3.14.9**（含 Tcl/Tk **9.0.4**），在源码目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools/windows-freeze-requirements.txt
.\.venv\Scripts\python.exe tools/build_windows.py
```

构建工具首次从 [固定 Windows 运行时清单](../materials/windows-runtime.json) 获取官方 OpenSSH ZIP 和 Tcl/Tk 许可；检查 SHA-256，在线构建额外验证微软签名。只取客户端和 crypto DLL，不安装 SSH 服务。当前固定上游版本名含 `Preview`，不把它宣称为稳定版。实际 Q10 连接使用经验证的 AES-CTR；旧 QNX SSH 宣告的 GCM 会让新客户端握手断开。旧 RSA 算法仅限此手机连接，已知主机严格校验保留。

材料和构建依赖均已缓存时，可以运行 `tools/build_windows.py --offline`；缓存缺失或散列不符立即停止，不自动替换。可用以下离线诊断验证发布文件：

```powershell
$app = Start-Process .\dist\bb10-volte-0.3.3-r1-windows-x64.exe -ArgumentList '--self-test selftest.json' -Wait -PassThru
Get-Content .\selftest.json
```

自检不连接手机，检查解释器、Tk 界面、编辑器往返、SSH/SCP、载荷散列和持久目录。构建脚本还回读 EXE 内部归档逐项校验资源，拒绝私钥、个人配置、固件和个人镜像混入。`--preflight-report report.json --ssh-config <个人配置>` 可执行只读兼容性预检；会在手机上传并清理检查脚本，不改通话配置。

实测范围和未覆盖项见 [桌面打包验收](../materials/desktop-package-acceptance.json)。隔离 PATH 的实测不是一台完全没有安装过 Python 的全新虚拟机；Windows 10 和 Q20 / Q30 实机仍待验证。
