# SQC100-4 电信：旧版成功配置与当前状态回传

适用现场：同一台 SQC100-4、同一张电信 SIM，曾用本项目旧版配合 AI 操作成功上网和打电话，目前无法正常使用移动数据。目标是比对两个状态，找出实际生效的配置和中间的变更。

## 1. 先保留当前现场

请保持现在的 SIM、网络设置和工具状态，先采集，再讨论修复。此次不需要重新安装、恢复旧版、重启、切换飞行模式、改 APN、改名或删除 XML、结束进程，也不要重新执行聊天记录里的修复命令。

以下命令在**已经连接手机的 root SSH 窗口**中执行，不是在电脑的 PowerShell 中执行。它们读取状态、列出指定目录和查询进程，不调用项目服务脚本，也不写入电话配置。输出留在终端；用电脑上的终端日志功能保存，或复制到电脑文本文件。

命令包含两层筛选：只读取相关对象，只输出指定字段。运营商私有状态仅提取 carrier ID、MCC/MNC 和配置路径，不回传整个私有对象。进程参数、文件名和另行下载的文件仍需按第 5 节检查。

## 2. 一次粘贴的只读采集命令

从下面第一个 `(` 复制到最后一个 `)`，整段粘贴。括号让临时函数在子 shell 内结束，不改变当前 SSH 会话的函数。没有输出的字段属于未报告/未识别，**不能按 0、关闭或不存在解释**。

如果某个命令不存在、读取失败或权限不足，保留错误，继续收集其他材料；不要为此安装组件或修改信任设置。如果长时间没有返回，可按 Ctrl+C，并注明停在哪个路径。此命令已做离线检查，尚未在这台反馈手机上运行。

```sh
(
printf 'BB10_READONLY_BEGIN\n'
date -u
id -u
cat /etc/os.version

bb10_read_pps() {
    printf '\nPPS %s\n' "$1"
    if [ ! -e "$1" ]; then printf 'MISSING_OR_UNREACHABLE\n'; return; fi
    if [ ! -r "$1" ]; then printf 'UNREADABLE\n'; return; fi
    awk -v mode="$2" '
    function atom(s, key, tail) {
        if (!match(s, "\"" key "\"[ \t]*:[ \t]*")) return "<absent>"
        tail = substr(s, RSTART + RLENGTH)
        if (match(tail, /^"[^"\\]*"/)) return substr(tail, 1, RLENGTH)
        if (match(tail, /^(true|false|null|-?[0-9]+)([ \t]*[,}]|[ \t]*$)/)) {
            tail = substr(tail, 1, RLENGTH)
            sub(/[,}].*$/, "", tail); gsub(/[ \t]/, "", tail); return tail
        }
        return "<unparsed>"
    }
    function num(s) { return s ~ /^[0-9]+$/ && length(s) <= 10 ? s : "<unknown>" }
    function flag(s) { return s == "true" || s == "false" ? s : "<unknown>" }
    function path(s) {
        if (s == "<absent>" || s == "" || s == "\"\"") return "<empty_or_absent>"
        if (s ~ /^".*"$/) s = substr(s, 2, length(s) - 2)
        if (s ~ /^\/(base\/)?etc\/carrier\/config\/[0-9]+\.xml$/ ||
            s ~ /^\/var\/addons\/volte\/data\/carrier-[0-9]+-volte\.xml(\.[A-Za-z]+)?$/ ||
            s ~ /^\/var\/(rootdata\/q10_volte|q20_volte|bb10_volte)\/runtime\/carrier\/[0-9]+(-ims)?\.xml$/ ||
            s ~ /^\/var\/radio\/cdsc\/[0-9]+(-ims)?\.xml$/) return s
        return "<other_path_not_exported>"
    }
    function service(s, name, apn, i, fields, count) {
        apn = atom(s, "apn")
        print name ".apn=" (apn ~ /^"(ctnet|ctlte|ctwap|ims|cmnet|3gnet|uninet)"$/ ? apn : "<unknown_or_other>")
        count = split("enabled active connectable connected", fields, " ")
        for (i = 1; i <= count; i++) print name "." fields[i] "=" flag(atom(s, fields[i]))
        print name ".xmlfile_path=" path(atom(s, "xmlfile_path"))
        print name ".carrierid=" num(atom(s, "carrierid"))
    }
    {
        line = $0; sub(/^\[[^]]*\]/, "", line)
        if (line ~ /^@/ || index(line, ":") == 0) next
        key = substr(line, 1, index(line, ":") - 1)
        value = substr(line, index(line, ":") + 1); sub(/^[^:]*:/, "", value)
        count_fields++
        if (mode == "device" && key == "modelnumber") print key "=" (value ~ /^SQ[NCW]100-[0-9]+$/ ? value : "<unknown>")
        if (mode == "board" && key == "Board_Type") print key "=" (value ~ /^(CLASSICATT|CLASSICVZW|WINDERMERE4ROW)$/ ? value : "<unknown>")
        if (mode == "radio" && key == "network_service") print key "=" num(value)
        if (mode == "radio" && key ~ /^(active_bands|band_capability)$/) print key ".lte=" num(atom(value, "lte"))
        if (mode == "radio" && key == "network_technology") {
            compact = value; gsub(/[ \t]/, "", compact)
            print key "=" (compact ~ /^\[("(lte|gsm|umts|wcdma|cdma|evdo)"(,"(lte|gsm|umts|wcdma|cdma|evdo)")*)?\]$/ ? compact : "<unknown>")
        }
        if (mode == "radio" && key == "power_status" || mode == "data" && key == "data_services_status" || mode == "settings" && key == "data_service_mode") print key "=" (value ~ /^(ON|OFF)$/ ? value : "<unknown>")
        if (mode == "data" && key ~ /^(internet|ims)$/) service(value, key)
        if (mode == "data" && key == "xmlfile_path" || mode == "settings" && key == "cdsc_xml") print key "=" path(value)
        if (mode == "data" && key == "carrierid") print key "=" num(value)
        if (mode == "carrier" && key == "true_home_carrier") {
            print "true_home_carrier.mcc=" num(atom(value, "mcc"))
            print "true_home_carrier.mnc=" num(atom(value, "mnc"))
            print "true_home_carrier.carrierid=" num(atom(value, "carrierid"))
            print "true_home_carrier.preloadedConfigFile=" path(atom(value, "preloadedConfigFile"))
            print "true_home_carrier.downloadedConfigFile=" path(atom(value, "downloadedConfigFile"))
        }
        if (mode == "ims" && key ~ /^(status|default_ran|default_sys)$/) print key "=" (value ~ /^(connected|disconnected|idle|lte|LTE|wlan|WLAN|cellular)$/ ? value : "<unknown>")
        if (mode == "ims" && key == "profiles") print "profiles=" (value ~ /^\[[ \t]*\]$/ ? "EMPTY_ARRAY" : "NONEMPTY_OR_UNPARSED")
        if (mode == "ims" && key == "allowVoLteProvisioning" || mode == "ir92" && key == "UsePreconditions") print key "=" (value ~ /^[01]$/ ? value : "<unknown>")
        if (mode == "policy" && key == "voice_domain_preference_EUTRAN" || mode == "engineering" && key == "voice_domain_preference_EUTRAN_override") print key "=" (value ~ /^[0-6]$/ ? value : "<unknown>")
        if (mode == "policy" && key == "ue_usage_setting") print key "=" (value ~ /^(voice_centric|data_centric)$/ ? value : "<unknown>")
        if (mode == "imscfg" && key ~ /^(IMS_profilesV2|supported_networks|IMS_services|Home_network_domain_name)$/) print key "=FIELD_PRESENT_CONTENT_NOT_EXPORTED"
    }
    END { print "parsed_attribute_count=" (count_fields + 0); print "UNLISTED_FIELDS_ARE_NOT_EVIDENCE_OF_ZERO_OR_ABSENCE" }
    ' "$1"
    bb10_read_result=$?
    printf 'reader_exit=%s\n' "$bb10_read_result"
}

bb10_read_pps /pps/services/deviceproperties device
bb10_read_pps /pps/services/hw_info/inventory board
bb10_read_pps /pps/services/cellular/radioctrl/status_public radio
bb10_read_pps /pps/services/cds/cnice/status data
bb10_read_pps /pps/services/cds/cnice/status_persistent settings
bb10_read_pps /pps/services/carriermanager/status_private carrier
bb10_read_pps /pps/services/ims/status_public ims
bb10_read_pps /pps/services/ims/status_persistent count_only
bb10_read_pps /pps/services/carrier_config/radio_common/cellular_protocol_configuration policy
for bb10_source in ims ims_defaults omadm test; do
    bb10_read_pps "/var/dca/sources/$bb10_source/services/carrier_config/radio_common/cellular_protocol_configuration" policy
done
bb10_read_pps /pps/services/escreens/config engineering
bb10_read_pps /pps/services/carrier_config/ims/ir92 ir92
bb10_read_pps /pps/services/carrier_config/ims/ims imscfg

printf '\nRELEVANT_PROCESSES\n'
/bin/pidin -p ims_rrm arguments
/bin/pidin -p ims_manager arguments
/bin/pidin -p python3.2 arguments | awk '/\/var\/(rootdata\/q10_volte|q20_volte|bb10_volte)\// {print}'

for bb10_dir in /var/addons/volte /var/addons/volte/data /var/addons/volte/init /var/addons/q10-unicom-volte/init /var/addons/bb10-unified-volte/init /var/rootdata/q10_volte /var/rootdata/q10_volte/runtime/carrier /var/q20_volte /var/q20_volte/runtime/carrier /var/bb10_volte /var/bb10_volte/runtime/carrier /var/radio/cdsc; do
    printf '\nDIRECTORY %s\n' "$bb10_dir"
    ls -ld "$bb10_dir"
    if [ -d "$bb10_dir" ]; then ls -l "$bb10_dir"; fi
done
printf '\nCONFIG_PRESENCE_ONLY\n'
ls -ld /var/ims/carrier/imsconfig_user.xml /pps/volte_probe /var/etc/autostart.conf

printf '\nNATIVE_FILE_CHECKSUMS\n'
if command -v sha256sum >/dev/null 2>&1; then
    printf 'ALGORITHM=SHA256\n'
    sha256sum /radio/bin/ims_rrm /radio/bin/qct_rrm /usr/sbin/dca /radio/lib/libradiocontrol.so.0.1 /etc/carrier/config/446.xml
else
    printf 'ALGORITHM=POSIX_CKSUM_NOT_SHA256\n'
    cksum /radio/bin/ims_rrm /radio/bin/qct_rrm /usr/sbin/dca /radio/lib/libradiocontrol.so.0.1 /etc/carrier/config/446.xml
fi
date -u
printf 'BB10_READONLY_END\n'
)
```

把从 `BB10_READONLY_BEGIN` 到 `BB10_READONLY_END` 的输出，包括错误，一起保存为电脑上的 `01-current-state.txt`。如果中途停止，保存已得到的部分，注明“采集中断”。不要只截最后几行，也不要把上面的命令文字当成运行结果。

这是依次读取的状态快照，不是同一时刻的原子快照。简单字段筛选不等于完整 JSON 校验；陌生格式保留为 unknown，不能据此宣布注册、数据或通话成功。工程 override 和 DCA 的枚举分别记录，不互换。命令不会读取基带注册拒绝原因或做真实数据、来电验收。

## 3. 当前手机上需要下载的文件

用现有 SSH 客户端的 SFTP/文件下载功能，**只从手机下载到电脑**，不要上传、移动、压缩或覆盖手机上的文件。下列路径不存在就标记“不存在”，权限不足就标记“无法读取”，不用新建或修复它。

| 优先级 | 路径/文件 | 回传用途 |
| --- | --- | --- |
| 必要，存在就提供 | `/var/addons/volte/data/` 内全部 `carrier-*-volte.xml*` 文件 | 包括 446、339、36、其他编号及 `.disabled`、`.bak` 等已有副本；保留真实文件名。只发 446 无法排查误选其他 XML。 |
| 必要，存在就提供 | `/etc/carrier/config/446.xml`；采集输出中实际选中的其他 `/etc/carrier/config/数字.xml` | 对比原厂数据 APN、IMS 段及 carrier ID。不要把整个原厂目录打包。 |
| 必要，存在就提供 | `/var/radio/cdsc/` 内运营商 XML；三个项目目录的 `runtime/carrier/` 内 XML | 三个目录为 `/var/rootdata/q10_volte`、`/var/q20_volte`、`/var/bb10_volte`。保留来源路径；不要合并覆盖同名文件。 |
| 必要，存在就提供 | 以上三个项目目录顶层的 `installation.json`、`payload-manifest.json`、`payload.json`、`carrier-profile.json`、`profile-request.json` | 判断具体版本、载荷和选择的模板。逐个核对敏感字段后再发。不是要求提供全部目录。 |
| 必要，存在就提供 | `/var/addons/volte/init/`、`/var/addons/q10-unicom-volte/init/`、`/var/addons/bb10-unified-volte/init/` 内启动脚本 | 只下载文本，不执行。用于核对启动的是哪个版本、哪个路径。 |
| 必要，若曾被 AI 修改 | 实际改过的启动脚本、服务脚本、XML、JSON、DCA 配置；电脑上当时生成的 `446.json` 等自定义配置 | 提供原路径、修改日期、当时是否实际运行；若不记得，写“不确定”，不要根据猜测补写。 |
| 补充，存在就提供 | 四个 `/var/dca/sources/{ims,ims_defaults,omadm,test}/services/carrier_config/radio_common/cellular_protocol_configuration` 文件 | 上述命令已提取关键字段；下载这些现有文件可比对其他策略项。不要把整个 DCA 目录打包。 |
| 补充，若当时改过 | `/var/etc/autostart.conf` 中本项目相关行，以及这些行指向的启动脚本 | 无关服务行不用发，注明删去了无关内容。 |

如果输出的 `cdsc_xml` / `xmlfile_path` / `preloadedConfigFile` 指向表格外的路径，请补充**脱敏后的路径和对应运营商配置文件**；路径若显示 `other_path_not_exported`，说明自动输出隐藏了陌生路径。请在本地核对该字段后补充，不要回传整个 `status_private`。

`/var/ims/carrier/imsconfig_user.xml` 本轮只需存在性，不要发送运行时原文；它可能包含 SIM 派生身份。不要回传 `state.json`、整个 `runtime/`、整个手机备份、私钥、Root 镜像、完整 SIM 私有状态或 SIP/AKA 认证日志。

## 4. 旧版成功时的材料：这部分最关键

请单独建立电脑文件夹 `03-old-working/`，和当前手机下载的 `02-current-files/` 分开。现在手机上的文件，即使文件名相同，也不能直接标成“成功时的版本”。

1. **当时实际使用的项目包**：原始 ZIP/安装包文件名、版本号/桌面修订号、下载地址或 Git 提交；仍保留安装包就一起提供。若只剩链接，提供链接和大约下载日期。不要重新下载最新版来代替旧包。若还用过上游 `volte.zip`，也请单独提供其来源和原包。
2. **AI 实际执行记录**：相关对话导出或终端日志，至少包含实际执行的命令、生成/修改文件的完整内容和执行后的输出。请区分“建议但没执行”“执行失败”“确实执行成功”；尤其保留安装、停用、删除/改名、DCA/语音域修改、启动和重启步骤的顺序。只需这次操作相关段落，不用发送完整聊天历史。
3. **成功时保存的配置副本**：当时的 446 运营商 XML、自定义 JSON、启动/服务脚本和改过的 DCA 文件；既要成功后的版本，也要还保留的修改前备份。每个文件注明“成功后保存”“修改前备份”或“来源不确定”。
4. **成功证据**：当时的检查报告、加载的 XML 路径、终端输出和已有通话/数据测试记录。有截图可以附上；没有就按下面模板回忆，不要求现在重新操作。

找不到旧包、日志或成功快照时，直接写“未保存”。AI 生成的事后总结可以附上，但请标明它是总结，不能替代原始命令和文件。

## 5. 回传前在电脑上检查敏感内容

本轮只需要技术配置。请在**电脑上的分享副本**中遮掉手机号、IMSI、ICCID、IMEI、设备 PIN、账号/密码、SSH 私钥、带身份的 SIP URI（IMPI/IMPU）、认证密钥和 token。截图也要检查。原件自行保留，不要编辑手机原文件。

保留字段名和结构，用 `[REDACTED]` 替换敏感值；注明哪些文件被脱敏。保留型号、系统版本、运营商 MCC/MNC、carrier ID、APN、非个人身份的运营商域名、策略枚举、服务状态、文件路径和哈希，这些是比对所需信息。若路径包含个人目录名，仅遮掉个人部分。哈希来自原文件，脱敏后文件内容变化是正常的。

## 6. 填写这份说明，一起发回

保存为 `04-timeline.txt`，不知道的写“不确定”，不要推测：

```text
当前采集时间（本地时间、时区）：
手机时间是否准确：
同一台 SQC100-4、同一张电信 SIM：是 / 否 / 不确定
当前 OS / Root 方案及版本：
当前电脑工具完整版本 / 桌面修订号：
旧版成功时的项目包文件名 / 版本 / 来源：
AI 操作记录：已附 / 未保存 / 仅剩事后总结

最后一次确认正常的大约时间：
当时实际移动数据能上网：是 / 否 / 未测
当时验证上网时 Wi-Fi、USB 网络是否排除：是 / 否 / 不确定
当时主动呼出：接通且双向有声音 / 仅拨号 / 未测
当时接听来电：能到达、接听且双向有声音 / 其他 / 未测
当时通话是否全程保持 LTE：有记录 / 没有记录 / 不确定
当时是否验证重启后仍正常：是 / 否 / 不确定
成功时实际加载的 XML 路径：已附记录 / 未保存

从最后一次成功到当前失败，按顺序列出发生过的操作：
1. 时间 — 操作（更新/卸载/停用/重刷/换卡/改 APN/改名或删除配置等）— 使用版本 — 操作后现象
2.
第一次发现失败是在上面哪一步后：
当前是否仍能偶尔上网或通话（只写已有观察）：
采集时 Wi-Fi / USB 连接状态，最近是否刚开机或切换网络：
哪些要求的文件不存在、无法读取或未保存：
哪些分享文件做了脱敏：
```

最后一次性发送：

- `01-current-state.txt`：此次命令的完整实际输出。
- `02-current-files/`：当前文件，按原路径保留子目录。
- `03-old-working/`：旧包、AI 实际操作记录、成功时配置和已有证据。
- `04-timeline.txt`：填写后的情况说明。
- `05-preflight/`：已经保存的 `bb10-volte-preflight.json`、排查摘要和界面截图，注明各自采集时间和工具版本。无需为本轮下载或启动另一版工具。

这些材料在**电脑上**打包后发回即可。我们会先比较版本、实际加载路径、XML 内容、启动链和 DCA 来源，再决定是否需要下一轮设备操作；本轮不承诺仅凭快照就能确定基带拒绝原因。

维护者依据：进程命令使用 QNX 的 [`pidin arguments`](https://www.qnx.com/developers/docs/6.5.0SP1.update/com.qnx.doc.neutrino_utilities/p/pidin.html) 查询接口。配置路径与字段依据本项目已有诊断及该设备反馈；当前安装状态不能证明旧配置来源或历史通话结果。
