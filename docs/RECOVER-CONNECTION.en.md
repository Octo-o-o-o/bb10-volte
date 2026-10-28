# Restore a connection to an already-rooted phone

[简体中文](RECOVER-CONNECTION.md) · [First use](FIRST-RUN.en.md)

On Windows and macOS, open **First use → Connection checks → Recover connection**. The workflow uses available materials and verified access, without requiring the original firmware package name. It does not flash or erase the phone.

An existing `ssh_config` can still be imported directly. With only an unencrypted RSA login private key, select it and a trusted phone RSA host public key (`ssh_host_rsa_key.pub`, or a `known_hosts` record for the USB address). Confirm its source and fingerprint. The app copies the login key into its protected private directory, creates a strict configuration, and verifies effective UID 0. Original files are preserved. PuTTY PPK files require OpenSSH export in PuTTYgen; encrypted keys can instead use the new-authorization path below.

Without any files, choose **No connection files**. This requires an existing working Root terminal on the phone, such as Term49 with `__root` / `u_root`. The app cannot grant phone permissions from an unauthenticated computer.

1. Generate and export the pairing script. A fresh RSA private key stays on this computer. Only the script containing its public key is exported. Copy it to the phone's internal Downloads folder.
2. Follow the displayed phone commands to enter the existing Root shell, verify UID 0, trust that exact script path and run it. The script validates the existing SSH layout before changing anything.
3. Type `PAIR` on the phone. Existing authorization is backed up and preserved; only this computer's public key is appended. The script exports a matching public result JSON. It does not replace phone keys, alter telephony or rewrite firmware.
4. If SSH is disabled, a separate `START` choice starts the existing server for the USB address. It does not change boot flags. Use the existing Root tools for persistent SSH startup when needed.
5. Copy the result back to the same computer and import it. The app checks the request ID and computer key, asks you to confirm the result's origin, pins the phone host key, and verifies Root access before saving the connection.

Pending keys survive restarting the desktop app. Different computers must pair independently. Conflicting existing host identities are preserved and rejected. Neither private keys nor passwords are included in the exported phone script or result.

If neither a Root terminal nor valid connection materials are available, restore access using the original Root tools first. Custom ports, non-USB addresses, non-RSA keys, conditional SSH settings or different authorization directories require an existing manual configuration. The script stops on unsupported layouts. This recovery path has desktop, real local key-generation and simulated phone-filesystem coverage, but no write acceptance on third-party-rooted phones; it is not a universal compatibility claim.

Sources: [AutoRoot v4](https://bb10.root.sx/blog/autoroot-v4) documents Root helpers, SSH flags and key paths; [v3](https://bb10.root.sx/blog/pre-rooted-autoloaders-v3) documents SSH being disabled by default.
