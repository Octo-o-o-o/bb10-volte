# Telecom adaptation and Q10 / Q20 / Q30 scope

[简体中文](TELECOM-PORT.md)

Local candidate **0.4.0-r4** records Q20 hardware acceptance and ports LTE attach preparation to Q10. Q10 automatic registration after a normal restart is accepted; calls without USB after that restart remain pending. The phone retains r3 during the call test. A new official release and Mac validation have not been performed in this session.

| Combination | Evidence | App behavior |
| --- | --- | --- |
| Q20 SQC100-2 / CLASSICATT / 10.3.3.3216 / existing Root v2 / Telecom 460-11 | LTE data, owned IMS, bidirectional audio and short LTE calls, normal-menu restart recovery, calls after restart without USB | Verify and manage the existing accepted adapter; preserve its boot hook |
| Same Q20 / Unicom 460-01 | Bidirectional short calls, restart recovery and calls without USB accepted | Reproduction tools retained; current app management manifest pins the Telecom revision |
| Q10 SQN100-3 / 10.3.3.3216 / AutoRoot v4 / Telecom 460-11 | LTE/IMS and bidirectional short calls accepted; normal restart yields a new boot, new processes and automatic registration with zero desktop starts; post-restart calls without USB pending | Controlled boot entry enabled for this trial; r4 receipt management and phone update await the call result. Other combinations remain manual experiments |
| Passport / Q30 / Telecom | No device access, SIM swap or hardware acceptance in this session | Provider lifecycle gate retained; read-only checks remain available |
| Peer Q20 SQC100-4 / Telecom | User-supplied report claims data, calls and received SMS; final loading path and native policy readings missing | External evidence, separate from this project's hardware acceptance |

Observed answered calls lasted about 4–10 seconds; neither 20-second sustained calls nor long-term stability is accepted. Telecom manager-to-registration after restart took 73.333 seconds; full system boot time was not measured. The first Telecom SIM was not retested with the working parameters. Mobile testing is deferred while that SIM and Passport remain in another chat. This session did not separately test Telecom SMS/MMS.

## Working Q20 parameters

Actual SIM: 460-11. Stock carrier XML: 446, SHA-256 `d94f9b7eaa664a9ac496475e706bb837c364635400dd1af9a79608337d57f407`. Preserve stock ctnet data; IMS uses ims, IPv4v6 and ims.mnc011.mcc460.3gppnetwork.org. Native DCA data_centric produces UE EFS 1; the verified RadioControl IMS-preferred request produces voice EFS 3 and reloads the modem. Temporary NAS preferences, voice policy alone, and UE1 without reload did not restore data in these trials.

The accepted legacy Root adapter lives in /var/q20_volte. It uses its own volatile boot nonce because Root v2 lacks /tmp/root.done. Its boot hook precedes the old Term49 installation wait. Explicit stop restores owned configuration and original policies while retaining the software provider until a normal-menu restart. The app verifies the exact accepted manifest before importing that adapter, preserves the working installation and does not require Root migration. A changed payload or operator profile needs a newly verified management manifest.

## Q10 manual port

The new [460-11 profile](../profiles/china-telecom-46011.json) explicitly selects telecom_data_centric_v1. Existing profile canonical bytes and the original 03/11 template are preserved. The port requires exact Q10 SQN100-3 identity, OS/ABI/native hashes, current USIM/carrier XML, no other IMS/VPN, original policies and clean overlays. Additional checks pin qct_rrm and DCA and accept only the four empty/header-only source files.

Installation saves originals, file identity/permissions and a plan. The desktop copies and independently hashes every original and plan before acknowledging any attach write. Manual service startup applies UE1 and voice3, tolerates modem/SIM reload, checks the same SIM and waits for normal LTE data. The existing core still requires LTE/data before IMS configuration. Timeout or failure restores the original source bytes, explicitly publishes voice_centric to recover native UE0, then restores the original missing-key state. Conflicting files are preserved for inspection. Q10 answered calls of 5.012/4.217 seconds are accepted. Normal-menu restart produced a new boot, new processes and 200 OK/LTE with zero desktop starts. Manager startup to registration was 311.549 seconds, mainly waiting for system IMS; full boot time was not measured. Post-restart calls without USB remain pending. The generic template keeps automatic startup false.

r4 startup management requires a maintainer-written acceptance receipt matching this phone, SIM, profile, original backups and 12 critical runtime files. Missing acceptance or a changed SIM/profile/runtime keeps the gate closed. Updates preserve accepted startup intent and do not re-enable an explicitly disabled installation. The call, attach, native and boot code is byte-identical to r3 used in the hardware test. Matching hashes alone do not validate Q30 provider lifecycle.

## Peer report comparison

The peer observed carrier ID 446 while cdsc_xml still selected a legacy carrier-339-volte.xml. Disabling old 339/36 overlays and restarting preceded the reported recovery, but the final loaded path was not captured. This is useful evidence for detecting stale carrier selection, not a demonstrated universal XML-only fix.

Our read-only cross-check found that /var/q20_volte/runtime/carrier/36-ims.xml contains CarrierID 446 and ctnet; its filename is historical. The app checks selection path, expected content derived from the current stock template, and the owned journal hash together. Existing clean-baseline checks preserve and block other tools' overlays rather than deleting or renaming them.

The peer uses AlwaysOn=false, DisableDAD=true and RequestSignallingBearerViaPCO=true. Our accepted configuration uses AlwaysOn=true and omits the latter two. No controlled comparison justifies changing the accepted values. Received SMS is the peer's result, not acceptance of our device.

See [Q20 acceptance](../materials/q20-device-validation-2026-10-30.json), [Telecom research](../materials/q20-telecom-research-2026-10-30.json), [peer comparison](../materials/q20-peer-telecom-comparison-2026-10-31.json) and [Root-v2 tools](../experiments/q20_autoroot_v2/README.md). Raw SIP, derived identities, SSH materials and complete backups stay private.
