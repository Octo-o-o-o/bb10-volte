# Startup network waits, LTE mode and manual selection

[中文](NETWORK-RESILIENCE.md) · [Three-carrier setup](AUTO-CARRIERS.en.md)

This guide describes **r49 / mobile 0.1.0.49**. Older r48 packages do not include these changes. Published older artifacts and the frozen macOS r43 package remain unchanged. A single Classic troubleshooting report is design input, not acceptance for every model, region or carrier.

## Default behavior

- Preserve automatic selection and accept a MANUAL selection made in Settings. Startup timeouts never automatically lock a PLMN.
- Give existing LTE attachment a short initial window before applying the established LTE-only activation policy. Reconcile valid changes such as mode 19 while retaining the original recovery record.
- After the initial readiness window, continue observing PPS events with a maximum 30-second fallback interval for stop requests. Event waiting works before native IMS exists; unsupported streams use bounded waits. No power measurement is claimed.
- Release the management lock while waiting so status and disable remain available. Explicit disable restores owned configuration and selection. OS shutdown does not force a radio-policy reload.
- Commit the once-per-boot attempt immediately before native configuration. A fully restored pre-native failure with the same SIM and no IMS/VPN/crypto resources may offer **Retry connection**. Native configuration attempts, SIM changes and Passport attach-policy transitions retain their reboot boundary. Never delete receipts to bypass it.

LTE-only has no 2G/3G fallback. If LTE stays unavailable, inspect settings and disable/restore when appropriate. A waiting manager does not prove calls work.

## Optional home-carrier LTE selection

The advanced action is available through the desktop JSON CLI. The phone's system manual-selection controls remain usable. Startup does not invoke this action automatically:

```bash
python tools/ai_skill.py volte probe
python tools/ai_skill.py volte lock-network
python tools/ai_skill.py volte status
python tools/ai_skill.py volte unlock-network
```

The installed backend must match the source package. Exact model, OS, Root, native files, SIM and recovery backups must pass. Mobile Network must be ON, calls idle, and native IMS/VPN/crypto resources unused. Busy resources cause rejection, not termination of IMS.

Prefer an observed serving PLMN in the SIM carrier group; otherwise use Mobile `460-00`, Unicom `460-01`, Telecom `460-11`. Do not blindly select a new-range USIM's HPLMN as though every cell broadcasts it. These candidates do not cover every shared network or region; restore AUTO or use system manual selection if needed.

Only an original AUTO selection is taken over. An existing MANUAL selection returns `system_manual_selection_preserved`: the serving network cannot prove the user's previous target. Save recovery intent before writes, require scan-mode readback, and send MCC/MNC as strings with integer RAT. Acknowledgement is not registration or call acceptance. On failure, attempt AUTO restoration; retain receipts and return an error if restoration is uncertain or the radio is off. Unlock, disable and the next confirmed SIM change release owned selection.

## USB and diagnostics

A unique BlackBerry link-local `/30` peer can change while retaining SSH identity and strict host-key trust. Ambiguous devices, other remote hosts and proxies are not automatically rewritten.

Discovery does not change old key `from=` restrictions, SSH listen addresses or host-key checks. Fixed-source authorization may still reject a new source; inspect the existing authorization or use established pairing rather than reflash or bypass trust.

If HTTP discovery works but SSH refuses, unlock and wait for Root services first. This proves neither missing Root nor a unique lock-screen cause. Diagnostics show selection mode, roaming settings and decoded LTE masks without cell or SIM identifiers. These observations and IMS 200 OK do not replace calls, audio, SMS or data acceptance. A new SIM may spend several minutes registering; transient `connecting` does not justify repeated enable/reboot attempts.

## Validation scope

Offline regressions cover radio-mode reconciliation/restoration, waiting and stop, native-attempt boundaries, SIM/resource guards, PPS acknowledgements/rollback, dynamic USB trust, and mobile update guidance without changing existing protocol states.

No phone was connected or changed. Weak-coverage boots, PPS behavior per suffix, same-SIM retry, selection restoration/SIM swaps, dynamic USB with old authorization, and power use remain pending device validation. Previous-version acceptance does not count as acceptance of this candidate.
