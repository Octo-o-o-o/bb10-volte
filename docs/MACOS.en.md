# macOS app and phone connection

<!-- unified-current:start -->
**Current experimental release: `bb10-volte-0.5.0-r8-macos-universal.dmg`.** It shares the Automatic carrier setup workflow and phone payload with Windows. See [installation and later powered-off SIM changes](AUTO-CARRIERS.en.md). Current Mac physical USB acceptance is deferred by the owner. Signing, notarization, software self-tests and historical USB transport checks are separate evidence; published-version records below retain their original version labels.
<!-- unified-current:end -->


[简体中文](MACOS.md) · [First use](FIRST-RUN.en.md) · [Connection recovery](RECOVER-CONNECTION.en.md)

Use the locally supplied universal macOS `.dmg` and matching `.dmg.sha256`; published versions are available from [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases). Verify SHA-256, open the DMG and drag `bb10-volte.app` to Applications. No separate Python, Tk or OpenSSH installation or application build is required. The app uses system `/usr/bin/ssh` and `/usr/bin/scp`; private files stay in `~/Library/Application Support/bb10-volte/private`.

## Daily use with an existing connection

1. Connect a USB data cable, unlock the phone and allow accessory access if macOS asks. Wait for USB networking. If no network appears, check **Settings → Storage and Access → USB Connection → Connect to Mac** on the phone. Charging or seeing a storage volume does not establish a network connection.
2. Open the app, leave the connection field empty and click **检查设备 / Check device**. It verifies known local owner configurations, fills the matching one and restores it on the next launch. You can also select a working local `ssh_config`; legacy `q10-root` aliases are matched automatically, with custom aliases under **More → Connection options**.
3. Confirm the model, OS and service state. If the existing service displays **4G 通话服务已启用 / 4G calling enabled**, use the phone's system dialer without reinstalling, pairing again or rooting again. A first service installation follows the [GUI guide](GUI.en.md) and separate confirmation. IMS registration still needs real incoming/outgoing calls, both audio directions and LTE checks.
4. After unplugging and reconnecting USB, choose **Recheck / Check device**, then read service status as needed. Retained results are the last check, not a live USB indicator.

On 2026-10-28, one Mac mini / Apple M6 / macOS 27.2 and Q10 SQN100-3 / BB10 10.3.3.3216 / Unicom 460-01 established networking with Apple's built-in CDC-NCM driver and DHCP `169.254.0.2/30`. **No additional driver or manual IP change was used.** This does not promise driver-free operation on every Mac, macOS version or phone USB mode. Do not preinstall old BlackBerry Link, treat libusb as a USB network driver or lower system security settings.

## First use on this Mac: choose your phone's situation

### The phone is not rooted

r6 integrates native initial Root preparation and separately confirmed staged execution on macOS 14+, as an **experimental feature without hardware first-flash acceptance**. Use `0.3.2-r6` or newer; the old r5 DMG does not contain this flow. Back up and verify the matching model first. The recipe is Q10-only; see [Mac initial Root](#can-a-mac-perform-initial-root) for steps and pause conditions. **Unrooted Q20/Passport (Q30) phones have no matching initial-flash materials integrated here and cannot use the Q10 automated recipe.** Their exact hardware variant, matching firmware, loader and Root method need separate integration. Never flash Q10 images onto them. Initial Root erases data; see [First use](FIRST-RUN.en.md). USB networking and development mode do not grant Root.

### The phone is rooted and you have your own connection materials

- **A complete, working local `ssh_config`**: use the daily steps above or **First use → Import existing connection**. Its login key and trusted `known_hosts` references must exist on this Mac, with host verification retained.
- **Materials on your other computer, or only the login key**: retrieve this phone's personal login private key and trusted RSA host public key/`known_hosts` through a method you control. Use **First use → Recover connection → Have a login private key** to create a Mac configuration. Windows `C:\…` absolute paths cannot be used unchanged on macOS; this flow creates protected local files with valid Mac paths. Do not use shared private keys or confuse the phone's `ssh_host_rsa_key` server private key with a computer login key.

Import creates a protected personal copy on this Mac. Confirm the trusted source and fingerprint before the app verifies phone identity and effective UID 0. This import does not append phone authorization. See [connection recovery](RECOVER-CONNECTION.en.md).

### The phone is rooted but you have no old Windows files or connection materials

**Old Windows files are unnecessary, but an existing working phone Root terminal and a supported SSH layout are required.** Choose **First use → Recover connection → No connection files**. The Mac creates its own key; only `bb10-pair-ID.py`, containing the public key, is exported. Run it in the existing phone Root terminal. Typing `PAIR` explicitly approves a **persistent addition to the phone's SSH authorization file**; existing authorization is backed up and preserved. This does not re-root, flash or change telephony. A separate `START` choice can start an existing SSH server temporarily, without enabling SSH at boot.

Finder access to internal phone storage and old Link are not required. One transfer option uses an existing readable/writable microSD card and a Mac card reader: export the script to the card and safely eject it → insert it in the phone → use the phone file manager to copy it to **internal device Downloads** → run the app's exact commands in the existing Root terminal → use the phone file manager to copy the matching `-result.json` from internal Downloads to the card → safely remove it and import through the Mac card reader on **the same Mac that generated the request**. Keep filenames/IDs unchanged; the private key stays on the Mac. Do not format or erase the card.

The app checks result origin, request ID, computer public key and phone host key, then verifies effective UID 0 with strict host checking. With neither valid login materials nor a working Root terminal, it cannot connect directly; restore access through the original Root tools first. Card transfer, new authorization writes and third-party Root layouts did not receive end-to-end hardware acceptance in this run. See [connection recovery](RECOVER-CONNECTION.en.md) for steps and limits.

## Troubleshoot by layer

- **No USB device**: check unlock, data cable, accessory access and phone USB mode. Compare System Information before and after unplugging; charging alone is insufficient.
- **USB device but no network interface**: inspect driver binding and Connect to Mac mode. Do not guess `enX`; interface numbers vary. Do not install old drivers or system extensions before identifying the cause.
- **A network interface exists**: the phone defaults to `169.254.0.1`, the computer to `169.254.0.2`. Verify the route and actual source address use that USB interface. Some old authorizations restrict the source to `169.254.0.2`; a different source address does not establish a broken key. The app does not automatically change other adapters, the default route or DNS. Record original settings and restore them after any necessary temporary configuration.
- **SSH fails**: distinguish unreachable network, refused TCP 22, changed host fingerprint, unauthorized login key and unavailable Root. Confirm changed host identity against trusted materials; do not disable checking. Working Root SSH does not require development mode to remain enabled.
- **Connected, but permission probing incomplete**: preserve the error instead of treating a failed remote command as a broken network. Do not lower phone security to suppress it. A running service owning its configuration is expected and does not call for reinstallation.

## Published package and validation scope

The real-device run used a DMG byte-identical to the GitHub `v0.3.2-r5` asset. Signature/notarization, actual Apple Silicon execution, strict SSH/effective UID 0, device and existing-service reads, owner-operated two-way calls and USB reconnection passed. The owner confirmed both audio directions and continued LTE; actual call durations were not recorded, and the phone was not rebooted in this run. Intel binaries were inspected, without Intel hardware testing.

**Published r5 still has a known First use defect**: its Python `-c` Root check is rejected by the current phone's security policy and misreported as a connection problem; USB fields may remain unconfirmed. The main window's daily Check device workflow passed. r6 includes the source fixes and UI guidance; build, self-test and notarization records accompany its Release. The historical r5 phone run does not establish phone acceptance of the new r6 package. New pairing, initial Root, service installation/reinstallation, sustained stability and other phone/carrier combinations remain outside this Mac acceptance.

See the [layered acceptance record](VALIDATION.en.md#mac-package-and-q10-daily-connection--october-28-2026) and [sanitized evidence](../materials/macos-device-validation-2026-10-28.json). The developer build instructions below are unnecessary for ordinary use.

## Can a Mac perform initial Root?

Upstream provides a native Mac path. **r6 integrates experimental initial preparation and staged flashing, without Mac hardware first-flash acceptance.** Published `0.3.2-r5` does not contain this code; the guide does not add features to that DMG.

### Experimental flow and requirements

1. The pinned firmware recipe is Q10-only. Check the actual `SQN100-1` through `SQN100-5` variant in the phone's About screen, back up and allow at least 15 GB. **Initial flashing erases phone data.** Use connection recovery for a rooted phone missing its keys.
2. Choose the actual variant under **First use → Initial Root**, then **Auto-prepare Root images**. **Preparation creates local files only; it does not connect to BootROM or flash a phone.** This toolchain requires macOS 14+, independently of daily GUI support. The app obtains pinned official AutoRoot/7-Zip, architecture-matched bb10mt and pinned official Homebrew libusb/LZO packages. It extracts them privately with licenses and SHA-256 checks; no Homebrew installation, global library installation or reduced security setting is required.
3. Every kit generates independent login/phone-host keys, replaces default authorization and preserves AppWorld. Build verification checks unchanged stock partitions and radio hashes. Native execution uses the generated unsigned OS payload and original signed radio, rather than double-clicking a Windows `.exe` autoloader. Building and flashing have separate acceptance.
4. Acknowledge the actual model, backup and data erasure. On Mac, also select **已核对手机尚未 Root，理解 Mac 首刷尚未实机验收 / Confirmed the phone is not rooted; Mac first flashing is not hardware validated**. Choosing **Start Root flashing** still requires a separate erase confirmation. The app rechecks one USB phone, its actual variant, image/tool hashes and computer USB address `169.254.0.2`. Verified existing Root or explicit key problems block reflashing. Do not change unrelated adapters, the default gateway or DNS to suppress an error.
5. A visible Mac Terminal runs the OS/radio stages. Enter a password only if the native tool asks; input is hidden and excluded from GUI arguments/logs. **Any native error, missing per-file completion evidence, cancellation or unknown outcome pauses with the state preserved; no automatic retry or radio continuation occurs.** Upstream can print success after errors, so neither that line nor exit 0 alone establishes success. The Windows recipe's “100% + two specific security messages + exit 73” exception does not apply to native Mac tools.
6. After an actual completed flash, finish phone setup and start Root through the original method. Connection checks must strictly verify phone identity and effective UID 0. Root success is separate from VoLTE service preflight and real call acceptance.

This experimental flow does not establish first-flash success across Macs, Root packages or Q10 variants, and it does not reflash the current working phone. Native OS-signature errors currently require stopping; do not guess an exception or continue radio before dedicated acceptance on an unrooted test phone. See [pinned Mac tools/dependencies](../materials/macos-root-tools.json).

### Original author and source evidence

The [AutoRoot v4 author's guide](https://bb10.root.sx/blog/autoroot-v4) describes Linux/macOS `bb10mt batch` construction. Pinned commit [`d45b66b` README](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/README.md), [Darwin targets](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/bb10mt.lpi) and [USB flashing implementation](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/uflash.pas) include native Apple Silicon/Intel targets and flash/BootROM logic. Source support does not establish successful flashing on this Mac.

On this arm64 Mac, native `--help`, Q10 offline preparation and `batch` construction completed. All four unchanged stock partitions matched size/hash, the original radio hash matched, and the kit produced a personal-key unsigned OS and original signed radio. A separate source Root probe verified effective UID 0 through the existing trusted connection; the 22 pre-existing stage directories remained unchanged in the before/after listing. **These checks do not establish successful Mac first flashing.** No BootROM/rebooting `info`, `loader` or `flash` command was run. Already-started work finished naturally; at the owner's request, subsequent work remains development without additional testing. The Q30 variant and matching initial-flash materials remain unconfirmed. See [development evidence](../materials/macos-development-2026-10-29.json) and the [separate integration acceptance scope](VALIDATION.en.md#this-branch-mac-initial-root-integration-without-first-flash-acceptance).

## Isolated build environment

On the Mac, choose a new build directory. The preparation script obtains the Python Software Foundation Python 3.14.9 installer from the [pinned manifest](../materials/macos-runtime.json), verifies its SHA-256 and Installer signature, and only extracts it into the user-owned directory. It does not run the system installer or replace system Python. It creates a venv and installs the [pinned build dependencies](../tools/macos-freeze-requirements.txt). The installer includes Tcl/Tk and universal2 binaries; initial dependency downloads require the Internet.

```bash
python3 tools/prepare_macos_runtime.py --build-root "$HOME/WorkSpace/bb10-volte-build"
```

Use a new directory; existing files are not overwritten. `--installer /path/to/python-3.14.9-macos11.pkg` reuses a previously downloaded package with the same verification. Python's native binaries target Intel macOS 10.15 / Apple Silicon macOS 11 or newer; confirm the final application's minimum OS through actual packaging and testing.

## Build, sign and notarize

1. Ensure the keychain has a **Developer ID Application** identity and a configured `notarytool` Keychain profile. Keep private keys and notarization credentials out of the repository.
2. Build in the logged-in user's GUI session; an SSH session may not have data-protection keychain access. `macos_session_job.py` creates an isolated job directory with an output log and exit status:

   ```bash
   build="$HOME/WorkSpace/bb10-volte-build"
   python3 tools/macos_session_job.py --job-root "$build" --cwd "$PWD" \
     --environment "$build/build-environment.json" -- \
     "$build/venv/bin/python" "$PWD/tools/build_macos.py" --identity 'Developer ID Application: YOUR NAME (TEAMID)'
   ```

   The builder uses an explicit resource allowlist, creates a universal2 app, signs embedded components with Hardened Runtime, and verifies bundled resources and notices.
3. Verify the app with `codesign --verify --deep --strict --verbose=2 dist/bb10-volte.app`. ZIP it with `ditto -c -k --keepParent` and submit it using `xcrun notarytool submit --keychain-profile <profile>`. Require **Accepted**, then run `xcrun stapler staple` and `validate` on the app.
4. Stage the stapled app and an `/Applications` shortcut in a new directory, create a DMG with `hdiutil create -format UDZO -srcfolder <staging>`, sign it with the same Developer ID, submit it for notarization and staple/validate the accepted DMG ticket.
5. Verify both signatures and tickets using `codesign`, `spctl` and `stapler`. Mount the DMG read-only and run its app's `--self-test` in a process sandbox that denies network connections. Check icon, profile editor, help and included files. The sandbox limits the app process, not the whole Mac's network.
6. Publish the DMG, SHA-256, build and acceptance records. Keep any phone-side steps not actually run marked unverified. The maintainer needs the Internet for signing timestamps and notarization; a stapled ticket supplies offline notarization evidence to recipients.

[PyInstaller architecture and signing](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support) · [Apple Developer ID](https://developer.apple.com/developer-id/) · [Apple notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
