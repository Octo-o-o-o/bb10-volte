# BB10 VoLTE — 4G Calling on BlackBerry Q10

[简体中文](README.md) | **English**

**Repository status: temporarily Private. The maintainer will make it Public after stabilization.** The source uses the MIT license; these documents also prepare for that future public release.

An open-source toolkit for enabling native VoLTE / 4G voice calling on BlackBerry 10, using the phone's own SIM, IMS stack and system dialer. The implementation and hardware validation currently cover **BlackBerry Q10 SQN100-3, BB10 10.3.3.3216, and China Unicom 460-01 in Beijing**.

**Tested on a real Q10 on October 27, 2026.** Outgoing calls completed an IMS `INVITE 200 / ACK / BYE` exchange, incoming calls reached ringing, and all 366 sampled radio states remained LTE. The owner reported successful use. Answered incoming calls and audio in each direction were not separately recorded. This is an **experimental release**: the revised persistent service still needs reboot, unplugged operation and full call acceptance. Other BB10 devices, firmware versions and carriers are untested.

[Installation](docs/INSTALL.en.md) · [Validation evidence](docs/VALIDATION.en.md) · [Build from source](docs/BUILD.en.md) · [MIT license](LICENSE)

## What it does

- Creates a dedicated `ims` APN and derives IMS identities from the Q10's own USIM. Authentication stays with the SIM and native IMS implementation.
- Builds a hash-checked copy of the stock IMS program with an isolated platform configuration and a two-byte change to the ordinary voice VoPS decision.
- Enables the existing QNX software crypto provider and selects IMS-preferred voice through the native radio API.
- Installs a phone-side service with status, start, stop, update, disable, collection and recovery commands.
- Provides complete Python, shell and C source, a reproducible 5,264-byte helper, pinned material manifests and regression tests.

The stock `/radio/bin/ims_rrm` is not overwritten. Original firmware files must match the published SHA-256 values. The toolkit does not unlock a SIM, obtain free service or provide a separate calling account; it needs an active VoLTE-capable subscription.

## Tested environment and requirements

| Component | Requirement / recorded environment |
| --- | --- |
| Phone | **BlackBerry Q10 SQN100-3**; other Q10 variants and BB10 models are untested |
| Phone operating system | **BlackBerry 10 OS 10.3.3.3216**; the firmware archive is named `Q10_10.3.03.3216_SQN100-1-2-3-4-5.7z`. Exact native file hashes are enforced by the installer |
| SIM and network | **China Unicom 460-01 USIM in Beijing**, working LTE data and a subscription confirmed to support VoLTE; the tested SIM had no ISIM |
| Phone access | Working **root SSH**, the owner's private key and a verified host key; the service uses the AutoRoot v4 addon mechanism |
| Computer | **Windows 11 x64** was used; the Root preparation and USB driver workflows require Windows. macOS/Linux deployment has not been validated |
| Desktop Python | **Python 3.14** (tested with 3.14.9); full Root preparation uses its Zstandard tar support. No third-party Python packages are required |
| Device Python | BB10's built-in **Python 3.2**, with the native libraries checked by the installer |
| Connection | Reliable USB data cable, BlackBerry USB networking and OpenSSH `ssh`, `scp`, `ssh-keygen`; `scp` must support `-O` |
| USB drivers | **BlackBerry USB Drivers 5.0.0.2 x64**; preparation checks file hashes and package/catalog signatures |
| Initial Root only | AutoRoot v4, Q10 stock firmware, **7-Zip**, libusb **1.0.30**, LZO **2.10-3**, and the pinned OpenSSL DLLs from **Git for Windows 2.55.0.windows.5 / OpenSSL 3.5.7**; allow about **15 GB** of workspace |
| Optional helper rebuild | **Zig 0.13.0**; no QNX SDK is needed to install the supplied helper |

Exact filenames, original download URLs and SHA-256 values are in [sources.json](materials/sources.json), [usb-drivers.json](materials/usb-drivers.json) and [stock-partitions.json](materials/stock-partitions.json). These are recorded working versions, not a request to use whichever version is newest. A hash mismatch stops preparation.

## Quick start

### 1. Obtain the source

```powershell
git clone https://github.com/Octo-o-o-o/bb10-volte.git
cd bb10-volte
python --version
python tools/check_release.py
```

You can also extract the experimental ZIP from [Releases](https://github.com/Octo-o-o-o/bb10-volte/releases) and enter its top-level folder.

### 2. Prepare the phone connection

If the matching Q10 already has working root SSH and USB networking, use its existing verified SSH configuration. The examples below use `private/root-kit/ssh_config` and the alias `q10-root`; substitute your own configuration path and `--host` alias when necessary.

For a stock phone, follow the [full installation guide](docs/INSTALL.en.md) to verify the USB drivers, obtain the pinned materials, create your own keys and build the Root images. **Initial Root flashing erases user data.** Back up the phone and keep a matching stock recovery image. The offline preparation scripts do not flash a phone.

### 3. Install and start VoLTE

Run these commands from the repository root with the phone connected:

```powershell
python tools/q10.py install --ssh-config private/root-kit/ssh_config
python tools/q10.py check --ssh-config private/root-kit/ssh_config
python tools/q10.py start --ssh-config private/root-kit/ssh_config

# After about one minute:
python tools/q10.py status --ssh-config private/root-kit/ssh_config
```

Look for `phase=running`, `manager_alive=true`, `register_status="200 OK"` and `ran="LTE"`, together with a live native IMS process and a connected IMS state. The first start may briefly reload the radio. An IMS registration response alone does not establish that voice calls work.

### 4. Test calls and recovery

Use the system dialer to make and answer calls, verify sound in both directions, and check that the phone stays on 4G. Repeat after a reboot and after disconnecting USB. Follow the [acceptance checklist](docs/VALIDATION.en.md); these checks remain necessary for each installation.

After hanging up, stop and restore the project's changes with:

```powershell
python tools/q10.py stop --ssh-config private/root-kit/ssh_config
python tools/q10.py status --ssh-config private/root-kit/ssh_config
python tools/q10.py check --ssh-config private/root-kit/ssh_config

# Also prevent the service from starting at the next Root startup:
python tools/q10.py disable --ssh-config private/root-kit/ssh_config
```

Wait for `stopped`, no live manager or project IMS process, original voice policy `0` and software provider `-1`. `cleanup_required` means recovery needs investigation. See the [installation guide](docs/INSTALL.en.md) for updating, collecting private diagnostics and removing the startup entry.

## Validation status

| Check | Evidence / status |
| --- | --- |
| Dedicated IMS APN, AKA/IPsec, `REGISTER 200 OK` | Verified on Q10 |
| System-dialer outgoing call | Verified `INVITE 200`, `ACK`, normal `BYE` on 2026-10-27 |
| Incoming call | Verified ringing; the captured call was cancelled by the caller |
| LTE during the original call trial | All 366 sampled states were LTE |
| Overall owner feedback | Successful use reported; each audio direction not separately documented |
| Persistent service installation, registration, stop/restore and restart | Verified on Q10 |
| Persistent service beyond the old 30-minute trial window | Same instance remained registered on LTE from 15:34 to 16:32 (UTC+8) |
| Revised service after reboot, calls without a computer, full persistent-service call/audio checks | **Pending** |
| Other models, versions, carriers, roaming, handover, long-term standby and emergency calls | **Not tested** |

See [validation details](docs/VALIDATION.en.md) and the [machine-readable evidence summary](materials/validation-summary.json). The original logs contain private communications data and are not distributed. Automated tests do not replace hardware acceptance.

## How it works

```mermaid
flowchart LR
  A[System dialer] --> B[Hash-checked native IMS copy]
  U[Q10 USIM] -->|Identity and AKA| B
  V[IMS-preferred voice selection] --> B
  B --> I[Native IPsec]
  S[Existing software crypto provider] --> I
  I --> P[Dedicated IMS APN]
  P --> N[China Unicom IMS network]
```

The patch changes an isolated PPS configuration path and one ordinary-voice branch after the existing registration, RAT and service checks. Exact offsets, original/result hashes, API behavior and references are documented in [the design notes (Chinese)](docs/DESIGN.md). The separate emergency-call code is unchanged, but emergency calling has not been validated.

## Build and checks

```powershell
python -m unittest discover -s tests -v
python -m compileall -q device tools tests
python tools/check_release.py --check-git
python tools/package_release.py

# Optional: reproduce the supplied helper byte for byte
python tools/build_helper.py --zig C:\Tools\zig-0.13.0\zig.exe
```

`--check-git` verifies that Git tracks exactly the public file allowlist; omit it in an extracted ZIP. GitHub Actions runs the source checks and packaging on Windows and Linux. This checks desktop tooling and public packaging, not phone support on either host platform. See [build details](docs/BUILD.en.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `device/` | Python 3.2 service, installer, native interfaces and recovery logic |
| `driver/` | Complete C helper source, export map and reproducible module |
| `tools/` | SSH controller, material preparation, build and release checks |
| `tests/` | Ownership, recovery, timeout, output and reboot-state regression tests |
| `materials/` | Source URLs, versions, hashes, payload manifest and evidence summary |
| `docs/` | Installation, design, build and validation guides |
| `docs/archive/` | Historical failures and troubleshooting conclusions |
| `downloads/`, `private/`, `build/`, `dist/` | Local inputs, keys, diagnostics and generated output; ignored by Git |

## Contributing and license

**If you use another BB10 OS version, Q10 variant or device model and encounter problems, please open an [Issue](https://github.com/Octo-o-o-o/bb10-volte/issues). [Pull requests](https://github.com/Octo-o-o-o/bb10-volte/pulls) with ports, fixes and test results are welcome.** The tested baseline remains Q10 SQN100-3 / BB10 OS 10.3.3.3216. New support requires independent validation rather than skipping firmware hash checks.

English and Chinese are both welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Provide model, full OS version, carrier MCC/MNC, project version and redacted status fields. Keep phone numbers, SIM/device identifiers, keys and raw SIP logs out of public issues.

Original project code, documentation and the source-built helper are released under the **[MIT License](LICENSE)**. BlackBerry/QNX firmware, stock IMS binaries, third-party Root tools and USB packages remain under their respective terms and are obtained separately from the pinned sources. See [NOTICE.md](NOTICE.md) for attribution and distribution boundaries.

## Acknowledgements

Special thanks to the authors and contributors of **[AutoRoot v4](https://bb10.root.sx/blog/autoroot-v4)** and **[bb10root / BB10 MultiTool (bb10mt)](https://github.com/bb10root/bb10mt)**. Their work on BB10 rooting, SSH access and firmware construction made this project's native IMS investigation and real-Q10 call validation possible. Our initial Root preparation builds on these tools. Please support the original projects and retain their attribution and license notices.
