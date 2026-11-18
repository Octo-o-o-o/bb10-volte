"""Pure functions for hash-pinned temporary IMS bytes and owned VPN cleanup.

Python 3.2 compatible. This module performs no device I/O or mutations.
"""
import hashlib
import json
import re
import struct

STOCK_SHA = '043d38b0f08cf6a9696ef405f3976679e32ff9ad943ec35294c3d3da69a12b67'
UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'


def _voice_binary(original, normal_voice=False):
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


def thumb_bl(source, target):
    """Encode a Thumb-2 BL without changing instruction width or ISA state."""
    delta = target - (source + 4)
    assert source % 2 == 0 and target % 2 == 0 and -(1 << 24) <= delta < (1 << 24)
    bits = delta & 0x1ffffff
    sign, i1, i2 = (bits >> 24) & 1, (bits >> 23) & 1, (bits >> 22) & 1
    first = 0xf000 | sign << 10 | (bits >> 12) & 0x3ff
    last = 0xd000 | (1 ^ i1 ^ sign) << 13 | (1 ^ i2 ^ sign) << 11 | (bits >> 1) & 0x7ff
    return struct.pack('<HH', first, last)


def _prel31(word, place):
    offset = word & 0x7fffffff
    if offset & 0x40000000:
        offset -= 0x80000000
    return place + offset


def _relative31(target, place):
    offset = target - place
    assert -(1 << 30) <= offset < (1 << 30)
    return offset & 0x7fffffff


def sms_ack_binary(image, patches=(), telecom_mo_ack=False):
    """Add a bounded correlation shim only to a known temporary IMS image.

    Keep the two original LOAD headers, QNX/GNU notes and dynamic imports.
    QNX's runtime linker selects one text and one data relocation bias: adding
    another RX header replaces the text bias and crashes before program entry.
    Extend the original RX mapping, then retain the original RW overlay and
    its zero-filled tail. New code/unwind data sit beyond the RW mapping.
    """
    assert type(telecom_mo_ack) is bool, 'Telecom MO ACK opt-in must be explicit'
    digest = hashlib.sha256(image).hexdigest()
    assert digest in (STOCK_SHA,
        'f388a23900d13d92c0390c662fc53e2de6d628bba2174973c0320416022a4438',
        '9d651395c0ecf54d6c7d230c206d5f8204da4e69e6279cf661e4f3825a7c322b',
        '647290caee0da86479ef7da7c42e68f98cd283fead8e9406f1c530a4a99c0494',
        '7479b023d634c1afddd46203251ec7613ab5170d8ea22d6e321c7dd7fc3e7411'), 'Unknown IMS patch input'
    assert image[:7] == b'\x7fELF\x01\x01\x01'
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', image)
    assert header[1:3] == (3, 40) and header[5] == 52 and header[9:11] == (32, 9)
    phdr = [list(struct.unpack_from('<8I', image, 52 + i * 32)) for i in range(9)]
    unwind, rx, rw = phdr[0], phdr[3], phdr[4]
    assert unwind[0] == 0x70000001 and unwind[1] == unwind[2] == 0x431bdc
    assert rw[0] == 1 and rw[6] == 6 and rw[2] + rw[5] == 0x4a2ebc
    assert rx[:6] == [1, 0, 0, 0, 0x450a58, 0x450a58] and rx[6:] == [5, 4096]
    assert [entry[0] for entry in phdr].count(1) == 2
    assert SMS_ACK_BSS_VA >= rw[2] + rw[5] and SMS_ACK_BSS_VA + SMS_ACK_BSS_SIZE < SMS_ACK_CODE_VA
    assert len(SMS_ACK_CODE) < 16384 and SMS_ACK_BSS_SIZE < 65536

    # Preserve targets, compact personalities and external unwind descriptors.
    entries = []
    for table, address in ((image[unwind[1]:unwind[1]+unwind[4]], unwind[2]),
                           (SMS_ACK_EXIDX, SMS_ACK_EXIDX_VA)):
        assert len(table) % 8 == 0
        for offset in range(0, len(table), 8):
            first, second = struct.unpack_from('<II', table, offset)
            target = _prel31(first, address + offset)
            descriptor = second if second == 1 or second & 0x80000000 else _prel31(second, address + offset + 4)
            entries.append((target, second == 1 or bool(second & 0x80000000), descriptor))
    assert all(a[0] < b[0] for a, b in zip(entries, entries[1:])), 'Unexpected unwind ordering'
    payload = bytearray(SMS_ACK_CODE)
    payload.extend(b'\0' * (-len(payload) % 4))
    table_offset, table_va = len(payload), SMS_ACK_CODE_VA + len(payload)
    for index, (target, compact, descriptor) in enumerate(entries):
        place = table_va + index * 8
        payload.extend(struct.pack('<II', _relative31(target, place),
                                   descriptor if compact else _relative31(descriptor, place + 4)))
    # The original RX mapping has identical file/virtual offsets. Preserve
    # that relationship for the appended bytes; a separately placed segment
    # cannot be represented by the loader's single text relocation bias.
    file_offset = SMS_ACK_CODE_VA
    assert len(image) <= file_offset and (SMS_ACK_BSS_VA + SMS_ACK_BSS_SIZE + 4095) & ~4095 <= file_offset
    changed = bytearray(image)
    changed.extend(b'\0' * (file_offset - len(changed)))
    changed.extend(payload)
    rw[5] = SMS_ACK_BSS_VA + SMS_ACK_BSS_SIZE - rw[2]
    rx[4] = rx[5] = len(changed)
    unwind[1:6] = [file_offset + table_offset, table_va, table_va, len(entries)*8, len(entries)*8]
    allowed = []
    for index in (0, 3, 4):
        start = 52 + index*32
        changed[start:start+32] = struct.pack('<8I', *phdr[index])
        allowed.append((start, start+32))
    # Keep the existing section description consistent with PT_ARM_EXIDX.
    shoff, size, count = header[6], header[11], header[12]
    assert size == 40
    found = 0
    for index in range(count):
        start = shoff + index*40
        section = list(struct.unpack_from('<10I', image, start))
        if section[1] == 0x70000001:
            section[3:6] = [table_va, file_offset + table_offset, len(entries)*8]
            changed[start:start+40] = struct.pack('<10I', *section)
            allowed.append((start, start+40))
            found += 1
    assert found == 1
    hooks = ((0x2eeff2, b'\x29\xf7\x51\xf8', SMS_ACK_RX),
             (0x2ee3c6, b'\xc7\xf6\xc5\xfc', SMS_ACK_TELECOM_TX if telecom_mo_ack else SMS_ACK_TX))
    if telecom_mo_ack:
        hooks = hooks + ((0xdaae2, b'\xff\xf7\x4b\xff', SMS_ACK_MO_POP),
                         (0xdab44, b'\x44\xf0\x8c\xf8', SMS_ACK_MO_SEND))
    for start, before, target in hooks:
        assert image[start:start+4] == before
        changed[start:start+4] = thumb_bl(start, target)
        allowed.append((start, start+4))
    previous = 0
    for start, end in sorted(allowed):
        assert changed[previous:start] == image[previous:start]
        previous = end
    assert changed[previous:len(image)] == image[previous:]
    result = bytes(changed)
    record = {'function': ('SmsManagerImpl raw 3GPP MT correlation + Telecom MO 2xx RP-ACK completion'
                           if telecom_mo_ack else 'SmsManagerImpl raw 3GPP MT report correlation'),
              'receive_file_offset': 0x2eeff2, 'send_file_offset': 0x2ee3c6,
              'code_sha256': hashlib.sha256(SMS_ACK_CODE).hexdigest(),
              'image_sha256': hashlib.sha256(result).hexdigest(),
              'validation': 'hash_pinned_sms_correlation_hardware_scope_recorded_separately'}
    if telecom_mo_ack:
        record.update(telecom_mo_ack=True, mo_pop_file_offset=0xdaae2, mo_send_file_offset=0xdab44)
    return result, list(patches) + [record]


def audio_tap_binary(image, patches=()):
    """Add an opt-in PCM capture ring buffer to a verified SMS-enabled IMS image."""
    assert image[:7] == b'\x7fELF\x01\x01\x01'
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', image)
    assert header[1:3] == (3, 40) and header[5] == 52 and header[9:11] == (32, 9)
    phdr = [list(struct.unpack_from('<8I', image, 52 + i * 32)) for i in range(9)]
    unwind, rx, rw = phdr[0], phdr[3], phdr[4]
    assert unwind[0] == 0x70000001 and unwind[1] == unwind[2] >= SMS_ACK_CODE_VA
    assert rw[0] == 1 and rw[6] == 6 and rw[2] + rw[5] == SMS_ACK_BSS_VA + SMS_ACK_BSS_SIZE
    assert rx[:4] == [1, 0, 0, 0] and rx[4] == rx[5] == len(image) and rx[6:] == [5, 4096]
    assert [entry[0] for entry in phdr].count(1) == 2
    assert AUDIO_TAP_BSS_VA >= rw[2] + rw[5]
    assert (AUDIO_TAP_BSS_VA + AUDIO_TAP_BSS_SIZE + 4095) & ~4095 <= SMS_ACK_CODE_VA
    assert len(image) <= AUDIO_TAP_CODE_VA and len(AUDIO_TAP_CODE) < 8192

    entries = []
    for table, address in ((image[unwind[1]:unwind[1] + unwind[4]], unwind[2]),
                           (AUDIO_TAP_EXIDX, AUDIO_TAP_EXIDX_VA)):
        assert len(table) % 8 == 0
        for offset in range(0, len(table), 8):
            first, second = struct.unpack_from('<II', table, offset)
            target = _prel31(first, address + offset)
            descriptor = second if second == 1 or second & 0x80000000 else _prel31(second, address + offset + 4)
            entries.append((target, second == 1 or bool(second & 0x80000000), descriptor))
    assert all(a[0] < b[0] for a, b in zip(entries, entries[1:])), 'Unexpected unwind ordering'
    payload = bytearray(AUDIO_TAP_CODE)
    payload.extend(b'\0' * (-len(payload) % 4))
    table_offset, table_va = len(payload), AUDIO_TAP_CODE_VA + len(payload)
    for index, (target, compact, descriptor) in enumerate(entries):
        place = table_va + index * 8
        payload.extend(struct.pack('<II', _relative31(target, place),
                                   descriptor if compact else _relative31(descriptor, place + 4)))

    file_offset = AUDIO_TAP_CODE_VA
    changed = bytearray(image)
    changed.extend(b'\0' * (file_offset - len(changed)))
    changed.extend(payload)
    rw[5] = AUDIO_TAP_BSS_VA + AUDIO_TAP_BSS_SIZE - rw[2]
    rx[4] = rx[5] = len(changed)
    unwind[1:6] = [file_offset + table_offset, table_va, table_va, len(entries) * 8, len(entries) * 8]
    allowed = []
    for index in (0, 3, 4):
        start = 52 + index * 32
        changed[start:start + 32] = struct.pack('<8I', *phdr[index])
        allowed.append((start, start + 32))
    shoff, size, count = header[6], header[11], header[12]
    assert size == 40
    found = 0
    for index in range(count):
        start = shoff + index * 40
        section = list(struct.unpack_from('<10I', image, start))
        if section[1] == 0x70000001:
            section[3:6] = [table_va, file_offset + table_offset, len(entries) * 8]
            changed[start:start + 40] = struct.pack('<10I', *section)
            allowed.append((start, start + 40))
            found += 1
    assert found == 1
    hooks = (
        (0x7f7d8, b'\xdc\xf7\x76\xe8', AUDIO_TAP_MIC_PARAMS),
        (0x7fa92, b'\xdb\xf7\x1a\xef', AUDIO_TAP_SPK_PARAMS),
        (0x7fdac, b'\xdc\xf7\x7c\xed', AUDIO_TAP_WRITE),
        (0x8078a, b'\xda\xf7\x4e\xec', AUDIO_TAP_READ),
    )
    for start, before, target in hooks:
        assert image[start:start + 4] == before
        changed[start:start + 4] = thumb_bl(start, target)
        allowed.append((start, start + 4))
    previous = 0
    for start, end in sorted(allowed):
        assert changed[previous:start] == image[previous:start]
        previous = end
    assert changed[previous:len(image)] == image[previous:]
    result = bytes(changed)
    record = {
        'function': 'ImsAudioImpl passive PCM ring buffer',
        'mic_params_offset': 0x7f7d8,
        'spk_params_offset': 0x7fa92,
        'write_offset': 0x7fdac,
        'read_offset': 0x8078a,
        'code_sha256': hashlib.sha256(AUDIO_TAP_CODE).hexdigest(),
        'image_sha256': hashlib.sha256(result).hexdigest(),
    }
    return result, list(patches) + [record]


def temporary_binary(original, normal_voice=False, sms_ack=False, telecom_mo_ack=False, audio_tap=False):
    """Require callers to select optional shims explicitly."""
    assert type(sms_ack) is bool and type(telecom_mo_ack) is bool and type(audio_tap) is bool, 'Candidate opt-in must be explicit'
    assert not telecom_mo_ack or sms_ack, 'Telecom MO ACK requires SMS shim'
    assert not audio_tap or sms_ack, 'Audio tap requires SMS-enabled runtime layout'
    changed, patches = _voice_binary(original, normal_voice)
    if not sms_ack:
        return changed, patches
    changed, patches = (sms_ack_binary(changed, patches, telecom_mo_ack=True)
                        if telecom_mo_ack else sms_ack_binary(changed, patches))
    return audio_tap_binary(changed, patches) if audio_tap else (changed, patches)


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


def mobile_binary(original, normal_voice=False, sms_ack=False):
    """Accepted Q20/Passport Mobile fix; only the temporary copy is changed."""
    assert normal_voice is True
    assert type(sms_ack) is bool, 'SMS candidate opt-in must be explicit'
    changed, patches = _voice_binary(original, normal_voice)
    offset = 0xb8eb0
    assert changed[offset:offset + 4] == b'\x02\x21\x78\x44'
    result = bytearray(changed)
    result[offset] = 0
    result = bytes(result)
    assert result[:offset] == changed[:offset] and result[offset + 1:] == changed[offset + 1:]
    assert hashlib.sha256(result).hexdigest() == '647290caee0da86479ef7da7c42e68f98cd283fead8e9406f1c530a4a99c0494'
    patches.append({'file_offset': offset, 'bytes_before': '0221', 'bytes_after': '0021',
                    'config_key': 'MediaDialog.EarlySdp', 'purpose': 'Reliable 180 without repeated SDP'})
    return sms_ack_binary(result, patches) if sms_ack else (result, patches)


def mt_voice_binary(original, normal_voice=False, sms_ack=False, telecom_mo_ack=False, audio_tap=False):
    """Cross-carrier MT call signaling fix; only the temporary copy is changed.

    Suppresses repeated or unreliable preview SDP in 180 Ringing
    (MediaDialog.EarlySdp=0) while keeping MediaDialog.Omit200OkSdp=1:
    - Precondition MT calls answered in reliable 183 Session Progress stay in
      SDPState 0xb (or 0xd) and omit illegal duplicate SDP in 200 OK (INVITE)
      per RFC 3262 / RFC 3311 / RFC 6337 (preventing silent-audio regressions).
    - Non-precondition MT calls without reliable 18x SDP have last_18x_present=0
      and early_update_200_ok=0, so 0x1a9040..0x1a9060 still attaches the
      mandatory RFC 3261 SDP answer in 200 OK (INVITE).
    """
    assert normal_voice is True
    assert type(sms_ack) is bool and type(telecom_mo_ack) is bool and type(audio_tap) is bool, 'Candidate opt-in must be explicit'
    assert not telecom_mo_ack or sms_ack, 'Telecom MO ACK requires SMS shim'
    assert not audio_tap or sms_ack, 'Audio tap requires SMS-enabled runtime layout'
    changed, patches = _voice_binary(original, normal_voice)
    omit_offset = 0xb8e9c
    early_offset = 0xb8eb0
    assert changed[omit_offset:omit_offset + 4] == b'\x01\x21\x78\x44'
    assert changed[early_offset:early_offset + 4] == b'\x02\x21\x78\x44'
    result = bytearray(changed)
    result[early_offset] = 0
    result = bytes(result)
    assert result[:early_offset] == changed[:early_offset] and result[early_offset + 1:] == changed[early_offset + 1:]
    assert result[omit_offset:omit_offset + 4] == b'\x01\x21\x78\x44'
    assert hashlib.sha256(result).hexdigest() == '647290caee0da86479ef7da7c42e68f98cd283fead8e9406f1c530a4a99c0494'
    patches.append({'file_offset': early_offset, 'bytes_before': '0221', 'bytes_after': '0021',
                    'config_key': 'MediaDialog.EarlySdp',
                    'purpose': 'Suppress repeated or unreliable preview SDP in 180 Ringing while preserving Omit200OkSdp=1'})
    if not sms_ack:
        return result, patches
    result, patches = (sms_ack_binary(result, patches, telecom_mo_ack=True)
                       if telecom_mo_ack else sms_ack_binary(result, patches))
    return audio_tap_binary(result, patches) if audio_tap else (result, patches)


# BEGIN GENERATED SMS ACK SHIM
SMS_ACK_CODE_VA = 0x500000
SMS_ACK_BSS_VA = 0x4a3000
SMS_ACK_BSS_SIZE = 50328
SMS_ACK_EXIDX_VA = 0x50144c
SMS_ACK_RX = 0x500002
SMS_ACK_TX = 0x500014
SMS_ACK_TELECOM_TX = 0x50002c
SMS_ACK_MO_POP = 0x500050
SMS_ACK_MO_SEND = 0x500060
SMS_ACK_CODE = bytes.fromhex(
    '704710b504460146284600f02ee804f1200010bd70b505460e4601f0cce92346284651464a4600f0ccec70bd70b50546'
    '0e4601f0c0e92346284651464a4600f0c0ec2346284651464a4600f07cee70bd10b582b0049c009400f084ef02b010bd'
    '10b501f08ee810bd000050e31eff2f01f04f2de94ddf4de201db4de20140a0e12090b4e5000059e31500000a0050a0e1'
    '04059fe5086081e200159fe500008fe00170c0e34d010de3c60f4fe301108fe000b087e00600a0e13bff2fe1000050e3'
    '0700000a081090e5010051e30400001a040090e5000050e300009015000050130300001a4ddf8de201db8de2f04fbde8'
    '1eff2fe10010a0e30120d0e7000052e30300000a011081e2020c51e3f9ffff1af3ffffea180051e3f1ffff3a020c51e3'
    'efffff0a78c49fe50010a0e30cc08fe0013050e7412043e21a0052e301205ce720308333020053e1e5ffff1a011041e2'
    '180071e3f5ffff1a1800d0e51f0050e3040000ca000050e30500000a090050e30300000adaffffea3b0050e320005013'
    'd7ffff1a950a0fe3cf0f4fe3001087e00400a0e131ff2fe1020050e3d0ffff3a0040a0e10000d9e5010050e3ccffff1a'
    'f0a39fe5ff0054e30aa08fe004809ae50800009a04008ae25bf07ff59f1f90e1011081e2912f80e1000052e3faffff1a'
    '5bf07ff5beffffea7c050be301eb8de2b50f4fe34b1f8ee2002087e00200a0e332ff2fe1000050e3edffff1a001a0ce3'
    '30059de59a1b43e3010050e1e8ffff2a2c059de50c808de50080a0e32c82cde510008de50600a0e12c80cde568139fe5'
    '01108fe03bff2fe114708de2000050e3182087e20500000a081090e5010051e30200001a040090e5000050e300809015'
    '0200a0e10810a0e108208de5cc0000eb000050e32200000a20139fe50600a0e1868f87e201108fe03bff2fe10010a0e3'
    '000050e30500000a082090e5010052e30200001a040090e5000050e3001090150800a0e1e10000eb000050e31000000a'
    '0110a0e35bf07ff59f0f9ae1912f8ae1000052e3fbffff1a000050e35bf07ff52a00000a04008ae25bf07ff59f1f90e1'
    '011081e2912f80e1000052e3faffff1ab2ffffea0110a0e35bf07ff59f0f9ae1912f8ae1000052e3fbffff1a000050e3'
    '5bf07ff50700000a04008ae25bf07ff59f1f90e1011081e2912f80e1000052e3faffff1aa1ffffea18009ae50110a0e3'
    '182500e3010080e218008ae50000a0e300308ae0207093e5050057e10300001a0160d9e5247093e5060057e12c108305'
    '020080e0a30c50e3f4ffff1a5a0000ea04009ae50c109de5000051e15600001a0010a0e318c500e30000a0e301b08ae0'
    '0030a0e10b00a0e12020b0e5000052e31100000a34709be504609ae5060057e10d00001a28709be510609de507e056e0'
    '0900003ab4005ee30700002a050052e10b00001a0120d9e524009be5020050e10300a0e10200001a3f0000ea000053e3'
    '0300a0110c1081e0a30c51e3e2ffff1a010000ea0300a0e1f9ffffea000050e32d00000a005080e50c209de50110d9e5'
    '08709de5142080e50020a0e310309de50a0080e9181080e2104080e50c2080e50230d7e7000053e30300000a012082e2'
    '020c52e3f9ffff1a022ca0e308709de5012082e20130d7e4012052e20130c1e4fbffff1a861f80e20020a0e30230d8e7'
    '000053e30300000a012082e2020c52e3f9ffff1a022ca0e3012082e20130d8e4012052e20130c1e4fbffff1a181400e3'
    '010080e00110d9e4014054e20110c0e4fbffff1a08008ae2000000ea1c008ae2001090e5011081e2001080e50000a0e3'
    '5bf07ff500008ae5f1feffea2c009be5000050e30500000a0100a0e32c008be510009ae5010080e210008ae5f2ffffea'
    '08109de538008be2f30000eb000050e3f4ffff0a8e0f8be20810a0e1ee0000eb000050e3efffff0a30009be5040050e1'
    'ecffff1a380400e300008be0000054e3e1ffff0a0110d9e4014044e20120d0e4010052e1f8ffff0ae2ffffea5dffffff'
    '46130000a5120000402efaffaa11000070110000000051e30600000a0030a0e3032051e7000052e30400000a013043e2'
    '020c73e3f9ffff1a00c0a0e3190000ea10402de9ff2d0fe300e063e2ff2f47e300c0a0e302001ee11100000a0020a0e3'
    '0240d1e72c0054e30d00000a7f4044e25e0074e30a00003a012082e202005ee1f6ffff1a0020a0e3024051e7020053e1'
    '024040e7014042e20420a0e1f9ffff1a01c0a0e31040bde80c00a0e11eff2fe1000051e32000000a0030a0e30320d1e7'
    '000052e30300000a013083e2020c53e3f9ffff1a180000eaff2d0fe3ff2f47e3020013e11400000af0472de90020a0e3'
    '0270d1e70a0057e31200000a0d0057e32c0057130f00000a012082e2020053e1f6ffff1a0020a0e30270d1e7200057e3'
    '090057130a00001a012082e2020053e1f8ffff1a0320a0e1280000ea00c0a0e30c00a0e11eff2fe100c0a0e3f047bde8'
    'faffffea020053e12000009a0260d1e701e082e20170a0e33c0056e30c00000a0270e0e1037087e0000057e31700000a'
    '0e60d1e7017047e201e08ee23c0056e3f8ffff1a01204ee20070a0e3030052e101700033000057e30b00000a03005ee1'
    '0e40a0e15d00002a0e40a0e100c0a0e30420d1e73e0052e35800000a014084e2040053e1f9ffff1adbffffea0e20a0e1'
    '020053e10800009a017041e20360d7e7200056e3090056130300001a013043e2020053e1f8ffff8a0230a0e102e043e0'
    '00c0a0e3024c4ee27f0f74e3caffff9a48619fe5021081e00070a0e306608fe0040057e31c00000a0750d6e70740d1e7'
    '017087e2050054e1f8ffff0a20619fe50070a0e306608fe0040057e31200000a0750d6e70740d1e7017087e2050054e1'
    'f8ffff0a00c0a0e306005ee3b2ffff3af0509fe50040a0e305508fe0050054e30500000a0460d5e70470d1e7014084e2'
    '060057e1f8ffff0aa7ffffea030052e11200002a019400e321a0e0e30180a0e3009441e30170a0e10e50a0e100c0a0e3'
    '0160d7e47f4046e27440efe6a20054e399ffff3a7660eae61c0056e30100008a180619e194ffff1a015055e2f3ffff1a'
    '00005ee30500000a032042e00030a0e10170d1e4012092e20170c3e4fbffff3a0010a0e301c0a0e30e10c0e786ffffea'
    '00c0a0e3030054e183ffff0a012084e2030052e10600002a0250d1e7200055e3090055137cffff1a012082e2020053e1'
    'f8ffff1a0e20a0e10430a0e1a6ffffea330c0000d80b0000fc0b000010402de9000050e30600000a0030a0e30320d0e7'
    '000052e30500000a013083e2020c53e3f9ffff1a00e0a0e30e00a0e11080bde8a324b0e100e0a0e3faffff1a02cca0e3'
    '000051e30800000a0020a0e30240d1e7000054e30300000a012082e2020c52e3f9ffff1a000000ea02c0a0e103005ce1'
    'ecffff1a0020a0e3020053e10500000a02c0d1e70240d0e7012082e20c0054e1f8ffff0ae2ffffea01e0a0e3e1ffffea'
    'f04f2de9a1df4de201db4de200a0a0e1010c42e2fe0070e30400003a000051e30170a0e10360a011000053130200001a'
    'a1df8de201db8de2f08fbde80000d7e5040050e302005013f8ffff1a1c039fe580808de20810a0e100008fe00190c0e3'
    '7c050be3b50f4fe3002089e00200a0e332ff2fe1000050e3ecffff1a001a0ce384009de59a1b43e3010050e1e7ffff2a'
    'e90508e380b09de5d4129fe5d10f4fe3002089e00a00a0e101108fe032ff2fe1000050e3ddffff1a5bf07ff50110a0e3'
    'b0529fe505508fe09f0f95e1912f85e1000052e3fbffff1a000050e35bf07ff5d2ffff1a04c095e50010a0e3182500e3'
    '010085e0203090e5060053e10c00001a0140d7e5243090e5040053e10800001a343090e5044095e5040053e10400001a'
    '283090e503305be00100003ab30053e30900009a021081e0a30c51e3ebffff1a140095e5010080e2140085e50000a0e3'
    '5bf07ff5000085e5b4ffffea2c1090e5000051e3f5ffff1a8e1f80e2387080e2382080e20030a0e30160d7e4000056e3'
    '0300000a013083e2020c53e3f9ffff1a023ca0e301eb8de2013083e20070a0e384608ee20140d2e40740c6e7017087e2'
    '070053e1faffff1a8e0f80e20020a0e30130d1e4000053e30300000a012082e2020c52e3f9ffff1a022ca0e3011082e2'
    '0020a0e3a13f8de20170d0e40270c3e7012082e2020051e1faffff1a0000a0e35bf07ff5000085e5040095e500005ce1'
    '86ffff1a950a0ee3a16f8de2d30f4fe304708de2002089e00700a0e10610a0e10c40a0e132ff2fe197050ce3d30f4fe3'
    '001089e00700a0e131ff2fe1000050e33e00000a040095e5000054e13b00001a550d05e304108de2cb0f4fe3002089e0'
    '0a00a0e132ff2fe10000a0e30010d6e7000051e30600000a010080e2020c50e3f9ffff1a3c00a0e38000cde5020ca0e3'
    '030000ea3c10a0e3000050e38010cde52c00000a011088e20020a0e30230d6e70230c1e7012082e2020050e1faffff1a'
    '080080e03e10a0e3b110c0e1810e08e3d10f4fe30820a0e18c109fe5004089e00a00a0e101108fe034ff2fe17c109fe5'
    '01eb8de284208ee20a00a0e101108fe034ff2fe10110a0e35bf07ff59f0f95e1912f85e1000052e3fbffff1a000050e3'
    '5bf07ff50500001a0c0095e5010080e20c0085e50000a0e35bf07ff5000085e5410106e3b60f4fe3001089e004008de2'
    '31ff2fe131ffffea0000a0e3d7ffffeae1f5ffffb00900007425faff6d0700004c070000f04f2de983df4de20050a0e1'
    '010c42e2fe0070e30300003a000051e30190a0e1000053130100001a83df8de2f08fbde80000d9e5000050e3faffff1a'
    'd0019fe5811f8de200008fe00140c0e37c050be3b50f4fe3002084e00200a0e332ff2fe1000050e3efffff1a001a0ce3'
    '08029de59a1b43e3010050e1eaffff2a0060a0e34d010de30460cde5c60f4fe3002084e0080085e204829de578119fe5'
    '01108fe032ff2fe1000050e30500000a081090e5010051e30200001a040090e5000050e30060901504008de20610a0e1'
    'e7fdffeb000050e3d3ffff0a5bf07ff50110a0e334a19fe50aa08fe09f0f9ae1912f8ae1000052e3fbffff1a000050e3'
    '5bf07ff5c8ffff1a0070a0e304508de200b0a0e307608ae00600a0e11840b0e5000054e30b00000a081090e5011058e0'
    '0800003ab40051e30600002a240086e20510a0e1a4feffeb000050e30b00a0e10300000a1b0000ea00005be30b00a011'
    '00b0a0e1837f87e2830d57e3e8ffff1a000050e31f00000a0110a0e3001080e50110d9e5020180e90c0080e20010a0e3'
    '0120d5e7000052e30300000a011081e2020c51e3f9ffff1a021ca0e3011081e20120d5e4011051e20120c0e4fbffff1a'
    '04008ae20c0000ea010054e30300001a0110d9e51c0096e5010050e10900000a0200a0e3180086e510009ae5010080e2'
    '10008ae5030000ea14008ae2001090e5011081e2001080e50000a0e35bf07ff500008ae584ffffea71f2ffff0a060000'
    'f0c4fafff04f2de985df4de200b0a0e138029de50160a0e100008de5f4019fe500008fe00140c0e37d090ae3bd0f4fe3'
    '007084e00b00a0e137ff2fe1000056e300a0a0e100005b130200001a0a00a0e185df8de2f08fbde8fe005ae3faffff8a'
    '7c050be3831f8de2b50f4fe3002084e00200a0e332ff2fe1000050e3f2ffff1a001a0ce310029de59a1b43e3010050e1'
    'edffff2a001096e50000a0e30c00cde50c008de20c829de569fdffeb000050e3e5ffff0a5bf07ff50110a0e358719fe5'
    '07708fe09f0f97e1912f87e1000052e3fbffff1a000050e35bf07ff5daffff1a0040a0e30c908de2046087e0185096e5'
    '000055e30900000a200096e5000058e00600003ab30050e30400008a240086e20910a0e128feffeb000050e30300001a'
    '834f84e2830d54e3eeffff1a350000ea0000a0e3010055e32d00001ad81002e30820a0e3015087e01c1096e5180086e5'
    '0030a0e10500a0e1006095e50040a0e3105095e5050058e1055048e001400023b40055e30050a0e301500033000056e3'
    '055004e001600013056006e0010056e30500001a045090e50b0055e10200001a085090e50a0055e10800000a000053e3'
    '145080e20300a011000056e30300a011012052e2e1ffff1a000050e30a00000a0120a0e308a080e5040880e80c1080e5'
    '108080e5080097e5010080e2080087e5040000ea180086e5020000ea140097e5010080e2140087e50000a0e35bf07ff5'
    '000087e58cffffea79f0fffff8c2fafff04f2de96cd04de20050a0e118029fe50160a0e100008fe00140c0e3610c0ee3'
    'c10f4fe300a084e00500a0e13aff2fe1000055e30090a0e1000056130200001a0900a0e16cd08de2f08fbde87c050be3'
    '01b056e5b50f4fe328108de2002084e00200a0e3147016e532ff2fe1000050e3f2ffff1a001a0ce32c009de59a1b43e3'
    '010050e1edffff2a28009de55bf07ff598619fe50120a0e306608fe09f1f96e1923f86e1000053e3fbffff1a000051e3'
    '5bf07ff5e1ffff1a0010a0e3d82002e3dce002e3018086e00830a0e102c0b3e700005ce30b00000a103093e5033050e0'
    '0800003ab30053e30600008a0e3098e7070053e10300001ae03002e3033098e70b0053e10600000a141081e2a00051e3'
    'ebffff1a0000a0e35bf07ff5000086e5c6ffffead81002e30000a0e30100a8e7000059e328308de20c1098e55bf07ff5'
    '000086e5bdffff1a0020a0e30200c3e7012082e2400052e3fbffff1a2710cde50010a0e30200a0e326208de268108de5'
    '0310a0e32610cde568108de244e001e325808de220108de5421001e305008de90170a0e32500cde50c008de2413001e3'
    '04c0a0e3824180e8850009e3c30f4fe34010a0e300308de5007084e028008de20320a0e3153001e31cc08de537ff2fe1'
    '0020a0e1010040e23f0050e397ffff8a28108de20500a0e10030a0e33aff2fe1000050e391ffff1a0110a0e35bf07ff5'
    '9f0f96e1912f86e1000052e3fbffff1a000050e35bf07ff588ffff1a0c0096e5010080e20c0086e5b9ffffea65eeffff'
    '00c1faff14209fe5553d05e3cb3f4fe302208fe00120c2e3032082e012ff2fe139ecffff74656c3a006170706c696361'
    '74696f6e2f766e642e336770702e736d730043616c6c2d494400436f6e74656e742d54797065007369703a00502d4173'
    '7365727465642d4964656e7469747900496e2d5265706c792d546f00736970733a000000ccb20181b0b0af0100000000'
    'a0b20181b0b0af0200000000'
)
SMS_ACK_EXIDX = bytes.fromhex(
    'b4ebff7f01000000aeebff7fb0b0a880b8ebff7fb0b0aa80ecebff7fb0a80180f4ebff7fb0b0a880f4ebff7fbcffff7f'
    '38f1ff7fb0b0a880ccf1ff7fb0b0ae8090f4ff7fb0b0a8802cf5ff7fa8ffff7fa8f8ff7faf02b280c0faff7faf04b280'
    'd4fcff7fb0af1a8000ffff7fb0b0b08018ffff7f01000000'
)
# END GENERATED SMS ACK SHIM


# BEGIN GENERATED AUDIO TAP SHIM
AUDIO_TAP_CODE_VA = 0x530000
AUDIO_TAP_BSS_VA = 0x4b0000
AUDIO_TAP_BSS_SIZE = 131152
AUDIO_TAP_EXIDX_VA = 0x53035c
AUDIO_TAP_MIC_PARAMS = 0x530022
AUDIO_TAP_SPK_PARAMS = 0x53002a
AUDIO_TAP_READ = 0x530032
AUDIO_TAP_WRITE = 0x53003a
AUDIO_TAP_CODE = bytes.fromhex(
    '42423130415441500100000000004b0000000100100000003000010000000000704710b500f00ee810bd10b500f078e8'
    '10bd10b500f0a2e810bd10b500f052e910bdd4d430482de90140a0e140109fe5a8280be301108fe0b22f4fe30110c1e3'
    '022081e00410a0e132ff2fe10050a0e1000050e30400001a18009fe50410a0e100008fe0100080e2030000eb0500a0e1'
    '3088bde8c5ffffff78fff7ff000051e31eff2f0110402de91ce081e242c204e30c409ee831c043e358109fe501109fe7'
    '0c0051e10a00000a4c109fe50140a0e301108fe0084081e50148a0e30c4081e5414405e3414045e3044081e55bf07ff5'
    '00c081e5102080e5083080e50ce080e55bf07ff5141090e5011081e2141080e51040bde81eff2fe13cfff7ff28fff7ff'
    '30482de90140a0e144109fe5a8280be301108fe0b22f4fe30110c1e3022081e00410a0e132ff2fe10050a0e1000050e3'
    '0500001a1c009fe50410a0e100008fe0300080e2010880e2cbffffeb0500a0e13088bde8e9feffff9cfef7ff70402de9'
    '0150a0e15c109fe50240a0e108200be301108fe0b22f4fe30110c1e3023081e00510a0e10420a0e133ff2fe10060a0e1'
    '000055e30900000a010056e3070000ba24009fe5040056e10640a0310510a0e100008fe00420a0e1100080e2030000eb'
    '0600a0e17080bde889feffff28fef7ff000052e31eff2f01f0412de9d8709fe5423204e3010a52e3313043e3012aa023'
    '07709fe7030057e10a00000abc709fe50160a0e307708fe0086087e50168a0e30c6087e5416405e3416045e3046087e5'
    '5bf07ff5003087e5003090e50160a0e101c083e200c080e55bf07ff504e090e57e30ffe67e50f0e6018863e20230a0e1'
    '020058e1205085e20830a0310370a0e10140d6e4017057e20140c5e4fbffff1a080052e10600009a034042e0031081e0'
    '203080e20150d1e4014054e20150c3e4fbffff1a02108ee05bf07ff5041080e5181090e5011081e2181080e55bf07ff5'
    '1cc080e5f041bde81eff2fe1e8fdf7ffd4fdf7ff70402de90150a0e160109fe50240a0e188280ce301108fe0b22f4fe3'
    '0110c1e3023081e00510a0e10420a0e133ff2fe10060a0e1000055e30a00000a010056e3080000ba28009fe5040056e1'
    '0640a0310510a0e100008fe00420a0e1300080e2010880e2a8ffffeb0600a0e17080bde821fdffffc0fcf7ff'
)
AUDIO_TAP_EXIDX = bytes.fromhex(
    'c4fcff7f01000000befcff7fb0b0a880d8fcff7fb083848028fdff7fb0b0a880a4fdff7fb0838480f8fdff7fb0b0aa80'
    '64feff7fb0b0ac8050ffff7fb0b0aa80c0ffff7f01000000'
)
# END GENERATED AUDIO TAP SHIM
