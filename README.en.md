# bb10-volte — Bring VoLTE to BlackBerry Q10, Q20 and Passport

<img src="assets/icon.png" width="96" alt="BB10 VoLTE">

[简体中文](README.md) | **English**

Install once from Windows or Mac. Then power off, change the SIM and start the phone: it automatically selects China Mobile, Unicom or Telecom, without reconnecting to a computer or flashing again. Keep your number, plan and native dialer for LTE calls.

**The latest release supports all three models and carriers. It remains experimental.** Supported exact variants: rooted **Q10 SQN100-3, Q20 SQC100-2, Passport SQW100-4**, on **OS 10.3.3.3216**. Passport may require one additional normal restart when entering or leaving the Telecom attach policy. The application explains the reason and provides a recheck action.

[Guide](https://bb10-volte.octoooo.com/en/guide.html) · [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases) · [Changelog](docs/UPDATELOG.en.md)

## Downloads

| Computer | System requirements |
| --- | --- |
| Windows | **Windows 10 / Windows 11, 64-bit (x64)** |
| Mac · Apple Silicon | **macOS 11 Big Sur or later** |
| Mac · Intel | **macOS 10.15 Catalina or later** |

**Windows 7, Windows 8 / 8.1 and 32-bit Windows are not supported.** The Universal DMG includes both Apple Silicon and Intel architectures. **Initial Root preparation separately requires macOS 14 or later.**

The Mac minimum versions were checked against the native binaries and libraries in the current release; they are not hardware validation of older macOS versions or Intel Macs. Packaging and startup have been verified on Windows 11 x64; Windows 10 x64 still awaits hardware testing. The Mac app has run on Apple Silicon, but has not been tested on Intel hardware. See the [Windows guide](docs/WINDOWS-EXE.en.md) and [Mac guide](docs/MACOS.en.md).

The website defaults to Cloudflare R2 and does not require GitHub connectivity. Both locations serve identical, version-matched files. Check the full SHA-256 before running. The alternative route does not guarantee reachability on every network.

| File | R2 direct download | GitHub alternative |
| --- | --- | --- |
| Windows x64 EXE | [Download](https://bb10-downloads.octoooo.com/v0.5.0-r13/bb10-volte-0.5.0-r13-windows-x64.exe) | [Download](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r13/bb10-volte-0.5.0-r13-windows-x64.exe) |
| macOS universal DMG | [Download](https://bb10-downloads.octoooo.com/v0.5.0-r13/bb10-volte-0.5.0-r13-macos-universal.dmg) | [Download](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r13/bb10-volte-0.5.0-r13-macos-universal.dmg) |
| Full source ZIP, including website | [Download](https://bb10-downloads.octoooo.com/v0.5.0-r13/bb10-volte-0.5.0-r13-experimental.zip) | [Download](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r13/bb10-volte-0.5.0-r13-experimental.zip) |
| SHA-256 checksums | [View](https://bb10-downloads.octoooo.com/v0.5.0-r13/SHA256SUMS.txt) | [View](https://github.com/Octo-o-o-o/bb10-volte/releases/download/v0.5.0-r13/SHA256SUMS.txt) |

EXE and DMG include Python and Tk. Windows includes SSH/SCP; Mac uses the system tools. The Windows EXE has no Authenticode publisher signature. The Mac app and DMG have Developer ID signatures, notarization and stapled tickets; Intel architecture is checked inside the package but has not run on Intel hardware. The earlier r10 Mac/Q20 connection and USB-reconnect checks passed; r13 adds package regression checks and does not imply new phone-call acceptance.

## Supported phones and carriers

**All nine combinations passed hardware functional acceptance and are supported in the latest release.**

![Q10, Q20 and Passport: all nine China Mobile, Unicom and Telecom combinations passed](website/src/assets/carrier-acceptance.png)

| Device / OS 10.3.3.3216 | China Mobile | China Unicom | China Telecom |
| --- | --- | --- | --- |
| Q10 SQN100-3 | Supported | Supported | Supported |
| Q20 SQC100-2 | Supported | Supported | Supported |
| Passport SQW100-4 | Supported | Supported | Supported |

Acceptance covers native incoming/outgoing calls, audio in both directions, LTE and SIM changes without a computer. Own-number and carrier display have also been checked. Phones in the image are illustrations. Exact SIM scope: Mobile 460-00, Unicom 460-01 and Telecom 460-11 USIM without ISIM.

**SMS send/receive and duplicate delivery have not passed device acceptance.** Source includes SMS PS policy and a [native MT ACK correlation candidate](docs/SMS-ACK-NATIVE.en.md), with offline instruction/ELF checks passed; the native ACK candidate is disabled by default. See [SMS diagnostics](docs/SMS-DIAGNOSTICS.en.md) for historical evidence and logging.

The [acceptance record](materials/unified-carrier-acceptance.json) retains dates, tested software revisions, initial-card versus SIM-change cases, and the distinction between logs and owner confirmation. Other variants, OS versions, roaming, long standby and emergency calls are not comprehensively validated.

## Windows interface

![Windows automatic carrier setup](website/src/assets/windows-setup.jpg)

Actual application UI using sanitized demonstration state, not a hardware acceptance screenshot. Windows and Mac share the same installation, restart and registration checks.

## Quick start

1. Confirm the exact model, OS, VoLTE-enabled USIM without ISIM, Root SSH and trusted connection material. Automatic carrier installation is separate from first-time Root.
2. Run the Windows EXE or move the Mac app to Applications and launch it. Connect and unlock one phone, then open Automatic carriers.
3. Back up and install automatic carrier support. The application saves and downloads verified original settings before installation and readback.
4. Restart through the phone power menu, unlock and allow about 3–5 minutes. Select the recheck action. Follow any extra normal-restart prompt on Passport. Success requires the current boot, SIM, native IMS registration and LTE.
5. Unplug USB. Make and receive calls using the native dialer; wait for the connected timer to reach at least 00:35 for each. Check audio, LTE, carrier name and your own number.
6. Later, power off, swap the SIM and start normally. Passport entering or leaving Telecom may need about five minutes of initial startup followed by one more normal restart. Hot swapping is outside the accepted workflow.

Recognized old payloads are stopped and restored before upgrade. Restart to clear old runtime components, install/verify/enable the update, then restart to launch it. Keep original backups and update receipts. Unknown files, missing receipts, active calls and conflicting external changes stop writes. See [Automatic carriers](docs/AUTO-CARRIERS.en.md).

## First-time Root and connections

`0.5.0-r13` adds [old-OS upgrades and model matching](docs/FIRMWARE-UPGRADE.en.md), guarded phone-pairing commands, and exported instructions. Upgrading erases phone data and requires separate confirmation. Physical old-OS upgrade acceptance is pending.

An already-rooted phone with trusted SSH does not need reflashing. `0.5.0-r13` builds integrate automatic Root preparation and staged flashing for Q10, Classic (Q20), and Passport (Q30). Select firmware for the exact hardware variant; initial flashing erases data. Offline Windows builds and verification passed for all three firmware families. The new wizard has not been validated by first-flashing an unrooted phone, and native Mac hardware acceptance remains pending. Allow at least 15 GB. After importing firmware, prepare Root images before confirming flashing. See [First use](docs/FIRST-RUN.en.md).

Stock-firmware browser alternatives include [ZSpace](https://t3.znas.cn/9jkbxczhAK4) and Baidu links inside the app, with model-specific import checks. Those downloads are separate from the desktop EXE/DMG. See [First run](docs/FIRST-RUN.en.md), [Mac](docs/MACOS.en.md) and [GUI](docs/GUI.en.md).

## Source and build

```sh
git clone https://github.com/Octo-o-o-o/bb10-volte.git
cd bb10-volte
python tools/check_release.py --check-git
python tools/gui.py
```

Source execution requires Python 3.14 with Tk. The original `/radio/bin/ims_rrm` is preserved; installation uses a verified independent copy. Native hash mismatches stop installation. Fixed materials, provenance and licenses are recorded in [sources.json](materials/sources.json) and [NOTICE](NOTICE.md).

Software tests, frozen-package checks, signatures/notarization and actual phone calls are separate evidence. Public packages use an explicit allowlist and privacy scan, excluding keys, raw communications logs, numbers and device identifiers. The bilingual website and its tests are included; see [website/README](website/README.md).

[Windows](docs/WINDOWS-EXE.en.md) · [macOS](docs/MACOS.en.md) · [Build](docs/BUILD.en.md) · [Automatic carriers](docs/AUTO-CARRIERS.en.md) · [Contributing](CONTRIBUTING.md) · [MIT license](LICENSE)

Historical single-carrier restrictions remain in dated records; they do not replace the current unified workflow scope above. Share exact-model, redacted results in [Issues](https://github.com/Octo-o-o-o/bb10-volte/issues). Do not upload private keys, private directories or raw number logs.

## Sharing and support

After installation and verified registration, the completion page offers localized sharing, a GitHub Star link and optional coffee support. Sharing copies a message and the project website URL; you choose where to send it. Alipay and WeChat offer CNY 9.90 / 19.90 / 29.90 / a custom amount. All features remain available without contributing. See [Completion and support](docs/SUPPORT.en.md).

Public packages contain the program, sanitized evidence and explicit public assets. They exclude SSH private keys, raw device logs, personal phone numbers, original payment screenshots and stock firmware. Public receipt codes use the OctoLab icon and preserve their payment destination. Check the recipient and amount in your payment app.

<sub>[Project website](https://bb10-volte.octoooo.com/en/) · [Made by OctoLab](https://octoooo.com/) · [Contact](mailto:octoooo@octoooo.com)</sub>
