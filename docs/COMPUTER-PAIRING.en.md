# Connect a computer from the phone app

Local desktop r32 / mobile 0.1.0.33 provides optional computer authorization. Phone-only VoLTE does not need pairing. Use it for a new computer or missing desktop authorization. Existing Root is required; this feature does not root a stock phone. Installation and handset acceptance remain recorded separately in the [SQW100-4 retest](SQW100-4-RETEST-2026-11-07.md).

1. Generate pairing materials in desktop connection recovery. Export `bb10-pair-…-request.json` and copy it to the phone's Downloads folder. The private key stays on the computer.
2. Open **BB10 VoLTE → Manage & restore → Connect computer**, tap **Load request from Downloads**, compare its computer fingerprint with the desktop, then tap **Authorize this computer**. If there are multiple requests, use the chooser to select this computer's file.
3. Copy the displayed `bb10-pair-…-result.json` back to the desktop and import it. The desktop checks the matching request and public keys, then verifies SSH and Root before resuming.

Requests contain only a public key and request ID. The phone uses a fixed program built into the app, preserves existing authorization and saves a backup. If SSH is unavailable, it starts the existing USB server only when its configuration permits that; boot settings remain unchanged. If authorization is saved but the service is unavailable, enable USB SSH with the existing Root tools and verify again on the desktop.

This entry requires the main app to be installed first. Use an existing local BAR installer or the desktop's retained terminal fallback for initial setup. The separate case-specific pairing app is not a required dependency. Only authorize requests from a computer you trust.
