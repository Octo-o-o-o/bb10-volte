# BB10 SMS domain and duplicate delivery investigation

[简体中文](SMS-DIAGNOSTICS.md)

2026-11-01: this source candidate adds an explicit SMS policy and an offline diagnostic tool. Follow-up analysis also implements a [native MT ACK correlation candidate](SMS-ACK-NATIVE.en.md). **Device SMS acceptance remains pending; elimination of duplicate delivery is not verified.** No phone was connected or modified, and no SMS was sent. Previous nine-combination acceptance covers voice, SIM changes and display, not SMS.

The report concerns Q20, OS 10.3.3.3216, AutoRoot v4 and Unicom 460-01. It describes four MT deliveries about 30 seconds apart with different RP references, and MO failure after CS with `no retry default`. Raw logs and the exact hardware variant were not supplied.

## MO configuration candidate

In the pinned stock `ims_rrm`, LTE SMS selection at `0x63378` returns PS (2) when registered and its internal `smsIP` flag is set; otherwise it returns CS (1). Voice policy and advertising `sms` in `IMS_services` do not initialize that flag. The candidate adds:

```text
Object: /pps/services/carrier_config/ims/ims
Field: SMS_Over_IP_Network_Indication:b:true
```

The carrier dictionary maps this field to ID `0x45`; the apply call at `0x105692` reaches `0x93cda`, then configuration ID `0x66` propagates through `0x9091c` to domain state byte `+9` at `0x9097e`. [Evidence](../materials/sms-investigation-2026-11-01.json) pins the binary hash. The alternative radio-common input `sms_over_ip_indication` reaches the same setter; this candidate uses only the IMS field. Whether the outer cellular service still starts with CS requires a device MO trace.

[service.py](../device/service.py) follows `ims.sms`, saves the original boolean or absence before applying it, restores that value, and refuses conflicting external edits. Legacy journals must be restored before adding ownership of the new field. The known-payload updater backs up and verifies the service update.

This retains registration and network-state conditions; it does not force PS while IMS is unavailable. A default `SmsConfig: smsOverIp[0]=1` log is not proof of applied domain state: it coexists with `domain 1` in both historical SMS captures. Changing `routingPreference`, observing `allowVoLteProvisioning=0`, or fabricating an imsconfig does not establish the SMS domain.

The constructor at `0x7cfa8` sets a default retry strategy to zero after CS has been attempted. The phrase `no retry default` alone does not mean that the first IMS send is forbidden. Processing at `0x7c0de` also checks domain, network failure suppression and previous IMS attempts. Verify `domain 2` and `sendSms=1` for an actual MO before considering retry changes. This candidate changes no native retry logic.

## MT correlation and other carriers

The delivery-report MESSAGE must associate with the incoming MESSAGE through `In-Reply-To`, and use the gateway identity for its target and To header. A new Call-ID on the ACK itself is not sufficient evidence of a defect. See [ETSI TS 124 341 V12.6.0 §5.3.2.4](https://www.etsi.org/deliver/etsi_ts/124300_124399/124341/12.06.00_60/ts_124341v120600p.pdf). Check the RP reference, headers and actual SIP response together. A log saying delivered over SIP does not establish successful RP correlation or single Hub delivery.

Nineteen distinct historical log hashes cover all nine supported combinations. Only two captures contain SMS transactions:

| Device | Mobile 460-00 | Unicom 460-01 | Telecom 460-11 |
| --- | --- | --- | --- |
| Q10 SQN100-3 | No captured SMS | No captured SMS | No captured SMS |
| Q20 SQC100-2 | ACK received SIP 400 | User report; no historical SMS capture | No captured SMS |
| Passport SQW100-4 | No captured SMS | No captured SMS | ACK received `400 Cannot find In-Reply-To` |

The reported Q20 hardware variant is unknown. Q20 Mobile is `capture-19` (incoming line 4300, ACK 4347). Passport Telecom is `capture-01` (incoming 797, ACK 844, explicit rejection 868). Both use domain 1 and the native exception allowing ACKs for MT received over IMS. Hashes, metadata provenance and sanitized transaction summaries are in the [evidence record](../materials/sms-investigation-2026-11-01.json).

The shared native image and configuration path make the MO omission relevant to all supported combinations. ACK failures are also observed across devices and carriers. No captured SMS means unknown, not a pass. No primary evidence establishes a known Unicom gateway defect, or proves that these captures reproduce the reported four deliveries. RP-reference deduplication would miss changing references; content deduplication could discard legitimate repeated messages. No Hub deduplication was added.

## SIP logging

Read `/bin/slog2info -b ims_rrm` through the existing trusted Root shell, preserving PID, timestamps and complete `<<<<<< IN` / `>>>>>> OUT` blocks. `SipLogger` at `0x132e50` replaces the slog2 `In-Reply-To` value with `PII` at `0x133060` → `0x1330a8`. Neither that placeholder nor a missing logged field proves an on-wire value.

The native dictionary also recognizes boolean `logSipToFile` and `logSipBody`, and integer `logSipMaxFileSize` / `logSipMaxNumFiles`, in `/pps/services/ims/status_persistent`. The file buffer receives headers before redaction (`0x133024..0x13304e`), under `/var/ims/log/`.

For a controlled capture, save the exact original fields first, request `logSipToFile:b:true` through a PPS field update, and enable `logSipBody:b:true` only if RPDU bytes are needed. Restore original values or absence afterwards without overwriting concurrent changes or replaying the entire PPS object. Rotation units and suitable limits were not verified here.

File logging is also gated by quip role. Verify actual file creation and inspect `sipLogToFile failed` and `logToFile / fd / quipRole` diagnostics; setting the flag alone does not prove capture. These switches were not tested on a phone, and no role changes are proposed. Raw logs can contain authentication material, numbers and message content; retain them locally.

```powershell
python tools/sms_diagnostics.py private/owned-ims.log --output private/sms-report.json
```

The tool accepts slog2 SIP blocks or native SIP files with direction markers. Spaced hexadecimal RPDUs yield type/reference only. Responses are matched by process, Call-ID, CSeq and Via branch; identities, addresses, Call-IDs, bodies and input filenames are not exported. Missing/redacted fields remain unknown. URI comparison is textual and may need manual review. Every report retains `sms_delivery_verified=false`. The tool has no phone access or send operation.

## Remaining acceptance

For each exact device/carrier pair, manually verify one MO, one MT, matching ACK headers/RP reference, the gateway response, and exactly one received message. Observe at least 180 seconds to cover this report's retry window; this is not a universal network retry limit. Also check intentional repeated content, multipart SMS, normal reboot, powered-off SIM changes, voice and restoration.

Follow-up native data-flow analysis identified two hook sites shared by all nine combinations and passed ARM instruction emulation and ELF checks. QNX loading and a complete device trace are still required to establish successful correlation and elimination of redelivery; see the [verification record](../materials/sms-ack-native-verification.json). The candidate is based on cached repository commit `0091630`, not a newly published installer. If the reported PR means [bb10root PR #1](https://github.com/bb10root/bb10-volte/pull/1), the inspected head `5e2ecaf5ad6c6e56e05d206e8939dbcad336d1ed` concerns carrier selection, IR92 and provisioning gates, not SMS correlation. This Python payload cannot directly replace that C project's installation; no GPL implementation was copied.
