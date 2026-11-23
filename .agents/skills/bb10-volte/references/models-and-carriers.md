# Supported BB10 Models, Firmware & 3-Carrier Runtime Reference

Canonical machine-readable catalogs in this repository:
- Model & hardware research: [device-support.json](../../../../materials/device-support.json)
- Compatibility & historical evidence: [compatibility-matrix.json](../../../../materials/compatibility-matrix.json)
- Runtime admission policy: [carrier_policy.py](../../../../device/carrier_policy.py)
- Verified firmware & tool hashes: [sources.json](../../../../materials/sources.json) and [first-run-tools.json](../../../../materials/first-run-tools.json)

Query live via CLI: `python tools/ai_skill.py models` or `python tools/ai_skill.py models --variant <SQX100-Y>`.

---

## 1. Complete 16-Model Hardware Matrix (OS `10.3.3.3216` Required)

All **16 models × 3 carriers = 48 entries** are **open for activation** (`admission: true`). Historical test status in [compatibility-matrix.json](../../../../materials/compatibility-matrix.json) informs users without blocking trial on untested or band-limited suffixes.

| Family | Variant | Pinned `Board_Type` | China FDD-LTE Bands | Stock `3216` Firmware ID | Auto-Root Recipe | Model-Specific Operational Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **Q10** | `SQN100-1` | *(any valid Q10)* | B5 | `stock-q10` | Yes | Shared Q10 engine; local LTE coverage depends on B5/band availability. |
| **Q10** | `SQN100-2` | *(any valid Q10)* | — | `stock-q10` | Yes | North America/regional LTE bands; check local carrier FDD overlap. |
| **Q10** | `SQN100-3` | *(any valid Q10, e.g. `R085`)* | B3, B8 | `stock-q10` | Yes | Primary Q10 hardware baseline; 3-carrier voice/SMS tested. |
| **Q10** | `SQN100-4` | *(any valid Q10)* | — | `stock-q10` | Yes | Shared Q10 engine; check local LTE band availability. |
| **Q10** | `SQN100-5` | *(any valid Q10)* | B5 | `stock-q10` | Yes | Shared Q10 engine; B5 overlaps China Telecom in many regions. |
| **Classic (Q20)** | `SQC100-1` | `CLASSICROW` | B1, B3, B5, B8 | `stock-classic` | Yes | Owner-confirmed 3-carrier calls, SMS, and data. |
| **Classic (Q20)** | `SQC100-2` | `CLASSICATT` | B1, B3, B5 | `stock-classic` | Yes | 3-carrier tested; r46 Telecom MO SMS `telecom_mo_ack` verified on live card. |
| **Classic (Q20)** | `SQC100-3` | `CLASSICVZW` | B3 | `stock-classic` | Yes | Owner-confirmed 3-carrier basic calls, SMS, and data. |
| **Classic (Q20)** | `SQC100-4` | `CLASSICNA` | B1, B5 | `stock-classic` | Yes | Windows Root prep adds `UseDNS=no` to `sshd_config` to avoid cellular DNS stalls. |
| **Classic (Q20)** | `SQC100-5` | *(unpinned; `CLASSICVZWNC` observed)* | — | `stock-classic` | Yes | Fresh-device preflight verified (`r44+`); check local LTE coverage. |
| **Passport (Q30)** | `SQW100-1` | `WINDERMEREEMEA` | B1, B3, B8 | `stock-passport` | Yes | Mobile (incl. `460-07`), Unicom, Telecom tested; extra reboot when switching Unicom ↔ Mobile/Telecom. |
| **Passport (Q30)** | `SQW100-2` | *(unconfirmed)* | — | `stock-passport` | Yes | Production identity unconfirmed in public filings; entry stays open. |
| **Passport (Q30)** | `SQW100-3` | *(unpinned; `WINDERMERENA` observed)* | — | `stock-passport` | Yes | Stock `3216` upgrade, AutoRoot v4, and `0.1.0.44+` install verified on hardware. |
| **Passport (Q30)** | `SQW100-4` | `WINDERMERE4ROW` | B1, B3, B8 | `stock-passport` | Yes | Mobile, Unicom, Telecom tested; extra reboot when switching Unicom ↔ Mobile/Telecom. |
| **P'9983** | `SQK100-1` | `KHANE` | B3 | `stock-q10` | Yes | Shares `stock-q10` firmware; owner-confirmed 3-carrier calls, SMS, and data. |
| **P'9983** | `SQK100-2` | *(unpinned)* | B5 | *(none bundled)* | **No** | Open for VoLTE & mobile app **when already rooted on `10.3.3.3216`** with matching native hashes; do **not** attempt first-time firmware flashing with unverified loaders. |

---

## 2. Stock `10.3.3.3216` Firmware Packages

Verified by SHA-256 in [sources.json](../../../../materials/sources.json) before extraction or Root image building:

- **`stock-q10`** (`SQN100-1..5`, `SQK100-1`):
  - Archive: `Q10_10.3.03.3216_SQN100-1-2-3-4-5.7z` (`sha256: 1cd4d70fe2fd0ebc7155d54deeb6cc4b45cc74b75dca76305a6fe6ffd7cec1e4`)
  - Extracted: `Q10_10.3.03.3216_SQN100-1-2-3-4-5.exe` (`sha256: 18ab9ab0da25ad4dfb0f2a885aad81ddf2119c484d5b9b0b392a3472eedfa207`)
- **`stock-classic`** (`SQC100-1..5`):
  - File: `Q20_10.3.03.3216_STA100-1-2-3-4-5-6.exe` (`sha256: d83b04dc9bb3e12b9b6a29b05d2aeb6350cabb6fca85866c231609ba575821e2`)
- **`stock-passport`** (`SQW100-1..4`):
  - Archive: `Passport_10.3.03.3216.7z` (`sha256: bddf3c0df422f2b594619dc436296dc1210b184a8841f3492dd0dd5fbb3931a7`)
  - Extracted: `Passport_10.3.03.3216_SQW100-1-2-3-4.exe` (`sha256: 2c5b7759ba83e50cad96217a285fbfb2cc14f60438903757c9067e1571a03ed4`)

---

## 3. Carrier Selection & Runtime Architecture (`r49` / Mobile `0.1.0.49`)

1. **Automatic Home-PLMN Selection**:
   - Reads the active USIM's home PLMN (`MCC=460`, no ISIM required; SIM `kind` must have USIM bit `2` set and ISIM bit `16` clear; China Broadnet `460-15` is explicitly reported as `china_broadnet_unsupported`):
     - `460-00`, `02`, `04`, `07`, `08` → `mobile` (China Mobile, APN `cmnet` / `cmwap`, SHA-256-pinned stock fallback `404.xml` + OI-normalized empty/default-APN bootstrap when BB10 maps newer HPLMNs to `0.xml`)
     - `460-01`, `06`, `09` → `unicom` (China Unicom, APN `3gnet` / `wonet` / `uninet`, SHA-256-pinned stock fallback `36.xml`)
     - `460-03`, `05`, `11`, `12` → `telecom` (China Telecom, APN `ctnet` / `ctlte`, SHA-256-pinned stock fallback `446.xml` with dead `10.0.0.200:80` CTWAP proxy stripped)
   - Releases from r55 can try China Mobile `460-13` and other home PLMNs when the current USIM and stock carrier XML match. The app labels the route untested. ISIM and lack of normal LTE are separate diagnostics. See [the PLMN and KT investigation](../../../../docs/NETWORK-DIAGNOSTICS.md).
   - Also applies volatile SE.13 operator-name overlay and numeric `current_ons` display fallback (`中国移动` / `中国联通` / `中国电信`) across all 12 admitted MNCs without touching read-only `/base/etc/network/BBSE-se13-network-override-list.txt`.
2. **Read-Only Stock Binary Integrity**:
   - `/radio/bin/ims_rrm` and the other 5 stock QNX radio/system binaries are **never modified on `/radio` or `/base`**.
   - The service verifies all 6 stock SHA-256 digests and runs a verified managed runtime copy under `/var/bb10_volte` with:
     - **`mt_voice_binary`** (`r47+`, all 3 carriers): Sets `MediaDialog.EarlySdp=0` while preserving `MediaDialog.Omit200OkSdp=1` so precondition MT calls answered in reliable `183 Session Progress` omit illegal duplicate SDP in `200 OK (INVITE)` (fixing silent-audio regressions) while non-precondition MT calls still attach the mandatory RFC 3261 SDP answer.
     - **`sms_ack`** (all 3 carriers): Handles inbound SIP `MESSAGE` RP-ACK shimming.
     - **`telecom_mo_ack`** (`r46+`, China Telecom `460-03`/`05`/`11`/`12`): Synthesizes local 3GPP `RP-ACK` (`03 <RP-MR>`) after SIP `202 Accepted` + `0x1014` IPC so `qct_rrm` releases the MO SMS slot instead of leaving delivered Telecom SMS stuck on `"Sending..."`.
     - **Classic 7-Dot BlackBerry Status-Bar Indicator** (`r46+`): Publishes to `/pps/system/navigator/status/bb_service?critical` while VoLTE is actively registered on LTE in the current boot, and clears immediately on loss of LTE/IMS, Airplane Mode, disable, rollback, or exit while preserving any real BlackBerry Infrastructure state.
