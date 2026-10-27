# 完整安装步骤

**简体中文** | [English](INSTALL.en.md)

本文面向 Windows。当前常驻代码尚在实机验收，具体完成项以 [VALIDATION.md](VALIDATION.md) 为准。

## 1. 核对设备与基线

测试组合是 Q10 **SQN100-3 / BB10 10.3.3.3216 / 中国联通 460-01 USIM**。先确认这张卡在支持 VoLTE 的设备上能够高清通话，并确认 Q10 原本能正常连接联通 4G。保留当前可用的原版恢复镜像。

初次 Root 刷写会清空手机用户数据，先备份。手机保持充足电量，使用稳定 USB 数据线。已有 Root、且本项目原生文件哈希全部匹配时，直接跳到第 3 节。

新电脑还需按 [Windows USB 驱动步骤](WINDOWS-USB.md) 准备并验证连接，再执行初次 Root。

## 2. 初次 Root 与自有 SSH 身份

1. 进入本项目目录；按 [材料清单](../materials/README.md) 下载文件到 `downloads/`。
2. 运行材料检查：

   ```powershell
   python tools/fetch_materials.py --verify-only
   ```

   缺失材料可运行 `python tools/fetch_materials.py` 下载，或使用浏览器下载到清单指定文件名后重新校验。

3. 准备独立 Root 工作目录及个人密钥。此操作只处理电脑文件，不连接或刷写手机：

   ```powershell
   python tools/prepare_root.py --seven-zip "C:\Program Files\7-Zip\7z.exe"
   ```

   生成目录为 `private/root-kit/`。脚本会保留 AppWorld，关闭 BerryCore 全目录授权，使用新生成的个人 SSH/主机密钥，替换包内默认授权。输入文件和依赖哈希不符时停止。

4. 在项目根目录构建镜像并检查原始分区：

   ```powershell
   python tools/build_root.py
   ```

   底层调用是 `bb10mt.exe batch -i 原版EXE -s patch-owner.txt -o 输出目录`，不调用刷写命令。完整日志与验证结果在 `private/root-kit/`；镜像位于其 `images/`。原始 IFS/RCFS/SIG2/MBR 和 radio 必须与 [基线清单](../materials/stock-partitions.json) 一致。

5. 按 Root 作者说明先运行 `private/root-kit/images/Q10_10.3.03.3216_SQN100-1-2-3-4-5_os.exe`，再运行同目录的 `Q10_10.3.03.3216_SQN100-1-2-3-4-5_radio.exe`。两者必须来自同一次构建。本文实测 radio 阶段返回 `Done` 并正常开机。OS 阶段出现过错误提示；任何错误都需要结合完整日志、后续 radio 结果及开机状态判断，不要一概忽略。
6. 手机正常开机后打开一次 **BlackBerry World**，等待 Root 完成。商店持续 loading 不影响这个触发步骤；Term49 出现只是提示，最终以 SSH 中的有效 UID 0 验证。
7. 电脑 USB 地址应为 `169.254.0.2`，Q10 为 `169.254.0.1`。准备脚本的授权仅允许这一 USB 电脑地址。测试：

   ```powershell
   ssh -F private/root-kit/ssh_config q10-root "echo connected"
   ```

   主机密钥使用自己准备镜像时生成的已知公钥固定校验。若手机已由另一套密钥 Root，使用那套经过验证的配置，勿替换本机信任记录来掩盖不匹配。

## 3. 安装 VoLTE 服务

回到项目根目录，保持手机开机、USB 连接及原卡。使用自己的 SSH 配置路径：

```powershell
python tools/q10.py install --ssh-config private/root-kit/ssh_config
python tools/q10.py check --ssh-config private/root-kit/ssh_config
python tools/q10.py start --ssh-config private/root-kit/ssh_config
```

安装器在修改网络配置前校验原生文件、原始策略 `00`、既有 IMS/VPN 与软件算法提供器。若提示已有实验进程或配置，先收尾原实验，不能删除未知对象来强行通过。

手机上安装到 `/var/rootdata/q10_volte`。启动入口为 `/var/addons/q10-unicom-volte/init/start.sh`，使用已安装 AutoRoot v4 的 addon 机制。原厂 `/radio/bin/ims_rrm` 不被覆盖。服务自己管理进程，电脑命令返回后继续运行。

首次启动会通过原生 RadioControl API 将语音策略改为 IMS 优先，可能出现一次短暂无线重载。此后服务等待 LTE 和 SIM 就绪，建立独立 IMS APN 并启动原生 IMS。

## 4. 查看状态并实际验收

约 1 分钟后：

```powershell
python tools/q10.py status --ssh-config private/root-kit/ssh_config
```

应看到 `phase=running`、`manager_alive=true`、`register_status="200 OK"`、`ran="LTE"`。注册成功后仍要完成 [通话验收](VALIDATION.md)：呼入接听、呼出、每次两个方向的声音、全程 4G，以及重启后复测。

启动入口在 Root 就绪后运行。若重启后 Root/SSH 尚未出现，先打开一次 BlackBerry World 等待；是否能完全自动恢复，以该机实际重启验收结果为准。

## 5. 停用、恢复与采集

先挂断通话。以下命令仅用于本项目自己的配置和进程：

```powershell
# 正常停止并恢复原语音策略、APN 和自有 VPN/软件提供器
python tools/q10.py stop --ssh-config private/root-kit/ssh_config
python tools/q10.py status --ssh-config private/root-kit/ssh_config

# 停止并禁止下次 Root 启动时自动运行
python tools/q10.py disable --ssh-config private/root-kit/ssh_config

# 保存私有日志，便于自己排障
python tools/q10.py collect --ssh-config private/root-kit/ssh_config

# 移除自动启动入口；保留恢复记录与程序，方便核对
python tools/q10.py uninstall --ssh-config private/root-kit/ssh_config
```

停止不是瞬间完成；状态应最终成为 `stopped`，`manager_alive=false`。`check` 应读回原语音策略 `0`、软件提供器 `-1`，且没有本项目 IMS 进程。`cleanup_required` 表示恢复遇到冲突，需要保留现场排查；不要重复安装覆盖日志。

若原生 IMS 自己退出，`native_exited` 会保留恢复记录，不在可能的系统关机过程中重载基带。设备稳定开机后先采集，再用显式 `stop` 恢复并核对。正常重启则由 addon 接续。

更新本项目脚本前，先 `stop`，等待上述恢复检查通过，再运行 `python tools/q10.py update --ssh-config private/root-kit/ssh_config`，然后 `start`。更新会校验旧文件仍与安装清单一致，并保留原恢复记录。若只安装、还没有启动，直接停用或卸载也可以。

`stop` 后 PPS 可能暂留上一次的 `register_status="200 OK"`。只有管理器存活、原生进程存在、当前 IMS 为 `connected` 且处于 LTE，才能判为正在注册在线。

`collect` 的内容可能包含手机号、SIM 标识和认证相关日志，保存在被 Git 忽略的 `private/`，不直接附到公开 issue。公开问题模板见 [提交问题](ISSUES.md)。
