# bb10-volte — Bring VoLTE to BlackBerry Q10, Q20 and Passport

<img src="assets/icon.png" width="96" alt="BB10 VoLTE">

[简体中文](README.md) | **English**

Install once from Windows or Mac. Then power off, change the SIM and start the phone: it automatically selects China Mobile, Unicom or Telecom, without reconnecting to a computer or flashing again. Keep your number, plan and native dialer for LTE calls.

Current version: **0.5.0-r8, experimental**. Supported exact variants: rooted **Q10 SQN100-3, Q20 SQC100-2, Passport SQW100-4**, on **OS 10.3.3.3216**. Passport may require one additional normal restart when entering or leaving the Telecom attach policy. The application explains the reason and provides a recheck action.

[Website and downloads](https://bb10-volte.octoooo.com/en/) · [Guide](https://bb10-volte.octoooo.com/en/guide.html) · [Release](https://github.com/Octo-o-o-o/bb10-volte/releases/tag/v0.5.0-r8) · [Changelog](docs/UPDATELOG.en.md)

## Downloads

The website defaults to Cloudflare R2 and does not require GitHub connectivity. Both locations serve identical, version-matched files. Check the full SHA-256 before running. The alternative route does not guarantee reachability on every network.

| File | R2 direct download | GitHub alternative |
| --- | --- | --- |
| Windows x64 EXE | [Download](https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-windows-x64.exe) | [Download](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/bb10-volte-0.5.0-r8-windows-x64.exe) |
| macOS universal DMG | [Download](https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-macos-universal.dmg) | [Download](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/bb10-volte-0.5.0-r8-macos-universal.dmg) |
| Full source ZIP, including website | [Download](https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-experimental.zip) | [Download](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/bb10-volte-0.5.0-r8-experimental.zip) |
| SHA-256 checksums | [View](https://bb10-downloads.octoooo.com/v0.5.0-r8/SHA256SUMS.txt) | [View](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r8/SHA256SUMS.txt) |

EXE and DMG include Python and Tk. Windows includes SSH/SCP; Mac uses the system tools. The Windows EXE has no Authenticode publisher signature. The Mac app and DMG have Developer ID signatures, notarization and stapled tickets; Intel architecture is checked inside the package but has not run on Intel hardware. Current Mac physical USB acceptance is deferred at the owner's request.

## Acceptance scope

All nine exact-model/carrier combinations passed functional acceptance. Each cell names the **phone payload actually tested**. All three phones now have r8, but the matrix does not claim nine retests on identical r8 bytes.

| Device / OS 10.3.3.3216 | Mobile 460-00 | Unicom 460-01 | Telecom 460-11 |
| --- | --- | --- | --- |
| Q10 SQN100-3 | Passed · r7 | Passed · r7 | Passed · r8 |
| Q20 SQC100-2 | Passed · r7 | Passed · r8 | Passed · r7 |
| Passport SQW100-4 | Passed · r8 | Passed · r7 | Passed · r7 |

Six cases include phone-only SIM changes; the three initial-card baselines are distinct. Tests cover native outgoing/incoming calls, audio in both directions and LTE. In the final round, the owner confirmed both calls over 35 connected seconds and correct own-number display on all three phones, plus the correct Mobile name on Passport. Q10 Telecom uses the owner's final successful pair; earlier peer-number problems are recorded separately, so first-attempt success is not assessed for that run.

Some ring logs rotated. Owner-confirmed duration and complete retained SIP timing are distinguished; a post-call LTE snapshot is not a continuous trace. Q10 Mobile also has about 20 minutes of LTE persistence and a separate pair of calls recorded. See the [structured acceptance matrix](materials/unified-carrier-acceptance.json).

r8 corrects authenticated own-number display and old-SIM cache restoration across all three models. Attach policy and IMS remain from r7; Q10 Unicom number display also has a separate successful check. Other variants, OS versions, MNCs, ISIM, all regions, roaming, long-term standby and emergency calls are not comprehensively validated.

## Quick start

1. Confirm the exact model, OS, VoLTE-enabled USIM without ISIM, Root SSH and trusted connection material. Automatic carrier installation is separate from first-time Root.
2. Run the Windows EXE or move the Mac app to Applications and launch it. Connect and unlock one phone, then open Automatic carriers.
3. Back up and install automatic carrier support. The application saves and downloads verified original settings before installation and readback.
4. Restart through the phone power menu, unlock and allow about 3–5 minutes. Select the recheck action. Follow any extra normal-restart prompt on Passport. Success requires the current boot, SIM, native IMS registration and LTE.
5. Unplug USB. Make and receive calls using the native dialer; wait for the connected timer to reach at least 00:35 for each. Check audio, LTE, carrier name and your own number.
6. Later, power off, swap the SIM and start normally. Passport entering or leaving Telecom may need about five minutes of initial startup followed by one more normal restart. Hot swapping is outside the accepted workflow.

Recognized old payloads are stopped and restored before upgrade. Restart to clear old runtime components, install/verify/enable the update, then restart to launch it. Keep original backups and update receipts. Unknown files, missing receipts, active calls and conflicting external changes stop writes. See [Automatic carriers](docs/AUTO-CARRIERS.en.md).

## First-time Root and connections

An already-rooted phone with trusted SSH does not need reflashing. Windows provides Q10 preparation; macOS 14+ has an experimental native preparation path. First-time Root flashing erases data, requires matching firmware and about 15 GB of storage, and has not been accepted on an unrooted phone. Q20 and Passport require their own matching Root methods; never flash the Q10 image onto them.

Stock-firmware browser alternatives include [ZSpace](https://t3.znas.cn/9jkbxczhAK4) and Baidu links inside the app, with model-specific import checks. Those downloads are separate from the desktop EXE/DMG. See [First run](docs/FIRST-RUN.en.md), [Mac](docs/MACOS.en.md) and [GUI](docs/GUI.en.md).

## Source and build

```sh
git clone https://github.com/Octo-o-o-o/bb10-volte.git
cd bb10-volte
python tools/check_release.py --check-git
python tools/gui.py
```

Source execution requires Python 3.14 with Tk. The original `/radio/bin/ims_rrm` is preserved; installation uses a verified independent copy. Native hash mismatches stop installation. Fixed materials, provenance and licenses are recorded in [sources.json](materials/sources.json) and [NOTICE](NOTICE.md).

The complete desktop regression ran 474 tests: 473 passed, one skipped. Software tests, frozen-package checks, signatures/notarization and actual phone calls are separate evidence. Public packages use an explicit allowlist and privacy scan, excluding keys, raw communications logs, numbers and device identifiers. The bilingual website and its tests are included; see [website/README](website/README.md).

[Windows](docs/WINDOWS-EXE.en.md) · [macOS](docs/MACOS.en.md) · [Build](docs/BUILD.en.md) · [Automatic carriers](docs/AUTO-CARRIERS.en.md) · [Contributing](CONTRIBUTING.md) · [MIT license](LICENSE)

Historical single-carrier restrictions remain in dated records; they do not replace the current unified workflow scope above. Share exact-model, redacted results in [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues). Do not upload private keys, private directories or raw number logs.
