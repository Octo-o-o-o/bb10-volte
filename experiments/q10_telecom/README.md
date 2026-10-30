# Q10 电信实机移植记录

本目录归档 2026-10-31 的 Q10 SQN100-3 / 10.3.3.3216 / AutoRoot v4 维护与取证工具。记录见 [实机证据](../../materials/q10-telecom-validation-2026-10-31.json)。核心入网功能已接入通用载荷；它仍在配置 IMS 前要求正常 LTE 数据连接。

当前已在与 Q20 同一张 460-11 电信卡上复现 UE EFS 1、voice EFS 3 和 modem 重载后的入网、独立 IMS 200/LTE、双向短通话及声音。实测接听后呼出 5.012 秒、呼入 4.217 秒；20 秒持续通话尚未验收。受控正常重启测试已启用，结果待记录更新。当前参数和完整 SIP 留在私有目录，公开证据不含号码、IMSI、ICCID、IMEI 或密钥。

## 维护连接

电脑还连接 Passport 时不能只靠默认 169.254.0.1 选择设备。使用已有的 Q10 私人 SSH 会话，保留其原主机密钥和授权，并在 `session.json` 写明已经识别的 USB 接口编号。socket 必须用 IP_UNICAST_IF 固定该接口，不额外绑定重复的本机源地址。每条远程命令再次检查 SQN100-3。

```powershell
$env:BB10_Q10_REPO = '<此仓库的绝对路径>'
$env:BB10_Q10_SESSION = '<已准备的 Q10 私人会话目录>'
$env:BB10_Q10_REPORTS = '<本地报告目录>'
python experiments/q10_telecom/q10_telecom_control.py refresh
python experiments/q10_telecom/q10_telecom_control.py telecom-preflight
```

`refresh` 只在指定接口读取现有 /30 地址并查询 discovery，确认 SQN100-3 后更新私人会话目标。Root 启动前后 USB 地址可能不同。首次换卡后本次 SSH 未自行出现，机主打开一次 BlackBerry World 才恢复；这一步不计为电信自动重启验收。后续重启必须保持不打开辅助程序，再独立核验新开机标识、管理器/原生进程、当前 IMS 以及电脑端零启动命令。

## 文件职责

- `q10_readonly_archive_phone.py`：在原联通服务在线时冻结 78 个文件及必要的私有状态，并确认服务状态未被改变。电脑逐份校验散列。
- `q10_stop_owned_phone.py`：仅针对当次准确散列与档案的旧 0.3.2 联通安装，空闲后调用原安装器停用；其他版本保留并拒绝处理。
- `q10_call_recorder_phone.py`：仅记录当前开机、自有原生 IMS PID 的 SIP 和 LTE 样本，不发起电话、不修改服务或网络；finish 只结束记录器。
- `q10_enable_controlled_reboot_phone.py`：严格核对人工双向声音/LTE、完整 SIP、当前 profile/开机/PID、同一张 SIM、原始备份、已拥有的 UE1/voice3 和开机入口，才启用本轮受控重启。它不等同于通用安装器已开放所有电信机型的自动启动。
- `q10_install_phase_probe_phone.py`、`q10_finish_prepared_install_phone.py`：归档当次安装准备错误的调查与收尾。后者只接受已知载荷的精确散列、完整文件、确切事务、无运行实例和原始策略；电脑验证原文备份回执后才完成该事务。它不是任意中断点的自动修复器。

本次修复了两个实际集成问题：数据设置 ON、实际服务 OFF 时应允许执行恢复入网的前置流程；手机 Python 的安装准备应从已校验并授予 scoped PathTrust 的安装目录导入 service。修正后正常更新与回读已经通过。

Q20 保留自己的成功配置，换出电信卡后保持关机。Passport 属于另一个活动会话，本轮没有向其发送命令。Q30 的提供器生命周期限制继续保留。
