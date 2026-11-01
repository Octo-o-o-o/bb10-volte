# BB10 短信域选择与重复接收排查

[English](SMS-DIAGNOSTICS.en.md)

2026-11-01：已加入发送侧配置候选修复和离线诊断工具；后续已定位并实现[MT ACK 原生关联修复候选](SMS-ACK-NATIVE.md)。**短信实机验收仍未完成，不能宣称 MT 重复已消除。** 本次没有连接、改写手机或发送短信。此前九项组合的验收范围是语音、换卡和显示，不能当作短信验收。

反馈为 Q20、10.3.3.3216、AutoRoot v4、联通 460-01：MT 每隔约 30 秒重投，共四次且 RP 参考号变化；MO 先尝试 CS，随后出现 `no retry default`。只有反馈摘要，没有该设备原始日志，以下区分静态分析、历史日志与尚待验证的推断。

## 发送侧：配置声明与实际域选择是两步

固定版本的原厂 `ims_rrm` 中，LTE 的短信域选择位于 `0x63378`。已注册且内部 `smsIP` 状态为真时返回 PS（2）；否则返回 CS（1）。这与语音域选择分开，现有语音补丁不会自动启用短信 PS。这里讨论本项目支持的 LTE 路径，不能推广到其他固件或 WFC。

`IMS_services` 中声明 `sms` 只声明能力。本仓库此前没有显式应用下面的原生短信策略：

```text
PPS 对象：/pps/services/carrier_config/ims/ims
字段：SMS_Over_IP_Network_Indication:b:true
```

证据链为 IMS carrier 字典 ID `0x45` → `0x105692` 调用配置 setter `0x93cda` → 配置 ID `0x66` 经 `0x9091c` 写入域选择对象的 byte `+9`（`0x9097e`）。原厂二进制 SHA-256 与定位记录见[脱敏证据](../materials/sms-investigation-2026-11-01.json)。

另一个输入是 `/pps/services/carrier_config/radio_common/cellular_protocol_configuration` 的 `sms_over_ip_indication:b:true`，其原生应用路径也进入上述 setter。候选修复选择 IMS 对象的字段，没有额外写 radio_common。它修正的是原生 IMS 的短信域决策；外层蜂窝服务是否仍先尝试 CS，需要在实机 MO 日志中验证。

[service.py](../device/service.py) 现在让 `ims.sms=true` 同时声明 SMS 服务并写入这个布尔值；关闭 SMS 时写 `b:false`。初次应用前保存字段原值，停用时恢复原值或原来的缺失状态，遇到并发配置冲突拒绝覆盖。旧安装必须先恢复再扩展配置日志；统一升级器支持备份并更新这份服务文件。

这不是无条件强制 PS：仍要求 IMS 注册和原生网络状态允许 SMS。`SmsConfig: smsOverIp[0]=1` 的默认值日志也不能证明 setter 已运行：历史日志中它与 `domain 1` 同时出现。修改 `routingPreference`、看到 `allowVoLteProvisioning=0` 或补造 `imsconfig`，均不足以证明短信域已改变。

`ImsApiSmsSend` 的 `no retry default` 出现在构造函数 `0x7cfa8`：CS 已尝试时把默认重试策略置零。它本身并非“禁止首次 IMS 发送”的总开关。`process`（`0x7c0de`）还检查域选择、网络失败禁用状态和之前的 IMS 尝试次数。应先确认一次 MO 是否进入 `domain 2`、`sendSms=1`；若仍失败，再定位该次实际拒绝原因。本次没有修改原生重试次数，也没有加入自动重发短信。

## 接收侧：RP 参考号正确仍不足以完成关联

根据 [ETSI TS 124 341 V12.6.0 §5.3.2.4](https://www.etsi.org/deliver/etsi_ts/124300_124399/124341/12.06.00_60/ts_124341v120600p.pdf)，MT 的 RP-ACK/RP-ERROR 通过另一条 SIP MESSAGE 上报：`In-Reply-To` 对应下行 MESSAGE 的 `Call-ID`，Request-URI 和 To 使用下行 `P-Asserted-Identity` 指示的 IP-SM-GW。ACK 使用新的自身 Call-ID，并不能单独判为错误。

需要在同一事务中核对 RP 参考号、关联头、网关目标和实际 SIP 响应。“delivered over SIP” 的日志文案不能替代这些检查。若网关无法关联，重投是合理怀疑；但当前证据不能把这次四次重投定性为联通 IP-SM-GW 的已知缺陷，也不能认定所有 SIP 400 都是相同原因。

不能仅按 RP 参考号去重：反馈中的重投每次都换参考号。按正文去重又可能吞掉用户确实收到的相同内容短信。本次未给 Hub 加掩盖症状的去重层。

## 其他设备与运营商

离线检查了 19 份不同 SHA-256 的历史日志，覆盖三机三网，其中仅两份捕获了 SMS 事务。它们来自此前的语音验收，采样窗口有限。

| 设备 | 移动 460-00 | 联通 460-01 | 电信 460-11 |
| --- | --- | --- | --- |
| Q10 SQN100-3 | 窗口内无 SMS 事务 | 窗口内无 SMS 事务 | 窗口内无 SMS 事务 |
| Q20 SQC100-2 | RP-ACK 收到 SIP 400 | 本次用户反馈；历史窗口无 SMS 事务 | 窗口内无 SMS 事务 |
| Passport SQW100-4 | 窗口内无 SMS 事务 | 窗口内无 SMS 事务 | RP-ACK 收到 `400 Cannot find In-Reply-To` |

用户没有给出 Q20 的硬件变体，不能用反馈确认 SQC100-2 已复现。Q20 移动证据为 `capture-19`（下行 4300 行、ACK 4347 行）；Passport 电信为 `capture-01`（下行 797 行、ACK 844 行、明确拒绝 868 行）。日志哈希、元数据来源及脱敏解析结果见[证据文件](../materials/sms-investigation-2026-11-01.json)。两份均显示默认 `smsOverIp[0]=1`、实际短信 `domain 1`，随后通过“MT 来自 IMS”的例外路径发送 ACK。

三机使用相同受校验的原生 IMS 二进制和公共配置路径，因此发送侧遗漏可能跨机型、跨运营商出现。后续静态分析也确认九种组合共用缺少关联头构造的 raw 3GPP ACK 路径，见[原生定位与候选](SMS-ACK-NATIVE.md)。已观察到的 ACK 拒绝跨越两家运营商和两款设备；移动的 `Decode SIP message Fail` 不能仅凭状态码归因，其余组合是未知，不能计作短信通过。

## 查看 SIP 与 In-Reply-To

先在已有可信 Root shell 中只读采集 `/bin/slog2info -b ims_rrm`，保留当前 IMS PID、时间戳和完整的 `<<<<<< IN` / `>>>>>> OUT` 块。避免只截取包含 `ACK` 的几行，事务关联还需要下行 Call-ID、CSeq、Via branch 和响应。

原生 `SipLogger`（`0x132e50`）会在 slog2 输出前将 `In-Reply-To` 值替换为 `PII`（`0x133060` → `0x1330a8`）。PII 不是实际发出的值；日志缺字段也不能单凭这一点证明线上报文缺字段。

原生还识别以下文件日志设置，位于 `/pps/services/ims/status_persistent`：

| 字段 | 类型／用途 |
| --- | --- |
| `logSipToFile` | 布尔值；请求写入原生 SIP 文件 |
| `logSipBody` | 布尔值；是否记录正文，核对 RPDU 时才需要 |
| `logSipMaxFileSize`、`logSipMaxNumFiles` | 整数；原生轮转控制，本次未验证单位与合适取值 |

文件头在脱敏前追加（`0x133024..0x13304e`），日志目录为 `/var/ims/log/`。受控取证时先保存这些字段的原值，用 PPS 字段更新设置 `logSipToFile:b:true`；需要 RPDU 时才设置 `logSipBody:b:true`。短时采集结束后逐字段恢复原值，原来不存在的字段删除，遇到其他修改保留冲突，不要回放覆盖整个 PPS 对象。

开关还受 quip role 限制。必须同时检查文件是否实际生成，以及 `sipLogToFile failed`、`logToFile / fd / quipRole` 等日志；不能把写入成功当作捕获成功。本次没有实机验证该开关，也不修改设备角色。原始文件可能包含号码、鉴权和短信正文，只在本地保管。

在电脑上运行新增的只读工具：

```powershell
python tools/sms_diagnostics.py private/owned-ims.log --output private/sms-report.json
```

工具支持 slog2 的 SIP 块和带上述方向标记的原生 SIP 文件；若正文是空格分隔的十六进制 RPDU，会提取类型和参考号。它按进程、Call-ID、CSeq 和 Via branch 关联响应，不导出号码、地址、Call-ID、正文或源文件名。缺失或脱敏值保持未知，URI 比较只是文本比对，报告始终标记 `sms_delivery_verified=false`。它不连接手机，不发短信，也不判定 Hub 已去重。

## 实机验收仍需完成

对每个准确机型／运营商组合分别验证：一次人工 MO 的实际域、首次 IMS 尝试及对端收到一次；一次 MT 的 RPDU、关联头、网关响应及 Hub 只入库一次；随后持续观察至少 180 秒以覆盖反馈中的重投窗口。再验证连续相同内容短信、长短信分段、正常重启与关机换卡，并回归语音和停用恢复。180 秒只覆盖这次反馈的窗口，不代表网络重试的通用上限。

后续已通过原生数据流确定两个修改点，并完成 ARM 指令仿真与 ELF 结构检查。现在需要实机确认 QNX 加载和完整 SIP 事务，判断候选是否消除实际重投；[验证记录](../materials/sms-ack-native-verification.json) 明确保留这些未验证项。

本候选基于本仓库缓存的 `0091630`，未发布为新安装包。用户提到的 PR 仓库尚未确认；若指 [bb10root/bb10-volte PR #1](https://github.com/bb10root/bb10-volte/pull/1)，核对的 head 为 `5e2ecaf5ad6c6e56e05d206e8939dbcad336d1ed`，内容涉及 carrier 选择、IR92 和 VoLTE provisioning 门槛，并没有短信关联修复。本项目的 Python 载荷不能直接覆盖该 C 项目的安装。本次未复制其 GPL 实现。
