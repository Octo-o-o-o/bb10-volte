# 从源码构建与检查

**简体中文** | [English](BUILD.en.md)

设备脚本依赖 BB10 自带 Python3.2 和已校验的原生库，安装不需要电脑上安装 QNX SDK。桌面工具和测试使用 Python3.14 验证。

## 运行测试

```powershell
python -m unittest discover -s tests -v
python -m compileall -q device tools tests
python tools/check_release.py
```

## 重建辅助模块

安装或解压 Zig **0.13.0**，然后：

```powershell
python tools/build_helper.py --zig C:\Tools\zig-0.13.0\zig.exe
```

输出应为5,264字节，SHA-256为 `504a6f5bdfb55f03aaf64b1a73f423e1a802e4786433f2621cd701c993224254`。构建器逐字节散列检查；不匹配时不会覆盖仓库中已验证的模块。

模块无 `DT_NEEDED` 外部库，仅引用目标io-pkt已有的 `swcr_id`、`swcryptoattach`、`crypto_unregister_all`，入口ABI为12字节结构。它不是通用Linux驱动；ARM ELF的布局、导入和QNX实际加载均需符合这里的已验证组合。

## 发布前

有意修改手机载荷后，使用 `python tools/q10.py manifest` 更新清单并检查哈希差异。提交前暂存需要公开的文件，再运行 `--check-git`，确认 Git 跟踪集合与发布白名单完全一致。解压 ZIP 使用时省略该参数。

```powershell
python tools/check_release.py --check-git
python tools/package_release.py
```

发布ZIP仅包含白名单源码、文档、清单与本项目辅助模块。下载固件、Root工作集、个人密钥、手机日志与构建中间件保留在本地。

GitHub Actions 在 Windows 与 Linux 上运行回归测试、语法检查、公开文件检查和打包回读；不代替手机端验收。常驻版验收未完成前，将公开版本明确标为实验版 / prerelease。修改支持型号或原生文件哈希，需要重新核对ABI、字节修改和实机通话，不能仅跳过检查。
