# macOS 与 DMG 可行性

[English](MACOS.en.md) · [Windows EXE](WINDOWS-EXE.md)

**可以从同一份 GUI 源码制作 macOS `.app`，再包装为 `.dmg`；不能把 Windows EXE 转成 DMG。** 必须在 Mac 上重新冻结 Python/Tk 和应用资源。当前发布物仍为 Windows EXE，尚未交付或验证 Mac DMG。

2026-10-27 只读环境检查：维护者 MacBook Pro 为 Apple Silicon，钥匙串查询返回 1 个有效 **Developer ID Application** 签名身份，`notarytool` 可用；Mac mini 未返回这种身份。没有导出证书私钥、修改钥匙串或提交 Apple 公证。MacBook Pro 的默认 Xcode Python 为 3.9.6，不能直接当作本项目固定构建环境使用，应选独立的 Python 3.14 + Tk 环境。该证据只证明签名身份可见，不证明已实际签名或取得公证凭据。

## 已整理的跨平台边界

- Tk GUI、配置校验和手机工作流的主体可复用；窗口图标在 Windows 使用 ICO，项目同时提供 [ICNS](../assets/app.icns)。
- 打包后的 Mac 使用系统 `/usr/bin/ssh`、`/usr/bin/scp`，无需另下 Windows SSH；个人数据路径为 `~/Library/Application Support/bb10-volte/private`。
- 手机工作流已限定旧 QNX SSH 所需的 AES-CTR 和 RSA 协商，主机密钥仍严格校验。实际 macOS 客户端与手机传输需要再测试。
- Root 镜像准备、刷写和 Windows USB 驱动流程依然是 Windows 路线；DMG 不包含它们。现代 macOS 能否识别这台 BB10 的 USB 网络是独立的实机待验项，不能因为 `.app` 能启动就认为手机连接可用。
- 可先通过已有可达网络和个人 SSH 配置验证 Mac GUI，再验收直接 USB。不要为此复制他人的私钥或盲改网络设置。

## 维护者构建、签名与公证路线

1. 在 Mac 的独立构建目录准备固定版本 Python、Tk、PyInstaller 和本项目公开文件；先运行源码回归测试和 GUI。不要复用 Windows `.venv` 或原生构建产物。
2. 使用 PyInstaller 的 **`--onedir --windowed`** 生成 `bb10-volte.app`。仅加入 Windows 构建器同等的显式资源清单，改用 ICNS，去掉 Windows SSH 和 Windows 运行时材料；保留实际 Mac Python/Tk 及 PyInstaller 的完整许可证。不要把整个源码工作目录作为 `--add-data` 输入。
3. 传入 `--codesign-identity`，选择本机 **Developer ID Application** 身份；PyInstaller 会签嵌入的 Mach-O 组件，并启用 Hardened Runtime。不能只签最外层应用，也不要把 Apple Development 当成站外分发身份。先从默认最小权限构建，按真实签名诊断处理，不关闭 Gatekeeper。
4. `codesign --verify --deep --strict --verbose=2 bb10-volte.app` 验证，测试启动、Tk、帮助、配置和手机预检。使用 ARM64 Python 先生成 ARM64 版本；Intel 需要单独 x86_64 构建，或所有依赖均支持 universal2 后生成通用包。
5. 将 `.app` 和指向 `/Applications` 的安装快捷入口放入新 staging 目录，用 `hdiutil create -format UDZO -srcfolder <staging> bb10-volte.dmg` 创建磁盘映像，再用 Developer ID 签名 DMG。
6. 用本机已配置的 Keychain profile 执行 `xcrun notarytool submit bb10-volte.dmg --keychain-profile <profile> --wait`；取得 **Accepted** 后执行 `xcrun stapler staple bb10-volte.dmg` 和 `xcrun stapler validate bb10-volte.dmg`。如需脱离 DMG 单独分发 `.app`，也应让应用附上其公证票据。
7. 用 `spctl --assess --type open --context context:primary-signature --verbose=2 bb10-volte.dmg` 核验，并在另一台 Mac 测试带下载隔离属性的安装和离线首次启动。发布带 SHA-256 的签名 DMG，不能把本机签名命令成功当作 Gatekeeper 实测通过。

构建依赖首次获取、Apple 签名时间戳和公证提交需要维护者联网；公证票据附入文件后，用户安装时无需依赖在线查询来取得票据。运行时仍只需要手机连接和运营商网络。实际最低 macOS 版本要依据选定的 Python/Tk 和最终构建验证确定，暂不承诺旧系统覆盖范围。

这是可行性与执行路线记录，尚未完成 `.app` 构建、签名、公证、USB 连接或 Mac 通话验收。证书和公证凭据只应留在 Mac 钥匙串，不能加入仓库或 EXE。

依据：[PyInstaller macOS 签名与架构](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support)、[PyInstaller 构建说明](https://pyinstaller.org/en/stable/usage.html)、[Apple Developer ID](https://developer.apple.com/developer-id/)、[Apple 公证流程](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)。
