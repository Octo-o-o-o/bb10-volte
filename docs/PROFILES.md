# 运营商与运行配置

[English](PROFILES.en.md)

GUI 可选择 Q10 联通实测参数，或联通多 MNC、移动、电信公开资料模板。“编辑 / 导入配置”提供三组字段，支持 JSON 导入、导出和应用。字段会参与手机预检、安装回读和运行。

| 配置 | 行为 |
|---|---|
| 档案 ID / 名称 | 用户可命名；名称不能把未验证的参数变成实测 |
| MCC / MNC 列表 | 匹配实际 SIM；MNC 保留前导零，如 `00, 02, 07` |
| 数据 APN 列表 | 检查当前数据连接和原厂配置中的 internet APN；不会修改用户的数据 APN 设置 |
| 原厂配置 ID / SHA-256 | `auto` 使用当前 SIM 的 `true_home_carrier.preloadedConfigFile`；可指定数字 ID 和可选哈希；只允许原厂目录中的文件 |
| IMS APN / IP 类型 | 创建独立 IMS 服务；支持 `IPv4`、`IPv6`、`IPv4v6` |
| IMS 域名 | `auto` 从实际 SIM 推导，两位 MNC 补为三位；也可填有效域名 |
| SMS 能力 | 控制是否声明 SMS 服务；不等于短信已验证 |
| SIM、IMS APN、旧 IMS 退出等待 | 手机服务使用的有界等待时长；IMS APN 每轮使用此值，最多三轮 |
| 注册验证等待 / 检查间隔 | 桌面观察注册时长，以及运行检查间隔 |
| 自动启动 | 安装时设置开机启动；关闭后仍可手动启动本次验证 |

模板对应 [公开数据快照](../materials/carrier-data-sources.json)。移动、电信及其他联通 MNC 需勾选实验试用；这只允许全部技术检查通过后的安装，不保证入网或通话。JSON 顶层只允许 `schema`、`id`、`label`、`carrier`、`ims`、`runtime`；格式、类型和范围均在手机端重新验证，未知字段会被拒绝。

```powershell
python tools/q10.py preflight --ssh-config private/root-kit/ssh_config --profile profiles/china-mobile.json --allow-experimental
python tools/q10.py setup --ssh-config private/root-kit/ssh_config --profile profiles/china-mobile.json --allow-experimental

# Q20 / Q30 使用默认联通 460-01 参数的试用
python tools/q10.py preflight --ssh-config private/root-kit/ssh_config --allow-experimental
```

CLI 的 `setup`、`update`、`start`、`enable` 等操作需传入同一配置和试用选项。SSH 别名可用 `--host` 自定义。GUI 沿用当前选择。注册观察默认 180 秒，可改为 30–900 秒；超时只表示 pending。

**更新参数：挂断电话 → 停用并恢复 → 应用新配置并预检 → 更新并验证 → 双向通话验收。** 改参数不能直接启动旧安装；配置与试用选项的指纹须匹配安装回执。GUI 关闭后自定义配置不自动保存，请导出 JSON，下次重新导入。

手机保存 `carrier-profile.json`，安装回执绑定其哈希；原厂 XML 仅替换 IMS 服务段，保留数据及其他原有段落。恢复日志保存实际写入的 PPS 值，换运营商后仍能恢复旧值。完整 v0.1/v0.2 安装可停用恢复后更新；中断和外部改动会阻止覆盖。

P-CSCF 由网络 PCO 提供，IMSI/IMPI/IMPU 在手机本地取得和派生；不会下载他人身份。当前引擎不支持 ISIM，也不提供可编辑的补丁偏移、原生哈希绕过或鉴权替代。需要适配时请附脱敏报告提 Issue / PR。
