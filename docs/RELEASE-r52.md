# Windows r52 与手机版 0.1.0.52

- 自动适配允许中国移动 460-13 和其他未实测运营商尝试。460-13 可用固定的中国移动原厂模板兜底。其他归属网从当前 SIM 对应的原厂 XML 读取互联网 APN 和可识别的 IMS 参数。界面标注未实测。有效的 SIM 认证路径、原厂配置、原生文件和配置备份仍是必要条件。
- SQW100-1／460-07 曾在启动时被两个空 APN 覆盖文件拦截。新版只接受逐字节匹配的空白 v3 `36.json` 和 `404.json`，保留文件。实机用仅含 APN 修复的候选冷启动后读到 LTE 和 IMS 200 OK，机主报告正常。逐项通话、短信、数据及恢复结果按实机记录保留。[实机记录](../materials/sqw100-1-intake-2026-11-23.json)
- 标准升级步骤为确认同一台 USB 设备与可信 SSH，核对 Root、OS、SIM 和原生文件，从手机读回原始配置备份，再按预检原地升级。需重启时使用电源菜单，开机解锁等 Root 后核对本次开机的 SIM、后台、LTE 和 IMS。已连接的同一版本无需额外重启或重刷。配对助手现在让 Root 生成的公开回执可由共享目录读取，并保留原有授权及严格主机校验。
- 韩国 KT M Mobile 450-08 的 [反馈 #10](https://github.com/Octo-o-o-o/bb10-volte/issues/10) 报告系统 MM#6／无 LTE，同时发现 ISIM。新版分别显示 SIM 含 ISIM、系统是否处于 LTE 和 LTE 数据是否已连，并单列 SIM 归属网与当前服务网。普通 USIM 与匹配原厂模板可试用；该报告使用的 ISIM 路径仍需另行验证。若原厂系统尚无 LTE，先按运营商正常流程核对 SIM、设备准入及型号登记。[KT M Mobile 官方说明](https://www.ktmmobile.com/cs/faqList.do?ctgVal=05&pageNo=2&sbstCtg=05) · [3GPP TS 24.301](https://www.etsi.org/deliver/etsi_ts/124300_124399/124301/18.07.00_60/ts_124301v180700p.pdf)

macOS 下载保留为封板 r43。新版按实验版发行。 [PLMN 范围与诊断](NETWORK-DIAGNOSTICS.md#plmn-识别与-volte-适配范围)
