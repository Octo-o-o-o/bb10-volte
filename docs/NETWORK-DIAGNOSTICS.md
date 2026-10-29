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

本次仅使用明确的整数 1 判定仅紧急服务，不把任意其他掩码视为注册成功。该样本未从反馈者设备重新导出；枚举不新增写操作或绕过现有系统/原生文件检查。

## 频段解读限制

按第 N−1 位对应 Band N 解读能力位图 16846939，可得到 B1/2/4/5/7/13/17/25，与对方系统关于页一致；同一解读下活动位图 16 对应 B5。这个交叉核对支持 B5 线索，但不证明其为电信小区、不证明成功注册，也不证明拒绝原因。产品保留原始数值，不把位图 16 显示成 B16。

## 修复范围与待验证项

r6 能区分已生成但未激活的 internet 服务与字段读取未知，并阻止仅紧急服务或已知数据未就绪的快照通过网络检查。真实 APN 匹配和布尔 connected=true 仍是必需条件；enabled/active/频段位图均不能替代它们。未知配置、APN 覆盖目录及其他安装前条件继续按原规则处理。

尚未确认数据服务设置、当时驻留的运营商、注册拒绝原因，或使用 ctnet/自动选网后能否入网。不能据此宣布 B3 不支持是唯一原因，也不能承诺改 APN、删覆盖文件、Root 或 VoLTE 安装能修复。现有证据不支持自动修改基带或运营商配置。
