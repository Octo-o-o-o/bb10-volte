# Windows r60 与手机版 0.2.5.0

- **修复双端海外设置页核心交互与布局缺陷**：
  - 桌面端 `OverseasCarrierDialog`（880×680，可滚动分页签，按钮栏常驻底部不随内容裁切）与 `AutoCarrierWindow`（780×700，带滚动条的详情区）完成双语几何自检；进入海外配置时预先提示服务运行状态、保留多运营商中其他非重叠条目、仅在当前 SIM 匹配该预设 PLMN 时注入实测 APN，并支持中文全角逗号 `，` 分隔及完整中英文错误提示。
  - 手机端原生 `OverseasCarrier.qml` 修复 `onCreationCompleted` 未就绪导致 `loadingForm` 卡死按钮的问题，接入 `overseasActionFinished` 信号与加载指示器、禁用自动纠错/首字母大写、隔离海外操作失败（不再污染主页状态错误），并将 `entry.py` Base64 解码上限与 16 KiB 原始 JSON 对齐。
- **设备端海外与原生引擎加固及去重**：
  - 修正 `IR.92` `UsePreconditions` 写入原生布尔格式 `b:false`/`b:true`（兼容旧数值配置读取）；将 `SIP_Timer_CSFB` 范围按秒级（`0..120`）校验并扩展允许 `IPsec`、`SIP_transport`、`RegExpiration` 等白名单 IMS PPS 项；勾选 `allow_isim` 且检测到真实 ISIM 应用时跳过生成合成 `imsconfig_user.xml`，保留 SIM 卡原生 ISIM 凭据；`AlwaysOn=false` 时增加有界 8 秒加载等待；`experimental` 档案保留显式 APN 优先级顺序并继续拒绝 `460-15`。
  - 修正 `lte_bands_disabled` 仅在 LTE 能力位图为 `0` 且无线开启、未驻留 LTE 时触发（消除 3G/2G/搜网期误报）；P-CSCF 主机路由同步增加失败重试队列、原生进程退出清理与运行态增量同步；扩展设备端与桌面反馈脱敏（统一复用 `redact_ipv6_addresses`，支持 `key::ipv6`、8 组带端口 IPv6 与海外 E.164/拨号号码脱敏）。
  - 统一 `unified_dca` 无线 PPS 读写封装与回滚路径，支持海外预配置原厂 `0.xml` 场景跳过不必要模板绑定、无归属匹配回退与未启动阶段保存配置后的同开机安全重试；将 `r59` 纳入 `PREVIOUS_PAYLOADS` 以支持原地安全更新。
- **海外运营商离线参考库升级至 Schema 2 与手机包瘦身**：
  - `materials/overseas-carriers.json` 升级至 Schema 2（297 项，61.5 KB，较上版缩减 33%）：提取公共 `mcc_regions` 与 `default_bb10_status: "untested"`，修复一级 MNO 排名（如 `311-480` Verizon Wireless、`440-10` NTT DOCOMO），排除测试/预留/垃圾条目并优先选取独立 `type="ims"` 行。完整保留 Apache-2.0 许可证与归属声明；从手机 BAR 与 OTA 更新包中移除 4 份运行时未读取的历史收机记录（瘦身 214 KB）。
  - 中国大陆（`460-*`）SIM 卡继续保持零回归、一键零配置与字节级不变的 XML/PPS 路径；同步更新 `tools/ai_skill.py`（新增 `overseas` 子命令）、精简 `tools/kt_isim_trial.py` 为兼容封装，并将离线窗口几何与目录校验纳入 Windows EXE `--self-test`。

macOS 下载继续固定为封板 r43。新版按实验版发行；海外参考参数与新运行时路径尚未完成实机验收。
