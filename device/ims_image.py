"""Pure functions for hash-pinned temporary IMS bytes and owned VPN cleanup.

Python 3.2 compatible. This module performs no device I/O or mutations.
"""
import hashlib
import json
import re

STOCK_SHA = '043d38b0f08cf6a9696ef405f3976679e32ff9ad943ec35294c3d3da69a12b67'
UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'


def temporary_binary(original, normal_voice=False):
    assert hashlib.sha256(original).hexdigest() == STOCK_SHA, 'Unknown stock IMS binary'
    old = b'/pps/services/carrier_config/radio_qct/ims\0'
    new = b'/pps/volte_probe/ims\0'
    offset = 0x366bed
    assert original.count(old) == 1 and original[offset:offset + len(old)] == old
    patches = [{'file_offset': offset, 'old_path': old[:-1].decode('ascii'),
                'new_path': new[:-1].decode('ascii'), 'reserved_bytes': len(old)}]
    changed = bytearray(original)
    changed[offset:offset + len(old)] = new.ljust(len(old), b'\0')
    allowed = set(range(offset, offset + len(old)))
    if normal_voice:
        # selectDomainVoice, after IR92, registered, RAT and service guards.
        # Ordinary cellular voice only. The probe config separately limits RAT to LTE.
        assert original[0x62c54:0x62c56] == b'\xc7\xb9'
        changed[0x62c54:0x62c56] = b'\x18\xe0'
        allowed.update((0x62c54, 0x62c55))
        patches.append({'file_offset': 0x62c54, 'bytes_before': 'c7b9', 'bytes_after': '18e0',
                        'before': 'cbnz r7, 0x62c88', 'after': 'b 0x62c88',
                        'function': 'selectDomainVoice', 'purpose': 'Bypass ordinary-voice VoPS veto only'})
    changed = bytes(changed)
    assert len(changed) == len(original)
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(original, changed)))
    # No byte after the ordinary voice function is changed until the separate PPS literal.
    assert changed[0x62e2c:offset] == original[0x62e2c:offset]
    expected = ('f388a23900d13d92c0390c662fc53e2de6d628bba2174973c0320416022a4438' if normal_voice else
                '9d651395c0ecf54d6c7d230c206d5f8204da4e69e6279cf661e4f3825a7c322b')
    assert hashlib.sha256(changed).hexdigest() == expected, 'Unexpected temporary image'
    return changed, patches


def proven_owned_profiles(configs, original_ids, event_text, native_stdout, pid):
    """Require process-owned UID evidence AND a newly created native IMS profile."""
    current_ids = set().union(*(set(re.findall(UUID.encode('ascii'), data)) for data in configs.values()))
    assert original_ids <= current_ids, 'An existing VPN identifier disappeared'
    added = current_ids - original_ids
    own_lines = '\n'.join(line for line in event_text.splitlines()
                          if 'ims_rrm.' + str(pid) + ' ' in line)
    proven = set(re.findall(r'vpn_login response: uid= (' + UUID + ')', own_lines))
    # stdout is redirected directly from this exact child, and survives slog ring wrap.
    proven.update(re.findall(r'^\s*uid \(string\) (' + UUID + r')\s*$', native_stdout, re.M))
    assert added <= set(uid.encode('ascii') for uid in proven), 'Unrecognized new VPN profile'
    owned = {}
    for data in configs.values():
        for line in data.decode('utf-8').splitlines():
            profile = json.loads(line)
            uid = profile.get('uid')
            if uid is None or uid.encode('ascii') not in added:
                continue
            assert uid not in owned, 'Duplicate profile UID'
            assert profile.get('adapter') == 'ims' and profile.get('owner') == 'ims_rrm'
            assert profile.get('server_type') == 'ims'
            name = profile.get('name', '')
            assert re.match(r'^ims_[0-9]+$', name), 'Unexpected IMS profile name'
            owned[uid] = name
    assert set(uid.encode('ascii') for uid in owned) == added, 'New profile not decoded exactly'
    return owned
