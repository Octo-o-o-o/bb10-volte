# macOS 应用与 DMG

[English](MACOS.en.md) · [Windows EXE](WINDOWS-EXE.md)

从 [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases) 下载 macOS 通用 `.dmg` 和同名 `.dmg.sha256`，核对 SHA-256 后打开 DMG，将 `bb10-volte.app` 拖到“应用程序”后启动。不需要另装 Python、Tk 或 OpenSSH，也不需要自行构建应用。发布附件的签名、公证与实测状态以 Release 和对应验收记录为准；应用包含 Apple Silicon / Intel 架构，Intel 实机尚未测试。下文的构建步骤面向开发者。

应用使用系统 `/usr/bin/ssh` 和 `/usr/bin/scp`，私有记录保存在 `~/Library/Application Support/bb10-volte/private`。需要针对手机本人配置已验证的 Root SSH 密钥和主机密钥。默认连接别名为 `bb10-root`；明确的旧 `q10-root` 配置会自动匹配，也可主动导入。首次使用向导提供设备端步骤提示，首次 Root 刷写目前需先在 Windows 完成，见[首次使用](FIRST-RUN.md)。

Q10 SQN100-3 / OS 10.3.3.3216 / 北京联通 460-01 是当前唯一的实机通话记录；Q20 / Q30 显示未实测适配，可在明确试用并通过所有技术检查后尝试。电脑上能够启动应用不代表 Mac 到手机的 USB 网络已经验证；当前没有 Mac 直连 BB10 的通话验收。首次 Root 与刷写仍需该机型自己的匹配固件和方法，不要将 Q10 镜像刷入其他型号。

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
