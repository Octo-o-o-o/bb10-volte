# 桌面 r48 / 手机版 0.1.0.48：APN 引导与三网名称加固、QNX 运行时防护及手机端诊断完善

2026-11-15。macOS 仍停在 **v0.5.0-r43**，本次没有新的 Mac 安装包。

- **加固 3GPP OI 后缀与新号段默认承载 APN 引导**：`profiles.normalize_apn()` 自动剥离高通基带／PGW 返回的 3GPP 运营商标识后缀（如 `.mnc008.mcc460.gprs`、`.mnc06.mcc460.gprs`）后再比对数据 APN 与 `ims` APN；当 `460-08`、`460-09`、`460-12` 等新号段在系统映射到空壳 `/etc/carrier/config/0.xml`（或留空）且受管 `cdsc_xml` 尚未接管时，除空 APN 外同时允许基站 MME 下发的默认附着 APN（如 `cmiot`）进入受控引导安装，并在绑定原厂只读模板时完整校验 `0.xml` SHA-256／非符号链接属性、保留 `fallback_used` 与 `original_preloaded_config` 审计元数据。
- **三网 12 号段运营商名称显示兜底与原地升级／回滚闭环**：`unified_operator_name.py` 将内存态 SE.13 运营商覆盖表（`/var/run/bb10-volte-se13-override.txt` 绑定覆盖，不改 `/base` 只读分区）与纯数字 `current_ons` 中文回退扩展至中国移动（`00`／`02`／`04`／`07`／`08`）、中国联通（`01`／`06`／`09`）、中国电信（`03`／`05`／`11`／`12`）全部 12 个商用号段，保留非纯数字既有品牌显示，并在升级／恢复时兼容识别 `r42`–`r47` 旧版仅含 `460|11` 的覆盖文件。
- **QNX Python 3.2 `IOError` 全链路防护与有界日志采集**：在手机端运行的全部 `device/` 与 `mobile/runtime/` 模块补齐 Python 3.2 下与 `OSError` 分离的 `IOError` 捕获；将 `service.collect_vpn_evidence()` 中无超时的 `slog2info -b ims_rrm` 调用改为 8 秒有界超时执行；补齐 `SQW100-3 -> WINDERMERENA` 板型映射、P’9983 `SQK100-1/2` 正则覆盖与损坏离线更新 ZIP 异常拦截。
- **手机原生应用首次点击具体拒因提示、冷启动缓存与 BAR 打包卫生**：手机端首次点击激活及冷启动重开均可直接展示中国广电 `460-15`、含 ISIM 的新版 5G USIM、系统已下载 OTA 运营商配置覆盖与未识别归属网络的具体说明（不再笼统退回通用不支持文案），同时新增 `waiting_sms` 冷启动状态缓存；`package_mobile.py` 在准备与打包阶段清理并强校验 `runtime`、`payload`、`profiles`、`materials` 四个资产目录，杜绝历史遗留未签名文件进入正式 BAR。
- **桌面端、内置 AI Skill 与中英文官网／文档全量对齐**：修复桌面离线导入配对响应时的主机指纹核对字段、恢复界面提示与英文翻译表漏译键，同步更新 `.agents/skills/bb10-volte`、`ai_skill.py` 与中英文官网及兼容性文档；完整保留 `r46` 电信发信本地完成补丁（`telecom_mo_ack`）与状态栏黑莓图标自动点亮、`r47` 三网全号段准入与 Passport 电信呼入语音修复。
- 已发布的 `r42`–`r47` 后台停用后可直接原地升级，保留原备份和恢复机制。本轮未连接实机；各型号与地区双向通话、短信及长期待机仍以用户真机实测为准，历史记录按原测试版本单列。Windows EXE 仍没有 Authenticode 发布者签名。
