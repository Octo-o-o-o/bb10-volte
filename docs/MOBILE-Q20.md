# Q20 中国移动适配

2026-10-31，本轮仅操作 Classic SQC100-2 / CLASSICATT / BB10 10.3.3.3216。Passport 在另一会话维护，Q10 未连接。本记录不能替代其他机型、其他移动卡或其他 MCC/MNC 的验收。

## 当前参数

| 参数 | 本机读数／选择 |
| --- | --- |
| 归属网络 | 中国移动 460-00 |
| SIM 路径 | USIM without ISIM，类型 2 |
| 原厂运营商模板 | 404.xml |
| 原厂模板 SHA-256 | `01093873ac626da82ec30c45a2db18925af12f5f9dec1fdca63c7ef3c70f0598` |
| 普通数据 | `cmnet` |
| IMS | `ims`，IPv4v6 |
| IMS 归属域 | `ims.mnc000.mcc460.3gppnetwork.org` |
| 安装配置 | `q20-sqc100-2-mobile-46000` |
| 配置 SHA-256 | `d35ba3d9e68e5b05bc55d8a9e33ca2a8275ba24c75a8795731a64f53779c7cb9` |
| Root / 开机入口 | 保留既有 Root v2 和已核验的 btool 入口 |

复现配置见 [Mobile 请求](../experiments/q20_autoroot_v2/configurations/mobile-46000-request.json)，现场状态和后续验收以 [移动实机记录](../materials/q20-mobile-validation-2026-10-31.json) 为准。目前独立 IMS 已注册，人工通话和自动恢复验收尚在进行。

## 从电信配置切换

原卡已由机主换成移动，但旧电信管理器及原生 IMS 已退出，仍有旧配置和 IMS VPN。先冻结 203 个文件、9,919,546 字节的私有备份，并在电脑逐项验证散列；停用旧自动启动，恢复自有 PPS、身份文件、DCA 来源和 UE／语音原值，删除自己拥有的 IMS VPN。保留软件加密提供器，直到机主从电源菜单正常重启。

正常重启后检查 provider=-1、voice=0、空 VPN 和干净的运营商配置，确认当前 460-00 SIM、cmnet 数据和 LTE，再调用配置选择器，固定手机原厂 404.xml 的内容散列。移动启动不调用电信的 UE1/data_centric 前置流程。

首次启动时原厂 IMS 进程仍在等待未配置的 profiles。工具核对了唯一进程、原厂执行路径和参数、空配置、无 VPN、无 REGISTER／INVITE 及电话空闲，再通过已有固定散列的交接函数发送一次 SIGTERM。只有原进程退出并重新通过干净基线检查后，才启动独立 IMS。没有按进程名批量结束，也没有对未知进程强制终止。

## App 范围

App 按当前安装的运营商配置核对 SIM 和实际加载的 XML；移动启动使用正常预检，电信启动继续要求它自己的 DCA 备份。手机 manifest 必须匹配程序内已核验的具体散列；未知版本在上传管理探针和授予 PathTrust 前拒绝操作。它管理这台已装独立适配的 Q20，不提供新机的一键安装或自动换卡切换。

完整 SIP、电话号码、SIM 派生身份和 SSH 材料仅保存在私有目录；公开记录提供配置、散列、过程和脱敏验收结论。短信／彩信、其他移动 MNC 和长期稳定性尚未验收。
