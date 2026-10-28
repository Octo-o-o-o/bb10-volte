# Validation and reproducible evidence

[简体中文](VALIDATION.md) | **English**

## Mac package and Q10 daily connection — October 28, 2026

This run used an owner-provided DMG byte-identical to the GitHub `v0.3.2-r5` asset, not a source build. A Mac mini / Apple M6 / macOS 27.2 (26B123) ran arm64. The Q10 SQN100-3 / BB10 10.3.3.3216 / Unicom 460-01 already had service 0.3.2 running. See the [sanitized record](../materials/macos-device-validation-2026-10-28.json) for the SHA-256, methods and layered outcomes. All times use UTC+8 (Asia/Shanghai).

| Layer | Result and evidence |
| --- | --- |
| Package | SHA-256 matched Release; app/DMG codesign, spctl and stapler checks passed; both architectures inspected, Intel hardware not run |
| USB | VID/PID `0fca:8017`; device and corresponding interfaces disappeared/reappeared in two unplug/replug comparisons; IORegistry showed Apple CDC-NCM binding |
| USB network | DHCP `169.254.0.2/30`; route to `169.254.0.1` and actual TCP source belonged to the identified USB interface. No added driver or manual IP change |
| SSH / Root | Owner explicitly authorized reuse of personal connection materials. Pinned host identity matched, public-key authentication and effective UID 0 passed |
| GUI / service | Main window identified model/OS and read existing running / IMS connected / 200 OK / LTE. Installation blocking while active was expected |
| Manual incoming/outgoing calls | Owner confirmed both answered, audio in both directions and continued 4G/LTE. All 23 status samples, approximately 5.2 seconds apart, showed running / 200 OK / LTE. Exact call start/end/durations were not recorded; samples are not continuous radio capture |
| USB reconnection / app restart | Strict SSH, Root and IMS checks recovered after reconnection; restarting the app restored the successful configuration |
| First use | **Published r5 failed**: phone EUID 0 policy rejected Python `-c`, but the wizard misreported a connection problem; Mac USB facts were incomplete |
| Not tested | Phone reboot (owner declined this run), Intel hardware, fresh-Mac new authorization writes, microSD transfer, initial Root, service installation/reinstallation, other combinations and long-term stability |

No project implementation, phone authorization/telephony/system setting or adapter configuration was changed. Existing diagnostics staged and cleaned temporary probe files. Owner-authorized personal materials were retained in protected Mac storage. The public record excludes personal paths, host fingerprints, device identifiers and keys; original logs/screenshots remain private.

Current repository changes separately fix First use permission probing, Mac USB facts and connection guidance. They do not alter the published r5 DMG. This record neither establishes publication of a new package nor treats local/simulated authorization tests as successful persistent phone writes. See the [Mac instructions](MACOS.en.md).

## This branch: Mac initial Root integration without first-flash acceptance

Current source adds native Q10 preparation on macOS 14+, pinned tools/dependencies, personal keys/image construction and separately confirmed Terminal OS/radio execution. Inputs come from the author's v4 archive, official 7-Zip and pinned Homebrew bottles, extracted into the private kit without installing Homebrew, global libraries or system extensions. See [pinned Mac tools](../materials/macos-root-tools.json).

On the current arm64 Mac, the maintainer verified actual tool architectures/dependencies and ran native `--help` successfully. Already-started Q10 offline preparation and `batch` construction completed naturally: all four unchanged stock partitions matched size/hash, the original radio hash matched, personal keys/AppWorld preservation were confirmed, and unsigned OS/original signed radio outputs were produced. The source Root probe verified effective UID 0 through existing trusted SSH; before/after stage listings preserved the same 22 directories, while Mac USB collection identified the actual NCM interface and `169.254.0.2`. See [development evidence](../materials/macos-development-2026-10-29.json). These are source, offline-build and existing-Root connection checks, **not successful first flashing**. Native classifier tests only establish that their known inputs pause on errors/missing evidence and never apply the Windows exit-73 exception on Mac.

**This branch did not run phone `info`, `loader` or `flash`, reboot/reflash the current working Q10 or establish a Mac hardware first flash.** Native flashing, password interaction, OS/radio handoff and Root recovery need a separately authorized test phone trial. Source integration, offline construction and package self-tests cannot replace it. Published r5 does not include this branch's integration. The owner subsequently requested development without further testing; after existing operations finished, no new test or device action was started. The unrooted Q30's exact variant and matching initial-flash materials remain unconfirmed and require separate preparation, never Q10 firmware.

## v0.2.0 preflight and desktop UI — October 27, 2026

All 43 local Windows tests passed, covering compatibility rejection, SIM changes, no retry after an unknown installation outcome, retention of in-flight transfer inputs, no activation after failed readback and report privacy. The GUI ran a real phone preflight and correctly disabled installation/update while the existing service was active.

All six device Python files compiled on the Q10's **Python 3.2.2**. Preflight matched Q10 / SQN100-3 / OS 10.3.3.3216, pinned native hashes, 460-01 USIM, LTE and 3gnet. The existing v0.1.0 payload was intact and busy, so installation/update/repeated activation were blocked. Only temporary probe files were staged; telephony configuration was unchanged and the service was neither stopped nor upgraded.

**At this v0.2.0 checkpoint, full hardware installation, update and restoration acceptance of the new GUI/workflow was pending.** Later 0.3.1 device acceptance is recorded at the end of this document. Earlier calling evidence below is separate. Synthetic cases for other provinces/carriers test decisions, not hardware compatibility. See [the machine-readable record](../materials/desktop-workflow-validation-2026-10-27.json).

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

The 0.3.1 device-hardening branch passed 85 tests; the desktop package integration passed **95 tests**, with public-file checks passing. On this Q10 it passed stop/restoration, previous-payload verification, Python 3.2 compilation, upgrade readback and fresh registration on LTE. Python-based staging cleanup also passed on-device. The hardened version then passed automatic recovery after a normal reboot and short calls in both directions; see the [structured record](../materials/startup-hardening-2026-10-27.json) and [desktop package acceptance](../materials/desktop-package-acceptance.json).

- The addon ran automatically at 23:21:30, Root was ready at 23:21:45, and the owned IMS registered at **23:26:27.291**. AppWorld was not opened manually and the service was not started again from the computer. Root-ready to registration was approximately **4 minutes 42 seconds**; the full boot duration was not measured in this run.
- Outgoing: INVITE at 23:30:18.753, INVITE 200 at 23:30:23.103, ACK at 23:30:23.117, BYE at 23:30:30.465, followed by BYE 200. Established duration was approximately **7.362 seconds**.
- Incoming: INVITE at 23:30:37.565, INVITE 200 at 23:30:42.313, ACK at 23:30:42.485, BYE at 23:30:46.987, followed by BYE 200. Established duration was approximately **4.674 seconds**.
- The owner confirmed both calls, two-way audio and 4G. All **208 samples showed LTE / IMS connected**. The final readback showed enabled/running, a live owned native process, REGISTER 200 from this boot, and an installed payload matching the manifest.
- A separate early dialog at 23:29 ended with INVITE 487 and was not counted as answered; the reason for termination was not established. The two subsequent complete INVITE 200 / ACK / BYE sessions provide the answered-call evidence.

USB remained connected during this run; earlier unplugged acceptance remains a separate afternoon record. These durations establish short calls, not 20-second or longer calls. The IMS APN connected in the first waiting round; second- and third-round boundaries were unit-tested but not deliberately induced on the phone. Only the read-only recorder was stopped; the service remains enabled with no expiry window.

## Startup latency acceptance for 0.3.2 — October 28, 2026

The same Q10, firmware and China Unicom SIM passed the 0.3.2 update, device Python 3.2 compilation and payload readback. All 107 local tests passed. The change only accelerates handoff from a verified idle, unregistered stock IMS process; APN/registration wait limits and the running call path remain unchanged. See the [latency and call record](../materials/startup-latency-2026-10-28.json).

| Measurement scope | Duration |
| --- | --- |
| 0.3.1, Root ready to IMS registration | 282.291 seconds |
| 0.3.2, boot after power-hold recovery, Root ready to registration | 43.498 seconds; not counted as clean normal-reboot acceptance |
| 0.3.2, normal phone-menu reboot, Root ready to registration | 44.698 seconds; 84.17% below the baseline |
| That normal menu reboot, system BootTime to registration | 227.698 seconds |

For the normal menu reboot, BootTime was 00:35:20, Root was ready at 00:38:23 and the owned IMS received REGISTER 200 at 00:39:07.698. AppWorld/Term49 were not opened manually and the computer did not start the service again. The idle stock process received one SIGTERM, followed by the existing configuration and registration flow after it exited.

The owner disconnected USB, tested incoming/outgoing calls, both audio directions and 4G, reported success and reconnected USB. Captured incoming INVITE 200 / ACK / BYE began with the answer at 00:46:18.579 and lasted **6.088 seconds**. The outgoing answer at 00:46:55.841 was followed by ACK / BYE and lasted **5.894 seconds**. A separate early outgoing dialog ended with INVITE 487 and was not counted as answered; its termination reason was not established. All 163 status samples showed LTE / IMS connected. The final state remained enabled/running with current-boot REGISTER 200 and a matching payload. Only the read-only recorder was stopped; the calling service has no expiry.

An earlier computer-requested reboot stalled at an unresponsive black screen. The owner recovered it by holding the power key. Its cause remains unresolved, and it is documented separately rather than counted as successful normal-reboot acceptance. The subsequent phone-menu reboot and calls above passed. Use the phone power menu for routine rebooting.

These were short calls, not verified 20-second or longer calls. The 44.698-second figure measures **registration after Root readiness**, not total device boot time or the earliest possible successful call at the precise registration instant. Long-term stability, roaming, handover and emergency calling remain untested.
