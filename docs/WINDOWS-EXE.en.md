# bb10-volte Windows EXE

[简体中文](WINDOWS-EXE.md) · [GUI controls](GUI.en.md) · [macOS / DMG](MACOS.en.md)

Double-click `bb10-volte-0.3.2-r5-windows-x64.exe`. Python 3.14.9, Tcl/Tk 9.0.4, SSH/SCP and its crypto library, operator templates, fixed phone payload, guides and third-party notices are embedded. Testers do not need Python, OpenSSH, Git, Codex or an AI account. This portable, single-file application extracts its runtime into a temporary directory and cleans it up on normal exit; normal use does not need administrator privileges; optional driver installation requests Windows UAC.

The target is Windows 10/11 x64; packaging and launch validation used Windows 11 x64. The EXE is currently unsigned. A matching SHA-256 file is provided. An Apple Developer ID cannot sign a Windows executable.

## Test distribution

Download the EXE and matching `.exe.sha256` from the public [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases), or share both files directly. The phone needs the correct root setup, and Windows needs BlackBerry USB networking drivers. Each phone must have its own private key, SSH configuration and verified host-key record. Select that configuration in the GUI; `bb10-root` is only a customizable SSH alias, not a forced device identity.

Choose/edit an operator profile, run preflight, then follow the fixed install/read-back/start/registration process. Q20/Q30 require explicit experimental opt-in and every technical check passing. OS **10.3.3.3216**, ARM32, exact native hashes, SIM/APN and stock carrier configuration remain mandatory. Q20/Q30 hardware has not been validated. Never flash a Q10 root image onto either device.

## Offline operation

**The prepared desktop workflow needs no Internet connection. First use obtains missing Root/driver materials only when the user enters that workflow; see [setup scope](FIRST-RUN.en.md).** The phone still needs its carrier network for IMS registration and real calls.

| Component / stage | Embedded? | External preparation |
| --- | --- | --- |
| Python, Tk, SSH/SCP, crypto library | Yes | No runtime downloads or system Python/SSH required |
| Phone scripts/helper, profiles, guides | Yes | Original firmware components are checked on the phone |
| Windows BlackBerry USB drivers | No | Obtain and verify once if absent; cached media can be supplied offline |
| AutoRoot, model-specific firmware, rooting tools/libraries | No | Obtain for initial rooting; preparation can use verified cached inputs |
| Per-device key, configuration and trusted host key | No | Generate and verify per owner/device; never download a shared private key |
| Active VoLTE SIM and LTE/IMS service | Not applicable | Required for registration and calls |
| Activation, billing server, telemetry, updater, AI service | None | No such runtime dependency |

Normal operations use SSH/SCP and anonymous discovery on the direct USB link. First preparation downloads pinned HTTPS materials. A user-supplied SSH configuration may specify a proxy, jump host or remote address. Windows itself may perform security/reputation/certificate checks, so this is not a claim of zero network traffic from the entire computer.

[sources.json](../materials/sources.json) and [usb-drivers.json](../materials/usb-drivers.json) pin initial-preparation downloads: AutoRoot v4, Q10 stock firmware, libusb, LZO, 7-Zip, the recorded Git for Windows/OpenSSL files and BlackBerry drivers. Q20/Q30 images still need model-specific verification. None is fetched on every EXE launch; all can be obtained and verified beforehand.

Private state lives in `%LOCALAPPDATA%\bb10-volte\private`, outside the temporary bundle. Profile import/export uses a user-selected path. Close the old app before replacing its EXE; personal connection files and saved logs remain. Source execution continues to use the repository's `private/` folder. Help and third-party notices are readable offline.

## Rebuild

Use Windows x64, Python **3.14.9** with Tcl/Tk **9.0.4**:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools/windows-freeze-requirements.txt
.\.venv\Scripts\python.exe tools/build_windows.py
```

The builder obtains the pinned official OpenSSH ZIP and Tcl/Tk licenses from [windows-runtime.json](../materials/windows-runtime.json), checks hashes and, in online mode, Microsoft signatures. Only client binaries are selected; no SSH service is installed. The pinned upstream channel is explicitly **Preview**. AES-CTR is selected for the old QNX SSH server because its advertised GCM path closes the new client's handshake. Legacy RSA support is scoped to device connections and strict host verification stays enabled.

`tools/build_windows.py --offline` requires cached build inputs and never downloads missing materials. The installed build packages must also be available beforehand. The builder reads the resulting EXE archive back, verifies every bundled resource, and excludes personal keys, firmware and generated owner-specific images while including the first-use workflow.

```powershell
$app = Start-Process .\dist\bb10-volte-0.3.2-r5-windows-x64.exe -ArgumentList '--self-test selftest.json' -Wait -PassThru
Get-Content .\selftest.json
```

The self-test checks the frozen runtime, Tk/editor, SSH/SCP, payload hashes and persistent data location without contacting a phone. `--preflight-report report.json --ssh-config <configuration>` runs phone compatibility checks; it temporarily uploads probe scripts without altering telephony configuration.

See [desktop acceptance evidence](../materials/desktop-package-acceptance.json). PATH-isolation testing does not equal a clean Windows VM with Python never installed. Windows 10 and Q20/Q30 hardware validation remain pending.
