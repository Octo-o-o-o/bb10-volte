# Q20 电信网络诊断记录

2026-10-29 社区反馈：Classic SQC100-4 / OS 10.3.3.3216，电信 SIM。以下仅包含与故障有关的字段，不含设备或用户身份。

## 2026-11-01 · 0.5.0-r8 后续反馈

**本日后续回传更新：** 已收到 `Desktop.rar`，其中 8 个配置/启动文件与上游网页包对应项完全一致。反馈者重新说明：自写 446 未起作用，网页包曾恢复通话，但短信和拔卡后的恢复异常。本次采集记录主要为命令兼容性错误，未取得有效网络快照。详见 [回传核对结论](SQC1004-RETURNED-EVIDENCE.md)；补问与只读命令已合并为 [第二轮清单](SQC1004-FOLLOWUP-R2.md)。以下保留之前各阶段的证据与推理，不再把早期关于 446 的归因当作已确认事实。

同一硬件型号的新快照仍未正常入网：`network_service=1` 含紧急服务标志而无 LTE 数据位，`data_service_mode=ON`、`data_services_status=OFF`，`data_connected=false`、APN 未知。internet 的 enabled/connectable/active 为 true，不能抵消这些失败条件。全部配置覆盖检查通过；`ims_count=1` 是另一个等待项，进程数量不足以确定它来自系统还是其他工具。

原报告的三项阻断是有效的；发现的桌面缺陷是主结论优先显示 IMS 数量、ON/OFF 文案含糊，以及列表长提示截断。未发布修订优先展示入网失败，直接区分设置 ON 与实际 OFF；选中列表项目后在下方完整换行展示处理方法。复制摘要与界面使用相同解释，不将未知值当作关闭或零。

报告使用的是通用 `china-telecom` 试用模板，没有 `lte_attach` 入网修复。三网自动适配的 Q20 准入为 **SQC100-2 / CLASSICATT**，这份 **SQC100-4** 报告不在该范围；勾选实验试用不会扩大三网流程的型号准入。新增界面及摘要说明这一差异，沿用手机端载荷、准入、备份和恢复规则。即使后续 IMS 进程自行退出，当前网络阻断仍然存在。

本轮只有用户提供的快照，没有连接反馈者的手机，**未修复或验收该手机的真实入网和通话**。现有数据缺少注册拒绝原因、IMS 进程来源及该硬件版本的策略验证，不能把数据开关、APN 或频段认定为唯一原因。后续应在原机核对这些信息和实际移动数据；不能用删除配置、结束未知 IMS 或套用 SQC100-2 参数来代替定位。独立的 SQC100-4 成功转述记录见 `materials/q20-peer-telecom-comparison-2026-10-31.json`，其缺少最终加载路径和原生策略读数，仍不构成本工具的实机验收。

后续 SSH 补充：用户确认在“不做任何操作”的情况下无法 4G 上网。两次读取 `/pps/services/ims/status_public` 均为 `default_ran::lte`、`status::disconnected`、`sys_list={"cellular":"disconnected"}`、`profiles=[]`；`/pps/services/ims/status_persistent` 只有对象头。这里的默认 IMS 接入类型不能证明无线网络已经正常注册；空 profiles 和空持久状态对象也不能单独证明配置损坏或需要人工补写。

仅上述 PPS 输出没有提供无线层正常入网或实际数据成功证据，不改变该快照的安装阻断。配置层 `ue_usage_setting` 与语音域读数也不能代替基带实际生效回读。随后用户补充的历史成功线索如下。

### 同机同卡的历史成功线索

本次远程取证使用 [SQC100-4 只读排查与回传清单](SQC1004-READONLY-COLLECTION.md)：当前状态与成功时保存的文件分开回传，保留旧包、AI 实际命令及变更时间线，不要求重新安装来重建现场。

用户进一步说明：同一台 SQC100-4、同一张电信 SIM，曾通过本项目旧版并配合 AI 辅助操作成功上网、打电话。此前还引用了 [bb10root VoLTE Addon 页面](https://bb10.root.sx/blog/volte)。尚未取得当时的本项目版本、AI 最终操作、成功时载荷与配置及从成功到失败的变更过程；不能仅凭网页链接断言实际使用的是上游原版插件。当前工具未纳入这个硬件版本的自动适配，不等于硬件或 SIM 被证明不可用。

排查重点因此调整为重建历史成功状态：确认是否缺少 AI 附加的入网配置、加载路径或启动步骤，并检查停用、重刷、迁移或更新过程；现有证据尚不能在这些原因之间作出选择。不得把“先恢复上网”当作没有入网适配方案时的循环前提，也不能只撤掉当前网络检查来替代适配。

离线重放同一组公开事实：`c643c2b`、`deae82e` 的旧版预检把 LTE 类型判为通过，但仍因 APN 状态未知和 IMS 基线而拒绝安装；`0d03ddc`、`e942ced`、`9850415` 另外明确报告紧急服务。五个版本的 `can_install` 与 `can_start` 均为 false。重放使用当前共享的 profile/native 定义，仅比较预检函数，不是执行五个历史安装包，更不代表重现了 AI 当时的操作。因此尚无依据将失败归因于新版单独收紧 LTE 位图检查。

本地 2026-10-31 的 SQC100-4 电信转述记录另有线索：曾出现 carrier ID 为 446、CDSC 实际路径却指向 `carrier-339-volte.xml`，后称调整文件并重启后恢复。尚未确认该记录就是本次反馈者的成功现场。公开上游固定提交 `8ac271b` 的 [find_carrier_xml](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L300) 返回目录中首个文件名以 `carrier-` 开头且包含 `.xml` 的条目，没有核对 SIM 的 carrier ID；追加 `.disabled` 也仍满足这个文件名条件。故不能直接重复转述记录中的改名操作，仍须取得实际加载路径和成功的 446 配置。上游网页与当前源码目录未自带 446 电信模板，这也要求核对 AI 是否补过配置，而非假定下载原版即可重现。

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

## PLMN 识别与 VoLTE 适配范围

更新于 2026-11-23。

PLMN 由三位 MCC 和两位或三位 MNC 组成，MNC 的前导零有意义。`sim_plmn` 来自 SIM 的归属网（HPLMN），是选择 VoLTE 模板的依据。`serving_plmn` 来自无线层的当前服务网，在漫游时可以与归属网不同，未取得有效服务网时留空。信号搜索结果、运营商显示名或 SIM 的手机号都不能代替归属网。[3GPP TS 23.003](https://www.etsi.org/deliver/etsi_ts/123000_123099/123003/17.10.00_60/ts_123003v171000p.pdf)

### 中国大陆

| 运营商或用途 | PLMN | 项目状态 |
| --- | --- | --- |
| 中国移动 | 460-00、02、04、07、08 | 现有自动配置入口，实测按型号、实卡和版本记录 |
| 中国联通 | 460-01、06、09 | 现有自动配置入口，实测按型号、实卡和版本记录 |
| 中国电信 | 460-03、05、11、12 | 现有自动配置入口，实测按型号、实卡和版本记录 |
| 中国移动 | 460-13 | 允许使用中国移动候选模板自动尝试，界面标注未实测 |
| 中国广电 | 460-15 | 允许原厂配置路线自动尝试，实际 LTE 频段和 IMS 待验证 |
| 中国铁通 | 460-20 | 允许原厂配置路线自动尝试，2G/GSM-R 无法满足 LTE 条件 |

前三行描述项目现有准入。中国移动在招股书列示了 460-13 的核配及有效期。中国联通美洲发布的代码表将 460-20 列为中国铁通，国家铁路局将 GSM-R 定义为铁路调度和运行安全的专用网络。看到 460-20 本身不足以确定手机屏幕上的字段来源或实际接入网络。[中国移动招股说明书](https://static.cninfo.com.cn/finalpage/2021-12-21/1211972455.PDF) · [中国联通美洲代码表](https://unicomam.com/zh/tools/mcc-mnc/cn/) · [国家铁路局 GSM-R 文件](https://www.nra.gov.cn/jglz/sbjg/fgsb/202204/t20220405_292249.shtml)

### 其他市场的试测候选

下表列出可按原厂配置路线自动尝试的 PLMN 示例。该路线适用于其他有效归属网代码，界面标注未实测。分配以所引公报或主管机关资料为准。

| 地区 | PLMN 示例 |
| --- | --- |
| 香港 | 454-00 HKT、454-03 Hutchison、454-06 SmarTone、454-12 中国移动香港 |
| 澳门 | 455-01 CTM、455-03 Hutchison、455-07 中国电信澳门 |
| 台湾 | 466-92 中华电信、466-97 台湾大哥大、466-01 远传 |
| 日本 | 440-10 NTT DOCOMO、440-11 Rakuten Mobile |
| 韩国 | 450-05 SK Telecom、450-06 LG U+、450-08 KT |
| 英国、德国 | 234-15 Vodafone UK、262-01 Telekom Deutschland |
| 美国 | 310-260 T-Mobile USA、310-410 AT&T Mobility |

[ITU E.212 公报附件](https://www.itu.int/dms_pub/itu-t/opb/sp/T-SP-E.212B-2023-PDF-E.pdf) · [台湾 NCC 移动网络识别码核配资料](https://www.ncc.gov.tw/chinese/show_file.aspx?file_sn=40977&table_name=news)

自动尝试时，程序核对当前 USIM、实际 HPLMN、原厂运营商配置与恢复备份。其他运营商使用这张 SIM 对应的原厂 XML 生成候选，按原厂配置推导数据 APN 和可识别的 IMS 参数。原厂配置缺失、OTA 覆盖、SIM 路径不匹配或 LTE 条件不成立时，程序会显示具体阻断原因。实测记录仍需覆盖 LTE 数据、IMS 注册、双向通话与音频、短信、重启和恢复。

统一服务候选只接纳在 SQW100-1 上采集并核对过的空白 v3 覆盖 `36.json` / `404.json`。文件须为普通文件并逐字节匹配空服务列表，其他文件名、符号链接、非空或改动的内容仍会阻断。现有文件原位保留。同一实机安装空配置修复后台后，正常开机读到 LTE 和 IMS 200 OK。机主报告本次实测正常。逐项通话、声音、短信、数据及恢复结果按原实机记录的范围保留。


### 韩国 KT M Mobile 450-08

[Issue #10](https://github.com/Octo-o-o-o/bb10-volte/issues/10) 的 Verizon Classic SQC100-5 报告系统 `MM#6`、无 LTE，以及应用提示检测到 ISIM。若原始消息确认是 3GPP EMM/MM 拒绝原因 6，标准释义为 *Illegal ME*。仅凭设备显示无法确定网络拒绝的具体理由。KT M Mobile 对某些外购设备提供型号登记，请运营商确认准确型号与服务资格。ISIM 属于独立的 IMS 认证路径，当前仍需实卡和原生认证流程验证。 [3GPP TS 24.301](https://www.etsi.org/deliver/etsi_ts/124300_124399/124301/18.07.00_60/ts_124301v180700p.pdf) · [KT M Mobile 官方说明](https://www.ktmmobile.com/cs/faqList.do?ctgVal=05&pageNo=2&sbstCtg=05)

保持系统网络设置和原配置，在电脑运行 `python tools/ai_skill.py --lang en volte probe`，或在手机版检查状态后导出诊断。可报告 `sim_plmn`、`serving_plmn`、`sim_has_isim`、`radio_lte`、`lte_data_connected`、应用版本和系统界面是否显示拒因。先确认同卡在已知兼容终端能接入 LTE，以及 Classic 原厂状态下是否能接入。反馈只需这些字段和观察结果。普通 USIM 且有匹配原厂模板的 450-08 可以走自动试用，实际 LTE、IMS、通话和短信结果仍待验证。
