# 手机构建、签名与发布

v12/r18 的 Passport／移动和 Q20／联通均已完成完整恢复、卸载、全新安装、IMS、三次较长通话、短信和验收记录保留；Q20 换移动卡后的通话、短信及验收保存也已通过，范围见[验收记录](MOBILE-VALIDATION.md)。Passport 换联通卡后经一次额外正常重启完成策略恢复，通话、短信及验收保存也已通过；v14 已补明确且有次数限制的重启提示，尚待真机交互验收。Q10 的 v13 应用安装、旧版恢复及更新到 r18 已通过；机主报告电信卡通话和短信正常，通话验收记录已保存。Q10 的 v17 安装和缓存、一次手动检查已有单项记录，v18 尚待独立实机验收。不能外推为三机型、三运营商全部通过。机主已接受 Passport 此前孤立的唤醒重启，不声称修复其根因。旧 review-only 压缩包是历史不可变记录，不用新结论覆盖其原字节。

v13 BAR 已包含手机阻断等待及通话验收保存反馈修复，并完成真实 SDK 构建、签名成员回读和两位独立 reviewer 核包；r19 桌面增加“安装手机应用”入口。旧 v12 BAR/r18 桌面产物不包含这些修改。Q10 首次图形安装暴露并修正了 QNX 进程启动、ZIP 普通文件类型及 PPS 初始权限通知兼容问题。原图形任务现已取得 SUD success、实际 v13 版本与 69 项文件核验通过的回执，机主已打开应用；此次采用受控通知恢复原任务，新助手全新安装路径仍须实机验证。v14 在 v13 基础上增加受严格条件限制的恢复提示，已完成真实 SDK 构建；最终桌面冻结包及 v14 手机交互也须单独验收，不能无声覆盖同名旧发行物。

此流程生成手机 **0.1.0.18 / 桌面 0.5.0-r19 / 后台服务 r18 / 协议 2** 的可审查候选，不会自动上传、创建 Release、修改线上下载或发送通知。v18 普通打开显示标明上次的缓存状态，按需手动检查；Root 请求在 150 秒没有实际校验进度时超时，整次请求上限为 15 分钟，独立底层超时保持原值。应用与管理组件版本、后台服务检测状态分别显示；在线更新绑定元数据、签名版本和下载字节。桌面保留已有机型检查、受控试验、反馈与教程。安装方法见[中文指南](MOBILE-INSTALL.md)和[英文指南](MOBILE-INSTALL.en.md)。

v11 已通过 Windows 759 项测试（2 项平台专用跳过）、最终 93 项手机专项回归、真实 SDK ARM BAR 构建、59 个签名成员与安装注册版本回读。两位 reviewer 对本次语言、原生界面与组件交互复评通过。r17 的 Passport 原生更新、策略重启、三次至少两分钟通话及短信在 v10 已通过，v11 无线载荷保持一致。网站 18 项静态与 25 项浏览器检查通过；最终 Mac 源码、冻结包、签名公证及其余人工验收按同版候选的独立回执记录，详见[验收记录](MOBILE-VALIDATION.md)。

## 固定依赖与身份

- ARMv7/QNX、C++98、Qt 4.8/Cascades；设备 Python 3.2。
- 构建镜像：`ghcr.io/xiazy/blackberry10-toolchain@sha256:60ce49510a37ed92368cca010bbaabf97b12d209b9fab179e8491b266bb2578f`，来源 [XIAZY/blackberry10-toolchain](https://github.com/XIAZY/blackberry10-toolchain)。构建容器无网络、无额外 capability。
- 应用 ID `com.octolab.bb10volte`，作者 `OctoLab`，作者 ID `gYAOctoLabBB10VoLTE20261102`。不要为改名或重构改变升级身份。
- 固定公钥在 `materials/mobile-release-key.json`。发行指纹为 `9e512df0eab3abcbe651a5bc30790c9412bb3fa74ffc8ddc9541e7b56a2fd6be`。Root 中使用 RSA-3072 / PKCS#1 v1.5 / SHA-256 校验完整 manifest 原始字节。

私钥仅保存在本机忽略的 `private/mobile-signing/`，不能进入 Git、BAR、ZIP、日志或公开备份。应单独安全备份；丢失私钥不能用新私钥无声替换现有用户的发行身份。首个 BAR 的信任来自可信发行渠道及公开指纹，不能由包内自带公钥自证。

## 复现候选

本次仅更新界面和桌面安装助手，设备载荷保留 r18 原字节及原清单，不能因桌面版本升为 r19 而重新生成设备清单。只有审查并决定发布新的设备引擎后，才单独更新对应载荷与迁移准入；不要为了消除不明差异而重封清单。以下构建命令应在隔离的干净检出中执行，不能覆盖已核验的同版本候选产物。

```powershell
python -m unittest discover -s tests -q
python -m compileall -q device tools tests mobile/runtime
python tools/check_release.py
python tools/build_mobile.py --key private/mobile-signing/release-private.pem --version 0.1.0.18
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

v17 及后续入口将自身和版本绑定到签名包核心内容，不会切回缺少任务结果保护或活动组件选择保护的旧管理组件；需要后台继续执行的旧任务若不能验证安全能力，则保留任务并导出诊断。回滚旧服务时保留新版管理组件；仅管理组件回退到无保护版本会被拒绝。手动降装旧 BAR 后，新入口保护不再适用。

v18 首次创建 Root 私有快照时仍完整检查来源；后续命中同一签名清单时只完整检查实际执行的快照，并在确定回退时不读取被舍弃旧组件的正文。因而未执行副本的正文损坏不一定立即被发现；不要把此优化描述为所有副本每次都全量校验。执行快照每次均验签、哈希并检查权限及目录结构。首次创建和升级后真实手机耗时须独立验收。

组件版本使用四段数字。更高协议版本必须同时规划最低客户端兼容性，不能发布让旧 native 客户端误解的响应。普通降级不能通过“更新”绕过；回滚使用已记录的私有归档。

桌面图形首装还需要固定完整 BAR，内层组件签名不能替代 C++/QML 的完整包验证。最终 BAR 经过审查后，维护者运行 `python tools/mobile_app_install.py --pin-bar <最终BAR>`，更新 `materials/mobile-app-artifact.json`，再运行 `test_mobile_app_install.py` 与 `test_mobile_app_gui.py` 并打包桌面。清单绑定完整包、全部实际安装成员、应用身份、目标版本和固定设备助手。普通用户不能导入或重封该清单。手机侧安装器必须复制到 Root 私有任务目录后验哈希、PathTrust 和执行；任务落盘后只提交一次，超时保留同一任务，后续核对 SUD 及实际安装内容。真实 QNX、断线恢复和最终冻结包仍是单独验收项。

v6 还从共享 variant_trials 定义生成并签入 19 个精确后缀 profile 与 catalog；与旧 4 配置组成 23 个原生选项。回读需确认 13 组受控手动、6 组 Passport 只读和实际 UI 选项一致。不得用新增名称代替原生哈希/ABI/恢复门槛。普通试测的 PPS journal、旧实验更新/卸载边界与自动协议 2 的原件回执、完整回滚/卸载分开发布说明，不能合并成一个能力承诺。

## 发布前同一次人工验收

在合并后自动检查通过的**最终同一组哈希**上，执行[一次人工验收清单](MOBILE-MANUAL-ACCEPTANCE.md)，更新[MOBILE-VALIDATION](MOBILE-VALIDATION.md)和[公开设备证据](../materials/mobile-device-validation-2026-11-02.json)。至少覆盖正常安装/权限、现有 waiting_reboot 任务继续、内置更新入口、备份、正常重启/IMS/双向通话/音频/LTE/短信、关闭重开应用、更新/回滚、完整卸载重装及 r18 两端共存。r14/r15/r16/r17 → r18 的实际样本分别记录。

安装通过需对应任务的 **SUD 最终 success + 实际注册版本 0.1.0.18 + 全部安装文件匹配**。仅安装器进程存在、等待状态、completed 字样或图标可见都不能算通过。v1 安装成功、v2 未验证升级、v5 仅复制和首次启动停在系统权限的历史事实均需保留。实际新引擎迁移或通话未完成时，不由探针结果推定成功。缺少某机型或运营商的证据时，不把该组合写成新增硬件已验收。

通过后再发布相同字节的 BAR/ZIP 和 SHA256SUMS，把运行组件 ZIP 上传到 `https://bb10-downloads.octoooo.com/mobile/` 的版本路径，把经核验的 `latest.json` 部署到 `https://bb10-volte.octoooo.com/mobile/latest.json`。必须先上传不可变版本文件，再更新 latest；避免用户下载到半份包。发布前后回读下载字节和签名。当前候选构建不会创建这些线上文件。

同时提供对应 r19 桌面包或明确提供该源码桌面版本，让新管理协议可由两端共同管理。后台载荷仍按实际 r18 校验，不能把桌面外壳版本当作无线载荷版本。旧 r14/r15 可继续使用其原有安装，但不能负责新协议的写操作。保留既有 r15 发布，不复用其版本号或无声替换旧发行文件。

## 固定边界

原厂未 Root 用户的首次 Root 仍需桌面流程；本产品不提供手机漏洞利用。AutoRoot v2/v3 的本机安装入口需要独立验证。新硬件名称、模拟测试或旧版本通话记录不构成新版本验收。首次系统权限对话框和设备密码锁需通过正常用户操作；不得修改系统安全设置来跳过测试。
