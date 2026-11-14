# 桌面 r46 / 手机版 0.1.0.46：修复中国电信发短信卡“发送中”＋状态栏黑莓图标自动点亮

2026-11-14。macOS 仍停在 **v0.5.0-r43**，本次没有新的 Mac 安装包。

- 修复中国电信（`460-03`／`460-11`）发出短信（MO SMS-over-IMS）已送达对方但本机一直显示“发送中”并阻塞后续发信的长期问题：原厂 `ims_rrm` 的 `ImsEngineSmsMgr::onSmsDeliverySuccess`（`0xdaa5e`）收到 SIP `202 Accepted` 后仅发送传输层 `NOTIFY_SMS_OUTGOING_RP_PDU_STATUS`（`0x1014`），而原厂 `qct_rrm`（`0xe5080..0xe6234`）在 3GPP 模式下仅把 `0x1014` 视为 SIP 已接收，必须再收到 `NOTIFY_SMS_INCOMING_RP_PDU`（`0x1015`）中的 3GPP `RP-ACK` 才释放出站短信槽位并清除本地“发送中”状态；电信 IMS 短信网关返回 `202 Accepted` 后不再另发下行 SIP `MESSAGE` 承载 `RP-ACK`。本次在电信 `460-03`／`460-11` 受管临时运行副本中启用 `telecom_mo_ack`：在 `0x2ee3c6` 记录发出 3GPP MO `RP-DATA`（类型 `0x00`）的 `RP-MR`，在 `0xdaae2`／`0xdab44` 确认同一事务 `0x1014` IPC 发送成功后，复用原厂 `0x139084` TLV 编码与 `0x11ec60` 发送器补发对应 `RP-MR` 的本地 2 字节 3GPP `RP-ACK`（`03 <RP-MR>`）。移动、联通保持原路径不变，原厂 `/radio/bin/ims_rrm` 只读不改。
- 当本次开机 VoLTE 在 LTE 网络上注册成功（`ims: connected`、`200 OK`、LTE 承载在线且与当前 SIM 一致）时，后台自动通过系统原生 `/pps/system/navigator/status/bb_service?critical` 点亮右上角状态栏 `4G` 与信号格之间的 7 点经典黑莓图标，无需手动开关。
- 当移动网络关闭／开启飞行模式、回落非 LTE、失去 IMS 注册、停用恢复、进程正常退出或异常终止（含 `SIGKILL`）以及关机重启时，QNX `?critical` 描述符关闭后自动撤回显示并恢复系统默认状态，不留残影；若系统原生黑莓服务已自行点亮该图标，则保持原状态不抢占。图标读写异常已完全隔离，不影响 VoLTE 注册、通话与恢复。
- 完整保留 **r45** 跨地区三网呼入 SIP/SDP 信令兼容修复（`MediaDialog.EarlySdp=0`、`MediaDialog.Omit200OkSdp=0`）及既有下行短信 `In-Reply-To` 确认补丁；已发布的 r42／r43／r44／r45 后台停用后仍可原地升级，保留原备份和恢复机制。
- 该图标复用系统状态栏原有的黑莓基础设施指示位作为辅助提示，亮标本身不单独等同于双向语音或短信验收。已在 `SQC100-2`（中国电信 `460-11`）实机验证发出短信状态闭环、启动自动点亮、移动网络开关熄灭重亮及进程异常退出自动清理；其他型号历史记录仍按各自测试版本保留。Windows EXE 仍没有 Authenticode 发布者签名。
