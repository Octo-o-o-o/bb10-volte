# 运营商资料调研（2026-10-27）

[English](CARRIER-RESEARCH.en.md)

本次没有找到覆盖所有省份、运营商、BB10 型号和 SIM 类型的完整实测配置库。能找到可追溯的 APN 样本和 IMS 标准，但它们不能替代用户的真实 SIM、网络开通和手机兼容性检查。

| 运营商 | MCC / MNC（本次快照） | 数据 APN | IMS APN / IP |
|---|---|---|---|
| 联通 | 460 / 01、09 | 3gnet | ims / IPv4v6 |
| 移动 | 460 / 00、02、07 | cmnet | ims / IPv4v6 |
| 电信 | 460 / 03、11 | ctnet | ims / IPv4v6 |

这些事实来自 [AOSP APN 配置固定提交](https://android.googlesource.com/device/sample/+/73f904fbeb872f5675cb5f18cd9dfb15856425a6/etc/apns-full-conf.xml)。源项目将文件定位为 [APN 示例](https://android.googlesource.com/device/sample/+/main/etc/README)，不是 BB10 适配认证。此次查询的 460-06 没有相应条目，因此没有将其自动加入模板。列表并非所有现用 MNC 的完整目录。固定提交、原始 XML 哈希和整理的数据见 [来源记录](../materials/carrier-data-sources.json)；发布包不包含整份原始 XML。

[ETSI TS 23.003，§13.2–13.3](https://www.etsi.org/deliver/etsi_ts/123000_123099/123003/16.11.01_60/ts_123003v161101p.pdf)给出了无 ISIM 时从实际 SIM 推导 IMS 身份和域名的规则，域名使用三位 MNC。代码据此保留前导零，并使用实际插入卡的数据，而非模板中第一个 MNC。

[ETSI TS 31.103](https://www.etsi.org/deliver/etsi_ts/131100_131199/131103/14.04.00_60/ts_131103v140400p.pdf)定义 ISIM 中的 IMPI、域名、IMPU 和 P-CSCF 等文件。由此不能推断有 ISIM 的卡可直接套用当前 USIM 路线；这部分需要专门实现。用户身份、鉴权信息、实际 P-CSCF、签约状态和终端策略不属于一份通用 APN 表可以提供的数据。

运营商官方页面还要求终端和业务具备 VoLTE 条件：[联通](https://img.client.10010.com/stprototype/volte/volte.html)、[电信](https://www.189.cn/volte/)。公开说明未提供可让任意 BB10 终端通话的完整 IMS 参数。不要把模板存在、预检通过或注册成功等同于通话可用。

实际适配以手机当前识别的原厂运营商配置为基础，仅替换 IMS 段。程序校验其数据 APN，避免在移动或电信卡上直接套用联通原厂配置。P-CSCF 从网络 PCO 获取。归属省份、使用省份、携号转网/漫游情况和真实通话验收由测试者补充。新增成功或失败样本欢迎通过脱敏报告和 PR 累积，形成逐台可追溯的兼容性记录。
