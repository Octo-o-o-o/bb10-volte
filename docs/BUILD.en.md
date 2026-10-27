# Build and release checks

[简体中文](BUILD.md) | **English**

Device scripts target BB10's Python 3.2 and hash-checked native libraries. Desktop tools and tests use Python 3.14, without third-party Python packages. Installing the supplied helper does not require a QNX SDK.

## Source validation

```powershell
python -m unittest discover -s tests -v
python -m compileall -q device tools tests
python tools/check_release.py
```

For a Git checkout, also use `python tools/check_release.py --check-git` after staging intended changes. This requires tracked paths to equal the public release allowlist. Release checks verify payload hashes, scan for common private identifiers and credentials, check syntax and local Markdown links, and require LF in shell scripts.

When a device payload is intentionally changed, regenerate `materials/payload-manifest.json` with `python tools/q10.py manifest`, review the changed hashes, and repeat validation. Do not regenerate it merely to hide an unexpected mismatch.

## Reproduce the helper

Install or extract **Zig 0.13.0**, then run:

```powershell
python tools/build_helper.py --zig C:\Tools\zig-0.13.0\zig.exe
```

The output under `build/` must be **5,264 bytes** with SHA-256:

```text
504a6f5bdfb55f03aaf64b1a73f423e1a802e4786433f2621cd701c993224254
```

The builder checks this exact digest and does not overwrite the bundled module. The helper has no external `DT_NEEDED` libraries; it imports only the existing io-pkt symbols `swcr_id`, `swcryptoattach` and `crypto_unregister_all`, with a 12-byte native driver-entry structure. Its ARM ELF layout and QNX loading were validated for the stated phone/firmware combination; it is not a general Linux driver.

## Package an experimental source release

```powershell
python tools/check_release.py --check-git
python tools/package_release.py
```

The ZIP in `dist/` contains only allowlisted source, documentation, manifests, workflow and the source-built helper, plus a per-file `RELEASE-MANIFEST.json`. The packager reads the ZIP back and verifies every file hash. A separate `.zip.sha256` records the archive digest.

Downloads, proprietary firmware, owner-specific Root images, SSH keys, private phone logs and intermediate build output are excluded. GitHub Actions repeats source tests and packaging on Windows and Linux; it does not run device integration tests or prove macOS/Linux deployment compatibility.

Earlier hosted Windows/Linux jobs on October 27, 2026 could not start because the account's Actions budget prevented further use. v0.2.0 passed 43 local tests, compiled all six device Python files on the Q10's Python 3.2.2, and completed a real GUI preflight. Full hardware installation acceptance of the new workflow is pending; no hosted pass is claimed.

Only single-device normal-reboot and short-call acceptance is established. Keep releases explicitly marked **experimental / prerelease**, and the repository temporarily **Private**, while longer-term validation continues. Extending model or firmware support requires native ABI, patch and actual-call validation, not bypassing hashes.
