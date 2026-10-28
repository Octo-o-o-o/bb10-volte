# macOS app and DMG

[简体中文](MACOS.md) · [Windows EXE](WINDOWS-EXE.en.md)

Download the universal macOS `.dmg` and matching `.dmg.sha256` from [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases), verify SHA-256, open the DMG and drag `bb10-volte.app` to Applications. No separate Python, Tk or OpenSSH installation or application build is required. Consult the release and its acceptance record for signing, notarization and validation status. The app contains Apple Silicon and Intel architectures; Intel hardware has not been tested. The build steps below are for developers.

The app uses system `/usr/bin/ssh` and `/usr/bin/scp`, and stores private state in `~/Library/Application Support/bb10-volte/private`. A device-specific root SSH key and verified host key are required. The default alias is `bb10-root`; explicit legacy `q10-root` profiles are matched automatically. First use provides guidance; initial Root flashing currently requires Windows. See [setup scope](FIRST-RUN.en.md).

For an already-rooted phone without connection files, First use → Recover connection can rebuild a profile or generate an owner-run pairing script. See [connection recovery](RECOVER-CONNECTION.en.md). This flow does not require Windows or reflashing; without login materials it still requires an existing phone Root terminal.

Q10 SQN100-3 / OS 10.3.3.3216 / Beijing Unicom 460-01 is the only hardware calling record. Q20/Q30 are experimental and require opt-in and all technical checks. Starting the desktop app does not establish direct Mac-to-phone USB networking or calling support. Initial rooting and flashing require the firmware and method specific to each model; never flash Q10 images onto another model.

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
