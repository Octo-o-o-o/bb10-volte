# 用另一台设备做 IMS 对照

本方案已经由 Q10 自己获得网络参数和完成 SIM 认证；安装不需要把安卓手机接在旁边。安卓对照的价值是确认卡与套餐能正常提供 IMS 语音，以及区分卡、数据连接和电话状态。本次实际对照是 Lenovo TB350XC / Android12，使用同运营商主副卡中的另一张卡。

主副卡属于同一套餐也有各自的 SIM 身份，不能复制另一张卡的 IMSI、IMPI、IMPU 或认证结果。本项目从 Q10 当前插入的 USIM 派生身份。

## Android 的只读方法

1. 使用自己允许调试的设备，开启 USB 调试并在手机确认电脑授权。用官方 [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) 中的 ADB。
2. 执行 `adb devices -l`，选定正确设备。以下 `$deviceSerial` 必须换成那台设备在本机显示的序列号。
3. 建立私有目录，读取服务列表；不同厂家暴露的服务名称不同。

   ```powershell
   $deviceSerial = '替换为自己的设备序列号'
   New-Item -ItemType Directory -Force private/android-control
   adb -s $deviceSerial shell dumpsys -l > private/android-control/services.txt
   adb -s $deviceSerial shell getprop ro.product.model
   adb -s $deviceSerial shell getprop ro.build.version.release
   ```

4. 本次联想实际可读取的服务包括以下几项。某项不存在或拒绝访问时记录结果，不为此更改基带或刷写配置。

   ```powershell
   adb -s $deviceSerial shell dumpsys -t 12 mtkIms > private/android-control/mtkIms.txt
   adb -s $deviceSerial shell dumpsys -t 12 telephony_ims > private/android-control/telephony_ims.txt
   adb -s $deviceSerial shell dumpsys -t 12 phone > private/android-control/phone.txt
   adb -s $deviceSerial shell dumpsys -t 12 telephony.registry > private/android-control/telephony.registry.txt
   adb -s $deviceSerial shell dumpsys -t 12 carrier_config > private/android-control/carrier_config.txt
   adb -s $deviceSerial shell dumpsys -t 12 connectivity > private/android-control/connectivity.txt
   ```

5. 在私有输出里依次核对：IMS 是否注册、MMTEL 语音能力是否可用、IMS 数据连接是否建立、IP 类型和网络返回的 P-CSCF。最后用系统拨号器实际测试双方声音；配置开关和注册状态各自只能证明其中一层。

`mtkIms` 是这台联想的实现名称，不能套用到所有安卓设备。高通平台有另一套 QMI/厂商服务；鸿蒙设备也不能假设开放相同 ADB 或系统转储接口。优先使用该设备本身已允许的只读诊断。

## 如何把对照结果用于 Q10

| 观察 | 可用于判断 | 不能直接复制 |
| --- | --- | --- |
| 同运营商卡能注册且可高清通话 | 运营商侧存在可用 IMS 业务 | 另一张卡的私有身份或会话凭据 |
| IMS APN、IP 类型 | 数据连接配置的方向 | 另一台设备当时的动态地址 |
| P-CSCF、路由、QCI | IMS 专用连接已建立 | 把临时 P-CSCF 硬编码成长期配置 |
| MMTEL voice capability | 该设备当前可提供 IMS 语音 | 认为 Q10 普通语音选择器已放行 |
| 系统拨号成功和双方声音 | 当前端到端通话成立 | 仅凭状态栏图标作同等结论 |

对照日志可能带号码、IMEI、SIM 标识和认证资料，保留在 `private/`。对外仅整理匿名化状态、时间和结论。

## 原始资料

- [AOSP IMS 架构](https://source.android.com/docs/core/connect/ims)：框架与厂商 IMS 实现的关系。
- [AOSP ISIM 读取代码](https://android.googlesource.com/platform/frameworks/opt/telephony/+/81ddb88/src/java/com/android/internal/telephony/ims/IsimUiccRecords.java)：ISIM 的 IMPI、IMPU、DOMAIN 文件读取；这些不是任意应用可读取的普通属性。
- [libqmi UIM 定义](https://github.com/linux-mobile-broadband/libqmi/blob/main/data/qmi-service-uim.json)：卡和应用状态查询的公开定义。本次 Q10 由原生库只读验证 USIM READY，没有 ISIM。
- [qmicli 作者文档](https://www.freedesktop.org/software/libqmi/man/latest/qmicli.1.html)：区分卡状态、数据连接和 IMS 状态的诊断入口；Q10 不直接依赖该工具。
- Q10 的身份派生与实际实现见 [设计说明](DESIGN.md)。
