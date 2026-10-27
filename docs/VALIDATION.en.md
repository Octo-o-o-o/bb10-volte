# Validation and reproducible evidence

[简体中文](VALIDATION.md) | **English**

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
| Revised addon after reboot | **Pending** |
| Calls with the computer disconnected | **Pending** |
| Answered incoming and outgoing calls for 20 seconds with both audio directions | **Pending separate recording** |
| Both calls remain on LTE with the persistent service | **Pending** |

The first reboot reached the desktop and LTE and started Root, according to the owner. It exposed startup-entry trust and empty-PPS-object handling problems. Those were fixed and regression-checked; the revised service registered on LTE at 15:35 and 15:50. Acceptance after a second reboot remains outstanding. The failures and bounded recovery are described in [the troubleshooting archive (Chinese)](archive/PITFALLS.md).

## Manual acceptance checklist

1. Check that the current service instance is running, registered and on LTE.
2. Call the Q10 from another phone. Record time, answer, talk in both directions for at least 20 seconds, then hang up.
3. Call back with the Q10 system dialer. Repeat the duration, both audio directions and LTE check.
4. Reboot normally, wait for Root and the service, then repeat both calls. Record the new instance and times.
5. Disconnect USB, wait several minutes and repeat to establish operation without a computer or timed trial window.
6. Reconnect and save private diagnostics. Keep reboot evidence distinct from previous instances.

A `200` for REGISTER, SUBSCRIBE, UPDATE or PRACK is not an INVITE `200`. Confirm the INVITE transaction, ACK, session termination and human audio observations together.

Other models, firmware versions, carriers, roaming, cell handover, long-term standby, emergency calling and future network-policy changes have not been tested. Publishing the source does not change these evidence boundaries.
