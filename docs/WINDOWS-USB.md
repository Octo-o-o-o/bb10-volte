# Windows USB 驱动与连接

本次使用 BlackBerry USB Drivers **5.0.0.2** 的 x64 组件。电脑已经能稳定识别 Q10 的 BlackBerry USB 设备和 USB 网络时，无需重新安装。

## 材料与离线核验

驱动来自 [安装包存档](https://github.com/anpho/BlackBerryInstallers)，具体七个分卷、文件大小、SHA-256 和提取后散列固定在 [usb-drivers.json](../materials/usb-drivers.json)。原 EXE 的 Authenticode 发布者实测为 **BlackBerry Limited**，驱动 CAT 的签名为 **Microsoft Windows Hardware Compatibility Publisher**，两者验证为 `Valid`。单独 SYS 没有内嵌签名，不等于整个驱动包没有目录签名。

```powershell
python tools/fetch_materials.py --with-usb-drivers
python tools/prepare_usb_drivers.py --seven-zip "C:\Program Files\7-Zip\7z.exe"
```

准备脚本只解包和核验，生成 `private/windows-usb/`：先核对七个分卷和完整 EXE，再从签名包内清单核对 CAB 与 x64 MSI，最后逐文件检查 USB 驱动和 CAT 签名。它不会安装驱动。

## 首次安装

安装需要 Windows 管理员权限。先保存电脑上的工作，在项目根目录的管理员 PowerShell 中执行：

```powershell
.\tools\install_usb_drivers.ps1
```

脚本安装已核验的 RIM USB INF 和同包 x64 Device Manager MSI，写安装日志，并禁止安装器自动重启。退出码 `3010` 表示 Windows 要求稍后重启。

旧版厂商 MSI 带有强制停止部分进程的自定义动作；脚本发现 `nginx`、`PeerManager`、`tunmgr`、`RimDeviceManager` 等正在运行时会先停止安装。根据具体进程的用途处理后再继续，不能无差别结束进程。

此配方沿用本机已成功使用的安装路径。公开脚本已做语法及材料验证，本轮整理过程中没有再次执行系统安装。

## 验证与排查

1. 手机开机并解锁，用数据线连接。设备管理器应出现 BlackBerry 设备；网络适配器中应出现 USB 网络。
2. 本机实测电脑端 USB 地址 `169.254.0.2`，Q10 地址 `169.254.0.1`。网络共享与普通 USB 数据网络是不同接口。
3. Root 就绪后用对应自有密钥的 SSH 配置连接。重新刷入另一套自有主机密钥后，应核对那套镜像的公钥，不能简单关闭主机校验。
4. 重启后 USB、桌面、4G、Root/SSH 和 IMS 服务可能先后就绪。一次连接拒绝不等于手机启动失败；先核实当前阶段。
5. 电脑完全没有枚举 USB 设备时，先检查数据线、连接和手机解锁状态。不要把物理连接消失误判为 IMS 认证故障。

不需要关闭 Windows 驱动签名校验或更改 UAC。安装和连接日志留在私有材料目录。
