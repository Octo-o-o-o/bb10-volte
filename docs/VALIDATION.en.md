# Validation and reproducible evidence

[简体中文](VALIDATION.md) | **English**

## v0.2.0 preflight and desktop UI — October 27, 2026

All 43 local Windows tests passed, covering compatibility rejection, SIM changes, no retry after an unknown installation outcome, retention of in-flight transfer inputs, no activation after failed readback and report privacy. The GUI ran a real phone preflight and correctly disabled installation/update while the existing service was active.

All six device Python files compiled on the Q10's **Python 3.2.2**. Preflight matched Q10 / SQN100-3 / OS 10.3.3.3216, pinned native hashes, 460-01 USIM, LTE and 3gnet. The existing v0.1.0 payload was intact and busy, so installation/update/repeated activation were blocked. Only temporary probe files were staged; telephony configuration was unchanged and the service was neither stopped nor upgraded.

**Full hardware installation, update and restoration acceptance of the new GUI/workflow is pending.** Earlier calling evidence below is separate. Synthetic cases for other provinces/carriers test decisions, not hardware compatibility. See [the machine-readable record](../materials/desktop-workflow-validation-2026-10-27.json).

## Recorded Q10 call trial — October 27, 2026

Device: **BlackBerry Q10 SQN100-3, BB10 10.3.3.3216, Beijing China Unicom, HPLMN 46001, USIM without ISIM**. The comparison device was a Lenovo TB350XC running Android 12 with another SIM on the same carrier's primary/secondary-card plan. It had working IMS registration and MMTEL voice capability. Times below are **UTC+8 (Asia/Shanghai)**.

- Before the fix, the 13:16 incoming INVITE reached the Q10 but domain selection returned `488` with VoPS `0`; outgoing selection chose CS and failed with `NO_SRV`.
- A short patched trial registered successfully. VoPS remained `0`, while normal voice selected PS `2` with `vdpE3`. Full restoration passed.
- Outgoing call: INVITE at **13:57:39.327**, INVITE `200` at **13:57:43.534**, ACK at **13:57:43.551**, then BYE at **13:57:50.317** followed by `200`.
- Incoming call: `180 Ringing` at **13:57:21.324**, then caller CANCEL / `487`. This proves ringing, not an answered incoming call.
- All **366 radio snapshots were LTE**. The owner reported successful use; audio was not separately documented in each direction.
- At **14:02**, restoration passed: voice policy `00` read back twice, provider `-1`, owned temporary identity/APN/copy/VPN state restored or removed and normal LTE available.

The raw evidence contains personal communications data and remains private. The public record contains protocol outcomes without identifiable numbers, SIM identifiers or authentication material.

## Persistent service

| Check | Result |
| --- | --- |
| Desktop syntax and 15 existing safety regression tests | Passed |
| Compile all deployed files with device Python 3.2 | Passed during installation with per-file hashes |
| Installation, independent execution and registration | Passed; connected / REGISTER 200 / LTE at 15:10 |
| Stop and restore voice policy / provider / APN | Passed at 15:12; no manager or IMS process, policy 00, provider -1 |
| Start again after stop | Passed at 15:16 with a new registered instance on LTE |
| Exceed the original 30-minute trial duration | Same instance started at 15:34 was still registered on LTE at 16:32 |
| Rebuild the helper from public C source | Byte-for-byte SHA-256 match |
| Four pinned Root inputs | SHA-256 verified |
| Fresh keys and offline Root preparation | Passed without replacing the active phone's keys |
| Offline Root image rebuild | Passed; original IFS/RCFS/SIG2/MBR and radio hashes preserved |
| Windows USB extraction and signatures | BlackBerry EXE and Microsoft CAT signatures Valid; MSI verified against the signed bundle contents |
| Revised addon after a normal reboot | Passed; reboot at 16:36:20, registered at 16:44:02.121 |
| Calls with the computer disconnected | Passed; owner confirmed both calls and two-way audio with USB disconnected |
| Answered incoming and outgoing calls with both audio directions | Short calls passed, approximately 14.226 and 5.636 seconds; 20-second or longer calls still need testing |
| Both calls remain on LTE with the persistent service | Confirmed by owner; all 64 samples were LTE / IMS connected |

The first reboot reached the desktop and LTE and started Root, according to the owner. It exposed startup-entry trust and empty-PPS-object handling problems. Those were fixed and regression-checked; the revised service registered on LTE at 15:35 and 15:50. The second normal reboot and short calls subsequently passed as described below. The failures and bounded recovery are described in [the troubleshooting archive (Chinese)](archive/PITFALLS.md).

## Latest reboot and unplugged call acceptance

The [acceptance record](../materials/call-acceptance-2026-10-27.json) was recorded at 17:00:56 (UTC+8) on October 27, 2026, with the same device, firmware and China Unicom SIM.

- Normal reboot: **16:36:20**. Root addon ran at 16:39:14, Root was ready at 16:39:27, and IMS registered at **16:44:02.121**. Boot-to-registration was approximately **7 minutes 42 seconds**, without manually opening AppWorld or starting the service from the computer.
- The owner disconnected USB, made and answered calls with the system dialer, confirmed two-way audio and 4G, then reconnected USB and reported success.
- Incoming: INVITE at 16:49:45.472, answer 200 at 16:49:53.126, ACK at 16:49:53.320, BYE at 16:50:07.352 and BYE 200 at 16:50:07.592. Established duration was approximately **14.226 seconds**.
- Outgoing: INVITE at 16:50:11.685, INVITE 200 at 16:50:16.922, ACK at 16:50:16.928, BYE at 16:50:22.558 and BYE 200 at 16:50:22.822. Established duration was approximately **5.636 seconds**.
- All **64 status samples showed LTE / IMS connected**. After reconnection the service remained enabled with a live manager, IMS connected, REGISTER 200 and LTE. The installed payload matched the repository sources.

This establishes short calls and normal-reboot recovery on this one device. It does not establish the suggested 20-second duration below, sustained stability, abrupt-power-loss recovery or emergency calling. Raw communications captures remain private.

## Manual acceptance checklist

1. Check that the current service instance is running, registered and on LTE.
2. Call the Q10 from another phone. Record time, answer, talk in both directions for at least 20 seconds, then hang up.
3. Call back with the Q10 system dialer. Repeat the duration, both audio directions and LTE check.
4. Reboot normally, wait for Root and the service, then repeat both calls. Record the new instance and times.
5. Disconnect USB, wait several minutes and repeat to establish operation without a computer or timed trial window.
6. Reconnect and save private diagnostics. Keep reboot evidence distinct from previous instances.

A `200` for REGISTER, SUBSCRIBE, UPDATE or PRACK is not an INVITE `200`. Confirm the INVITE transaction, ACK, session termination and human audio observations together.

Other models, firmware versions, carriers, roaming, cell handover, long-term standby, emergency calling and future network-policy changes have not been tested. Publishing the source does not change these evidence boundaries.

## Evening recovery and 0.3.1 hardening, 2026-10-27

After selected applications were removed and the phone rebooted, version 0.1.0 timed out waiting 45 seconds for its dedicated IMS APN, restored its configuration and exited. Native dependencies, every installed payload and the Root addon still matched their recorded hashes. A REGISTER 500 also existed before application removal; no causal link to a removed application has been established.

After restoring the failed state and rebooting normally, with no application reinstallation or firmware flash, 0.1.0 obtained a new REGISTER 200 at 22:48:49.980. The owner confirmed incoming/outgoing calls, both audio directions and LTE. The private capture independently verifies one answered incoming call lasting approximately 7.134 seconds; it does not establish the requested 20-second duration.

Version 0.3.1 passed 85 local tests and public-file checks. On this Q10 it passed stop/restoration, previous-payload verification, Python 3.2 compilation, upgrade readback and fresh registration on LTE. Python-based staging cleanup also passed on-device. The hardened version then passed automatic recovery after a normal reboot and short calls in both directions; see the [structured record](../materials/startup-hardening-2026-10-27.json).

- The addon ran automatically at 23:21:30, Root was ready at 23:21:45, and the owned IMS registered at **23:26:27.291**. AppWorld was not opened manually and the service was not started again from the computer. Root-ready to registration was approximately **4 minutes 42 seconds**; the full boot duration was not measured in this run.
- Outgoing: INVITE at 23:30:18.753, INVITE 200 at 23:30:23.103, ACK at 23:30:23.117, BYE at 23:30:30.465, followed by BYE 200. Established duration was approximately **7.362 seconds**.
- Incoming: INVITE at 23:30:37.565, INVITE 200 at 23:30:42.313, ACK at 23:30:42.485, BYE at 23:30:46.987, followed by BYE 200. Established duration was approximately **4.674 seconds**.
- The owner confirmed both calls, two-way audio and 4G. All **208 samples showed LTE / IMS connected**. The final readback showed enabled/running, a live owned native process, REGISTER 200 from this boot, and an installed payload matching the manifest.
- A separate early dialog at 23:29 ended with INVITE 487 and was not counted as answered; the reason for termination was not established. The two subsequent complete INVITE 200 / ACK / BYE sessions provide the answered-call evidence.

USB remained connected during this run; earlier unplugged acceptance remains a separate afternoon record. These durations establish short calls, not 20-second or longer calls. The IMS APN connected in the first waiting round; second- and third-round boundaries were unit-tested but not deliberately induced on the phone. Only the read-only recorder was stopped; the service remains enabled with no expiry window.
