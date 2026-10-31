# Q20 电信网络诊断记录

2026-10-29 社区反馈：Classic SQC100-4 / OS 10.3.3.3216，电信 SIM。以下仅包含与故障有关的字段，不含设备或用户身份。

## 已观察到的事实

- `cnice/status` 中存在 `internet`；`enabled=true`、`connectable=false`、`active=false`，没有 `apn` 或 `connected` 字段；`data_services_status=OFF`。
- `radioctrl/status_public` 报告 `power_status=ON`、`network_technology=["lte"]`、`network_service=1`、LTE `active_bands=16`、`band_capability=16846939`。
- 用户此前提供的 `446.json` 只覆盖 internet 的 APN 为 ctlte，无 IMS 段。报告原厂 `/etc/carrier/config/446.xml` 的 SHA-256 为 `d94f9b7eaa664a9ac496475e706bb837c364635400dd1af9a79608337d57f407`，与本地原厂样本相同；样本 internet APN 为 ctnet。

数据服务 OFF 是实际状态，不证明用户关了设置。r6 单独只读采集 `cnice/status_persistent` 的 `data_service_mode`，未读到则标未知，不写入该对象。也不读取或导出其其他内容。

## 网络服务枚举依据

本地原厂 cellular-control 样本 SHA-256：`1fb9b34d9e4b401ce2e7add1dff20f1c8c08dc926d6f25b0ae6b586f122470ec`。

离线检查其 Thumb `service_to_str`（地址 `0x5aff0`）：`0x5b000` 比较参数 1，`0x5b002` 跳转到 `0x5b118`，`0x5b11a` 返回字符串 EMERGENCY。另有 0→NONE、0x100→DATA、0x200000→DATA_LTE 分支。这是 BB10 原生样本证据，不借用 Android 或旧版 BlackBerry Java 的数值定义。

r6 只比较整数是否等于 1，后来证明这是错误的：这些值是可组合的位标志。r7 按位读取 0x1（EMERGENCY）与 0x200000（DATA_LTE），紧急标志存在、LTE 数据位缺失，或位图缺失/类型无效时均不允许网络检查通过。该原生样本未从反馈者设备重新导出；枚举不新增写操作或绕过现有系统/原生文件检查。

## r6 后续反馈与 r7 修正

同日 21:35 的报告出现 `data_service_mode=ON`、`data_services_status=ON`、internet active/connectable/connected 均为 true、运行时 APN 为 ctnet，但用户确认手机界面仍为 ctlte、实际无法上网且仅紧急通话。

该报告的 `network_service=33555457`，即 `0x02000401`，包含：

- `0x1`：EMERGENCY。
- `0x400`：CONCURRENT_VOICE_AND_DATA。
- `0x02000000`：IMS_VOICE_SUPPORTED。

它不含 `0x00200000`（DATA_LTE）。能力标志不能抵消紧急状态，也不能代替正常 LTE 数据服务。r6 的“只剩安装前状态”显示漏掉了这项矛盾，不能据此判断网络已恢复；r7 纠正组合位图检查，即使假设其他安装前条件均通过，仍会阻止安装、更新和启动。

本地 qct_rrm 样本（SHA-256 `71835f701affcb9254eadb4ee299e8f7d07547543b3e0f61519456b8241dcb3b`）的 `ss_determineNetworkServiceLte` 在 `0x7e852` 设置 LTE 数据位；`0x7e8c4..0x7e8de` 根据 IMS voice support 字段单独设置 `0x02000400`（常量位于 `0x7e90c`）。两个路径独立，支持上述能力与实际服务的区别。本地既有 Q10 LTE 样本位图为 2098186，即 `0x0020040a`，含 LTE 数据位而无紧急位；不将其作为 Q20 实机验收。

尚不能确定不同层读数不一致来自状态延迟、配置未生效、连接失效还是其他原因。r7 保留原始只读观察及各位解释，不用其中一层覆盖另一层，也未放宽 APN 覆盖目录限制。

## 频段解读限制

按第 N−1 位对应 Band N 解读能力位图 16846939，可得到 B1/2/4/5/7/13/17/25，与对方系统关于页一致；同一解读下活动位图 16 对应 B5。这个交叉核对支持 B5 线索，但不证明其为电信小区、不证明成功注册，也不证明拒绝原因。产品保留原始数值，不把位图 16 显示成 B16。

## 修复范围与待验证项

r7 保留 r6 对 internet 服务与设置的观察，并修正组合紧急标志的漏判。真实 APN 匹配、布尔 connected=true、无线层 LTE 数据服务位和无紧急标志仍不足以证明真实上网或通话，只是预检的必要条件。未知配置、APN 覆盖目录及其他安装前条件继续按原规则处理。

尚未确认数据服务设置、当时驻留的运营商、注册拒绝原因，或使用 ctnet/自动选网后能否入网。不能据此宣布 B3 不支持是唯一原因，也不能承诺改 APN、删覆盖文件、Root 或 VoLTE 安装能修复。现有证据不支持自动修改基带或运营商配置。
