# 测试反馈与问题报告 / Test results and issues

欢迎提交 Q10、Classic（Q20）、Passport（Q30）和其他 BB10 设备、地区与运营商的测试反馈，**可用和不可用都欢迎**。目前唯一的实机通话组合是 Q10 SQN100-3 / BB10 OS 10.3.3.3216 / 北京中国联通 460-01。通过公开的 [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues) 提交，中文或英文均可。

请复制填写以下项目；无法取得的信息写“未知”，不必为了反馈另装诊断工具。

```text
结果：可用 / 不可用 / 部分可用
机型与硬件变体：
BB10 完整版本：
运营商与 MCC/MNC（如有）：
号码归属地区 / 实际使用地区（无需手机号）：
漫游 / 携号转网：
项目版本或提交号：
使用方式：源码 / Windows EXE / macOS DMG
电脑系统（源码用户另附 Python 版本）：
已完成步骤 / 失败阶段 / 错误提示：
呼入与呼出：
双方声音与通话是否保持 4G：
断开 USB 后的通话结果：
手机菜单正常重启后的结果：
```

可附 GUI 导出的脱敏预检 JSON、所选配置 JSON 和是否开启实验试用。报告包含自动识别的型号、硬件变体、OS 和原生文件指纹。自定义名称不要填写个人信息。单纯注册成功不等于实际通话可用，请区分“未测试”和“失败”。

请先审阅内容，再提交公开issue。不要上传 `private/`、Root镜像、SSH密钥、原始SIP日志、IMSI/ICCID/IMEI/PIN、号码或认证字段。固件哈希、阶段、SIP状态码、匿名化事务时序通常足够初步判断。

新增型号支持需要独立原生文件和ABI验证，不能只删除哈希检查。提出支持请求时，先说明固件版本和哪些文件散列不同。

## English

Both working and non-working device/carrier combinations are welcome in [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues). Only Q10 SQN100-3 / BB10 OS 10.3.3.3216 / Beijing China Unicom 460-01 has hardware calling evidence so far.

Include the result, phone model/variant, full BB10 version, carrier and region, MCC/MNC if available, roaming/number-porting status, project version, source/EXE/DMG method and desktop OS. Source users should include the Python version. Describe the completed steps or failure stage/error, incoming/outgoing calls, audio in both directions, continued 4G, USB-disconnected use and recovery after a normal phone-menu reboot. Mark checks you have not performed as untested. Registration alone does not prove calling works.

Optionally attach the GUI's redacted preflight report and selected profile. Do not publish private directories, Root images, SSH keys, raw SIP logs, phone numbers, SIM/device identifiers or authentication material. Unknown fields may be left as unknown; no extra diagnostic tools are required to report a result.
