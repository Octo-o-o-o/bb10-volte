"""Inspect only an owner-selected directory; never execute discovered SSH configs."""
import hashlib
import os
from pathlib import Path

from connection_recovery import read_host_key, RecoveryError

MAX_ENTRIES = 2000
MAX_DEPTH = 6


def scan_materials(folder, recursive=True):
    root = Path(folder).resolve(strict=True)
    if not root.is_dir():
        raise RecoveryError('folder_unreadable')
    identities, hosts, configs = {}, {}, []
    count, limited, unreadable, putty = 0, False, False, False
    def cannot_read(_):
        nonlocal unreadable
        unreadable = True
    for current, dirs, files in os.walk(root, followlinks=False, onerror=cannot_read):
        here = Path(current)
        depth = len(here.relative_to(root).parts)
        # Owners may explicitly select this directory alone when a real Root
        # kit also contains large/deep build trees. Never silently narrow a
        # partial recursive search or accept its incomplete candidate list.
        if not recursive:
            dirs[:] = []
        safe_dirs = []
        for name in sorted(dirs):
            child = here / name
            if name in ('.git', 'node_modules', '__pycache__') or child.is_symlink() or child.is_junction():
                continue
            count += 1
            if depth < MAX_DEPTH:
                safe_dirs.append(name)
            else:
                limited = True
        dirs[:] = safe_dirs
        if count > MAX_ENTRIES:
            limited = True
            break
        for name in sorted(files):
            count += 1
            if count > MAX_ENTRIES:
                limited = True
                break
            path = here / name
            try:
                if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                    continue
                if path.stat().st_size > 65536:
                    continue
                lower = name.lower()
                if lower in ('ssh_config', 'config'):
                    configs.append(path)
                if lower in ('known_hosts', 'known_hosts2') or (lower.endswith('.pub') and lower.startswith(('ssh_host_', 'q10_host_'))):
                    try:
                        key = read_host_key(path)
                        hosts.setdefault(key, path)
                    except (RecoveryError, UnicodeError):
                        pass
                    continue
                # Only inspect plausible key names, not every personal document.
                if not (lower.startswith(('id_rsa', 'identity', 'q10_root', 'bb10_root')) or lower.endswith(('.pem', '.key', '.ppk'))):
                    continue
                if lower.startswith(('ssh_host_', 'q10_host_')) or lower.endswith('.pub'):
                    continue
                raw = path.read_bytes()
                if raw.startswith(b'PuTTY-User-Key-File-'):
                    putty = True
                elif b'PRIVATE KEY' in raw[:100]:
                    identities.setdefault(hashlib.sha256(raw).hexdigest(), path)
            except OSError:
                unreadable = True
        if limited and count > MAX_ENTRIES:
            break
    # A partial search must not silently choose one of several possible devices.
    state = ('limited' if limited else 'unreadable' if unreadable else 'ambiguous' if len(identities) > 1 or len(hosts) > 1 else
             'ready' if identities and hosts else 'host_missing' if identities else
             'putty' if putty else 'identity_missing' if hosts else 'config_only' if configs else
             'unreadable' if unreadable else 'empty')
    return {'state': state, 'identities': list(identities.values()), 'hosts': list(hosts.items()),
            'configs': configs, 'folder': root, 'recursive': recursive}
