# MT 短信 ACK 原生关联修复候选

**r13 发布边界：** 已合并短信发送域配置与离线诊断；原生 MT ACK 关联候选保留在源码和验证器中，默认不启用。服务生成的语音 IMS 镜像保持此前受校验的字节；维护者离线验证器通过显式 `sms_ack=True` 评估候选。QNX 加载、网关接受 ACK、真实收发和重复短信消除仍待实机验收。

[English](SMS-ACK-NATIVE.en.md) · [短信域与取证](SMS-DIAGNOSTICS.md)

2026-11-01 初次离线调查定位了缺失的关联构造，并实现源码候选。后续 Q20 私有候选首次启动在 QNX 动态加载器内触发 SIGSEGV，早于 IMS 主程序。新增第三个 LOAD 段使此加载器的文本重定位基址被替换；通用 ELF 检查和调用点仿真未覆盖这个平台限制。

修订候选保留两个 LOAD 头，扩展原 RX 映射并保留原 RW 覆盖和零填充。原版与修订版均通过同机 `LD_TLO=1` 依赖枚举，旧候选在同一检查中复现崩溃。修订版随后已在 Q20 Root-v2 上实际启动，验证代码 RX、缓存 RW；该次 REGISTER 超时，未观察到 SIP 响应，已停用恢复。**网关接受 ACK、重复消除及通话回归仍待完成。** 进度见[实机验收记录](SMS-ROOT-ACCEPTANCE-2026-11-01.md)。

## 定位结果

分析对象是 OS 10.3.3.3216 的 `ims_rrm`，SHA-256 为 `043d38b0f08cf6a9696ef405f3976679e32ff9ad943ec35294c3d3da69a12b67`。下列地址均为此 ELF 的静态虚拟地址；两个 hook 位置也等于文件偏移，运行时须加装载基址。其他固件不套用地址。

| 原生位置 | 已核实的行为 |
| --- | --- |
| `SmsManagerImpl::onTransactionStart`，`0x2eed42` | 进入接收 MESSAGE 的 raw 分支，该入口由多种内容类型共用。`0x2eeff2` 调用 `0x218098` 取得正文，随后调用 `onSmsRaw`；此处 `r5` 是同一 SMS manager。候选在此显式核对 3GPP Content-Type。 |
| `ImsEngineSmsMgr::onSmsRaw`，`0xdaf7a` | `0xdb0ae..0xdb0e4` 将下行 P-Asserted-Identity 保存到 engine `+0x548`。传给蜂窝短信服务的 TLV 没有携带下行 Call-ID。 |
| `ImsApiSmsSend::process`，`0x7c0de` | RP 报告分支在 `0x7c8ec` 取出上述网关地址，`0x7ca8e` 经 SMS manager 虚表调用 raw send，没有传下行 Call-ID。 |
| `SmsManagerImpl` raw send，`0x2ee2c4` | 3GPP 分支经 `0x303a5c` 新建 MESSAGE。`0x2ee3c6` 调用 Request-URI setter；随后提交事务。此处 `r4` 是 manager，`r9` 是 RPDU 长度，`r10` 是 RPDU 指针。 |

这条路径保留了 RPDU，却没有把原下行 Call-ID 带到 ACK 的 `In-Reply-To`。二进制中存在这个头的字符串和通用操作，并不代表短信发送端会构造它；例如 `0x1b55ec` 的引用属于通用头删除逻辑。ACK 自己生成新 Call-ID 是独立事务的正常行为，不能把它替换成下行 Call-ID 来修复。

[ETSI TS 124 341 V12.6.0 §5.3.2.4](https://www.etsi.org/deliver/etsi_ts/124300_124399/124341/12.06.00_60/ts_124341v120600p.pdf) 要求 RP 报告的 `In-Reply-To` 指向下行 MESSAGE 的 Call-ID，Request-URI 和 To 指向该次下行 P-Asserted-Identity 中的网关。

历史证据与这个缺陷相符，但证据强度不同：

- Passport SQW100-4／电信 460-11：`capture-01` 的 ACK 后明确收到 `400 Cannot find In-Reply-To`，位于 868 行；MT、ACK 分别从 797、844 行开始。
- Q20 SQC100-2／移动 460-00：`capture-19` 的 ACK 后收到 `400 Decode SIP message Fail`，位于 4371 行；MT、ACK 分别从 4300、4347 行开始。此响应没有明确指出 In-Reply-To，不能仅凭 SIP 400 归为同因。
- Q20／联通 460-01：仍只有用户反馈摘要。四次重投、参考号和“delivered over SIP”尚未在这台设备的原始日志中独立核实。

两份历史日志 SHA-256、元数据和脱敏事务解析在[初次排查记录](../materials/sms-investigation-2026-11-01.json)。日志的 slog2 路径会隐藏关联头值，不能以日志省略或 `PII` 占位符单独证明线上缺头；本次结论同时依据原生数据流。现有材料不能认定联通网关存在已知缺陷。

## 候选如何修复

[driver/sms_ack.c](../driver/sms_ack.c) 在接收回调之前保存下行上下文，在原生提交 ACK 事务之前补齐关联。它只处理 `application/vnd.3gpp.sms` 的 RP-DATA（类型 1）与对应 RP-ACK／RP-ERROR（类型 2／4）。原生 3GPP2 分支、MO RP-DATA、RP-SMMA 和重试策略保持原行为。

缓存键是 SMS manager 身份与 RP 参考号；值包含 Call-ID、网关 URI、完整 RPDU 和时间。使用 32 个槽位、180 秒期限，头部最多 511 字节、RPDU 最多 255 字节。完整 RPDU 仅用于内存中的冲突检查，不记录或输出短信正文；期限是本候选的保守实现边界，不是运营商重试上限。

收到匹配报告时使用该次 MT 的网关，避免从“最后一条收到的短信”借地址。`In-Reply-To` 写入原 Call-ID；Request-URI 使用原生 URI 类型的构造、验证及复制接口；To 写成 `<URI>`，以保留 `;user=phone` 等 URI 参数的含义，遵循 [RFC 3261 §20.10](https://www.rfc-editor.org/rfc/rfc3261#section-20.10)。ACK 的自身 Call-ID 和 RPDU 原样保留。

相同活动参考号对应不同 Call-ID、网关或 RPDU 时，该键被标记为歧义，即使此前已经构造过 ACK 也不覆盖。完全相同的重传不延长缓存期限。缺字段、多值身份、无法解析的地址、超限、缓存满或过期时保留原生行为。错过一次接收捕获（如缓存锁竞争或取时失败）会使旧缓存代际失效，避免恢复后误用旧参考号。已有 In-Reply-To 不被覆盖。缓存锁仅保护内存访问，不跨原生 API 调用持有。

这些边界意味着候选没有保证所有异常流量都能修复；它避免在关联不充分时猜测。没有新增发送事务、自动重发或 Hub 去重，因此不会用正文相同作为丢弃短信的理由。

## 二进制与 ABI 边界

[device/ims_image.py](../device/ims_image.py) 仍从 SHA-256 受校验的原生文件构造临时副本。新增代码是本项目独立编写的 MIT 实现，没有在仓库中分发原厂固件或复制其他项目的 GPL 实现。

- 接收 hook：`0x2eeff2` 原指令 `29 f7 51 f8`，即 `BL 0x218098`。保存寄存器、捕获上下文，返回原 getter 的 `message + 0x20`。
- 报告 hook：`0x2ee3c6` 原指令 `c7 f6 c5 fc`，即 `BL 0x1b5d54`。先执行原 URI setter，再尝试补齐关联；保留 r4–r11 与栈对齐。
- 使用原生头映射查找 `0x16d14c`、头存在检查 `0x2185e8`、复制型头 setter `0x218e80`。SAL String 是一个数据指针；正文长度使用原生 `0x1ffa94`。头数组的值指针位于 `+4`，数量位于 `+8`，与原生读取器 `0x218574` 一致。
- 原生 URI 值类型大小为 `0x7c`，构造／验证／复制／析构入口分别是 `0x23ea94`、`0x23c596`、`0x1b5d54`、`0x66140`。Thumb 入口使用低位 1；`clock_gettime` PLT `0x5b57c` 使用 ARM 状态。
- 时间调用沿用此二进制已有的 `clock_gettime(2, ...)` ABI，读取两个 32 位字段。取时失败或时间倒退不关联；没有用其他 QNX 版本的宏值猜测该固件 ABI。

ELF 保留原来的两个 LOAD 头及两个 PT_NOTE；扩展原 RX 映射，代码仍位于文件偏移与虚拟地址相同的 `0x500000`。原 RW 映射随后覆盖其原有范围，零填充尾部扩展到 `0x4a3000` 起的缓存区；新增代码与 unwind 表位于 RW 页范围之外。原生 15,823 个 ARM unwind 条目全部重定位复制，并附加 shim 的 unwind 条目；原装载地址、动态导入、解释器和 RELRO 不变，无 RWX 段。原短信代码只改上述两个 4 字节调用点。Q20 修订版实际进程映射已核验，不能推广为其他设备的运行证明。

离线验证覆盖 ELF 结构和指令执行，**不能替代 BB10 原生 C++ API、SIP 栈与网络集成验收**。依赖枚举通过也不证明 IMS 注册、短信或通话可用。

## 三机三网的范围

| 精确变体 | 移动 460-00 | 联通 460-01 | 电信 460-11 |
| --- | --- | --- | --- |
| Q10 SQN100-3 | 共用这两个调用点 | 共用这两个调用点 | 共用这两个调用点 |
| Q20 SQC100-2 | 共用；历史 ACK SIP 400 | 共用；用户变体未确认 | 共用这两个调用点 |
| Passport SQW100-4 | 共用这两个调用点 | 共用这两个调用点 | 共用；历史明确缺关联头拒绝 |

九种配置均启用原生 3GPP SMS，使用同一固定哈希的固件。移动临时副本额外修改的是 EarlySdp 语音行为，不改变短信调用点；联通与电信使用相同的另一份临时副本。[九组合验证记录](../materials/sms-ack-native-verification.json) 包含实际生成的镜像哈希和各三种 ASLR 基址下的调用点仿真结果。表中的“共用”是代码覆盖结论，不能当作九台／九网短信复现或修复验收。不推广到其他变体、固件、WFC 或 3GPP2 短信。

另对三款设备的[历史二进制存档](../materials/sms-ack-native-archives.json) 逐字节比对了短信域、引擎、接收、报告构造区间和两个调用点：Q20、Passport 的原厂文件哈希相同；Q10 的历史电信 r6 临时镜像哈希不同，但上述短信区间全部相同。这是对本地存档的验证，不是本次读取三台实机的结果。

## 复现与待验收

编译器固定为 Zig 0.13.0，不自动下载安装。维护者在源码根目录执行：

```text
python tools/build_sms_ack.py --zig <Zig-0.13.0-executable>
python -m pip install unicorn==2.1.4
python -m unittest discover -s tests -p "test_sms*.py" -v
python tools/verify_sms_ack.py --native private/ims_rrm --report private/new-sms-ack-verification.json
```

第一条命令重新编译并比较已提交的机器码；仅显式 `--write` 才更新它。[生成清单](../materials/sms-ack-shim.json) 固定 C 源码、机器码、符号、编译选项和 unwind 数据。验证器只读本地原生文件，拒绝未知 SHA-256，输出不含原始日志、号码、地址或短信内容。CI 在 Windows／Linux 上安装 Unicorn 并执行同一套机器码回归；本次本地执行平台为 Windows。

测试覆盖按反馈构造的 E3→FA→FB→0C 序列、交错网关、相同参考号冲突、有效期、缓存竞争、时钟失败、错误输入、已有关联头、URI 参数和多基址 ABI。该四参考号用例是合成输入，不是对用户原始报文的回放。

实机下一步应先确认临时 IMS 能在 QNX 正常加载，再短时采集同一条 MT 与 ACK 的原始 SIP：检查 `In-Reply-To == 下行 Call-ID`、RP 参考号、网关 Request-URI／To 和 SIP 成功响应，并观察至少 180 秒、Hub 只新增一次。随后验证并发短信、长短信分段、合法重复内容、MO、语音、正常重启／关机换卡及停用恢复。原生 SIP 文件日志的开关、保存与恢复步骤见[取证文档](SMS-DIAGNOSTICS.md#查看-sip-与-in-reply-to)。

升级器会备份并替换已知载荷的 `ims_image.py`，新临时镜像只在服务正常重新启动后生成；运行中的进程不会被热改写。正式源码中的原生候选仍默认关闭；Q20 私有验收的失败及修订见上文，旧的语音验收不能用于新镜像。用户所述 `bb10root/bb10-volte main+PR#1` 是另一个 C 项目，本项目 Python 载荷不可直接覆盖其安装；需基于同一受校验的原生文件采用相应集成方式并实机验收。
