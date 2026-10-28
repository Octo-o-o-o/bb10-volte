# Restore a connection to an already-rooted phone

[简体中文](RECOVER-CONNECTION.md) · [First use](FIRST-RUN.en.md)

On Windows and macOS, open **First use → Connection checks → Recover connection**. The workflow uses available materials and verified access, without requiring the original firmware package name. It does not flash or erase the phone.

A complete, working local `ssh_config` can be imported directly, provided its login key and trusted host records are readable on this computer. Windows `C:\…` paths cannot be used unchanged on a Mac; import your own login key and trusted host public key below to create valid local paths. With only an unencrypted RSA login private key, select it and a trusted phone RSA host public key (`ssh_host_rsa_key.pub`, or a `known_hosts` record for the USB address). Confirm its source and fingerprint. The app copies the login key into its protected private directory, creates a strict configuration, and verifies effective UID 0. Original files are preserved. PuTTY PPK files require OpenSSH export in PuTTYgen; encrypted keys can instead use the new-authorization path below.

Without any files, choose **No connection files**; old Windows files are unnecessary. This requires an existing working Root terminal on the phone, such as Term49 with `__root` / `u_root`, and a supported existing SSH layout. A terminal icon or development mode alone is insufficient. The app cannot grant phone permissions from an unauthenticated computer.

1. Generate and export the pairing script. A fresh RSA private key stays on this computer. Only the script containing its public key is exported. Copy it to the phone's internal Downloads folder.
2. Follow the displayed phone commands to enter the existing Root shell, verify UID 0, trust that exact script path and run it. The script validates the existing SSH layout before changing anything.
3. Type `PAIR` on the phone. Existing authorization is backed up and preserved; only this computer's public key is appended. The script exports a matching public result JSON. It does not replace phone keys, alter telephony or rewrite firmware.
4. If SSH is disabled, a separate `START` choice starts the existing server for the USB address. It does not change boot flags. Use the existing Root tools for persistent SSH startup when needed.
5. Copy the result back to the same computer and import it. The app checks the request ID and computer key, asks you to confirm the result's origin, pins the phone host key, and verifies Root access before saving the connection.

## Mac transfer without old connection files

If USB networking is unavailable or the Mac cannot browse internal phone storage, one transfer option uses an existing readable/writable microSD card, a matching Mac card reader and the phone file manager. It requires neither old BlackBerry Link nor Finder access to internal phone storage. Do not format or erase the card.

1. Generate and export `bb10-pair-ID.py` to the card on this Mac. Transfer only this public script; leave the private `identity` on the Mac.
2. Safely eject the card from the Mac and insert it in the phone. Use the phone file manager to copy the script from the media card to **internal device Downloads**, without changing its name or ID.
3. In an existing working phone Root terminal, trust and run the exact internal Downloads path shown by the app. The script checks effective UID 0 itself and stops before writing authorization if unavailable. Only type `PAIR` after deciding to approve a **persistent addition of this Mac's public key to phone SSH authorization**. It backs up the file and preserves existing keys, firmware and telephony settings.
4. Choose `START` separately only if the existing SSH server needs a temporary start. Pairing does not install Root or create a universal SSH configuration; unsupported layouts stop.
5. The result is written to **internal Downloads** as `bb10-pair-ID-result.json`. Copy it to the card with the phone file manager, safely remove it and import through the Mac card reader on **the same Mac that generated the request**. Confirm it came from this phone before the app pins host identity and strictly verifies SSH/effective UID 0.

This only transfers public files; a usable USB network is still required for connection. Each computer pairs independently. Without a card/reader, another owner-controlled file transfer method is required. With neither valid materials nor a working Root terminal, restore access through the original phone Root tools first.

The Mac hardware run reused existing personal connection materials. It did not exercise card transfer, persistent `PAIR` writes or `START`; this is not end-to-end fresh-Mac pairing acceptance. See the [Mac guide](MACOS.en.md#published-package-and-validation-scope) for the published r5 Root-probe issue and the scope of repository source fixes.

Pending keys survive restarting the desktop app. Different computers must pair independently. Conflicting existing host identities are preserved and rejected. Neither private keys nor passwords are included in the exported phone script or result.

If neither a Root terminal nor valid connection materials are available, restore access using the original Root tools first. Custom ports, non-USB addresses, non-RSA keys, conditional SSH settings or different authorization directories require an existing manual configuration. The script stops on unsupported layouts. This recovery path has desktop, real local key-generation and simulated phone-filesystem coverage, but no write acceptance on third-party-rooted phones; it is not a universal compatibility claim.

Sources: [AutoRoot v4](https://bb10.root.sx/blog/autoroot-v4) documents Root helpers, SSH flags and key paths; [v3](https://bb10.root.sx/blog/pre-rooted-autoloaders-v3) documents SSH being disabled by default.
