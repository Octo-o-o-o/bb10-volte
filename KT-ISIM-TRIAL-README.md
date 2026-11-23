# Experimental ISIM + KT (450-08) VoLTE Trial Build

> **Experimental build for Issue #10 (`SQC100-5` / OS `10.3.3.3216` / KT M Mobile `450-08` with ISIM).**
> Stock `/radio/bin/ims_rrm`, `/etc/carrier/config/0.xml`, and `/base` remain **100% read-only**.
> Full 4-file desktop + phone backups and one-command `restore` are preserved.

## What this experimental build adds (on top of `v0.5.0-r52`)

1. **Opt-in ISIM trial gate (`allow_isim: true`)**: Controlled strictly by `/var/bb10_volte-exp-trial.json` (root-only). Without that file, stock `r52` behavior is unchanged.
2. **Verified stock `0.xml` runtime copy (`allow_stock_default_xml: true`)**: Stock BB10 `10.3.3.3216` does not ship a KT `450-08` XML (only SKT `450-05` / `175.xml`), so KT SIMs fall back to `0.xml`. This build verifies `0.xml`'s exact SHA-256 and generates a managed runtime copy with your `data_apns` and `ims` settings without modifying the stock file.
3. **Editable JSON parameters (`kt-45008-trial.json`)**: You can switch `ims.apn`, `ims.ip_family`, `ims.home_domain`, `data_apns`, or `ims.sms` without waiting for a new build.
4. **Sanitized diagnostic trace**: Captures `isim_status`, `preloaded_carrier_config`, `observed_data_apn`, and redacted `ims_rrm` registration events (`UICCRequired`, `ISIM`, `P-CSCF`, `REGISTER` status codes) without exposing IMSI, IMEI, IMPI, IMPU, phone numbers, or IPs.

## Step-by-step instructions

Keep the Classic connected over USB with Root SSH working (same pairing used by the desktop app).

### Step 1 — Read-only probe first
```bash
python tools/kt_isim_trial.py probe
```
Check `observed_data_apn`, `isim_status`, `preloaded_carrier_config`, and `downloaded_carrier_config_present`.
- If `observed_data_apn` is different from `lte.ktfwing.com`, update `data_apns` in `kt-45008-trial.json` first.

### Step 2 — Apply experimental config & install
```bash
python tools/kt_isim_trial.py apply --config kt-45008-trial.json
```
This backs up your 4 original carrier files (phone + computer), installs the experimental backend, and pushes `kt-45008-trial.json`.

### Step 3 — Normal restart & check status
1. Use the phone's **power menu** to restart normally.
2. Unlock the phone, wait 2–3 minutes on LTE, then run:
```bash
python tools/kt_isim_trial.py status
```
- **If `ims == "connected"` and `register_status == "200 OK"`**: unplug USB and test an outbound call, inbound call (check if 4G stays on LTE instead of dropping to 3G CSFB, and check two-way audio), and SMS!

### Step 4 — If it does not register on the first try
Before reporting back, you can optionally test the two most common KT parameter tweaks by editing `kt-45008-trial.json` and re-running `apply` → normal restart → `status`:
1. Change `"apn": "ims.ktfwing.com"` → `"apn": "ims"` (if `status` stays in `waiting_for_ims_apn`).
2. Change `"ip_family": "IPv4v6"` → `"ip_family": "IPv6"` (or `"home_domain": "auto"` → `"ims.kt.com"`).

If it still fails, please paste the sanitized JSON output of `probe` and `status` directly into Issue #10 (no IMSI/IMEI/phone numbers/raw logs needed).

### Step 5 — Clean rollback to stock anytime
```bash
python tools/kt_isim_trial.py restore
```
Then restart the phone normally from the power menu.
