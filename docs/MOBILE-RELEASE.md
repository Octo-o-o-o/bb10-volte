# 手机构建、签名与发布

此流程生成手机 **0.1.0.6 / 桌面 0.5.0-r16 / 协议 2** 的可审查候选，不会自动上传、创建 Release、修改线上下载或发送通知。r16 保留并合入已有 r15 的机型检查、受控试验、反馈与教程。安装方法见[中文指南](MOBILE-INSTALL.md)和[英文指南](MOBILE-INSTALL.en.md)。

合并前 v5 已完成双平台 697 项测试、73 项独立 mobile 测试和两位 reviewer 窄复评。合并后 v6 已通过 Windows 744 项测试（51.515 秒，2 项平台专用跳过）和真实 SDK BAR/完整签名包构建；Mac 合并后全量测试、最终复评及文档收尾后产物回读另补。底层设备探针已通过，最终 BAR 安装、权限、UI、新引擎迁移与无线验收仍待完成，详见[验收记录](MOBILE-VALIDATION.md)。

## 固定依赖与身份

- ARMv7/QNX、C++98、Qt 4.8/Cascades；设备 Python 3.2。
- 构建镜像：`ghcr.io/xiazy/blackberry10-toolchain@sha256:60ce49510a37ed92368cca010bbaabf97b12d209b9fab179e8491b266bb2578f`，来源 [XIAZY/blackberry10-toolchain](https://github.com/XIAZY/blackberry10-toolchain)。构建容器无网络、无额外 capability。
- 应用 ID `com.octolab.bb10volte`，作者 `OctoLab`，作者 ID `gYAOctoLabBB10VoLTE20261102`。不要为改名或重构改变升级身份。
- 固定公钥在 `materials/mobile-release-key.json`。发行指纹为 `9e512df0eab3abcbe651a5bc30790c9412bb3fa74ffc8ddc9541e7b56a2fd6be`。Root 中使用 RSA-3072 / PKCS#1 v1.5 / SHA-256 校验完整 manifest 原始字节。

私钥仅保存在本机忽略的 `private/mobile-signing/`，不能进入 Git、BAR、ZIP、日志或公开备份。应单独安全备份；丢失私钥不能用新私钥无声替换现有用户的发行身份。首个 BAR 的信任来自可信发行渠道及公开指纹，不能由包内自带公钥自证。

## 复现候选

先审查全部设备源文件改动，再刷新清单并验证。不要为了消除不明差异而重封清单。

```powershell
python tools/bb10.py manifest
python -c "import sys; sys.path.insert(0, 'tools'); import auto_carrier; auto_carrier.write_manifest()"
python -m unittest discover -s tests -q
python -m compileall -q device tools tests mobile/runtime
python tools/check_release.py
python tools/build_mobile.py --key private/mobile-signing/release-private.pem --version 0.1.0.6
```

已有发行私钥时不要运行生成新密钥命令。新项目首次建立发行身份可使用 `tools/package_mobile.py generate-key`，该命令拒绝覆盖已有私钥/公钥。

原生构建明确设置 `BB10_ALLOW_INCOMPLETE_BUNDLE=OFF`，避免 UI-only 测试缓存污染交付。每次生成入口编译哈希，并在打包后逐字节回读 BAR 中的所有签名组件，与发行 ZIP 比对。UI-only 编译不算可用 BAR。

`mobile/bootstrap/INSTALL.txt` 是包内输入；修改后 bootstrap 字节和 SHA-256 会变化。所有文档收尾后再生成并回读最终产物，不沿用旧 bootstrap 哈希。打包器替换命令与目标版本的 VERSION 占位符，发布前检查实际说明的文件名、目标版本和安装成功判据一致。

`dist/mobile/` 包含：

| 文件 | 用途 |
| --- | --- |
| `bb10-volte-<版本>.bar` | 原生应用首次安装及界面更新 |
| `bb10-volte-<版本>-bootstrap.zip` | 已有 AutoRoot v4 Root 终端用户的本机引导包，含 `pkg.bar`、包 manifest 和版本对应的 `INSTALL.txt` |
| `bb10-volte-<版本>-update.zip` | 已安装应用的离线/在线签名运行组件更新；不替换 C++/QML |
| `latest.json` | 手机在线更新元数据 |
| `SHA256SUMS.txt` | 各候选文件哈希 |
| `package-validation.json` | 构建镜像、签名回读和产物哈希；不自动声称硬件验收 |

组件版本使用四段数字。更高协议版本必须同时规划最低客户端兼容性，不能发布让旧 native 客户端误解的响应。普通降级不能通过“更新”绕过；回滚使用已记录的私有归档。

v6 还从共享 variant_trials 定义生成并签入 19 个精确后缀 profile 与 catalog；与旧 4 配置组成 23 个原生选项。回读需确认 13 组受控手动、6 组 Passport 只读和实际 UI 选项一致。不得用新增名称代替原生哈希/ABI/恢复门槛。普通试测的 PPS journal、旧实验更新/卸载边界与自动协议 2 的原件回执、完整回滚/卸载分开发布说明，不能合并成一个能力承诺。

## 发布前同一次人工验收

在合并后自动检查通过的**最终同一组哈希**上，执行[一次人工验收清单](MOBILE-MANUAL-ACCEPTANCE.md)，更新[MOBILE-VALIDATION](MOBILE-VALIDATION.md)和[公开设备证据](../materials/mobile-device-validation-2026-11-02.json)。至少覆盖正常安装/权限、现有 waiting_reboot 任务继续、内置更新入口、备份、正常重启/IMS/双向通话/音频/LTE/短信、关闭重开应用、更新/回滚、完整卸载重装及 r16 两端共存。r14 → r16 与 r15 → r16 分别记录。

安装通过需对应任务的 **SUD 最终 success + 实际注册版本 0.1.0.6**。AutoRoot installer 在 120 秒超时后打印 completed 的样本不能算通过。v1 安装成功、v2 未验证升级、v5 仅复制和首次启动停在系统权限的历史事实均需保留。实际新引擎迁移或通话未完成时，不由探针结果推定成功。缺少某机型或运营商的证据时，不把该组合写成新增硬件已验收。

通过后再发布相同字节的 BAR/ZIP 和 SHA256SUMS，把运行组件 ZIP 上传到 `https://bb10-downloads.octoooo.com/mobile/` 的版本路径，把经核验的 `latest.json` 部署到 `https://bb10-volte.octoooo.com/mobile/latest.json`。必须先上传不可变版本文件，再更新 latest；避免用户下载到半份包。发布前后回读下载字节和签名。当前候选构建不会创建这些线上文件。

同时发布对应 r16 桌面包或明确提供该源码桌面版本，让新管理协议可由两端共同管理。旧 r14/r15 可继续使用其原有安装，但不能负责新协议的写操作。保留既有 r15 发布，不复用其版本号或无声替换旧发行文件。

## 固定边界

原厂未 Root 用户的首次 Root 仍需桌面流程；本产品不提供手机漏洞利用。AutoRoot v2/v3 的本机安装入口需要独立验证。新硬件名称、模拟测试或旧版本通话记录不构成新版本验收。首次系统权限对话框和设备密码锁需通过正常用户操作；不得修改系统安全设置来跳过测试。
