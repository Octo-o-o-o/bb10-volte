# Windows r55 与手机版 0.2.1.0

- **刷写排障可视化与安全解锁**：首次 Root 刷写与原版系统升级现在会记录是否真正进入写入阶段（`writing_started`）；若未完成（如缺少 BlackBerry USB Bootrom 驱动、连接超时或密码提示中断），刷写控制台不再瞬间闪退而是暂停展示退出码与原因，并将脱敏日志摘要自动写入反馈包。`root-flash.lock` 暂停期间顶部新增「查看刷写日志并解除暂停…」入口，支持确认手机状态后安全解除暂停并保留全部原镜像、密钥与日志；Windows 驱动准备与安装不再被 `root-flash.lock` 阻塞，且开机已有 USB 网络时仍允许补装 Bootrom（`RimUsb`）驱动。
- **修复 Windows 驱动 PowerShell 策略拦截与中文用户名 SSH 解析失败**：`prepare_usb_drivers.py`、`install_driver_kit()` 与构建签名校验统一优先调用 System32 Windows PowerShell 5.1 并显式传入 `-ExecutionPolicy Bypass`，避免严格执行策略下报 `CalledProcessError`。配对与 Root 密钥生成统一添加 `-C ''`，公钥读取兼容含中文用户名/主机名注释的 `.pub` 文件，彻底修复 `UnicodeDecodeError`。
- **修复旧版目录阻塞死锁与后台阶段清理锁竞争**：`unified_install.probe()` 将 `unvalidated_legacy_installation` 等旧版/Root 方案断言转为明确 `scope_error`，手机版与桌面版均给出清晰清理与重启指引（不再报晦涩的 `remote_operation_failed`）。`cleanup-stage` 移出非阻塞 `management_lock()`，消除换卡重启或停用恢复期间与后台服务的锁竞争。
- **新增脱敏错误码与预启动 LTE-only 自动回滚**：后台 `public_status()` 在本次开机异常时导出白名单 `error_code`（同步至桌面版、手机版与脱敏反馈包）；若准备阶段在写入日志前异常中止，在空闲条件下自动恢复原 4G/3G/2G 选网模式，避免手机卡死在“Searching”。同时优化等待 4G/LTE 数据阶段提示、通话中勿切移动网络提醒、Defender 瞬时锁文件重试、Passport 旧版主界面引导以及 `kt_isim_trial.py` 默认 `--host bb10-root`。

macOS 下载继续固定为封板 r43。新版按实验版发行。
