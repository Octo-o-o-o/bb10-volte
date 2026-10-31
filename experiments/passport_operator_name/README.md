# Passport 电信名称修正

适用于本次已核验的 Passport SQW100-4 / WINDERMERE4ROW / BB10 10.3.3.3216。机主确认顶部已由 `460-11` 变为“中国电信”。记录见 [现场验收](../../materials/passport-operator-name-validation-2026-10-31.json)。

手机原厂 `BBSE-se13-network-override-list.txt` 为 9,231 字节，SHA-256 `bddd9ab02035490838c39c2ca33668d920753083153ffcd209a640d28febf810`，缺少 460-11。将完整原文保存在私有备份，在副本尾部追加唯一的 `中国电信|中国电信|460|11` UTF-8 行，副本 SHA-256 为 `48cf1cf31f55f5fe5c0632ae70283a2a282724270180a5ae9905f8ec562c9f59`。

`name.py` 使用 QNX `pathmgr_symlink` 将名称表路径指向副本，再仅更新 UICC `current_ons` 的长短名称。系统 RUM 和 navigator 随之自行显示“中国电信”，没有写入这些下游对象。原厂表字节不被覆盖；[QNX 文档](https://www.qnx.com/developers/docs/6.5.0SP1.update/com.qnx.doc.neutrino_lib_ref/p/pathmgr_symlink.html)说明该内存链接会随重启消失。

部署目录 `/var/rootdata/passport_operator_name` 与已有电信试验目录独立，包含本目录的 `name.py`、`start.sh`，以及从固定散列源码复制的 `device/native.py`、`device/device_info.py`（部署时分别名为 `native.py`、`device_info.py`）。四份文件的散列写入本目录独立 manifest，执行前逐项回读；本机仅针对这组文件授予 PathTrust。

`name.py install` 建立 `/var/addons/passport-operator-name/init/start.sh` 和独立 enabled 标记。启动脚本最多等待 Root 完成 120 秒，再由名称工作进程每 10 秒核对一次。同卡处于 460-11 归属 LTE、非漫游且正常服务时补上名称；不覆盖已有非数字品牌名，换到其他网络时移除自己的覆盖。停用时先移除本组件 enabled 标记，等待工作进程退出；它会清理自己的内存链接。未知链接、未知表内容均保留并拒绝覆盖。

本轮已验证入口文件散列、实际手动执行入口、重复执行复用同一工作进程以及手机顶部显示。**尚未进行正常菜单重启验收**，不把入口手动执行等同于实机重启通过。

本轮操作前，原电信测试服务的 1,800 秒期限已到期，原程序自行完成配置恢复，IMS 进程为空；残留的 `200 OK` 不是当前注册证据。本补丁仅修复名称，没有启动、停止或改写原电信 VoLTE 服务，也没有修改其自动启动许可。通话和电信重启入网应由原流程另行验收。

本地检查：

```powershell
python -m unittest discover -s tests -p test_passport_operator_name.py -v
```

7 项测试覆盖 Passport 的多位服务状态、错误归属卡、漫游、紧急服务、其他名称覆盖、原始表保留、真实品牌名称保留、换卡后的恢复隔离、保留新的非名称字段以及缺少 addons 父目录时的安装。
