# BB10 VoLTE Desk

[简体中文](GUI.md)

The Windows GUI uses the same fixed workflow as the CLI. Requirements: Windows 11, Python 3.14 including Tk, OpenSSH, and your own verified root SSH configuration. No AI account, cloud service or third-party Python package is needed. The first UI is in Chinese; this guide describes its controls.

Extract the complete release and double-click `Start-GUI.cmd`, or run `python tools/gui.py`. Keep the complete directory. Do not regenerate a manifest on a customer's machine to bypass a package mismatch.

1. Select the phone's `ssh_config`; the default alias is `q10-root`. A blank config field uses the existing OpenSSH configuration. Strict host-key checking remains enabled.
2. Select a preset or **编辑 / 导入配置 / Edit or import profile**. Edit MCC/MNC, data/IMS APNs, IP family, domain, waits and autostart; import/export JSON. Q20/Q30 and untested operators require explicit experimental opt-in. Changes invalidate preflight. See [profiles](PROFILES.en.md). Then click **运行预检 / Preflight**: it recognizes the device and checks OS, root, native hashes, SIM, LTE, selected data APN, stock carrier configuration and existing state. Four probe modules and a configuration request are temporarily uploaded; executed scripts are individually trusted and cleaned up on success. It does not change telephony settings.
3. Resolve blocked or waiting checks. Confirm the backup, carrier VoLTE provisioning and absence of an active call. **安装并验证 / Install and verify**, or **更新并验证 / Update and verify**, becomes available only when the required checks pass. An existing active service must first be stopped and restored.
4. Installation verifies the fixed package, repeats phone-side preflight, writes the release/profile, reads it back and starts IMS validation. Autostart follows the selected profile. Registration observation defaults to 180 seconds and is configurable. Keep USB connected; do not swap SIMs or use another installer. First activation may briefly reload the radio.
5. IMS registration requires a live manager, live native process, LTE and connected IMS with `200 OK`. It does not prove calls work. Verify incoming/outgoing calls, audio in both directions, continued LTE, unplugged operation and a normal reboot. The existing reboot trial needed approximately 7 minutes 42 seconds from reboot to registration. A desktop timeout reports pending registration, not automatic success or a repeated installation.

**启动验证 / Start and verify** starts a complete current installation. **查看状态 / Status** reads current state. **停用并恢复 / Disable and restore** turns off startup and checks restoration of the project's changes. **导出脱敏报告 / Export sanitized report** saves only allowlisted diagnostic fields, without full SIM/device identifiers, keys, host addresses or raw SIP logs. Reports are never uploaded automatically.

After a connection failure, recheck before retrying. Interrupted writes leave an installation transaction receipt or an incomplete directory and block replacement. Arbitrary interrupted installs do not yet have automatic repair; preserve the files for maintainer inspection. Initial Root flashing is separate, erases user data and is not started by the GUI; follow [INSTALL.en.md](INSTALL.en.md).

Q20/Q30 show “Not hardware validated; experimental use available.” Explicit opt-in never bypasses OS/native hashes or SIM compatibility. Only one Beijing Unicom Q10 has call evidence. Public-data Mobile, Telecom and other Unicom templates are untested; ISIM remains unsupported. Reports include selected profile and file fingerprints; keep personal details out of profile labels. See [compatibility](COMPATIBILITY.en.md). Never flash the bundled Q10 Root images onto Q20/Q30.
