# 来源与第三方材料 / Third-party notices

Original Python, shell and C code, documentation and tests in this repository are licensed under MIT. The bundled helper is built from the complete source in `driver/volte_swcrypto.c`.

## Community research / 社区研究

[imqinyu/BB10DeviceVoLTEResearch](https://github.com/imqinyu/BB10DeviceVoLTEResearch), pinned at `376f492ade10efad371dca64d49fe39549820844`, is acknowledged as a source of device observations and research leads. Its NOTICE does not grant a project-wide license; the author subsequently gave explicit reuse permission in an [issue reply](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472554806). This integration contains independently written code, factual summaries and links; no upstream source snapshots, binaries, distribution archives or carrier XML are redistributed. Other contributors' permissions have not been separately confirmed; provenance questions remain in the [issue #1 confirmation request](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472384217). See [integration scope](docs/COMMUNITY-RESEARCH.en.md).

感谢 imqinyu 及其项目贡献者提供其他机型的实验记录、来电排查和移植限制。本次收录自行整理的事实与来源，并由本项目编写诊断和检查代码；未复制其源码、二进制、发行包或运营商 XML，也未将第三方材料重新声明为 MIT。作者已在 [issue 回复](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472554806) 明确允许复用其材料；其他贡献者材料的单独授权范围仍在确认，见[整合说明](docs/COMMUNITY-RESEARCH.md)。

BlackBerry/QNX firmware, stock IMS binaries and carrier XML are supplied by the owner/device and are not distributed in this repository. The toolkit checks their hashes and creates a dedicated copy on the phone. AutoRoot v4 and bb10mt belong to their original authors; obtain them from the [author's release page](https://bb10.root.sx/blog/autoroot-v4) and [bb10mt repository](https://github.com/bb10root/bb10mt) under their respective terms. MIT licensing of this toolkit does not relicense third-party materials.

libusb, LZO, OpenSSL, Git for Windows, Zig and 7-Zip retain their respective licenses. Preparation scripts use pinned sources or verified installed files and retain the associated local license files where implemented. The [design notes](docs/DESIGN.md) identify the public standards and implementation references used in the investigation; offsets and ABI details were validated against the actual device files.

## 中文说明

本仓库的Python、shell、C辅助模块、文档和测试按MIT许可证提供。辅助模块完整源码位于 `driver/volte_swcrypto.c`；构建后的模块也由本项目源码生成。

BlackBerry/QNX原厂固件、原生IMS程序及运营商XML由设备或用户自行提供。本项目在设备上读取并检查散列，生成专用副本；原厂二进制不随公开源码包分发。

AutoRoot v4 / bb10mt 属于原作者项目，请遵守其发布条件：[作者发布页](https://bb10.root.sx/blog/autoroot-v4)、[bb10mt](https://github.com/bb10root/bb10mt)。本项目不把第三方Root包重新声明为MIT。

libusb、LZO、OpenSSL、Git for Windows、Zig与7-Zip按各自许可证分发。材料准备脚本从指定来源或已验证安装目录取文件，相关许可证随本地材料保留。MIT授权不替代这些第三方许可。

排查参考了3GPP/ETSI、Qualcomm、libqmi与AOSP的公开资料，具体链接与用途见 [设计说明](docs/DESIGN.md)。最终补丁偏移和ABI以这一台设备的原生文件验证为准。

## Desktop application bundle / 桌面应用打包

The Windows EXE embeds CPython, Tcl/Tk, the PyInstaller bootloader and Microsoft Win32-OpenSSH client/crypto binaries. Full upstream licenses and notices, including the PyInstaller bootloader exception, are available offline in the application. Sources and hashes are pinned in [windows-runtime.json](materials/windows-runtime.json). No third-party Root kit, stock firmware, USB driver or personal SSH credential is embedded. The generated project icon follows the owner-requested BlackBerry-style design; it does not indicate endorsement. See [branding](docs/BRANDING.md).

Windows EXE 内置 CPython、Tcl/Tk、PyInstaller 引导程序和 Microsoft Win32-OpenSSH 客户端 / crypto 文件，原作者许可完整保留，可在应用内离线查看。未内置第三方 Root 包、原版固件、USB 驱动和个人 SSH 凭据；本项目 MIT 许可不替代第三方许可。
