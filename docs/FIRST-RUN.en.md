# First use and connection setup

[简体中文](FIRST-RUN.md) · [GUI](GUI.en.md)

Desktop revision `0.3.2-r5` provides a First use wizard for connection checks, Windows SSH components, USB drivers and initial Q10 Root preparation.

Already-rooted devices can use Check device directly. The app discovers saved references, known owner-created kits, a configuration next to a portable executable and explicit `bb10-root` / `q10-root` aliases. Unsaved automatic discovery is limited to the direct USB address and keeps strict host verification. Other addresses require an explicitly imported configuration. Only configuration references are saved; private keys stay in their original kit.

Already-rooted phones without connection files can use Recover connection to import a login key or authorize this computer through an existing phone Root terminal. The flow is shared by Windows and macOS; see [connection recovery](RECOVER-CONNECTION.en.md).

**The connection field may remain empty.** Check device discovers both `root-kit/ssh_config` and `root-kit-*/ssh_config` in the owner's private directory, verifies the connection and fills the field. A successful selection is restored on the next launch. Auto preparation creates these files; after flashing and Root verification the wizard passes the configuration to the main window. Numbered kits remain discoverable after restarting before a connection has been saved. Multiple kits are selected by verified access, never merely by which file is newest. An already-rooted phone without its matching key still requires its original configuration.

An installed service is read as an existing installation. Normal registration/LTE displays enabled; startup displays pending. Its active configuration is expected rather than an installation failure. USB, development mode, SSH, Root and IMS are distinct. Development mode being disabled does not establish missing Root, and working Root SSH does not require development mode to remain enabled. Anonymous USB discovery reads only allowlisted model, OS and development-mode fields. Diagnostic checks do not open and abandon development sessions or raw SSH sockets.

On initial use, unlock and connect the phone. Use the wizard's USB/driver checks and on-phone instructions. Development mode is under Settings → Security and Privacy. A rooted device may need BlackBerry World opened once to trigger local startup; the store's network error or endless loading does not establish Root failure. If SSH still refuses, use a normal phone-menu reboot and wait for Root. A key mismatch requires the original trusted profile, not disabled checks or reflashing.

On Windows, choose the matching Q10 `SQN100-1` through `SQN100-5` variant, back up the phone and allow at least 15 GB of disk space. Auto preparation downloads and hashes AutoRoot v4, fixed Q10 firmware, libusb/LZO, portable 7-Zip and fixed OpenSSL DLLs from MinGit. Users do not separately install Git, 7-Zip or another Root project. Source users can obtain SSH components through the same wizard. Preparation generates independent personal keys and checks both OS/radio images; it does not flash the phone.

Flashing requires a separate, explicit data-erasure confirmation. The workflow rechecks the single USB phone's model, image hashes and existing Root access, runs OS then radio, and pauses on unknown outcomes. Passwords are entered in the vendor's native console, never GUI command arguments. For the pinned v4 recipe, only OS writing reaching 100%, both recorded security-error messages and exit code 73 allow the documented radio continuation; arbitrary errors are not accepted. See the [author's instructions](https://bb10.root.sx/blog/autoroot-v4). Complete phone setup, open BlackBerry World, verify effective UID 0, then continue with preflight and VoLTE installation.

Windows driver preparation downloads and verifies the BlackBerry bundle, embedded MSI and Microsoft-signed catalog. Actual installation requests standard Windows UAC. Existing working drivers need no replacement.

Only the Windows Q10 initial-root recipe is provided. Q20/Passport need their own verified firmware; Q10 images are prohibited. The Mac app supports already-rooted device workflows and instructions; initial flashing requires Windows. Actual Mac-to-phone acceptance remains separate from desktop startup testing.

This iteration verified portable inputs, personal-key generation, construction and hash checks of both Root images, driver extraction/signatures, and read-only access to an already-rooted Q10. The flashing branch has simulated regression coverage but **has not been exercised on an unrooted phone**, and the current working phone was not reflashed. The wizard remains experimental. First preparation needs Internet access or correctly cached materials; normal prepared use has no activation, billing or AI dependency.

Pinned inputs: [first-use tools](../materials/first-run-tools.json), [Root materials](../materials/sources.json), [drivers](../materials/usb-drivers.json). Private kits and proprietary firmware remain outside public application/source bundles. Preserve the owner-specific kit for future connections and recovery.
