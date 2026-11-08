> Historical document: r42 opens all catalog models. The former admission restrictions below are superseded; use [current compatibility](COMPATIBILITY.md).

# Local trials for additional variants

SQC100-4 update, 2026-11-07: Telecom 460-11 retains automatic setup and its known SMS notice. Unicom is unsupported at the owner’s request and its trial entry is closed; Mobile 460-00 did not obtain usable LTE in this field test. The current catalog exports 14 trials: 11 manual and three read-only. See the [SQC100-4 record](SQC100-4-INTAKE-2026-11-06.md).

[Copy or download instructions and feedback forms for each exact variant](https://bb10-volte.octoooo.com/en/trials.html).

[简体中文](VARIANT-LOCAL-TRIALS.md) · [Full research (Chinese)](ALL-VARIANTS-COVERAGE-PLAN.md)

Local candidate r29 / mobile 0.1.0.30, 2026-11-07: SQW100-1 / WINDERMEREEMEA adds Mobile 460-00 to the exact automatic route alongside Unicom 460-01, Mobile 460-07 and Telecom 460-11. Mobile 460-00 private-backend functions and normal-boot checks passed; package installation, UI and stop/restore acceptance is version-specific. Telecom pending-send and duplicate-receive SMS issues remain separate and do not block activation. See the [intake record](SQW100-1-INTAKE-2026-11-06.md). This expands the observed Mobile PLMN without adding model/carrier trial combinations; other MNCs remain blocked. The r15 description below records the older 19-profile release.

This is an experimental route for variants without new hardware acceptance. It reuses the existing manual service and adds exact-model binding, six native-file checks, fixed carrier settings and separate installation/start steps. It does not add candidates to automatic carrier support.

Use an already rooted phone with working AutoRoot v4 / Root SSH. A report does not require wiping or reflashing. First Root remains subject to model-specific image and loader limits.

| Variant | Candidate route |
|---|---|
| SQN100-1, SQN100-5 | Telecom 460-11; working local LTE B5 data is required |
| SQC100-1, SQC100-3, SQC100-5 | Mobile 460-00, Unicom 460-01, Telecom 460-11 |
| SQW100-3 | Checks and export for all three carriers; installation remains blocked pending native lifecycle/restoration validation |

There are 13 manual candidates and six read-only candidates. Actual checks still require OS 10.3.3.3216, QNX ARM32, Root, matching native files, USIM without ISIM, the selected home PLMN, working LTE data, a verified stock template and a clean baseline. Band overlap does not establish local coverage or voice support.

SQN100-3, SQC100-2 and SQW100-4 keep their existing automatic route. Domestic cases for SQN100-2/-4, SQC100-4/Mobile and the unconfirmed SQW100-2 do not receive trial installation. Other MNCs and ISIM are outside this batch.

SQW100-1/-3 only inspect and export feedback. Skip steps 4–7 below: do not install, start, or disable/restore. The standalone Passport instructions cover the read-only route separately.

1. Use the r15 Windows EXE or macOS DMG and verify its supplied SHA-256. The trial entry does not establish hardware acceptance. Keep the same package throughout the trial. Do not overwrite an active automatic installation or mobile transaction.
2. Select the full variant from Settings / About and the actual carrier. Choose **Check this phone**; the main window also offers **More / Local candidate variant trials**. This does not automatically consent, install, flash or reboot.
3. If blocked, use **More / Export check report**. Unknown native files, mismatched hardware/SIM, unavailable LTE data or unverified restoration cannot be bypassed by retrying or editing the profile.
4. After technical checks, explicitly opt into experimental use and recheck. Confirm a backup, provisioned VoLTE and no active call. **Install and verify** installs only. The trial does not change radio attachment policy; Telecom requires working LTE data first.
5. Start separately, then use the native dialer for owner-directed incoming/outgoing calls, two-way audio and continuous LTE checks. IMS registration is not call acceptance.
6. Test short and long SMS, two separately sent messages with identical content, sending, and later duplicates. Do not submit message text or phone numbers.
7. Choose **Disable and restore**, wait for verified restoration, then restart normally and confirm autostart remains off. Further trials require the same selection, fresh checks and manual start. Keep reports when restoration fails; do not reinstall over uncertain state.
8. Submit the sanitized check report and result form. Mark unperformed tests as untested.

The candidate dialog exports 19 bound profiles, a 42-case matrix and a blank result form into a new directory without contacting a phone. Source entry points:

```sh
python tools/gui.py --variant-trials
python tools/gui.py --trial-variant SQC100-3 --trial-operator unicom
python tools/variant_trials.py --export /path/to/new-trial-folder
```

Both r15 Windows and Mac packages include the trial entry and Python/Tk. The older r14 packages do not include it. No new variants have hardware acceptance in this release.

Mobile integration should reuse the reserved `variant-trial-` profiles and the device-side compatibility checks. Include the allowlisted `variant_trial` field in reports; never interpret it as hardware acceptance. Keep installation separate from start and autostart disabled. Merge the shared installer semantically and regenerate both manifests; only two additional fixed Python files, `profiles.py` and `compatibility.py`, join the known inactive-update set. Native binaries and automatic model/carrier authorization remain unchanged.
