# Windows r63 与手机版 0.2.5.0

- 反馈包收集器不再读取处于隐藏状态的横幅文案（如未触发时的“刷写暂停”提示），`SetupWizard` 与 `FirmwareDialog` 在未锁定时同步清空该标签文本，避免误导排查。
- Windows 驱动安装因冲突进程（例如 `nginx`、`RimDeviceManager`、`PeerManager`、`tunmgr`）停止时，状态栏直接显示具体冲突进程名称，并在“Windows 驱动”页补充安装前关闭冲突程序的提示。
- USB 已连上但未能识别机型时，本地 USB 探测记录脱敏原因码（`discovery_reason`，如 `no_link_local_30`、`http_401`、`http_403`、`timeout`、`connection_refused`、`multiple_usb_links`），在连接检查与反馈包中明确提示排查方向，并说明离线下载固件可先拔线手动选型号。

手机版仍是 0.2.5.0，没有新的手机载荷。macOS 下载继续固定为封板 r43。本版没有新的通话、短信或数据验收。
