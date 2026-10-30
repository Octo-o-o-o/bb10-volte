# Q20 SQC100-2 实机适配

本目录保存 2026-10-30 的 Q20 独立适配工具。它使用项目中经过散列校验的原生组件，在手机 `/var/q20_volte` 下管理自己的文件和进程。本目录的范围由实机验收记录决定；后续 App 的既有服务管理及 Q10 手动移植范围见 [电信适配说明](../../docs/TELECOM-PORT.md)。

当前记录见 `../../materials/q20-device-validation-2026-10-30.json`。联通已完成手动 IMS 注册、呼出、呼入、双向声音和 LTE 验收；正常菜单重启后自行恢复，拔下 USB 后再次完成双向声音和 LTE 验收。实测通话为约 5–10 秒的短通话，未完成 20 秒持续通话验收。电信最初两张 460-11 卡均出现紧急服务；在第二张卡上找到原生 UE 数据优先与 IMS 优先组合后，已完成 ctnet 数据连接、独立 IMS 注册及双向短通话/声音/LTE 验收，正常重启自动恢复和重启后拔 USB 的双向通话也已通过。第一张电信卡未用成功参数复测。移动卡仍在另一会话使用的 Passport 中，待机主提供后测试。

## 已确认组合

- BlackBerry Classic / SQC100-2 / CLASSICATT / BB10 10.3.3.3216。
- 现有预 Root v2，手机有可用的 root SSH；没有刷写系统或清除数据。
- 中国联通 460-01，USIM without ISIM，数据 APN `3gnet`。
- IMS APN `ims`，IPv4v6，归属域 `ims.mnc001.mcc460.3gppnetwork.org`；身份由当前 SIM 在手机端派生。
- `ims_rrm`、`io-pkt-v6-hc`、`libradiocontrol.so.0.1` 和联通原版 `36.xml` 与项目固定散列完全匹配。
- 语音策略经原生 RadioControl API 从原值 `0` 切换到 IMS 优先 `3`。
- 使用临时 IMS 副本和固定散列的软件加密提供器；不覆盖原厂 IMS 程序。

`/tmp/root.done` 在这套旧 Root 中不存在。本适配用 `/dev/shmem/q20-volte-boot.json` 的随机标识区分开机周期，检查真实 root 权限、机型、ABI 和原生文件散列。状态查询不创建开机标识。

## 连接和现场保护

电脑同时连接 Passport 时，两台黑莓可能都报告 `169.254.0.1`。本轮连接使用指定 Windows USB 接口的独立 socket，不把重复的 `169.254.0.2` 作为显式源地址绑定。每条远程命令先检查 `modelnumber::SQC100-2`；手机上的写入路径再次检查 SQC100-2、CLASSICATT 和原生散列。SSH 继续固定校验已有主机密钥。

私人会话目录包含 `ssh_config`、`known_hosts`、USB stdio 代理和 `session.json`；`session.json` 的 `interface` 是本机确认过的 Q20 接口编号。不得复用 Passport 的密钥配置或调整全局路由来选择手机。

完整 SIP、SIM 派生配置和电话对象仅保存于手机的 mode-700 状态目录及电脑私有目录。公开记录只包含运营商参数、文件散列、时间、SIP 方法和验收结论，不包含号码、IMSI、ICCID、IMEI、认证数据或 SSH 私钥。

## 本机维护入口

在仓库根目录运行，使用已准备好的独立 Q20 私人连接目录：

```powershell
$env:BB10_Q20_SESSION = '<Q20 私人会话目录的绝对路径>'
$env:BB10_Q20_REPORTS = '<Q20 本机报告目录的绝对路径>'
python experiments/q20_autoroot_v2/q20_volte_control.py refresh
python experiments/q20_autoroot_v2/q20_volte_control.py status
```

`refresh` 仅查询指定 USB 接口的现有地址并读取设备 discovery，确认 SQC100-2 后更新本会话连接目标。它保留 SSH 主机密钥信任记录。`status` 仅读取当前开机周期和进程状态；陈旧的 `200 OK` 不能代替当前管理器、原生进程、connected 和 LTE 的联合证据。

首次现场准备由 `snapshot` 离线复制并校验当前项目载荷，再由 `stage`、`probe`、`stage-service`、`precheck` 顺序完成。`launch` 是明确的手动启动动作。各步骤拒绝覆盖未知的既有目录；中断后先检查状态。它们是本次维护工具。候选 App 已接入这套既有 Q20 电信服务的查询、手动启动和停用恢复；新手机的一键安装尚未提供。

`q20_profile_switch_phone.py` 在旧配置收尾、正常关机换卡后，按当前 SIM 的 MCC/MNC 选择单一运营商配置，并固定原厂 XML 的编号与散列。新运营商先通过人工通话和 SIP 验收，才能用 `enable-current` 重新启用已有的开机入口。当前电信配置为 460-11、原厂 XML 446、数据 APN 候选 `ctnet`/`ctlte`、IMS APN `ims`、IPv4v6、域 `ims.mnc011.mcc460.3gppnetwork.org`；它已在当前电信卡上完成手动注册和双向短通话，自动启动已启用，正常重启自动恢复及重启后通话已通过。

`q20_nas_snapshot_phone.py` 只读 NAS 服务状态、选网偏好和系统信息。`q20_telecom_selection_trial_phone.py` 限时测试 LTE-only 和 data-centric 偏好，使用 until-power-cycle 时限，结束后逐项独立回退并回读；另有 watchdog 收尾。此测试不提供通话验收结论，也不写 APN、永久选网设置或语音 NV。一次 LTE 扫描能看到 460-11 归属网络，标记为可用且非禁用；限时手选 460-11 LTE 的请求已接受，观察期仍未注册，随后自动选网已回读恢复。上轮语音偏好试验在最终读回时遇到 QMI 错误；换卡正常重启后已单独确认恢复原值 0，保留该失败记录。

本轮进一步单独测试了原生 IMS 优先策略（NV 0→3）、DCA 的 `voice_domain_preference_EUTRAN=3`、NAS PS-only 服务域，以及 PS-only/LTE/data-centric 的组合，均未得到有效 LTE 数据连接。每项结束后均回读恢复原值。原生语音策略切换会重启 modem/SIM 会话；早期脚本因短暂的 NOT_READY 提前退出，最终脚本改为记录该过渡，并在 SIM 恢复 READY 后重新核对同一卡的指纹。失败和后续修正分开记录。

当前 Q20 的 `qct_rrm` 日志记录了 domain 1、cause `0x12`（十进制 18）的网络拒绝，附近系统标识为 460-11。该原因在 [libqmi 1.34.0 枚举](https://www.freedesktop.org/software/libqmi/libqmi-glib/1.34.0/libqmi-glib-NAS-enumerations-and-flags.html)和 [3GPP TS 24.301](https://www.etsi.org/deliver/etsi_ts/124300_124399/124301/18.07.00_60/ts_124301v180700p.pdf)中对应“CS domain not available”。这提供语音域兼容性调查线索；尚不能据此断言电信卡有故障、该机永久无法使用电信，或仅修改该字段就能修复。

后续找到了可复现的入网组合：通过原生 DCA 源设置 `ue_usage_setting::data_centric`，确认基带 EFS 值为 1，再通过已验证的原生 API 设置 IMS 优先（mask 2、native value 1，对应 voice EFS 3）并重新加载 modem。单独修改临时 NAS 选项，或仅写入原生 UE 值而不重新加载，本轮均未恢复入网；成功组合下已确认 460-11 LTE 注册、ctnet 数据、IMS REGISTER 200。详见 `../../materials/q20-telecom-research-2026-10-30.json`。

`q20_telecom_carrier.py` 将这一步作为当前 460-11 的手机端启动前置流程，保留原核心引擎在配置 IMS 前的 LTE/数据检查。四份 DCA 原文先复制到电脑并逐一核验散列，写入保留原 inode、权限、所有者及其他内容，停止时显式恢复 UE0/voice0 和原来的缺失字段状态。未知运营商、原生文件、已有配置或备份回执不匹配时拒绝应用。跨运营商重新建立 journal 时，仅按已完成旧轮记录中的精确散列接管旧 runtime 文件；未知文件保留并拒绝覆盖。

当前电信手动通话的 SIP 记录为呼出接听后 6.154 秒、呼入 5.943 秒，67 个样本全部 LTE，双方声音由机主确认。前面一轮取消的呼出仍作为未接通尝试保留。该组参数已启用开机入口，正常菜单重启后，新管理器由 root-v2 开机入口启动，约 73.333 秒后注册在线；该时长从管理器启动开始计算，并非完整系统开机耗时。期间电脑端服务启动次数为 0。拔 USB 后再次呼出/呼入成功，双方声音和全程 4G 由机主确认；信令记录接听后分别为 4.185/4.645 秒，43 个样本均为 LTE。

## 自动恢复的入口和验收

旧 Root 的入口位于 Android Runtime 的 `native/system/xbin/btool`。安装器保存原脚本，核对固定原文散列，在 `. /base/scripts/sudtools.sh` 之前插入独立后台入口。原脚本的字节顺序、inode、权限和 ACL 得以保留。该位置避开旧 Term49 安装过程没有超时的等待；把入口放在整个脚本末尾已被本轮启动检查证明不可靠。

`start.sh` 完成设备核对和 scoped PathTrust 后启动 Q20 包装器。自动启动需要匹配当前 profile 的人工双向通话、音频、LTE 和 SIP 证据回执。服务保留现有原生 IMS 的被动等待，不终止尚未证明空闲的原厂进程。

本适配在停止或错误恢复时恢复自己拥有的配置，并保留软件加密提供器直到正常重启；不执行提供器卸载。配置切换先收尾旧运营商、正常关机换卡，再验证新卡，避免把旧卡身份带入新卡。

验收采用手机电源菜单正常重启。开机后仅做只读查询，验证新的随机开机标识、`last-launch.json` 中的 `root-v2-boot-hook` 来源、新管理器和原生 IMS 进程、独立 IMS 连接及 REGISTER 200/LTE。之后再次实测呼出、呼入、双方声音和全程 4G。各轮信令用 `q20_call_evidence.py` 独立解析；取消或未接通的 INVITE 留在 `attempts`，不计为已接听通话。

本轮联通管理器从启动至注册在线耗时约 304.653 秒，主要等待原生 IMS 结束；没有测量手机完整开机耗时。不要据此承诺固定五分钟开机恢复。

## 拨号界面自身号码

联通卡的通话和对端来电显示正常，但本机电话界面缺少自身号码。手动修复取当前原生 IMS 的 REGISTER 200 回复中的唯一 `P-Associated-URI` 电话号码，填写本机电话界面的 PPS 显示缓存，机主已确认显示正确；没有改写 SIM 或来电显示设置。换卡前已还原该缓存，避免遗留旧号码。

新版 `q20_own_number_auto.py` 将同样的显示缓存操作绑定到配置时的 SIM 指纹、当前开机周期和自有 IMS 进程。只接受当前 REGISTER 200，不把 IMSI 转成号码，不接受其他通话或其他进程的数据；SIM 改变后拒绝写入。自动重填代码已部署，电信注册与重启中已运行，但没有识别出可用号码候选，也未写入显示缓存；本机电信号码显示正确由机主确认，不能归因于该辅助程序。自动填号效果仍需单独实测。

## 本地测试

```powershell
python -m unittest discover -s experiments/q20_autoroot_v2 -p test_q20_volte_adapter.py -v
```

23 项本地测试覆盖拒绝 Passport、开机标识的归属和冷启动变化、拒绝伪布尔回执、SIP 方向与完整接通流程、入口必须位于旧安装等待之前、自身号码来源与换卡保护、拒绝永久/无关 modem 写入，一个偏好回读失败时仍独立恢复另一偏好，以及语音策略首次读取失败时仍发送回退请求并复核原值。硬件通话、声音和正常重启仍以对应的实机证据为准。
