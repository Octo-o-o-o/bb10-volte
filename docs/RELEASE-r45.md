# 桌面 r45 / 手机版 0.1.0.45：跨地区三网呼入 SIP/SDP 信令兼容修复

2026-11-14。macOS 仍停在 **v0.5.0-r43**，本次没有新的 Mac 安装包。

- 统一移动、联通、电信三网运行副本中的呼入 SIP/SDP 信令配置：将 `MediaDialog.EarlySdp` 设为 `0`，不在可靠的 `180 Ringing` 中重复附带已在 `183 Session Progress` 协商过的 SDP，也不在非可靠 `180 Ringing` 中发送预览 SDP，避免部分省份中兴（ZTE）SBC/TAS 收到重复 SDP 后立即取消呼入，或外省彩铃（CAT AS）／SBC 因 `180` 携带 SDP 与 `P-Early-Media: inactive` 导致主叫听不到回铃音。
- 同时将 `MediaDialog.Omit200OkSdp` 设为 `0`：当呼入 `INVITE` 未通过可靠的 `18x`（`100rel`）完成 SDP 应答时，接听发出的 `200 OK (INVITE)` 始终保留 RFC 3261 要求的 `application/sdp` 应答，避免非 `precondition` 互通呼叫或振铃期间发生早期 `UPDATE` 后接通异常。标准 `precondition` 呼叫（`SDPState 0xd`）仍走原空包 `200 OK` 分支，不改变既有本地正常通话路径。
- 原厂 `/radio/bin/ims_rrm` 仍只读不改，修改仅作用于受管临时运行副本并完成固定 SHA-256 与 ARM/Thumb 指令仿真核验。已发布的 r42／r43／r44 后台停用后仍可按原校验直接升级，保留原备份和恢复机制。
- **已经能用的手机不需要重新刷机或重做 Root。** 外地遇到呼入振铃即断、对方无回铃音或接起异常时，安装手机版 **0.1.0.45**（或用 Windows **r45** 更新），先在应用内停用当前 VoLTE，再更新后台并正常重启测试。

本次修复已完成离线原生指令仿真与回归校验，尚未取得外省实机回执，不将离线仿真冒充各地运营商真机验收。历史实测、未测及电信短信状态显示已知问题仍按原版本保留。Windows EXE 仍没有 Authenticode 发布者签名。
