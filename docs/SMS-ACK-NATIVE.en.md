# Native MT SMS ACK correlation candidate

**r13 release boundary:** SMS send-domain policy and offline diagnostics are integrated. The native MT ACK candidate remains available in source and the verifier, disabled by default. Normal startup retains the previously hash-checked voice IMS bytes. The offline maintainer verifier explicitly selects `sms_ack=True`. QNX loading, gateway acceptance, real SMS delivery and duplicate elimination still require device acceptance.

[简体中文](SMS-ACK-NATIVE.md) · [SMS policy and capture](SMS-DIAGNOSTICS.en.md)

2026-11-01: a missing correlation step has been identified in the pinned native IMS image and a source candidate implemented. **ARM instruction emulation and ELF checks pass; QNX loading, gateway acceptance and single Hub delivery remain untested on devices.** No phone was connected or SMS sent.

## Native finding

The input is OS 10.3.3.3216 `ims_rrm`, SHA-256 `043d38b0f08cf6a9696ef405f3976679e32ff9ad943ec35294c3d3da69a12b67`. Addresses below are ELF virtual addresses before relocation. Hook addresses also equal file offsets in this image.

| Location | Observed behavior |
| --- | --- |
| `SmsManagerImpl::onTransactionStart`, `0x2eed42` | The raw receiver shared by content types calls body getter `0x218098` at `0x2eeff2`, then `onSmsRaw`. r5 identifies the manager. The candidate explicitly checks for a 3GPP Content-Type here. |
| `ImsEngineSmsMgr::onSmsRaw`, `0xdaf7a` | `0xdb0ae..0xdb0e4` saves P-Asserted-Identity to engine `+0x548`. The cellular SMS TLV carries no incoming Call-ID. |
| `ImsApiSmsSend::process`, `0x7c0de` | The RP report path obtains that gateway at `0x7c8ec`, then calls raw send through the manager vtable at `0x7ca8e`. No incoming Call-ID is passed. |
| Raw send, `0x2ee2c4` | The 3GPP branch creates a new MESSAGE via `0x303a5c`, calls the Request-URI setter at `0x2ee3c6`, then submits it. r4 is the manager, r9 the RPDU length, r10 the RPDU pointer. |

This path preserves the RPDU but does not transfer the incoming Call-ID into In-Reply-To. Generic references to this header elsewhere, such as header removal at `0x1b55ec`, do not construct SMS correlation. A new Call-ID for the report's own transaction is normal. [ETSI TS 124 341 V12.6.0 §5.3.2.4](https://www.etsi.org/deliver/etsi_ts/124300_124399/124341/12.06.00_60/ts_124341v120600p.pdf) requires In-Reply-To to identify the incoming MESSAGE and Request-URI/To to identify its gateway.

Historical evidence has different strengths:

- Passport SQW100-4 / Telecom 460-11, `capture-01`: MT at line 797, ACK at 844, explicit `400 Cannot find In-Reply-To` at 868.
- Q20 SQC100-2 / Mobile 460-00, `capture-19`: MT at 4300, ACK at 4347, `400 Decode SIP message Fail` at 4371. This reason does not establish the same cause.
- Q20 / Unicom 460-01: only the user's summary, with no raw trace or confirmed hardware variant. Its four deliveries have not been independently reproduced.

Capture hashes and provenance are in the [initial evidence record](../materials/sms-investigation-2026-11-01.json). Slog2 redacts header values, so omission or `PII` alone does not prove an on-wire defect. Native data flow provides the additional evidence here. There is no basis to classify this as a known Unicom gateway bug.

## Implementation

[driver/sms_ack.c](../driver/sms_ack.c) captures context before incoming callbacks and patches the report before native transaction submission. It handles only raw 3GPP RP-DATA type 1 and matching outgoing RP-ACK/RP-ERROR types 2/4. It creates no transaction, changes no RPDU/retry policy and suppresses no Hub message. 3GPP2, MO RP-DATA and RP-SMMA remain on their original paths.

A 32-slot, 180-second memory cache keys by manager identity and RP reference. Each slot retains bounded Call-ID/gateway strings (511 bytes each) and the full RPDU (up to 255 bytes) for collision detection, with no message logging. The timeout is an implementation limit, not a network retry guarantee. A matching report receives its own MT gateway and In-Reply-To. To uses `<URI>` so URI parameters retain their meaning under [RFC 3261 §20.10](https://www.rfc-editor.org/rfc/rfc3261#section-20.10); the report's own Call-ID is preserved.

Different Call-ID, gateway or RPDU for a live reference marks it ambiguous, including after an ACK. Identical retransmissions do not renew expiry. Missing, malformed, multiple, oversized, expired or full-cache context preserves stock behavior. Missed captures due to cache contention or clock failure invalidate older cache generations to prevent stale reuse after recovery. Existing In-Reply-To is respected. Locks protect memory only, never native API calls. These limits intentionally leave some exceptional cases uncorrected rather than infer a correlation.

## ABI and ELF boundaries

[device/ims_image.py](../device/ims_image.py) modifies only a hash-verified temporary copy. The shim is independently written MIT code; proprietary firmware is not distributed.

- RX hook `0x2eeff2`: replace `29 f7 51 f8` (`BL 0x218098`), capture, return the original `message + 0x20` body getter result.
- TX hook `0x2ee3c6`: replace `c7 f6 c5 fc` (`BL 0x1b5d54`), run the original URI setter, then attempt correlation. r4–r11 and stack alignment are preserved.
- Header lookup/existence/copy setters: `0x16d14c`, `0x2185e8`, `0x218e80`. Header arrays expose values at `+4`, count at `+8`, consistent with getter `0x218574`. SAL String is a data pointer; native length getter is `0x1ffa94`.
- URI size is `0x7c`; constructor/validator/copy setter/destructor: `0x23ea94`, `0x23c596`, `0x1b5d54`, `0x66140`. Thumb targets have bit 0 set; the `clock_gettime` PLT at `0x5b57c` is ARM. Clock ID 2 and two-word timestamps follow this image's native code, not assumptions from another QNX release. Failure/backwards time rejects correlation.
- New RX code at `0x500000`; cache at `0x4a3000` in the extended zero-filled RW tail. Adjacent PT_NOTE descriptions are combined, preserving QNX/GNU note contents and freeing a program-header slot. All 15,823 original ARM unwind entries are rebased/copied and shim entries appended. Existing load addresses, imports, interpreter and RELRO remain unchanged, with no RWX segment. Only the two 4-byte SMS calls change in original SMS code.

Native header/URI/clock APIs are mocked at their inspected ABI boundaries in emulation. These tests do not execute the QNX loader, native C++ APIs, SIP stack or carrier network.

## Device/carrier coverage

All nine combinations of SQN100-3, SQC100-2, SQW100-4 and Mobile 460-00, Unicom 460-01, Telecom 460-11 use the same pinned image and these 3GPP SMS call sites. Mobile's additional EarlySdp voice patch does not change them. Unicom and Telecom share the other generated image. The [verification record](../materials/sms-ack-native-verification.json) lists image hashes and three emulated ASLR bases per combination. Shared code is not evidence that every combination reproduced or passed SMS acceptance. Other variants, firmware, WFC and 3GPP2 are outside this finding.

[Archived binaries from all three devices](../materials/sms-ack-native-archives.json) also have byte-identical SMS domain, engine, receive and report-construction ranges and call sites. Q20/Passport stock hashes match; Q10's archived Telecom r6 temporary image has a different whole-image hash but matching SMS ranges. These are local archives, not new live-device reads.

## Reproduction and remaining acceptance

Use an explicit Zig 0.13.0 executable. The builder performs no download:

```text
python tools/build_sms_ack.py --zig <Zig-0.13.0-executable>
python -m pip install unicorn==2.1.4
python -m unittest discover -s tests -p "test_sms*.py" -v
python tools/verify_sms_ack.py --native private/ims_rrm --report private/new-sms-ack-verification.json
```

The default build compares compiled output with committed bytes; only explicit `--write` regenerates them. The [manifest](../materials/sms-ack-shim.json) pins source, code, symbols, options and unwind data. Verification reads but never rewrites the owned native image and rejects unknown hashes. Reports contain no raw logs, identities or message content. CI installs Unicorn on Windows/Linux; local validation here ran on Windows.

Tests execute actual ARM/Thumb instructions for a synthetic E3→FA→FB→0C sequence, interleaving, collisions, expiry, contention, clock failures, malformed input, existing headers, URI parameters and ASLR/ABI. The four-reference sequence is derived from the feedback, not a replay of unavailable user packets.

On a device, first verify QNX loading, then correlate one raw MT and report: In-Reply-To, RP reference, gateway target/To, successful SIP response, and one Hub entry over at least 180 seconds. Follow with concurrent/multipart/intentional repeated content, MO, voice, reboot, powered-off SIM change and restoration. See [capture instructions](SMS-DIAGNOSTICS.en.md#sip-logging).

Known-payload updates back up and replace `ims_image.py`; the new temporary image is generated on a normal service restart, without modifying a running process. The native candidate is included in source, disabled by default and not deployed to phones; prior voice acceptance does not cover it. The user's `bb10root/bb10-volte main+PR#1` is a separate C project: this Python payload cannot directly replace its installation. Integration there requires the same native hash guard and separate device acceptance.
