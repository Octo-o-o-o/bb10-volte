# 有效方案与原生接口

## 为什么已有 4G 数据仍无法打电话

原联通配置中 `ims` 服务只是 `internet/3gnet` 的别名。即使补齐 IMS 注册，原生普通语音选择器仍读取 VoPS：本机 NAS 的 `IMS Voice Support=false` 使 VoPS=0。实际来电到达后，Q10 因 domain selection 返回 488；呼出则选择 CS，回落旧网络后报 `NO_SRV`。

`LTE Voice Support=true` 与 `IMS Voice Support=true` 是不同字段。本机 NAS 查询 0x4d 的 IMS Voice TLV 为 0x29，通知 0x4e 的对应 TLV 为 0x2a。已通过本机原生解码器的合成输入验证布局。查询、通知的编号不能混用。

## 六个必要部分

| 部分 | 实现 | 证据与边界 |
| --- | --- | --- |
| IMS 数据连接 | 原厂 CID36 XML 的 IMS alias 替换为独立 APN `ims`，IPv4v6、LTE、请求 P-CSCF via PCO | 本机获得 IPv6/P-CSCF/QCI5；不抄安卓地址 |
| 身份与认证 | 从当前 USIM IMSI/HPLMN 推导 IMPI/初始 IMPU；AKA 仍由本机 SIM 完成 | 依据 3GPP TS23.003/23.228；网络返回关联身份由原生 IMS 使用 |
| IMS 平台入口 | IMS 副本只读取独立 `/pps/volte_probe/ims`，其平台为 `common` | qct_rrm 原 carrier PPS 保持原状 |
| IPsec 算法 | 激活 io-pkt 自带软件提供器，支持协商的 NULL 密码套件 | 修复 PF_KEY SA add errno22；不改会话密钥和算法实现 |
| 语音偏好 | 原生 20 字节 by-value RadioControl 设置，mask2，仅设置语音偏好；PPS 同步为3 | API值1→NV03，API值4→NV00；PPS枚举不能直接传给API |
| 普通语音选路 | 已注册、IR92、支持RAT、非受限服务等检查之后，跳过 VoPS 的普通蜂窝语音否决 | 实测改选PS2，出现真正INVITE200/ACK；网络VoPS报告仍为0 |

## 精确修改范围

原 IMS SHA-256：`043d38b0f08cf6a9696ef405f3976679e32ff9ad943ec35294c3d3da69a12b67`。

1. 文件偏移 `0x366bed`：43 字节 PPS 路径保留区中，将 `/pps/services/carrier_config/radio_qct/ims` 改为 `/pps/volte_probe/ims` 并补零。
2. 文件偏移 / Thumb VA `0x62c54`：`c7 b9`（`cbnz r7,0x62c88`）改为 `18 e0`（`b 0x62c88`）。位于 `selectDomainVoice`。

最终副本 SHA-256：`f388a23900d13d92c0390c662fc53e2de6d628bba2174973c0320416022a4438`。构建函数校验原件、范围、长度和最终散列。`0x62e2c` 开始的独立紧急呼叫选择代码不变；这不等于紧急通话功能已实测。

原生 IMS 仍以 `453:31,80,387,427,521,1001` 运行，保留系统拨号器和音频路径。主程序只做初始化、状态记录、进程管理及恢复；不自动拨号，也不写 SIM。

## 常驻与恢复

运行日志和恢复账本只保存在手机 root 私有状态目录。服务处理 Root 就绪、SIM/LTE 就绪、进程互斥、原始策略备份和自有文件哈希。USB 连接不承担服务生命周期。LTE 临时掉线交由原生 IMS 状态机处理。

为避免长期运行积累无限日志，事件记录和原生输出按大小保留有限的近期内容。VPN UID 所有权先写入恢复账本再轮换日志。重要测试后及时使用 `collect` 留存；采集记录仍按私有通信数据处理。

正常 `stop` 停止自有 IMS，按自有进程的 UID 证据清理 VPN，再恢复 APN、carrier 字段、软件算法提供器和 NV00。其他应用创建的 VPN 不被删除。检测到其他配置改动时保留现场并报告冲突。

系统关闭时不反复触发语音策略重载；原始恢复账本保留供下一次启动核对。修订后的常驻实现已完成一次正常重启自动恢复与双向短通话验收；突然断电和长期稳定性仍需验证，见 [验收记录](VALIDATION.md)。

## 资料

- [AutoRoot v4 作者说明](https://bb10.root.sx/blog/autoroot-v4)：Root 环境和 addon 机制；实际入口另由本机 btool 字符串核对。
- [3GPP TS23.003](https://www.etsi.org/deliver/etsi_ts/123000_123099/123003/13.10.00_60/ts_123003v131000p.pdf)：身份和域名格式。
- [3GPP TS23.228](https://www.etsi.org/deliver/etsi_TS/123200_123299/123228/16.06.00_60/ts_123228v160600p.pdf)：无 ISIM 的 USIM 注册身份。
- [Qualcomm QMI decoder API](https://github.com/qualcomm/qmi-framework/blob/main/include/qmi_idl_lib.h)：原生布局验证所用解码 ABI。
- [libqmi 1.34 NAS 定义](https://github.com/linux-mobile-broadband/libqmi/blob/1.34.0/data/qmi-service-nas.json)：与本机原生定义交叉核对；本项目运行时不依赖 libqmi。
