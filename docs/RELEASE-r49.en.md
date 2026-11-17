# r49 / mobile 0.1.0.49

Windows and mobile update. macOS remains frozen at v0.5.0-r43.

## Changes

- Wait for system network selection at boot, then keep observing network changes. Retry a pre-native failure only with the same SIM, fully restored configuration and unused native IMS resources.
- Preserve original radio-mode recovery records and offer explicit, reversible network-selection assistance. Disable also restores owned selection during handoff before an IMS journal exists.
- Keep the original host-key pin when the USB address changes; distinguish component updates from activation and add sanitized band, selection and roaming diagnostics.
- Add offline call-rejection analysis and native-path regression tests. The repeated incoming-call UI report remains unreproduced and is not claimed fixed. No new hardware acceptance is established.

## Upgrade and recovery

Retains r48 admission for all 12 three-carrier ranges, APN bootstrap, SMS and voice paths. Published r42-r48 payloads can upgrade in place after original-backup and payload verification. Check status and follow the app's stop, update and normal-restart instructions. Do not delete attempt tokens or force-unload a crypto provider. The new BAR updates native UI and runtime components; the component ZIP alone cannot replace native UI.

Use `volte lock-network` / `unlock-network` only when explicitly requested, with verified identity, native files, SIM, recovery backups and idle radio resources. Existing system MANUAL selection is preserved. IMS registration does not establish calls, audio, SMS or mobile-data acceptance.

## Validation scope

The release runs the full Python suite, native ARM/Thumb matrix, public-file and privacy checks, signed mobile asset and BAR readback, Windows EXE offline self-test, and bilingual website static/browser checks. Final CI results are available in GitHub Actions for the release tag. Existing device, carrier and lifecycle results remain tied to their actual versions.

Device behavior for network waiting, radio-mode reconciliation, same-SIM retry, manual selection and dynamic USB remains to be tested on this version; no measured battery improvement is claimed. See the [call-rejection investigation](CALL-REJECTION-INVESTIGATION-2026-11-17.md) and [network guide](NETWORK-RESILIENCE.en.md). The Windows EXE has no Authenticode publisher signature.
