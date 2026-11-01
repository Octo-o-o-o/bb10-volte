# Native mobile installation and use

[简体中文](MOBILE-INSTALL.md) | **English**

The native Cascades app (`com.octolab.bb10volte`) coexists with the desktop manager. This branch produces candidate artifacts; consult the [validation record](MOBILE-VALIDATION.md) before publishing. Installing the icon does not activate VoLTE or change radio configuration.

## Installation paths

| Starting state | First step | Entirely on the phone? |
| --- | --- | --- |
| Rooted, working local BAR installer | Download the BAR and open it with that installer | Yes, after the local Root entry is verified |
| Working Root terminal and AutoRoot v4 installer | Download the bootstrap ZIP; run its version-specific command | Yes |
| Rooted, no usable local installer or Root terminal | Restore that existing entry, or install the BAR once from desktop | Browser-only bootstrap is not established |
| Stock, unrooted | Existing Windows/Mac first-Root workflow | No current complete on-phone route |
| AutoRoot v2/v3 or other Root | Validate helper, installer and sandbox behavior separately | Do not inherit v4 bootstrap results |

[AutoRoot v4 documentation](https://bb10.root.sx/blog/autoroot-v4) describes unsigned BAR support and local privilege helpers. A Root label alone does not establish those capabilities. The app does not flash firmware, exploit a stock phone or change global PathTrust.

Download only from the official HTTPS project page or official Release. With an existing BAR installer, install the `.bar` and wait for its final result. With only a Root terminal, download the same-version `-bootstrap.zip` to Downloads and execute the exact command in its `INSTALL.txt`, using the phone's existing `/var/rootdata/installer`. Keep the input until the install completes. A submitted task, unpacked files or a visible icon is not proof of activation.

The release page must publish hashes and the pinned publisher key fingerprint. A public key bundled with an untrusted first download does not authenticate that download. BAR, bootstrap ZIP and signed runtime update ZIP are different artifacts.

## Enable VoLTE

1. Open **BB10 VoLTE**. It verifies the entry hash, signed payload, Root environment and actual phone/SIM state.
2. Choose the backup location. A mounted SD card is preferred; internal Documents is allowed but cannot protect against losing the phone or storage failure.
3. Tap **Enable VoLTE**. The Root engine repeats device and idle-call checks, saves originals, exports them and verifies every copied hash before activation. Background tasks survive closing the UI; reopening queries the same task.
4. Restart normally from the power menu when asked. Unlock, wait about 3–5 minutes and check again. Passport may need a second normal restart when entering or leaving China Telecom attach policy; the app explains this separately.
5. Once IMS is connected, make and receive a call. Confirm audio in both directions and LTE during the call. Only then record the four manual checks. The app does not place calls, and registration alone is not calling acceptance.
6. Test SMS separately: incoming/outgoing, short/long, Chinese/English and notifications. The manual call record is bound to the current boot, SIM and payload; changes require revalidation.

Power off before later SIM changes. The automatic engine then selects a supported carrier without USB, SSH or a running computer.

## Manage and recover

Advanced provides online update checks and offline signed `-update.zip` import. Downloads enforce HTTPS, domain and size restrictions; the Root verifier independently checks the publisher signature and creates a private immutable snapshot. Runtime updates do not replace the native C++/QML app: install a newer same-identity BAR for UI updates.

An r14 desktop installation must first be disabled, restored and normally restarted before protocol-2 adoption. Upgrade the desktop manager too; released r14 cannot manage a protocol-2 phone. New desktop and mobile writers share a device lock and persistent transaction records.

Rollback restores the recorded previous version only after service shutdown and a normal restart. It never invents a desktop backup receipt when only a mobile copy exists. Full service uninstall restores and restarts, verifies/removes owned files and hooks, then requests the final normal restart to verify stock state. Originals and diagnostics remain. Delete the app icon separately afterward; deleting it alone does not remove the service.

Exports use `BB10-VoLTE/<random operation ID>/` in the selected storage. **Keep original backups private.** Shareable diagnostics and compatibility reports use allowlisted fields and exclude IMSI, ICCID, IMEI, phone numbers, SIM digests and raw logs.

## Compatibility

The automatic route retains exact existing gates: OS `10.3.3.3216`; Q10 `SQN100-3`, Classic `SQC100-2`, Passport `SQW100-4`; eligible USIMs for China Mobile `460-00`, Unicom `460-01`, Telecom `460-11`. Current phone and carrier provisioning checks still apply.

Advanced preserves existing manual experimental profiles for Unicom, Mobile, Telecom and Telecom 460-11 attach. Other Q10/Classic devices receive actions only when native hashes, ABI, network, stock baseline and recovery checks pass. Autostart stays disabled. SQC100-4 is an adaptation candidate; simulated eligibility is not hardware calling acceptance. Passport's legacy recovery gate remains enforced.

Unknown devices can export partial compatibility evidence before installation eligibility is evaluated. Further support needs actual Root, native ABI/radio, restore and call evidence. Adding a model name or bypassing hashes does not establish support.

See [build/release instructions](MOBILE-RELEASE.md) and the [UI contract](MOBILE-UX.md).
