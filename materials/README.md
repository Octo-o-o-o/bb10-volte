# 材料集中清单

机器可读的版本、来源和 SHA-256 在 [sources.json](sources.json)。安装载荷的逐文件哈希在 [payload-manifest.json](payload-manifest.json)。

原版固件提供极空间与百度网盘手动下载入口。百度备用分享及提取码记录在每个固件条目的 `backup_manual_download_url`、`backup_manual_download_code` 中；分享网页不进入自动下载节点。用户下载后仍须按机型进行完整 SHA-256 校验导入。

## 已有匹配 Root 的 BB10 设备

需要已验证的 BB10 设备 Root SSH 密钥、SSH 配置和 USB 网络。Windows EXE 已内置 Python 与 SSH；源码运行则需自行准备。手机端使用 BB10 自带 Python 3.2。安装器会在手机上读取并核验原厂文件，再生成 IMS 副本和 APN 文件。

`driver/devnp-volte_swcrypto_probe.so` 是本项目由 C 源码构建的 5,264 字节模块。SHA-256：

`504a6f5bdfb55f03aaf64b1a73f423e1a802e4786433f2621cd701c993224254`

## 从原版 Q10 系统开始（其他机型需对应固件与 Root）

| 材料 | 固定版本 / 用途 |
| --- | --- |
| [AutoRoot v4](https://bb10.root.sx/blog/autoroot-v4) | 2026-10-22 发布包；保留 AppWorld 触发入口 |
| [Classic / Q20 固件存档](https://archive.org/details/black-berry-classic-sqc-100) | `Q20_10.3.03.3216_STA100-1-2-3-4-5-6.exe`，完整原版系统文件；不自动运行 |
| [Passport / Q30 固件存档](https://archive.org/details/blackberry-passport-apps-software) | `Passport_10.3.03.3216.7z`，含 SQW100-1/2/3/4 原版包；不自动刷写 |
| [Q10 固件存档](https://archive.org/details/black-berry-q20) | `Q10_10.3.03.3216_SQN100-1-2-3-4-5.7z`，解出同名 EXE |
| [libusb](https://github.com/libusb/libusb/releases/tag/v1.0.30) | 1.0.30；选 `VS2022/MS64/dll/libusb-1.0.dll` |
| [MSYS2 LZO](https://mirror.msys2.org/mingw/mingw64/mingw-w64-x86_64-lzo2-2.10-3-any.pkg.tar.zst) | 2.10-3；将 `liblzo2-2.dll` 作为 `lzo2.dll` 放入构建器目录 |
| [Git for Windows](https://gitforwindows.org/) | 本次使用 2.55.0.windows.5 自带 OpenSSL 3.5.7；两个 DLL 与工作副本逐字节一致 |
| [7-Zip](https://www.7-zip.org/) | 解压 7z 固件和 libusb |
| [Python](https://www.python.org/) | 本次电脑使用 Python 3.14；材料准备使用其 Zstandard tar 支持 |
| [BlackBerry Windows USB 驱动](../docs/WINDOWS-USB.md) | 5.0.0.2 x64；七个来源分卷、EXE与CAT签名、MSI完整性均有核验步骤 |

OpenSSL 的两个文件是 `libcrypto-3-x64.dll`、`libssl-3-x64.dll`。准备脚本从 `git --exec-path` 定位，并逐个校验哈希，不从任意 DLL 下载站取文件。

完整 Root 构建的本地工作集建议预留 15 GB。将下载材料放入 `downloads/`；Root 镜像、个人密钥与 SSH 配置由准备脚本放入 `private/`。已有匹配 Root 的手机不需要重复准备大固件。

固件存档的下载散列和解压校验已通过；这不表示本项目验证过制造商签名。发布代码时，第三方固件与个人 Root 镜像保留在本地材料目录。
