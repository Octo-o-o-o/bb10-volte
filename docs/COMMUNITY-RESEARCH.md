# 社区研究与适配进展（0.3.3）

**简体中文** | [English](COMMUNITY-RESEARCH.en.md)

本次整合来自 [imqinyu/BB10DeviceVoLTEResearch](https://github.com/imqinyu/BB10DeviceVoLTEResearch)，由 [issue #1](https://github.com/Octo-o-o-o/bb10-volte/issues/1) 提供。引用固定在提交 [376f492](https://github.com/imqinyu/BB10DeviceVoLTEResearch/tree/376f492ade10efad371dca64d49fe39549820844)，日期为 2026-10-28。机器可读的来源、证据等级、限制和待验证项目见 [community-research.json](../materials/community-research.json)。

## 本版本已经整合

- 在桌面预检、CLI 和导出的报告中附上精确匹配的社区记录。匹配要求公开 Board_Type（或 Z30 型号）、系统版本及实际 SIM 的 MCC/MNC 同时一致，不使用所选模板代替实际网络身份。无精确匹配时不推断支持。
- 读取白名单中的 Board_Type 以补充型号信息。它不能替代型号、ABI、系统版本和原生文件哈希；若与原有机型身份冲突则拒绝安装。
- 只读采集 IMS 注册状态、LTE 大小写归一后的网络类型、VoLTE provisioning、工程语音域、DCA 语音域及 IR92 preconditions 的有限枚举。未知字段记为 null；不导出任意 PPS 内容、SIM 身份或异常原文。
- 桌面注册判断兼容已观察到的 LTE/lte 两种拼写，仍要求本项目管理器和原生 IMS 存活、200 OK 及当前 LTE。
- 暂停 Passport 自动安装、更新、启动及会触发提供器注销的恢复操作；继续允许预检、状态查看和报告导出。GUI、CLI、手机安装入口和启动入口执行一致的限制。
- 保留现有 Q10 的补丁、语音策略、提供器实现和恢复流程。此次没有复制上游程序、二进制、发行 ZIP 或原厂运营商 XML。

这些社区记录不会设置本项目的 hardware_validation 为已验收，不会改变原生哈希白名单，也不会自动拨号或修改手机配置。新版本尚未进行实机复测；既有 Q10 通话验收属于 0.3.2 及以前版本。

## 证据如何解释

| 精确组合（OS 均为 10.3.3.3216） | 来源等级 | 已报告结果 | 不能推断的结论 |
| --- | --- | --- | --- |
| Classic AT&T / CLASSICATT / 移动 460-00 | 上游作者本地实验 | 注册、人工呼出和双向 RTP 的会话记录 | 来电成功、重启自动恢复、本工具安装成功 |
| Classic Verizon / CLASSICVZW / 联通 460-01 | 上游贡献者报告＋作者 issue 补充 | 原档案记载注册，作者后续确认接打成功 | 本项目独立验收；新原始通话证据尚未提供 |
| Passport / WINDERMERE4ROW / 联通 460-01 | 上游收录的贡献者报告 | 呼出及普通手机主叫的呼入成功 | 所有 Passport 可用、参数各自的因果关系、本工具恢复安全 |
| Z30 STA100-3 / 移动 460-00 | 上游作者本地失败记录 | 当地网络未附着 LTE，报告能力为 B4/B13 | 所有 Z30 不支持 VoLTE，或更改 IMS 配置能解决频段问题 |

10 月 28 日的 Q20 新快照处于 LTE 已附着、IMS idle 状态，不能把它算作当天再次通话成功。Q20 来电失败反馈缺少完整的逐变体诊断。表中“上游作者本地”不是本项目维护者的独立实测；来源详见固定提交中的 [验证记录](https://github.com/imqinyu/BB10DeviceVoLTEResearch/blob/376f492ade10efad371dca64d49fe39549820844/docs/05-validation-and-evidence.md)。

## Passport 为什么暂缓自动操作

上游的 Passport 贡献记录描述了注销软件加密提供器后 io-pkt 重启、USB 连接中断，并选择让提供器保留至重启。我们的 Q10 流程在停止自有 IMS、清理自有 VPN 并检查无活动 VPN 后注销提供器；这些检查尚不能证明 Passport 不会复现该问题。

当前按 Passport 家族保守暂停，而不是声称所有 Passport 都必然失败。恢复策略及真实设备验证完成前，实验试用选项不能绕过。已有旧版本服务也不会被新桌面工具自动停止、覆盖或迁移；请保留现场、查看状态并提供脱敏报告，由维护者依据实际 Root/addon、IMS/SA 清理和模块加载状态制定恢复步骤。仅更换电脑端程序不能修改旧手机端代码；不要把新限制理解为旧版本自动获得修复。

重新开放至少需要明确的注销复现条件、清理后状态、网络/USB 可用性、重复启用、正常重启和真实双向通话结果。另一条路线是提供器保留至重启，但这需要单独的状态模型，不能仍报告“已完全恢复”。

## 来电诊断与后续验证

报告的 incoming_diagnostics 只描述配置快照；call_acceptance 始终为 not_assessed。Provisioning=1 或 UsePreconditions=0 不等于可接电话。

1. 用真实手机主叫，先判断 INVITE 是否到达 BB10。
2. 到达后区分设备拒绝、振铃、主叫 CANCEL、接听/ACK 和音频问题。
3. 对照当前运营商自己的用户配置，逐项验证 provisioning、工程语音域、IR92 参数；每次只改变一个变量并保留原状态。
4. 完成双方声音、全程 LTE、拔 USB、正常重启和较长通话的验证。

上游工程枚举 override=5 与 DCA 的 voice_domain_preference_EUTRAN=3 属于不同接口，不能互换。联通 carrier 36 的文件不能复制到移动 carrier 404。上游最终成功的来电仍出现 183/PRACK，因此没有证据把关闭 preconditions 归为唯一修复；本版本不写这些候选参数。

黑莓小点作为注册指示的方案已记录为可选功能候选；本版本没有安装监控器或写入 Navigator。图标代表注册状态的设计也必须区分通话验收，并验证大小写、状态过期、停止恢复和飞行模式切换。

## 来源与许可

上游 NOTICE 明确未选择项目级许可证，且收录了其他贡献者材料。作者已在 [issue 回复](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472554806) 明确允许复用其材料；项目级许可证仍未更新，其他贡献者材料的单独授权范围尚未核实。我们在 [确认问题](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472384217) 记录了许可及第三方贡献的授权问题。

本次新增代码由本项目编写，资料表是自行整理的事实摘要及链接，未将上游内容声明为 MIT 或重新分发。后续若复制代码或构建产物，必须按确认后的许可保留署名、通知和来源。中英文 README 最下方保留致谢。

## 作者补充与自启动限制

作者在 [issue 回复](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472554806) 确认：移动卡设备（称为 sqc-2）只实现呼出，另外两台已实现接打。此处保留为作者陈述，不升级为本工具独立实测，也不据简称新增型号映射。

作者同时提醒开机自启动容易卡在开机动画，尚未说明精确机型和启动入口。为此，所有未验收的机型／运营商组合仅允许手动启动，须将配置 runtime.autostart 设为 false；三个试用模板已默认关闭自动启动。Q20 使用默认联通配置时，也需在“自定义 → 运行选项”关闭自动启动后重新检查。CLI 的 enable 和手机端入口同样不能绕过此限制。已有验收的 Q10 SQN100-3＋默认联通参数保留原有自动启动。Passport 还受到独立的提供器生命周期限制，关闭自动启动并不会放行其自动操作。

旧版本安装不会因更新电脑程序而自动变更配置；请先按当前可用的恢复流程处理旧配置，再在关闭自动启动的请求下更新。Passport 旧安装继续保留现场，由维护者确认恢复方案。我们已在 [后续问题](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472842554) 询问受影响设备与启动方式，无需重新触发故障。
