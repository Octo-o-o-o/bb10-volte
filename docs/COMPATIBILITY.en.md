# Compatibility preflight

[简体中文](COMPATIBILITY.md)

The fixed profile is `q10-sqn100-3-os3216-unicom01-usim-v1`. The GUI, CLI and phone installer share `device/compatibility.py`. A passing preflight does not prove carrier IMS provisioning or working calls.

| Combination | Decision | Hardware evidence |
|---|---|---|
| Q10 SQN100-3 / OS 10.3.3.3216 / Unicom 460-01 / USIM without ISIM / connected 3gnet / LTE / exact native hashes | Eligible when the installation baseline is also clean | One Beijing device, short calls in both directions and a normal reboot |
| Another province with all the same conditions | Eligible for experimental acceptance; province cannot be inferred from MCC/MNC | No cross-province hardware validation |
| Another Unicom MNC, ISIM, or unknown identity layout | Adaptation required; installation blocked | Unverified |
| China Mobile, China Telecom or another carrier | Adaptation required; installation blocked | Unverified |
| Another model, variant, OS or native hash | Unsupported by this profile; installation blocked | Unverified |
| SIM, Root, LTE or data APN unavailable | Not ready; installation blocked | Recheck after resolving the condition |

There is no hardcoded Beijing P-CSCF address: discovery uses PCO on the IMS APN. Carrier provisioning, terminal policies, roaming and local network conditions still require real-device testing. Province is not used to generate a configuration.

Ask the customer for the model/variant/full OS version, existing Root/SSH setup, carrier and home/current province, porting/roaming status, and whether this SIM makes working VoLTE calls in another supported phone. Request the sanitized preflight JSON and a call acceptance checklist. Do not request full phone numbers, IMSI/IMEI/ICCID, PIN, SIM authentication material or SSH keys. SIM identity layout is reduced to a boolean on the phone.

A clean baseline requires no unknown IMS/VPN/software crypto provider, original voice policy 0 and no conflicting overrides. A complete legacy installation can be updated after restoring it. Changed files, interrupted writes and unknown directories block replacement. New profiles need reviewed code, pinned hashes and hardware acceptance. Reports and PRs for other versions are welcome.
