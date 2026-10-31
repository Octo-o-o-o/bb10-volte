# Automatic carrier setup

[简体中文](AUTO-CARRIERS.md) · [Windows](WINDOWS-EXE.en.md) · [macOS](MACOS.en.md)

The current experimental release is **0.5.0-r8**. Windows and Mac use the same installer and phone payload. The phone generates configuration from the current SIM during normal startup; later powered-off SIM changes need no computer or flash.

## Scope and acceptance

Scope: **SQN100-3, SQC100-2, SQW100-4, OS 10.3.3.3216**, with **Mobile 460-00, Unicom 460-01 and Telecom 460-11** USIMs without ISIM. Model-appropriate Root, trusted SSH and working carrier service are prerequisites. Automatic carrier setup does not perform the initial Root flash.

Currently **9/9** combinations have functional acceptance:

| Model | Mobile | Unicom | Telecom |
| --- | --- | --- | --- |
| Q10 SQN100-3 | Passed (r7) | Passed (r7) | Passed (r8) |
| Q20 SQC100-2 | Passed (r7) | Passed (r8) | Passed (r7) |
| Passport SQW100-4 | Passed (r8) | Passed (r7) | Passed (r7) |

The [structured acceptance record](../materials/unified-carrier-acceptance.json) identifies the actual payload version and boot, USB, SIM-switch and call evidence for each case. Installed-SIM baseline calls and computer-free SIM changes are separate checks. The owner checks the connected-call timer, bidirectional audio, first outgoing call and LTE throughout; reconnection verifies the current boot's SIM, profile and native process. Rotating phone logs may retain only the end of a call. Complete bidirectional SIP evidence and owner-confirmed calls are labeled separately. A post-call LTE snapshot is not continuous call-time sampling.

Current Mac physical USB acceptance is deferred by the owner. Historical Mac transport checks, software self-tests, signatures and notarization are separate evidence. Other variants, systems, PLMNs, SIM routes, locations, roaming and long-term reliability remain unverified.

## Installation and later SIM changes

1. Connect and unlock one rooted target phone over USB, select its trusted connection configuration, open Automatic carrier setup, and check the exact model and current SIM.
2. Choose the backup/install action. The program saves and downloads verified original attach settings and the old boot entry before migrating the previous manager. Original backups and old payloads are retained.
3. Restart normally from the phone's power menu, unlock it and wait about 3–5 minutes. Click **Restarted — check again**. The app verifies the carrier, IMS registration and LTE from this boot before showing **Registered on this boot; verify calls**. Disconnect USB and verify incoming/outgoing calls and bidirectional audio with the system dialer.
4. For later SIM changes, power off normally, change SIM and boot normally. The phone selects the new configuration. Hot swapping is outside the accepted procedure.
5. When Passport first changes its Telecom attach policy, wait about five minutes and restart normally again so the modem adopts the saved policy at startup. Entering and leaving Telecom may both need this step. Airplane mode does not replace that restart.

Both desktop entry points on Windows and Mac show **One more normal restart required; setup incomplete**, explain why and provide **Restarted — check again**. Startup waiting is shown separately, without repeatedly requesting a restart. Success requires registration and LTE confirmed from this boot. If USB disconnects during restart, use **Check connection again**. Reopening the app resumes from phone status without reinstalling. If automatic startup remains disabled after an update, the app first directs you to **Enable automatic setup**.

## Own-number display

r8 extends Q20's authenticated number-display mechanism to Q10 and Passport. A number must come from a successful IMS REGISTER response belonging to the current boot, native process and SIM. It updates the dialer's number-display cache; this feature does not write SIM records, calling identity or radio settings.

Without one unique authenticated number, the current display is preserved. Independent existing numbers are preserved. A previous SIM's service-owned number is not used as the new SIM's rollback value. Interrupted updates retain the original values for same-boot, same-SIM recovery. Actual numbers remain in private phone state; desktop checks report only presence and matching. Number display, operator labels and 4G icons have separate acceptance from real calls.

## Updates and disabling

Recognized earlier payloads can be updated. Stop the old manager and restore settings, restart normally to clear old runtime components, then install, verify and enable the new version. Restart normally again to start it. Old Python files are backed up and downloaded for verification before the new payload manifest is committed. Native IMS starts only once per normal boot; the software crypto provider is retained until normal restart.

After disabling, use the same window to enable automatic setup once restoration completes, then restart normally. The main window prioritizes the unified service over earlier independent adapters. Active calls, unknown stock files, missing backup receipts or independent configuration changes block affected writes.

r8 retains r7's sustained-LTE correction for Q10 Mobile. Phone-code changes are confined to own-number display, restoration and update support; attach policy and the IMS engine retain r7 content. Short calls and the existing roughly twenty-minute LTE observation do not establish long-term reliability.
