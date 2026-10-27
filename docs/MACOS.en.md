# macOS / DMG feasibility

[简体中文](MACOS.md) · [Windows EXE](WINDOWS-EXE.en.md)

The same GUI can be frozen as a macOS `.app` and distributed in a `.dmg`. This requires a native Mac build; wrapping the Windows EXE does not produce a Mac application. **No Mac DMG has been built or validated for this release.**

A read-only check on October 27, 2026 found one valid Developer ID Application signing identity and `notarytool` on the maintainer's Apple Silicon MacBook Pro. The Mac mini returned no such identity. No key was exported, keychain changed or notarization submitted. The MacBook Pro's default Xcode Python is 3.9.6; use an independent Python 3.14 + Tk build environment. Finding an identity does not prove successful signing or availability of notarization credentials.

The GUI/workflow is largely portable. An [ICNS icon](../assets/app.icns) is included. Frozen Mac execution selects `/usr/bin/ssh` and `/usr/bin/scp`, and stores private state in `~/Library/Application Support/bb10-volte/private`. AES-CTR/legacy RSA negotiation is scoped to the old QNX server with strict known-host verification. Actual Mac-to-phone transport is still untested.

Root-image preparation, flashing and Windows USB drivers remain separate Windows workflows. Modern macOS USB networking support for this BB10 device must be verified independently. Application launch alone cannot establish USB or calling compatibility. An already reachable SSH connection can validate the GUI before testing direct USB.

## Distribution workflow

1. Prepare pinned Python/Tk/PyInstaller in an isolated Mac build directory. Run source tests and the GUI. Do not reuse a Windows virtual environment or native binaries.
2. Build `bb10-volte.app` with PyInstaller `--onedir --windowed`, ICNS and an explicit resource allowlist matching the Windows workflow, excluding Windows SSH/runtime materials. Include the actual Mac Python/Tk and PyInstaller licenses; never bundle the whole working directory.
3. Pass the Developer ID Application identity through `--codesign-identity` so embedded Mach-O files are signed and Hardened Runtime is enabled. Apple Development is not the identity for normal distribution outside the App Store. Do not sign only the outer application or disable Gatekeeper.
4. Verify with `codesign --verify --deep --strict --verbose=2 bb10-volte.app`; test Tk, profiles, help and phone preflight. Build ARM64 first; Intel needs a separate x86_64 build, or universal2-compatible Python and every native dependency.
5. Stage the app and an `/Applications` shortcut in a fresh directory, create a compressed DMG with `hdiutil create -format UDZO -srcfolder <staging> bb10-volte.dmg`, then sign the DMG with Developer ID.
6. Submit with `xcrun notarytool submit bb10-volte.dmg --keychain-profile <profile> --wait`. Require **Accepted**, then run `xcrun stapler staple` and `xcrun stapler validate` on the DMG. Staple the app too if distributing it outside the DMG.
7. Assess the DMG with `spctl --assess --type open --context context:primary-signature --verbose=2`, then validate a quarantined download/install and offline first launch on another Mac. Publish SHA-256 alongside the signed artifact.

Build downloads, signing timestamps and Apple notarization require the maintainer to be online. Stapled tickets allow recipients to obtain notarization evidence offline. Runtime still needs phone connectivity and carrier service. Minimum supported macOS must be established from the final Python/Tk build and testing.

Application build, signing, notarization, direct USB and Mac phone acceptance are **not run**. Keep signing keys and notarization credentials in the Mac keychain, never in the repository or EXE.

Primary references: [PyInstaller macOS support](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support), [build options](https://pyinstaller.org/en/stable/usage.html), [Apple Developer ID](https://developer.apple.com/developer-id/), [custom notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).
