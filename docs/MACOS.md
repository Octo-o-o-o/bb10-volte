# macOS 应用与手机连接

[English](MACOS.en.md) · [首次使用](FIRST-RUN.md) · [连接恢复](RECOVER-CONNECTION.md)

从 [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases) 下载 macOS 通用 `.dmg` 和同名 `.dmg.sha256`，核对 SHA-256 后打开 DMG，将 `bb10-volte.app` 拖到“应用程序”后启动。不需要另装 Python、Tk 或 OpenSSH，也不需要自行构建应用。应用使用系统 `/usr/bin/ssh` 和 `/usr/bin/scp`；私有文件保存在 `~/Library/Application Support/bb10-volte/private`。

## 已有连接的日常使用

1. 用 USB 数据线连接手机并解锁，允许 macOS 提示的附件连接。等待 USB 网络就绪；若没有网络，在手机“设置 → 存储和访问 → USB 连接”核对“连接至 Mac”。能充电或看到存储盘不等于 USB 网络成功。
2. 打开应用，连接配置可留空，点击“检查设备”；应用会验证本机保存的个人配置，成功后自动填写，下次启动会恢复。也可“手动选择”本机有效的 `ssh_config`；旧 `q10-root` 别名可自动匹配，自定义别名在“更多 → 连接选项”。
3. 核对型号、系统和服务状态。已有服务显示“4G 通话服务已启用”时可以直接使用系统拨号器，不必重装、重新授权或重新 Root。首次安装另按[GUI 指南](GUI.md)通过预检并确认；IMS 注册仍需真实呼入、呼出、双向声音及 LTE 验证。
4. 拔插 USB 后点击“重新检查”或“检查设备”，再按需“查看状态”。界面保留的上次检查结果不是实时在线指示。

2026-10-28 的单机实测中，Mac mini / Apple M6 / macOS 27.2 与 Q10 SQN100-3 / BB10 10.3.3.3216 / 联通 460-01 通过 Apple 内置 CDC-NCM 驱动自动建立 USB 网络，电脑 DHCP 获得 `169.254.0.2/30`。本轮**没有额外安装驱动，也没有手动改 IP**。这不是对所有 Mac、macOS 版本或手机 USB 模式的免驱承诺；不要预先安装旧 BlackBerry Link、把 libusb 当成 USB 网络驱动，或降低系统安全设置。

## 第一次在这台 Mac 使用：按手机现状选择

### 手机尚未 Root

本分支在 macOS 14+ 集成原生首次 Root 准备和确认后的分阶段执行，仍属**未实机首刷验收的实验功能**；已发布 r5 DMG 没有这个入口，需等待审查和新包。请先备份并核对匹配型号的方法；当前配方只支持 Q10，具体步骤及暂停条件见[Mac 首次 Root](#mac-能否首次-root)。**未 Root 的 Q20 / Passport（Q30）目前没有已集成的匹配首刷材料，不能使用 Q10 自动配方。** 这些型号需先核对具体硬件变体，再分别接入匹配固件、loader 与 Root 方法，禁止刷入 Q10 镜像。首次 Root 会清空数据，详见[首次使用](FIRST-RUN.md)。USB 网络和开发模式都不能代替 Root。

### 手机已 Root，有本人的连接材料

- **本机已有完整、有效的 `ssh_config`**：按上面的日常步骤检查，或在“首次使用 → 导入已有连接”选择它。配置引用的登录私钥和可信 `known_hosts` 必须存在，主机密钥校验保留。
- **材料在本人另一台电脑，或只有登录私钥**：经本人控制的安全方式取回这台手机的个人登录私钥及可信 RSA 主机公钥/`known_hosts`，使用“首次使用 → 恢复连接 → 有登录私钥”补建配置。Windows 配置中的 `C:\…` 绝对路径不能原样在 Mac 使用；此入口会为 Mac 创建受保护目录和正确路径。不要使用他人的共享私钥，也不要把手机的 `ssh_host_rsa_key` 服务端私钥当作电脑登录私钥。

补建配置会在 Mac 保存受保护的个人副本，核对可信来源和主机指纹后才验证手机身份及有效 UID 0；不会为此追加手机授权。详见[连接恢复](RECOVER-CONNECTION.md)。

### 手机已 Root，没有旧 Windows 文件或任何连接材料

**不需要旧 Windows 文件，但需要手机已有可用的 Root 终端及受支持的 SSH 配置。** 在“首次使用 → 恢复连接 → 没有连接文件”生成这台 Mac 的独立密钥，只导出含公钥的 `bb10-pair-编号.py`。在手机已有 Root 终端运行脚本后，由本人输入 `PAIR` 才追加授权：这会持久修改手机的 SSH 授权文件，先备份并保留原授权。新授权不会重新 Root、刷机或改通话参数。若 SSH 未运行，可另行输入 `START` 临时启动已有服务；这不保证重启后 SSH 自动开启。

新 Mac 不必通过 Finder 浏览手机内部盘，也不必安装旧 Link。可用已有可读写 microSD 卡和 Mac 读卡器传文件：Mac 导出脚本到卡并安全推出 → 卡放回手机 → 手机文件管理器将脚本复制到**设备内部存储 Downloads** → 在已有 Root 终端按应用显示的精确命令运行 → 手机文件管理器把内部 Downloads 中同编号的 `-result.json` 复制到卡 → 安全取出卡，用 Mac 读卡器导入到**原来生成请求的同一台 Mac**。保持编号与文件名不变，私钥始终留在 Mac，不要格式化或清空卡。

应用核对结果来源、请求编号、本机公钥和手机主机公钥，再以严格主机校验验证有效 UID 0。没有可用登录材料、也没有有效 Root 终端时，不能直接连接；先在手机原有 Root 工具中恢复访问。卡传文件、新授权写入和第三方 Root 布局的完整流程本轮未做实机验收，具体步骤及限制见[连接恢复](RECOVER-CONNECTION.md)。

## 连接失败时按层排查

- **USB 设备未出现**：检查解锁、数据线、附件许可及手机 USB 模式。拔插对比系统信息中的 BlackBerry USB 设备，不能只凭充电判断。
- **设备出现但无网络接口**：检查实际驱动绑定和“连接至 Mac”模式。不要猜 `enX`；接口编号因电脑和插拔而变。未确认原因前不安装旧驱动或系统扩展。
- **网络接口存在**：手机默认 `169.254.0.1`，电脑默认 `169.254.0.2`；确认到手机的路由和实际源地址属于该 USB 接口。部分旧授权限制来源为 `169.254.0.2`，换成其他电脑地址后认证失败不能据此判定密钥坏了。应用不会自动改其他网卡、默认路由或 DNS；需要临时配置时先记录原值并在结束后恢复。
- **SSH 失败**：网络不通、TCP 22 拒绝、主机指纹不符、登录私钥未授权和 Root 未就绪分别处理。主机指纹变化时核对原有可信材料，不关闭校验；已有有效 Root SSH 不要求一直开启开发模式。
- **已连接但权限诊断未完成**：保留报错，不把远程命令失败当成网络断开，不为消除报错降低手机安全设置。已安装服务运行时占用通话配置是预期状态，不应据此重装。

## 当前发布包与验证范围

真实测试的是与 GitHub `v0.3.2-r5` 附件字节一致的 DMG：签名、公证、Apple Silicon 实际运行、严格 SSH/UID 0、设备与现有服务读取、机主手动双向通话及 USB 重连通过。机主确认双向声音正常、全程 LTE；本轮没有记录实际通话时长，也没有重启手机。Intel 仅核验随包架构，没有 Intel 实机结论。

**已发布 r5 的“首次使用”向导仍有已知缺陷**：使用 Python `-c` 检测 Root，被当前手机的安全限制拒绝后误报连接问题；USB 字段也可能显示“待确认”。日常主界面的“检查设备”已实测可用。当前仓库针对这些问题的源码修复和界面指引需要独立审查、测试及重新打包；本记录不表示旧 r5 DMG 已包含修复，也没有发布新的 DMG。初次授权、初次 Root、安装/重装服务、长时间稳定性、其他机型/运营商仍不在本次 Mac 验收内。

详见[逐层验收](VALIDATION.md#2026-10-28mac-发布包与-q10-日常实机连接)、[脱敏证据](../materials/macos-device-validation-2026-10-28.json)；构建方法在下方，普通用户无需执行。

## Mac 能否首次 Root？

上游有 Mac 原生技术路径，**本分支已集成实验性的首次准备与分阶段刷写，但未进行 Mac 首刷实机验收**。已发布 `0.3.2-r5` DMG 不包含这部分代码，不要把本指南当成旧 DMG 已有的功能。

### 实验流程与条件

1. 仅适用于当前固定固件配方的 Q10，先从手机“关于”核对 `SQN100-1` 至 `SQN100-5` 变体并备份数据。准备至少 15 GB 空间。**首次刷写会清空手机数据**；已 Root 只缺连接材料时使用恢复连接，不用首刷修复密钥。
2. 在“首次使用 → 首次 Root”选择实际变体，点击“自动准备 Root 镜像”。**此步骤只在 Mac 准备文件，不连接 BootROM、不刷手机**。工具链要求 macOS 14+，与日常 GUI 的系统范围分开；应用获取固定官方 AutoRoot/7-Zip 和匹配架构的 bb10mt，以及固定 Homebrew 官方 libusb/LZO 包。只解包到个人工作目录，保留许可并核验 SHA-256，不需要安装 Homebrew、全局库或关闭安全设置。
3. 每套工作目录生成独立个人登录密钥和手机主机密钥，替换默认授权、保留 AppWorld。构建后核对原厂分区和 radio 散列；原生执行使用构建出的 unsigned OS 载荷及原版 signed radio，不在 Mac 双击 Windows `.exe` autoloader。镜像构建与实际刷入分别验收。
4. 核对备份和机型后，勾选“已备份并核对机型，同意清空手机数据”；Mac 还须勾选“已核对手机尚未 Root，理解 Mac 首刷尚未实机验收”。点击“开始刷写 Root”后仍需单独确认清空。程序再次验证唯一 USB 手机及实际变体、镜像/工具散列和电脑 USB 地址 `169.254.0.2`；已有有效 Root 或明确密钥问题会阻止重刷。不能通过更改其他网卡、默认网关或 DNS 来消除错误。
5. Mac 打开可见 Terminal 运行 OS/radio 阶段，密码只在原生终端需要时输入，输入隐藏，不进入 GUI 参数或日志。**任何原生错误、缺少逐文件完成证据、取消或未知退出都会暂停并保留状态，不自动重试或继续 radio**。上游可能在报错后仍输出 success，程序不以这一行或 exit 0 单独判定成功。Windows 固定配方的“100% + 两条安全提示 + 退出 73”续跑例外不适用于 Mac 原生工具。
6. 真正刷写完成后仍需手机开机完成必要设置，按原 Root 方法启动，回到连接检查严格验证手机身份及有效 UID 0。Root 成功不等于 VoLTE 通过，通话服务需另按预检和真实通话流程验收。

该实验入口不代表所有 Mac、Root 包或 Q10 变体已通过实刷，也不会重新刷写本轮已启用的手机。若 OS 签名阶段出现原生错误，当前必须停下；在单独的未 Root 备机验收之前，不猜测可忽略的异常或自动接续 radio。固定工具和依赖见[Mac Root 工具清单](../materials/macos-root-tools.json)。

### 原作者与源码依据

[AutoRoot v4 原作者说明](https://bb10.root.sx/blog/autoroot-v4)给出 Linux/macOS 的 `bb10mt batch` 镜像构建用法。固定提交 [`d45b66b` 的 README](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/README.md)、[Darwin 构建目标](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/bb10mt.lpi)与 [USB 刷写实现](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/uflash.pas)包含 Apple Silicon/Intel 原生目标及 flash/BootROM 逻辑。源码存在这些能力不等于本机实刷成功。

本机 arm64 原生工具 `--help`、Q10 离线准备与 `batch` 构建已完成；4 个原厂分区的大小/散列及 radio 原散列核对通过，产出个人密钥对应的 unsigned OS 与原版 signed radio。源码 Root 诊断另外通过已有可信连接只读验证有效 UID 0，临时目录检查前后均为原有 22 个。**这些不证明 Mac 首刷成功**；没有执行会连接 BootROM/重启手机的 `info`、`loader` 或 `flash`。已启动操作自然结束后，按用户选择只开发、不再新增测试；Q30 的具体变体和匹配首刷材料仍待就绪。见[开发检查记录](../materials/macos-development-2026-10-29.json)及[独立验收范围](VALIDATION.md#本分支-mac-首次-root-集成不代表实刷验收)。

## 在 Mac 上准备构建

使用新的独立工作目录。以下脚本从 [固定清单](../materials/macos-runtime.json) 获取 Python Software Foundation 的官方 Python 3.14.9 安装包，核验 SHA-256 和 Installer 签名，仅解包到用户工作目录，不运行安装器、不更改系统 Python。安装包内含 Tcl/Tk 及 universal2 运行时；脚本在同一工作目录创建独立 venv 并安装[固定构建依赖](../tools/macos-freeze-requirements.txt)。首次下载依赖需要联网。

```bash
python3 tools/prepare_macos_runtime.py --build-root "$HOME/WorkSpace/bb10-volte-build"
```

如果工作目录已存在，请选择新的目录，脚本不会覆盖。已提前下载官方包时可加 `--installer /path/to/python-3.14.9-macos11.pkg`，仍会核验哈希与签名。Python 3.14.9 的原生运行库最低版本为 Intel macOS 10.15 / Apple Silicon macOS 11；最终应用的系统范围仍以实际构建和验收为准。

## 构建、签名与公证

1. 确认钥匙串中有站外分发所需的 **Developer ID Application** 身份，并已配置 `notarytool` Keychain profile。私钥和公证凭据留在钥匙串，不放入仓库。
2. 以登录用户 GUI 会话运行构建；SSH 会话可能无法访问数据保护钥匙串。`macos_session_job.py` 为每次操作创建独立任务目录并输出日志与退出码：

   ```bash
   build="$HOME/WorkSpace/bb10-volte-build"
   python3 tools/macos_session_job.py --job-root "$build" --cwd "$PWD" \
     --environment "$build/build-environment.json" -- \
     "$build/venv/bin/python" "$PWD/tools/build_macos.py" --identity 'Developer ID Application: YOUR NAME (TEAMID)'
   ```

   构建器采用显式资源清单，生成 universal2 `.app`，签署内嵌组件、启用 Hardened Runtime，并逐项回读资源和开源许可。输入或哈希不符会停止。
3. 用 `codesign --verify --deep --strict --verbose=2 dist/bb10-volte.app` 检查签名。使用 `ditto -c -k --keepParent` 压缩 `.app` 并以 `xcrun notarytool submit --keychain-profile <profile>` 提交；等待状态为 **Accepted** 后对 `.app` 执行 `xcrun stapler staple` 和 `validate`。
4. 在新的 staging 目录中放置已附票据的 `.app` 与指向 `/Applications` 的快捷入口，用 `hdiutil create -format UDZO -srcfolder <staging>` 创建 DMG；用同一 Developer ID 签名 DMG，并提交 Apple 公证。接受后对 DMG 执行 `stapler staple` 与 `validate`。
5. 使用 `codesign`、`spctl`、`stapler` 检查应用和 DMG。以只读方式挂载 DMG，并在拒绝网络连接的进程沙盒中运行应用的 `--self-test`；另外验证图标、配置编辑、帮助和内置文件。沙盒限制的是应用进程，不等于整个 Mac 已断网。
6. 发布 DMG、SHA-256、构建和验收记录。未在真实手机上执行的步骤保持未验证标记。公证提交与签名时间戳需要维护者联网；附加票据后用户可在离线状态取得随包的公证证据。

[PyInstaller 架构与签名](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support) · [Apple Developer ID](https://developer.apple.com/developer-id/) · [Apple 公证流程](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
