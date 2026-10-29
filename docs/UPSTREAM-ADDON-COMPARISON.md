# BB10 VoLTE Addon 对照记录（2026-10-29）

**简体中文** | [English](UPSTREAM-ADDON-COMPARISON.en.md)

本记录比较 [发布文章](https://bb10.root.sx/blog/volte)及 `bb10root/bb10-volte` 提交 [8ac271b](https://github.com/bb10root/bb10-volte/tree/8ac271b5b1170ae98c60dd248dc5c4485edf95f3)，本项目比较基线为 `08224a8`。结论来自源码检查，未在手机上安装或执行该插件。机器可读摘要见 [upstream-addon-research.json](../materials/upstream-addon-research.json)。

## 本次落实的收益

桌面“检查详情”和可复制、可导出的排查摘要解释既有 `incoming_diagnostics` 的六项白名单读数：IMS 状态、承载网络、VoLTE provisioning、工程语音域、DCA 语音域和 IR92 preconditions。缺失或不合法的值保持“未知”，观察值不标为通过或失败；工程语音域与 DCA 语音域保留为不同枚举。注册和参数快照不能替代来电接听、双向声音等实际验收。

此次新增的是桌面展示和离线资料。手机探针、手机端载荷、补丁、运营商参数、安装/恢复门槛及支持范围保持原状，不增加手机读取或配置写入。该资料不进入精确机型的通话成功记录，不改变 `hardware_validation` 或 `call_acceptance`。既有实机证据与限制见 [社区研究](COMMUNITY-RESEARCH.md) 和 [验收记录](VALIDATION.md)。

## 可继续研究，尚未采用

| 方向 | 上游事实 | 本项目的决策与验证要求 |
| --- | --- | --- |
| 原厂 IMS 启动 | [管理器](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L391)直接启动原厂 `ims_rrm`，同时修改 DCA、provisioning 和工程语音域。 | 可探索减少二进制补丁依赖；这不能证明本项目已验收 Q10 可以去掉 VoPS 补丁。需独立实验并核对真实呼入/呼出与恢复。 |
| 运营商参数 | 带有联通 36、移动 404、Vodafone Ukraine 339 配置，详见下表。 | 作为参数差异样本；不导入整份 XML，不新增已支持组合。逐项修改才可能区分效果。 |
| 状态栏黑莓图标 | [监控器](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/berry_monitor.c#L34)读取 IMS PPS 并写 Navigator，退出路径尝试按 BBM/RCP 状态恢复。 | 有可见性收益，但需要手机 UI 写入、旧状态/大小写/退出/飞行模式/冲突验证。当前保留为候选，不把图标解释成通话成功。 |
| 事件与恢复统计 | [PPS 监控](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L572)记录掉线与重连情况。 | 可用于设计后续观测与验收；当前不增加常驻监控，不采用其强制重启 IMS 策略。 |
| 软件提供器参数 | [辅助模块](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/devnp-volte-swcrypto.c#L13)调用 `swcryptoattach(0)`，本项目调用参数为 `1`。 | 源码差异不证明其 BB10 语义或 Passport 恢复效果。不修改参数，也不绕过现有所有权、VPN 与机型限制。 |

以下比较限于三份上游 XML 的 **IMS 服务段** 与本项目 [IMS 段生成器](../device/profiles.py)，不是网络认证结论。省略的字段不等于 `false`，实际默认语义未由本次验证。

| 字段 | 上游三份样本 | 本项目 |
| --- | --- | --- |
| `AlwaysOn` | `false` | `true` |
| `DisableDAD` | `true` | 不显式设置 |
| `RequestSignallingBearerViaPCO` | `true` | 不显式设置 |
| `RequestPCSCFViaPCO` | `true` | `true` |
| IP 类型 | `IPv4v6` | 默认 `IPv4v6`，配置可选 |

来源：[联通](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/pkg/data/carrier-36-volte.xml#L88)、[移动](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/pkg/data/carrier-404-volte.xml#L88)、[Vodafone Ukraine](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/pkg/data/carrier-339-volte.xml#L75)。

图标实现还存在需验证的具体细节：[连接判断](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/berry_monitor.c#L34)只看公共 PPS，按大写 `LTE` 比较，未核对自有进程存活或本轮 REGISTER 200；[关闭图标](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/berry_monitor.c#L89)沿用较短的开启字符串长度，写入少了末尾换行。本次未验证 PPS 是否接受该写入，不能据此断言图标必然失效。本项目注册结论继续使用管理器、原生 IMS 存活及当前注册状态等联合证据。

## 不采用的行为及已有方案的优势

| 触发条件与源码事实 | 影响 | 保留的本项目行为 |
| --- | --- | --- |
| 数据目录有多份 carrier XML 时，[find_carrier_xml](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L300)返回首个匹配文件；它没有比较 SIM 的 carrierID，后备路径还使用 MNC。provisioning 的另一处 carrierID 解析没有用于此选择。 | 可能向 CDSC 选择其他运营商的配置；目录顺序并不能保证匹配。 | 按当前 SIM 核验原厂配置及数据 APN，只替换该配置的 IMS 段。 |
| [incoming_ready_pps](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L250)只检查 provisioning 与 preconditions。 | `INCOMING_READY` 不证明真实来电到达、振铃、接听或双向声音。 | 配置观察与实际通话验收分开，`call_acceptance=not_assessed`。 |
| [启用过程](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L457)覆盖四个 DCA 来源的语音域配置，并改 provisioning XML。[终止路径](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L688)没有配置回滚、IMS/VPN 清理或提供器注销。 | 进程退出不能说明已恢复安装前状态；这些路径之外的部署清理未获验证。 | 通过账本、所有权证据、并发改动检查和回读恢复自有状态。Passport 提供器恢复仍受限制。 |
| [网络监控](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L627)失去 LTE/SIM/Data 就停止 IMS；[重连路径](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L520)也未重新检查通话空闲。停止工具按[命令行子串](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/sys_utils.c#L319)匹配，可从 TERM 升级为 KILL。 | 可能影响仍存活的通话/会话或不归该管理器所有的 IMS；源码检查不表示每台设备都会发生故障。 | 运行期短暂 LTE 变化交由原生 IMS 处理；启动交接继续要求特定已验收组合、精确进程与空闲证据。 |

当前 Q10 的补丁范围、恢复账本和启动交接依据见 [设计说明](DESIGN.md)。本次没有新增重启、长通话、长期待机、飞行模式或提供器生命周期的实机证据。未验收组合仍仅允许手动启动，Passport 自动操作继续暂缓。

## 来源与许可

上游 [README](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/README.md) 与 [LICENSE](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/LICENSE) 声明 GPL-3.0。本项目本次只归档自行整理的事实和来源链接，没有导入上游代码、XML、二进制或发行 ZIP，也未将上游材料重新声明为 MIT。后续如需代码复用或分发，须单独核对许可与第三方材料来源。
