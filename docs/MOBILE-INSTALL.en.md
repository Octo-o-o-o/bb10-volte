# Native mobile installation and use

[简体中文](MOBILE-INSTALL.md) | **English**

During VoLTE installation or enablement, a confirmed OFF Mobile Network can be turned on by continuing setup. The app verifies ON and rechecks the SIM before continuing the same task; completed backups remain available. If the system rejects the request, times out, or reports an unknown state, check Mobile Network and Airplane Mode in settings before continuing. Only an explicit activation action can trigger this; status refresh and boot monitoring do not turn the network on. Hardware acceptance for this version is pending.

Current release: desktop r42 / mobile 0.1.0.43, management protocol 2. All catalog suffixes across four families have three-carrier entry, with tested and unknown results recorded separately. It includes optional [computer authorization on the phone](COMPUTER-PAIRING.en.md), SIM-switch guidance and a separate Telecom SMS sending-status notice. Historical device results are not acceptance of this integrated release; see [release notes](RELEASE-r42.md), the [desktop installer](https://bb10-volte.octoooo.com/en/mobile-installer.html) or [manual BAR](https://bb10-volte.octoooo.com/en/mobile-manual.html).

This release limits each foreground screen hold to ten minutes, stops background UI refresh, reduces stable-service polling and writes, defaults to LTE only with exact original-mode restoration, and adds conservative action-needed notices. Battery, LTE-only calls/SMS and automatic notices still require handset acceptance; see the [behavior and validation scope](MOBILE-LIFECYCLE-2026-11-08.md).


On validated Passport builds, the service checks residual SMS busy state during normal startup and acts only after the SMS services are confirmed idle. If Waiting for the SMS service persists, export a report; do not resend delivered messages or keep restarting. The Telecom outgoing-SMS completion issue remains separate.
**Recommended approach: Root ready → native BAR → BB10 system registration → backup and activation on the phone.** A local installer and desktop assistance are alternative first-install routes. Installing the icon does not enable the service. This release includes the Telecom CTNET proxy correction; see the [validation record](MOBILE-VALIDATION.md) for exact version and device coverage.

Use the [manual checklist](MOBILE-MANUAL-ACCEPTANCE.md) for formal device acceptance. Existing tasks are preserved. To check or continue a task after a normal restart, wait for the system Root success notification before opening the app. An unambiguous saved task is checked once and can also be checked manually; do not submit another enable or update to replace it.

## Installation paths

| Starting state | First step | Entirely on the phone? |
| --- | --- | --- |
| Rooted, working local BAR installer | Download the BAR and open it with that installer | A local route exists; verify Root, final installation version and permissions |
| Rooted, no usable local BAR installer | Use r42 desktop **More → Install phone app** once | A computer is needed for setup; later management is on the phone |
| Working Root terminal and AutoRoot v4 installer | Optional bootstrap ZIP with its version-specific command | Retained alternative; ordinary users need not type terminal commands |
| Stock, unrooted | Existing Windows/Mac first-Root workflow | No current complete on-phone route |
| AutoRoot v2/v3 or other Root | Validate helper, installer and sandbox behavior separately | Do not inherit v4 bootstrap results |

[AutoRoot v4 documentation](https://bb10.root.sx/blog/autoroot-v4) describes unsigned BAR support and local privilege helpers. A Root label alone does not establish those capabilities. The app does not flash firmware, exploit a stock phone or change global PathTrust.

**Recommended click flow:** use an existing on-phone BAR installer, or r42 desktop **More → Install phone app** for one-time setup. Check the rooted phone and confirm the bundled, verified BAR installation, then manage service from the phone. Existing r18 desktop artifacts do not have this menu. Device acceptance is recorded separately for each version. An Android-to-Root helper experiment caused a Q20 kernel reset; that route was retired and no APK bootstrap is shipped. An ordinary ZIP is not a clickable native installer.

Obtain the target **0.1.0.43** BAR and checksums from the same candidate handoff or official HTTPS Release. Do not guess an unpublished download URL. With an existing BAR installer, open the `.bar` and confirm system prompts normally. Otherwise connect the rooted phone to r42 desktop, choose **More → Install phone app**, check the model and confirm the bundled BAR. The wizard checks the complete package, identity, installation result and installed files. An unknown result is reconciled using the original task, never a repeated submission. Experienced Root-terminal users may instead use the same-version bootstrap ZIP and its `INSTALL.txt`; this is optional.

Installation passes only with **the same job's final SUD success and an actual registered app version of 0.1.0.43**. The desktop wizard performs these checks before reporting success. An earlier v2 attempt printed completed after a timeout while the actual version stayed unchanged. Each new artifact needs its own verification. A completed message, extracted files, icon or working older version is insufficient.

Unlock normally, accept the first-use system app permissions and check the actual UI application version. Reaching a permission dialog does not establish that Cascades loaded. Restore an unavailable Root entry through its original method; do not bypass system permissions or the lock screen.

The release page must publish hashes and the pinned publisher key fingerprint. A public key bundled with an untrusted first download does not authenticate that download. BAR, bootstrap ZIP and signed runtime update ZIP are different artifacts.

## Enable VoLTE

Call checks are optional in this release. Ordinary restarts do not require opening the app. Follow any unfinished installation or recovery task without replacing it.

**Check an existing recovery task first.** Follow its instructions without replacing it. If an older multi-stage task lacks current safety protections, the app retains it and asks you to export diagnostics instead of resuming it automatically. After a supported old service is stopped, restored and normally restarted, the primary action offers the bundled update to r42. Do not import the same-version ZIP for that step. r42 includes a narrowly scoped Telecom proxy correction. The first-install steps below apply only when the service is genuinely absent.

1. Open **BB10 VoLTE** and tap **Check**. It verifies the entry hash, signed payload, Root environment and actual phone/SIM state.
2. Choose the backup location. A mounted SD card is preferred; internal Documents is allowed but cannot protect against losing the phone or storage failure.
3. Tap **Enable VoLTE**. The Root engine repeats device and idle-call checks, saves originals, exports them and verifies every copied hash before activation. A waiting dialog prevents duplicate actions during submission and reconciliation. Background tasks survive closing the UI; after reopening, the app checks an unambiguous saved task once, and you may check it manually.
4. Restart normally when prompted. The enabled automatic service starts with the phone; network readiness may take 3–5 minutes. Open the app to check and continue any unfinished task. When opening it, wait for the system Root success notification first; do not repeatedly tap an unresponsive icon. Passport may require another normal restart when its network policy changes.
5. Once the service is connected, use the system dialer for calls. Checking and recording outgoing calls, incoming calls, both audio directions and LTE is **optional**. The app does not place calls, and IMS registration alone does not establish that real calls have been verified. Formal device acceptance has a separate [manual checklist](MOBILE-MANUAL-ACCEPTANCE.md).
6. Check SMS separately. A voluntary call record applies to the current boot, SIM and service payload; a changed context no longer has a current confirmation, but normal use does not depend on recording it again.

Power off before later SIM changes. The automatic engine then selects a supported carrier without USB, SSH or a running computer.

This release includes a system popup and a BlackBerry Hub notification on the first verified registration of each boot, even with the app closed. Existing background services require the normal service update flow. An isolated notification test was confirmed visible on SQW100-1; the complete automatic boot flow remains unverified; see the [implementation and acceptance notes](MOBILE-CONNECTION-NOTIFICATION.md) (Chinese).

The first launch without a cache also requires one manual check. Ordinary later launches, foreground returns and unlocks show the labelled last observation without an automatic status check. A saved, unambiguous pending task receives one automatic foreground check. Ordinary restarts do not require opening the app; open it and check when you need the current status or management. Cached data does not authorize changes: saving an optional call check revalidates the current SIM, boot and IMS. The app's Root request times out after 150 seconds without actual verification progress, with a 15-minute total limit; independent lower-level deadlines are unchanged.

## Manage and recover

After an old installation is stopped and restored, the bundled-update action applies the current BAR's signed payload without another download. Online update checks and offline signed `-update.zip` import require a newer runtime version; same-version or older ZIPs are not ordinary updates. Downloads enforce HTTPS, domain and size restrictions; the Root verifier independently checks the publisher signature and creates a protected private snapshot. Runtime updates do not replace the native C++/QML app: install a newer same-identity BAR for UI updates.

Supported old payloads require disable, restoration and a normal restart before updating to r42; accept each starting version separately. Use desktop r42; older desktop versions cannot manage an unknown newer payload. New desktop and mobile writers share a device lock and persistent transaction records; this cannot stop an old process that already passed its old write checks.

Rollback uses the verified archive to restore the previous service or management component after any shutdown and normal restart steps the app requires. Newer management may be retained for task safety, and unsafe component-only downgrades are refused. It never invents a desktop backup receipt when only a mobile copy exists. Full service uninstall restores and restarts, verifies/removes owned files and hooks, then requests the final normal restart to verify stock state. Originals and diagnostics remain. Delete the app icon separately afterward; deleting it alone does not remove the service.

Exports use `BB10-VoLTE/<random operation ID>/` in the selected storage. **Keep original backups private.** Shareable diagnostics and compatibility reports use allowlisted fields and exclude IMSI, ICCID, IMEI, phone numbers, SIM digests and raw logs.

## Compatibility

All catalog Q10 SQN100-1–5, Q20 SQC100-1–5, Passport SQW100-1–4 and P’9983 SQK100-1–2 entries are open. SQW100-2 identity remains unconfirmed; an entry does not establish that a retail model exists. Tested, untested and historically unsuccessful combinations are all allowed to try. See the [exact-model evidence](COMPATIBILITY.md).

Runtime still requires working Root, OS `10.3.3.3216`, matching native files, USIM without ISIM, carrier provisioning and verified restore backups. Existing home-network templates cover Mobile `460-00/07`, Unicom `460-01` and Telecom `460-11`. Evidence status and radio notes do not block entry, but software cannot add missing radio bands. First-Root firmware recipes remain a separate identity check; SQK100-2 has no first-flash recipe yet.

Every catalog suffix now uses the main automatic route. The advanced page no longer offers old per-suffix trial menus. Generic profiles and recovery of existing legacy installations remain available; new users should check, back up and enable from the main page.

### Experimental restoration has a separate scope

The original-file export, activation and full update/rollback/uninstall workflow above belongs to **automatic protocol 2**. It does not automatically apply to legacy trials. The historical ordinary trials do not use Telecom attach modification; restoration uses the PPS journal captured at each start. This is not a protocol-2 original-file export receipt. Back up personal data separately. Exported trial observations carry `last_checked_not_live`: they describe the last check, not live state or accepted calls.

- Stopping an experiment disables its legacy autostart marker and waits for restoration.
- Updating an experiment requires prior disable/restoration and no pending install transaction, then uses the existing legacy updater. An interrupted install-transaction remains; do not retry blindly or delete its record.
- Uninstalling experimental startup entries uses the legacy uninstaller and retains private payloads and backups. It is not automatic protocol-2 full file removal.
- No legacy rollback has been added. Do not apply automatic rollback or backup-receipt promises to legacy trials. Historical read-only diagnostics did not authorize writes.

Unknown devices can export partial compatibility evidence before installation eligibility is evaluated. Further support needs actual Root, native ABI/radio, restore and call evidence. Adding a model name or bypassing hashes does not establish support.

Desktop r42 and mobile share admission and evidence catalogs. Offline checks are not new hardware acceptance. See [build/release instructions](MOBILE-RELEASE.md) and the [UI contract](MOBILE-UX.md).
