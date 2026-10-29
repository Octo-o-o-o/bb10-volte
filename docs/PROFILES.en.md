# Operator and runtime profiles

[简体中文](PROFILES.md)

In 0.3.3, experimental opt-in cannot bypass the Passport lifecycle hold. Incoming-call research parameters are diagnostic leads, not importable runtime options or automatic writes. See [community research](COMMUNITY-RESEARCH.en.md).

The GUI offers the recorded Q10/Unicom parameters and public-data Unicom, Mobile and Telecom templates. The editor has operator, IMS and runtime tabs with JSON import/export. Options participate in validation, installation or runtime behavior.

| Field | Effect |
|---|---|
| ID / label | User-defined names; cannot assert validation |
| MCC / MNC list | Match actual SIM; retain leading zeros |
| Data APNs | Check active data and stock internet configuration; do not change user data APN settings |
| Stock ID / SHA-256 | `auto` uses `true_home_carrier.preloadedConfigFile`; optional numeric ID and hash; stock carrier files only |
| IMS APN / IP family | Dedicated IMS service using IPv4, IPv6 or IPv4v6 |
| Home domain | `auto` derives from actual SIM MCC/MNC, padding MNC to three digits; validated custom domains allowed |
| SMS capability | Advertise IMS SMS; does not establish working SMS |
| SIM, IMS APN and existing-IMS waits | Bounded phone readiness waits; the IMS APN value applies per round, with at most three rounds |
| Registration wait / poll interval | Desktop observation duration and runtime polling |
| Autostart | Set boot startup; explicit manual start still works when disabled |

Templates cite a [pinned snapshot](../materials/carrier-data-sources.json). Mobile, Telecom and other Unicom MNCs require experimental opt-in and all technical gates. JSON accepts only `schema`, `id`, `label`, `carrier`, `ims`, `runtime`; phone-side checks enforce types and ranges and reject unknown fields.

```powershell
python tools/bb10.py preflight --ssh-config private/root-kit/ssh_config --profile profiles/china-mobile.json --allow-experimental
python tools/bb10.py setup --ssh-config private/root-kit/ssh_config --profile profiles/china-mobile.json --allow-experimental

# Q20 trial with default Unicom parameters; Passport preflight only
python tools/bb10.py preflight --ssh-config private/root-kit/ssh_config --allow-experimental
```

Pass the same profile and opt-in to subsequent CLI setup/update/start/enable commands. Set the SSH alias with `--host`. The GUI carries its selection. Registration observation defaults to 180 seconds and accepts 30–900 seconds; timeout means pending.

**Change configuration by hanging up, stopping/restoring, applying the new profile, rerunning preflight, updating and testing calls.** Changed profiles cannot start an older configuration. The profile and opt-in fingerprint must match the receipt. Export custom JSON before closing the GUI; desktop settings are not automatically persisted.

The phone stores `carrier-profile.json`, hash-bound to its receipt. Only the stock XML's IMS section is replaced; data and other sections remain intact. Recovery records exact applied PPS values, so later profiles do not change restoration. Complete v0.1/v0.2 installs can update after restoration; interruptions or outside edits block replacement.

P-CSCF comes from network PCO. IMSI/IMPI/IMPU stay local; subscriber credentials are never downloaded. The current engine requires USIM without ISIM. Patch offsets, native hash bypasses and authentication substitutes are not profile fields. Submit sanitized reports for further ports.

All three experimental presets default to autostart off. Q20 with the default Unicom parameters must also disable it under Customize → Runtime options. runtime.autostart=false is mandatory for experimental combinations and enable cannot bypass it. Passport retains its separate hold.
