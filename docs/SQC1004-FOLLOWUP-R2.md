# SQC100-4 第二轮统一补充清单 · 2026-11-01

谢谢，这次的包已经完整看过。你发来的 3 份 XML 和 5 个 init 文件，都与网页当前的 volte.zip 对应文件一致，这 8 个文件不用重复发送。

之前那段长采集命令不适合你当前环境：有命令缺失，且 awk 直接读 PPS 的缓冲区不够。这个问题在采集方案一侧，不表示手机必然没有 Root。下面换成短命令，并把需要澄清的事项一次列齐。

## 一、请一次回答这 6 项

不知道就写“不确定”，未保存就写“未保存”，不需要为回答问题重新刷包或拔卡。

1. **文件来自哪里、采集时是什么状态？** 这次 3 份 XML 和 init 是从手机哪个完整路径下载的，还是从电脑里的 volte.zip 解压取得？跑上次命令时，是刚刷包后可用，还是拔卡后失效、卸载后、重刷系统后或其他状态？这两件事分别回答。
2. **连接和 Root 环境。** 手机系统版本、Root 方案/版本；命令是在电脑 SSH、手机原生终端还是 Android 终端执行的？客户端名称和登录用户是什么？上次贴出的命令/日志是否经过 AI 改写、网页格式转换或手工整理？不要发登录密码。
3. **“刷 VoLTE 包”具体做了什么？** 当时用的 ZIP 文件名、下载日期，以及实际成功执行的安装/启动命令和顺序。是只安装 addon，还是还重刷系统、重新 Root、执行其他脚本？成功与失败都请贴原始命令和错误；“权限不够”的具体报错也请保留。包里没有自写 446，若它确实未起作用，不必重新制作它。
4. **当时“可用”的验证范围。** 主动呼出、接听来电是否都接通且双方有声音？是否有通话时仍为 LTE 的记录，还是只看到 4G/VoLTE 图标？当 APN 显示 cmnet 或 internet 时，普通移动数据是否也确实能上网、是否排除了 Wi-Fi/USB 网络？只写当时实际测过的项目。
5. **失效顺序。** 是同一张电信 SIM 拔出再插回，还是换了另一张卡？开机拔插还是关机换卡？第一次失效前后按时间列出：拔卡、插卡、重启、重新 Root、重新安装/启动等操作。特别说明“不拔卡、仅重启”以前是否测试过，是否也失效。现在不必新增这些测试。
6. **短信现象。** 普通手机发到本机、本机发到普通手机，分别是收不到、发不出、延迟还是重复？异常是在电话仍可用时就存在，还是只在拔卡失效后发生？业务短信/验证码的重复、延迟是否有大约时间记录？不需要电话号码、验证码或短信正文。

## 二、只读补采：在现有手机 SSH/终端中逐行执行

先保持当前状态。不要为采集重装、拔卡、重启或改 APN。若目前已经可用，注明“当前可用”；若失效，注明“当前失效”。已有另一状态的旧日志可以一起提供，不要求现在造出另一状态。

请从纯文本附件直接复制完整的一行，保留英文引号。不要通过 AI 重写命令，也不要手工补反斜杠或把终端里的提示符复制进去。输出在电脑端保存；命令没有往手机文件写入的 of=、输出重定向或安装操作。

### 先执行这一条，检查读取工具

```sh
dd if=/etc/os.version bs=262144 count=1
```

看到系统版本号即可继续。后面的 `records in/out` 是 dd 的正常统计信息，保留即可。若 dd 报找不到/无法执行，请试下面这条已知更基础的读取，并保留两条的结果，然后跳过 PPS 补采，继续第三节的文件/进程检查；不要安装 dd 或修改权限。

```sh
cat /etc/os.version
```

### dd 可用时执行这些 PPS 读取

每一行都是一次读取，未报告的字段是未知。管道里的 awk 只处理 dd 读出的文本，不直接打开 PPS。若出现 Message too long、Permission denied、语法错误或没有预期输出，保留原错误，不把它解释为 OFF/0/不存在，也不要扩大到导出所有私有状态。

```sh
echo BB10_R2_RADIO
dd if=/pps/services/cellular/radioctrl/status_public bs=262144 count=1 | awk -F: '$1 ~ /power_status|network_technology|network_service|active_bands|band_capability/ {print}'
echo BB10_R2_DATA
dd if=/pps/services/cds/cnice/status bs=262144 count=1 | awk -F: '$1 ~ /data_services_status|internet|ims|xmlfile_path|carrierid/ {print}'
echo BB10_R2_DATA_SETTINGS
dd if=/pps/services/cds/cnice/status_persistent bs=262144 count=1 | awk -F: '$1 ~ /data_service_mode|cdsc_xml/ {print}'
echo BB10_R2_IMS
dd if=/pps/services/ims/status_public bs=262144 count=1 | awk -F: '$1 ~ /status|default_ran|default_sys|allowVoLteProvisioning/ {print}'
echo BB10_R2_IR92
dd if=/pps/services/carrier_config/ims/ir92 bs=262144 count=1 | awk -F: '$1 ~ /UsePreconditions|SMS_Format/ {print}'
echo BB10_R2_IMS_CONFIG
dd if=/pps/services/carrier_config/ims/ims bs=262144 count=1 | awk -F: '$1 ~ /IMS_services|IMS_profilesV2|supported_networks|PCSCF_discoveryV2|SDK_Config|IMS_always_on/ {print}'
echo BB10_R2_VOICE_POLICY
dd if=/pps/services/carrier_config/radio_common/cellular_protocol_configuration bs=262144 count=1 | awk -F: '$1 ~ /voice_domain_preference_EUTRAN|ue_usage_setting|wcdma_to_lte_ps_ho_support/ {print}'
echo BB10_R2_ENGINEERING
dd if=/pps/services/escreens/config bs=262144 count=1 | awk -F: '$1 ~ /voice_domain_preference_EUTRAN_override/ {print}'
```

DATA 输出中的 internet/ims 是服务信息，可能带地址或账号；分享前按第四节脱敏。这里没有读取 UICC/SIM 私有对象，也没有导出运行时 IMS 身份文件。输出的 APN、加载路径和策略值仍须保留，方便定位。

## 三、文件、进程和已有日志

以下操作仅查看，不运行 ims_manager 的 check/probe/enable，不执行 start.sh。

```sh
echo BB10_R2_ENV
echo "$PATH"
pwd
echo BB10_R2_LOCATIONS
ls -ld /var/rootdata /var/addons /tmp/root.done
ls -l /var/addons/volte
ls -l /var/addons/volte/init
ls -l /var/addons/volte/data
echo BB10_R2_PROCESSES
/bin/pidin -p ims_manager arguments
/bin/pidin -p ims_rrm arguments
echo BB10_R2_LOG_FILES
ls -l /var/log/installer.log /var/tmp/bb10-volte /var/run/bb10_volte_stats.txt
echo BB10_R2_STATS
cat /var/run/bb10_volte_stats.txt
echo BB10_R2_MANAGER_EVENTS
grep BBE /var/log/installer.log | tail -n 160
echo BB10_R2_END
```

如果上述目录不存在，而你的文件在另一位置，只需提供实际原路径。不要创建目录或把包复制进去来匹配这些路径。日志不存在或命令不支持也保留错误。若终端只保存了错误、没保存正常输出，请开启电脑端终端记录并保存整个会话，不要手工整理成一份“结论”。

若以下**现有文件**可以从手机通过 SFTP 下载，请只下载到电脑，并保留原始目录关系：

- `/var/tmp/bb10-volte/provider.log`、`dca-enable.log`：提供器与 DCA 执行结果。
- `/var/log/installer.log` 中这次 VoLTE 操作及失败前后的相关段落。如果上面已拿到完整相关 BBE 事件，不必重复提供无关安装日志。
- `/var/dca/sources/ims/services/carrier_config/ims/ims`、`ir92`：实际落盘的 IMS/SMS 配置。
- `/var/dca/sources/ims/services/carrier_config/radio_common/cellular_protocol_configuration`。
- `/var/dca/sources/ims_defaults/services/carrier_config/radio_common/cellular_protocol_configuration`。
- `/var/dca/sources/omadm/services/carrier_config/radio_common/cellular_protocol_configuration`。
- `/var/dca/sources/test/services/carrier_config/radio_common/cellular_protocol_configuration`。
- `/etc/carrier/config/446.xml`，以及本次 DATA/DATA_SETTINGS 输出实际指向的运营商 XML。它若与已经发来的包内 XML 是同一个文件，说明手机原路径即可；若修改过，请发当前副本。

不存在或没有保存的项目写明即可。不要发送整个 runtime、整份 ims-start.log、SIP/AKA 认证日志或运行时 imsconfig 身份文件。

## 四、一次回传的内容

1. 上面 6 项的文字回答。
2. 本轮命令的完整输出，标注手机当时“可用/失效”、采集时间和时区，包含错误。
3. 第三节能取得的现有文件/日志，以及已保存的成功状态、失败状态原始记录（如果有）。

请在电脑分享副本中隐藏手机号、SIM/设备标识、账号密码、私钥、认证内容和个人 IP 地址；字段名、APN、carrier ID、系统路径、策略值、状态和时间要保留。原件自己保存，不修改手机文件。不要发送短信正文和验证码。

这轮主要确认“安装包到底执行了哪些步骤、实际加载了哪个 XML、拔卡后哪一步没有恢复”。无需继续试删 XML、补写 446 或反复刷包。修订命令已按 QNX 文档核对并做离线管道筛选检查，仍未在你的手机实测；错误仍需如实保留。

维护者参考：[QNX PPS 读取语义](https://www.qnx.com/developers/docs/6.5.0SP1.update/com.qnx.doc.neutrino_pps/subscribe.html)、[dd 参数](https://www.qnx.com/developers/docs/6.5.0SP1.update/com.qnx.doc.neutrino_utilities/d/dd.html)。
