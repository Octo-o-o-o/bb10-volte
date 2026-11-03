# Experimental release r21 / mobile 0.1.0.19

Desktop r21 and mobile 0.1.0.19 retain both desktop and phone management. The automatic workflow targets rooted Q10 SQN100-3, Q20 SQC100-2 and Passport SQW100-4 on BB10 10.3.3.3216. Exact model, system, SIM, original-file and recovery checks still apply. Other variants remain gated experiments, not newly accepted devices.

The mobile app opens with its last checked status instead of repeatedly starting a full check. A pending task is identified and observed without repeating a write. The app distinguishes an unavailable task observation, a busy service, and a confirmed disabled mobile network. It does not change the network switch. The release includes the Telecom CTNET proxy correction, narrowly bound to the matching carrier and exact known original configuration; it preserves unrelated APN and MMS entries.

## Device evidence and limits

- Q20/Unicom and Passport/Mobile completed the recorded restoration, uninstall, reinstall, call and SMS cycles with mobile v12 and service r18. Q20/Mobile and Passport/Unicom SIM-swap checks were also recorded.
- After reflashing, a Q10 SQN100-3 with Telecom passed desktop-assisted installation of mobile v18, activation, three owner-reported calls with two-way audio and LTE, saved call checks, and bidirectional short, long and duplicate-message SMS. Its 4G browser still failed; the generated CTNET proxy matched the known faulty original configuration.
- The same r21 service payload's Telecom proxy correction was installed on a Passport with Telecom. After a normal restart the proxy was absent, and the owner confirmed HTTP and HTTPS browsing, a call and SMS. This does not establish the outcome on Q10 or any other SIM.
- The owner approved publishing without another physical-device retest. Consequently the integrated mobile v19 / service r21 package has **not** completed new Q10 device acceptance, including its mobile-data fix, and the existing Q10 does not receive the fix until updated. Automated builds and tests do not replace device evidence.
- A Q10 first-Root native flash sequence was observed on an Apple Silicon Mac mini, but the full first-use GUI and other Mac/phone combinations were not established by that observation. A separately reported flash hang remains unresolved. An earlier isolated Passport wake/restart was accepted by the owner; its cause is not claimed fixed. Long-term stability remains separate.

## Installation and updates

For an already rooted phone, the Windows and macOS desktop packages include the exact matching BAR under **More → Install phone app**. A phone with an existing compatible local BAR installer may instead install the same BAR directly. The optional bootstrap ZIP is for an already working AutoRoot v4 local terminal and its verified installer. Root alone does not establish a working local installer, and phone-only first Root is not supplied. See the [Chinese installation guide](MOBILE-INSTALL.md) and [English installation guide](MOBILE-INSTALL.en.md).

The BAR updates the native application; the signed update ZIP updates the phone management components and service, and does not replace the native UI. Follow the app's existing-task and normal-restart instructions. Preserve original backups and do not resubmit an operation whose result is unknown. Check the release checksums and use only version-matched artifacts. The BAR is packaged in BB10 development mode, not signed by BlackBerry's platform signing service; installation depends on the existing compatible installation route.

The Windows executable is not Authenticode signed. The macOS package's signing, notarization and validation results are recorded with its corresponding artifact, not inferred from the source. No source or artifact contains user Root keys, private phone logs, SIM identifiers or original backups.

Historical details and version-specific validation are retained in [mobile validation](MOBILE-VALIDATION.md), [Telecom internet correction](TELECOM-INTERNET-PROXY.md), and the structured records under `materials/`. Earlier r20 artifacts and tags remain unchanged.
