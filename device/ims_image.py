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


def sms_ack_binary(image, patches=()):
    """Add a bounded correlation shim only to a known temporary IMS image.

    Keep the two original LOAD headers, QNX/GNU notes and dynamic imports.
    QNX's runtime linker selects one text and one data relocation bias: adding
    another RX header replaces the text bias and crashes before program entry.
    Extend the original RX mapping, then retain the original RW overlay and
    its zero-filled tail. New code/unwind data sit beyond the RW mapping.
    """
    digest = hashlib.sha256(image).hexdigest()
    assert digest in (STOCK_SHA,
        'f388a23900d13d92c0390c662fc53e2de6d628bba2174973c0320416022a4438',
        '9d651395c0ecf54d6c7d230c206d5f8204da4e69e6279cf661e4f3825a7c322b',
        '647290caee0da86479ef7da7c42e68f98cd283fead8e9406f1c530a4a99c0494'), 'Unknown IMS patch input'
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
             (0x2ee3c6, b'\xc7\xf6\xc5\xfc', SMS_ACK_TX))
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
    record = {'function': 'SmsManagerImpl raw 3GPP MT report correlation',
              'receive_file_offset': 0x2eeff2, 'send_file_offset': 0x2ee3c6,
              'code_sha256': hashlib.sha256(SMS_ACK_CODE).hexdigest(),
              'image_sha256': hashlib.sha256(result).hexdigest(),
              'validation': 'candidate_pending_device_sms_acceptance'}
    return result, list(patches) + [record]


def temporary_binary(original, normal_voice=False, sms_ack=False):
    """Keep the accepted voice image unless a maintainer opts into the shim.

    The native SMS candidate has no QNX loader or carrier acceptance yet.
    Normal service startup must not silently replace every accepted IMS image.
    """
    assert type(sms_ack) is bool, 'SMS candidate opt-in must be explicit'
    changed, patches = _voice_binary(original, normal_voice)
    return sms_ack_binary(changed, patches) if sms_ack else (changed, patches)


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


# BEGIN GENERATED SMS ACK SHIM
SMS_ACK_CODE_VA = 0x500000
SMS_ACK_BSS_VA = 0x4a3000
SMS_ACK_BSS_SIZE = 41760
SMS_ACK_EXIDX_VA = 0x500d7c
SMS_ACK_RX = 0x500002
SMS_ACK_TX = 0x500014
SMS_ACK_CODE = bytes.fromhex(
    '704710b504460146284600f010e804f1200010bd70b505460e4600f064ee2346284651464a4600f09cec70bd000050e3'
    '1eff2f01f04f2de94ddf4de201db4de20140a0e12090b4e5000059e31500000a0050a0e17c059fe5086081e278159fe5'
    '00008fe00170c0e34d010de3c60f4fe301108fe0008087e00600a0e138ff2fe1000050e30700000a081090e5010051e3'
    '0400001a040090e5000050e300009015000050130300001a4ddf8de201db8de2f04fbde81eff2fe10010a0e30120d0e7'
    '000052e30300000a011081e2020c51e3f9ffff1af3ffffea180051e3f1ffff3a020c51e3efffff0af0c49fe50010a0e3'
    '0cc08fe0013050e7412043e21a0052e301205ce720308333020053e1e5ffff1a011041e2180071e3f5ffff1a1800d0e5'
    '1f0050e3040000ca000050e30500000a090050e30300000adaffffea3b0050e320005013d7ffff1a950a0fe3cf0f4fe3'
    '001087e00400a0e131ff2fe1020050e3d0ffff3a00a0a0e10000d9e5010050e3ccffff1a68449fe5ff005ae304408fe0'
    '04b094e50800009a040084e25bf07ff59f1f90e1011081e2912f80e1000052e3faffff1a5bf07ff5beffffea7c050be3'
    '01eb8de2b50f4fe34b1f8ee2002087e00200a0e332ff2fe1000050e3edffff1a001a0ce330059de59a1b43e3010050e1'
    'e8ffff2a0000a0e32c02cde52c00cde52c059de510008de50600a0e1e4139fe501108fe038ff2fe1000050e30700000a'
    '081090e5010051e30400001a040090e5000050e300009015000050132500001a0110a0e35bf07ff59f0f94e1912f84e1'
    '000052e3fbffff1a000050e35bf07ff50700000a040084e25bf07ff59f1f90e1011081e2912f80e1000052e3faffff1a'
    'cbffffea180094e50110a0e3182500e3010080e2180084e50000a0e3003084e0207093e5050057e10300001a0160d9e5'
    '247093e5060057e12c108305020080e0a30c50e3f4ffff1a0000a0e35bf07ff5000084e577ffffea14108de2182081e2'
    '861f81e208108de50010a0e30c208de5012050e7000052e30300000a011041e2020c71e3f9ffff1accffffeaff3d0fe3'
    '002061e2ff3f47e3030012e1c7ffff0a0030a0e30370d0e72c0057e3c3ffff0a7f7047e25e0077e3c0ffff3a013083e2'
    '030052e1f6ffff1a0c709de50020a0e3023050e7020051e1023047e7013042e20320a0e1f9ffff1a8c129fe50600a0e1'
    '01108fe038ff2fe10010a0e3000050e30500000a082090e5010052e30200001a040090e5000050e30010901508009de5'
    '960000eb000050e3a4ffff0a0110a0e35bf07ff59f0f94e1912f84e1000052e3fbffff1a000050e35bf07ff50700000a'
    '040084e25bf07ff59f1f90e1011081e2912f80e1000052e3faffff1a70ffffea040094e500005be1b2ffff1a0010a0e3'
    '18c500e30000a0e3018084e00030a0e10800a0e12020b0e5000052e31100000a347098e5046094e5060057e10d00001a'
    '287098e510609de5077056e00900003ab40057e30700002a050052e10b00001a0120d9e5240098e5020050e10300a0e1'
    '0200001a3f0000ea000053e30300a0110c1081e0a30c51e3e2ffff1a010000ea0300a0e1f9ffffea000050e33000000a'
    '005080e50020a0e30110d9e510309de50a0080e9181080e214b080e510a080e50c2080e50c309de50230d3e7000053e3'
    '0300000a012082e2020c52e3f8ffff1a022ca0e3012082e20c709de5012052e20130d7e40c708de50130c1e4f9ffff1a'
    '861f80e20020a0e308309de50230d3e7000053e30300000a012082e2020c52e3f8ffff1a022ca0e3012082e208709de5'
    '012052e20130d7e408708de50130c1e4f9ffff1a181400e3010080e00110d9e401a05ae20110c0e4fbffff1a080084e2'
    '000000ea1c0084e2001090e5011081e2001080e557ffffea2c0098e5000050e30500000a0100a0e32c0088e5100094e5'
    '010080e2100084e54effffea0c109de5380088e2cc0000eb000050e3f4ffff0a08109de58e0f88e2c70000eb000050e3'
    'efffff0a300098e50a0050e1ecffff1a380400e3000088e000005ae33dffff0a0110d9e401a04ae20120d0e4010052e1'
    'f8ffff0ae2ffffea99ffffffb20c0000110c00007c2efaff1a0b0000d4090000000051e32000000a0030a0e30320d1e7'
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
    'f8ffff1a0e20a0e10430a0e1a6ffffeac3050000680500008c05000010402de9000050e30600000a0030a0e30320d0e7'
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
    '31ff2fe131ffffea0000a0e3d7ffffea41f6ffff40030000d425fafffd000000dc00000014209fe5553d05e3cb3f4fe3'
    '02208fe00120c2e3032082e012ff2fe109f3ffff74656c3a006170706c69636174696f6e2f766e642e336770702e736d'
    '730043616c6c2d494400436f6e74656e742d54797065007369703a00502d41737365727465642d4964656e7469747900'
    '496e2d5265706c792d546f00736970733a000000ccb20181b0b0af0100000000a0b20181b0b0af0200000000'
)
SMS_ACK_EXIDX = bytes.fromhex(
    '84f2ff7f010000007ef2ff7fb0b0a88088f2ff7fb0b0aa8098f2ff7fccffff7f54f8ff7fb0b0ae8018fbff7fb0b0a880'
    'b4fbff7fc0ffff7f30ffff7fb0b0b08048ffff7f01000000'
)
# END GENERATED SMS ACK SHIM
