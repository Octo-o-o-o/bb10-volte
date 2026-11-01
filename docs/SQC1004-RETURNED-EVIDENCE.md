# SQC100-4 电信回传材料核对 · 2026-11-01

本次仅离线读取 `Desktop.rar`，没有运行包内启动脚本、管理器或驱动，没有连接或修改反馈者手机。原始材料保留在私有取证目录，本文只记录技术事实。归档 SHA-256：`b7419c58456087825b6556d9f1a8267cf034ecd690913b9d0a58e327aff104ae`。

## 已确认的文件事实

压缩包含说明、采集记录、3 份运营商 XML 和 5 个 init 文件。与 2026-11-01 从[上游发布页](https://bb10.root.sx/blog/volte)下载的 `volte.zip` 比较，**8 个配置/启动文件与发行包对应项全部逐字节相同**，包括 `ims_manager` 和驱动。未发现这些回传文件中的自定义修改；这不证明手机从未有过其他修改，也不能确定这些文件来自手机当前目录还是电脑中的发行包。

网页包 SHA-256：`7af0b51d3af48a0bebfff82b8d8d245f8a43f168fcde39ed0bd01c1fce9831b5`。逐文件哈希见 [机器可读比对记录](../materials/sqc1004-returned-evidence-2026-11-01.json)。归档中没有 446 配置、旧版成功状态快照、AI 实际命令记录或完整操作时间线。

| 文件 | 普通 internet APN | IMS APN | XML 内 CarrierID |
| --- | --- | --- | --- |
| carrier-339-volte.xml | internet | ims | 255，和文件名编号不同 |
| carrier-36-volte.xml | 3gnet / 3gwap | ims | 36 |
| carrier-404-volte.xml | cmnet / cmwap | ims | 404 |

三份文件共同包含 IMS 的 IPv4v6、PCO 获取 P-CSCF、请求信令承载、DisableDAD、ProtectRouting 等配置，IMS 的 AlwaysOn 均为 false。339 另含编解码、SIP 定时器和乌克兰 EPDG 配置。普通上网 APN 不同，不能因为 IMS 通话的转述结果相同，就把这些 APN 都当作适合电信上网。

## 反馈内容的更新

最新说明修正了先前“自写 446 恢复”的解释：反馈者称网页包中的任一剩余 XML 都曾使电信 VoLTE 可用，普通上网 APN 随所选 XML 改变；普通短信收发异常，业务短信可能重复、延迟；拔插 SIM 后回到紧急状态，重启不能恢复，需要再次“刷 VoLTE 包”。这是反馈者的观察和归因，尚缺有效成功/失败快照与具体操作记录。

因此，不能继续将“自定义 446 是成功原因”作为前提，也不能把“收到了验证码”记为短信验收通过。“刷包”究竟指重新安装 addon、手动启动还是重新刷系统，仍需澄清。

## 源码支持的排查方向

对照上游固定提交 `8ac271b5b1170ae98c60dd248dc5c4485edf95f3`，返包二进制中的路径和配置字符串与以下机制相符。没有重建该二进制，源码对照不等于证明每个分支在此手机上执行过。

- [XML 选择](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L300)取目录里首个名称以 `carrier-` 开头且包含 `.xml` 的文件，不以当前 SIM 的 carrier ID 匹配；`.xml.disabled` 仍符合条件。只剩一个文件会影响选择，但不证明该文件全部配置正确。
- [首次启用](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L830)同时启用加密提供器、写 DCA/IR92/IMS 配置、修改 provisioning、选择 CDSC XML、写工程语音域并重启 IMS。共同的 IMS 配置和这整套初始化动作都是候选原因，不能用单个 XML 对比排除它们。
- [重连](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L520)主要停止 IMS、重写 provisioning 并重启 IMS，没有重做首次启用的完整步骤；重试耗尽后等待系统状态变化。需要用实际进程、配置路径与重连日志判断拔卡后的失败点，尚不能确定就是这个分支的问题。
- [IMS 配置](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L457)只声明 voice 服务并设置 SMS_Format=3GPP。这是短信排查差异，不足以证明补一个 sms 字段就能解决延迟、重复或发送失败。

## 采集失败是独立问题

`01-current-state.txt.txt` 主要是命令回显和错误，未取得可用的网络、APN、DCA、IMS 结果：

1. `printf`、`id` 报不能执行/文件不存在。不能由此认定 Root 权限不足。
2. `awk` 直接读 PPS 报 `Message too long`。QNX 的 PPS 要求一次读取缓冲区容纳整个对象，缓冲区太小会失败；[官方说明](https://www.qnx.com/developers/docs/6.5.0SP1.update/com.qnx.doc.neutrino_pps/subscribe.html)及 [EMSGSIZE 修正记录](https://www.qnx.com/developers/docs/6.5.0SP1/momentics/release_notes/rel_6.5.0_SP1.html)支持这个解释。前版手册把普通文本文件上的 awk 验证当成了足够的兼容性检查，这是采集方案缺陷。
3. 回显中出现转义丢失、额外 HTML 结束标签和异常换行。暂不能确定这些变化发生在执行前，还是整理/转发日志时；不能据此复原实际执行的每一个字符。
4. 多个 addon/项目目录的 ls 输出为不存在，但归档又附有 init 文件。文件来源、采集时点和终端环境必须先对应，不能直接宣布当前安装位置或配置已被删除。

旧版长命令已撤下，改为[第二轮统一补充清单](SQC1004-FOLLOWUP-R2.md)：先验证读取工具，再用有界的大块读取把 PPS 送入管道筛选；不使用 printf/id，不执行安装包入口，不要求复现拔卡故障。仍需在反馈机验证，报错保留，不算通过。

## 对“必须先有正确 APN 和 4G 才能安装”的回答

这不是所有配置写入方式的技术前提。当前通用安装入口要求可用数据网络，是该流程的准入条件；上游启用入口检查 LTE 类型、SIM 就绪、数据设置 ON 和通话空闲，并不要求普通 internet APN 已匹配或数据已连接。两者不能混为网络技术的必然条件。

如果某台手机需要初始化 IMS/语音策略才能恢复服务，就需要单独设计经过核验、备份和回滚的恢复流程；不能要求它先满足恢复后的成功状态。但这也不等于把当前失败状态显示为正常、把所有型号放行，或把其他运营商完整 XML 直接移植。安装/恢复准入与恢复后的上网、呼入呼出、短信、重启和 SIM 变化验收必须分别定义。

本轮已确定上游包身份和共同配置，修正取证方法；**尚未确定现场恢复所需的最小改动，也未完成 SQC100-4 实机修复或验收**。不再要求重新提供已一致匹配的 8 个包内文件，待补内容集中在来源、实际操作、有效状态和日志。
