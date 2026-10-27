# Compatibility preflight and customer information

[简体中文](COMPATIBILITY.md)

v0.3.0 separates device recognition, operator profiles and native patch compatibility. GUI, CLI and the phone installer share `device/compatibility.py`. Preflight cannot establish subscriber provisioning or working calls.

| Combination | Result | Hardware evidence |
|---|---|---|
| Q10 SQN100-3 / OS 10.3.3.3216 / Unicom 460-01 / USIM without ISIM / 3gnet / LTE / matching hashes | Eligible after clean-state checks | One Beijing phone, short incoming/outgoing calls and normal reboot |
| Another Unicom province with identical conditions | Eligible for individual acceptance; MCC/MNC does not identify province | No cross-province validation |
| Classic / Q20 (SQC100-*), Passport / Q30 (SQW100-*), other Q10 variants | **Not hardware validated; experimental use available** with explicit opt-in and every technical gate passing | Recognition and simulated gate tests only |
| Other Unicom MNCs, Mobile, Telecom, custom profiles | Matching profile plus experimental opt-in and all technical gates required | Public-data templates only |
| ISIM, unknown SIM type or different identity layout | Needs a different implementation; installation blocked | Untested |
| Unknown/conflicting device identity, different OS or any native hash mismatch | Installation blocked; report export available | Opt-in cannot bypass these checks |
| Root, SIM, LTE or data APN unavailable; existing installation not restored | Resolve and repeat preflight | Existing state is preserved |

Identity comes from `/pps/services/deviceproperties`; full OS from `/etc/os.version`. The variant prefix identifies a device when its friendly name is absent, but conflicting identities fail closed. Official model examples: [Classic SQC100-2](https://www.att.com/support_static_files/manuals/BlackBerry_Classic_SQC100-2.pdf), [Passport SQW100-3](https://www.att.com/support_static_files/manuals/BlackBerry_Passport_SQW100-3.pdf). Recognition does not validate radio, drivers or IMS.

Every trial requires **OS 10.3.3.3216, root, QNX ARM32 and all four exact native SHA-256 values**, matching SIM/profile, verifiable stock carrier configuration, active LTE/data APN and a clean baseline. Editing JSON or enabling trials cannot bypass native checks. Engine: `qnx-arm32-os3216-native-v1`; other hashes/builds need implementation and hardware acceptance.

**Bundled firmware and Root image preparation remain Q10-only. Q20/Q30 testers must supply working root SSH prepared for their own model. Never flash the Q10 images onto them.** This release extends VoLTE trials on already-rooted phones.

P-CSCF comes from network PCO; no Beijing address is hardcoded. Province is not a code gate, but provisioning, terminal policies, bands, APNs and roaming affect results. See [profiles](PROFILES.en.md) and [research](CARRIER-RESEARCH.en.md).

Ask customers for model/variant/full OS and root readiness; operator, home/current province and porting/roaming status; whether the same SIM supports two-way VoLTE in a supported phone; selected JSON and sanitized preflight; per-device call results/failure stage. Full phone numbers or SIM identities are unnecessary.

Reports do not automatically collect full IMSI, IMEI, ICCID, PIN, SIM secrets, authentication material or SSH keys. Keep personal details out of profile labels. Configuration edits invalidate preflight; stop and restore before updating. Issues and PRs for other builds, models and carriers are welcome; see [reporting guidance](ISSUES.md).
