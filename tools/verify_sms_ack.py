"""Offline verification against a locally owned stock IMS binary; never writes it.

Requires optional Unicorn 2.1.4. The report contains hashes, offsets and booleans,
not firmware bytes, paths, subscriber identities or message content.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'device'))
import carrier_policy
import ims_image as image
from sms_ack_emulator import Emulator


def programs(raw):
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    return [struct.unpack_from('<8I', raw, header[5] + i*header[9]) for i in range(header[10])]


def notes(raw):
    result = []
    for h in programs(raw):
        if h[0] != 4:
            continue
        at, end = h[1], h[1]+h[4]
        while at < end:
            names, size, kind = struct.unpack_from('<III', raw, at)
            name = raw[at+12:at+12+names]
            desc = (at + 12 + names + 3) & ~3
            result.append((name, kind, raw[desc:desc+size]))
            at = (desc + size + 3) & ~3
        assert at == end
    return result


def unwind(raw):
    h = next(h for h in programs(raw) if h[0] == 0x70000001)
    result = []
    for i in range(0, h[4], 8):
        first, second = struct.unpack_from('<II', raw, h[1] + i)
        function = image._prel31(first, h[2] + i)
        compact = second == 1 or bool(second & 0x80000000)
        result.append((function, compact, second if compact else image._prel31(second, h[2] + i + 4)))
    return result


def branch(raw, at):
    first, last = struct.unpack_from('<HH', raw, at)
    assert first & 0xf800 == 0xf000 and last & 0xd000 == 0xd000
    sign = first >> 10 & 1
    i1, i2 = 1 ^ (last >> 13 & 1) ^ sign, 1 ^ (last >> 11 & 1) ^ sign
    value = sign << 24 | i1 << 23 | i2 << 22 | (first & 1023) << 12 | (last & 2047) << 1
    if sign:
        value -= 1 << 25
    return at + 4 + value


def elf_checks(stock, patched):
    assert notes(stock) == notes(patched), 'Platform/build notes changed'
    old = unwind(stock)
    new = unwind(patched)
    assert new[:len(old)] == old, 'Original unwind targets changed'
    assert all(a[0] < b[0] for a, b in zip(new, new[1:]))
    for function, compact, descriptor in new[len(old):]:
        assert image.SMS_ACK_CODE_VA <= function <= image.SMS_ACK_CODE_VA + len(image.SMS_ACK_CODE)
        if not compact:
            assert image.SMS_ACK_CODE_VA <= descriptor < image.SMS_ACK_CODE_VA + len(image.SMS_ACK_CODE)
            assert struct.unpack_from('<I', image.SMS_ACK_CODE, descriptor-image.SMS_ACK_CODE_VA)[0] & 0x80000000
    headers = programs(patched)
    loads = [h for h in headers if h[0] == 1]
    assert all(h[4] <= h[5] and h[1]+h[4] <= len(patched) and h[6] in (5, 6)
               and (h[1]-h[2]) % h[7] == 0 for h in loads)
    # QNX records one text and one data relocation bias. A third LOAD can
    # pass generic ELF checks yet crash in the linker before IMS starts.
    assert len(loads) == 2 and [h[6] for h in loads] == [5, 6]
    rx, rw = loads
    old_loads = [h for h in programs(stock) if h[0] == 1]
    assert rx[:4] == old_loads[0][:4] and rw[:5] == old_loads[1][:5]
    assert rx[1] == rx[2] == 0 and rx[4] == rx[5] == len(patched)
    assert rw[5] >= old_loads[1][5] and rw[2]+rw[5] == image.SMS_ACK_BSS_VA+image.SMS_ACK_BSS_SIZE
    rw_page_end = (rw[2]+rw[5]+4095) & ~4095
    assert rw_page_end <= image.SMS_ACK_CODE_VA
    assert all(h[1] == h[2] for h in headers if h[0] == 0x70000001)
    assert [h for h in programs(stock) if h[0] in (2, 3, 6, 0x6474e552)] == [
        h for h in headers if h[0] in (2, 3, 6, 0x6474e552)]
    assert branch(stock, 0x2eeff2) == 0x218098
    assert branch(stock, 0x2ee3c6) == 0x1b5d54
    assert branch(patched, 0x2eeff2) == image.SMS_ACK_RX
    assert branch(patched, 0x2ee3c6) == image.SMS_ACK_TX
    for start, end in ((0x63378, 0x6339e), (0x7c0de, 0x7d154), (0xdaf7a, 0xdb74c),
                       (0x2ee2c4, 0x2ee3c6), (0x2ee3ca, 0x2eeff2),
                       (0x2eeff6, 0x2ef4b0), (0x303a5c, 0x303b68)):
        assert patched[start:end] == stock[start:end], 'Unexpected change to existing SMS logic'
    # Getter and string-length contracts used by the shim, verified in the
    # original instructions instead of inventing C++ object layouts.
    assert stock[0x218098:0x21809c] == bytes.fromhex('20307047')
    return {'original_unwind_entries_preserved': len(old), 'shim_unwind_entries': len(new)-len(old),
            'notes_preserved': True, 'dynamic_imports_and_relro_unchanged': True,
            'qnx_two_load_headers_preserved': True, 'original_rw_overlay_and_bss_preserved': True,
            'shim_outside_rw_pages': True, 'no_writable_executable_segment': True,
            'original_bl_targets_checked': True, 'stock_sms_logic_preserved_except_two_hooks': True,
            'qnx_loader_validated': False}


def verify(stock):
    assert hashlib.sha256(stock).hexdigest() == image.STOCK_SHA, 'Unknown stock IMS image'
    defaults = {'mobile': image.mobile_binary(stock, True)[0],
                'unicom': image.temporary_binary(stock, True)[0],
                'mt_voice': image.mt_voice_binary(stock, True)[0]}
    expected = {'mobile': '647290caee0da86479ef7da7c42e68f98cd283fead8e9406f1c530a4a99c0494',
                'unicom': 'f388a23900d13d92c0390c662fc53e2de6d628bba2174973c0320416022a4438',
                'mt_voice': '7479b023d634c1afddd46203251ec7613ab5170d8ea22d6e321c7dd7fc3e7411'}
    assert {key: hashlib.sha256(raw).hexdigest() for key, raw in defaults.items()} == expected
    legacy_unicom = image.temporary_binary(stock, True, sms_ack=True)[0]
    legacy_mobile = image.mobile_binary(stock, True, sms_ack=True)[0]
    unified_mt = image.mt_voice_binary(stock, True, sms_ack=True)[0]
    elf_checks(stock, legacy_unicom)
    elf_checks(stock, legacy_mobile)
    checks = elf_checks(stock, unified_mt)
    images = {'mobile': unified_mt, 'unicom': unified_mt, 'telecom': unified_mt}
    matrix = []
    for variant, (family, board) in carrier_policy.MODELS.items():
        for mnc in carrier_policy.CARRIERS:
            selected = carrier_policy.select(
                {'variant': variant, 'board_type': board, 'os_version': carrier_policy.OS_VERSION},
                {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': mnc, 'imsi': '460'+mnc+'0'*10})
            assert selected['request']['profile']['ims']['sms'] is True
            patched = images[selected['operator']]
            for load in (0, 0x10000000, 0x28000000):
                emu = Emulator(load)
                emu.install_callsites(patched)
                # Reverse ACK order catches a last-message-only cache.
                emu.receive(ref=1, call='first@invalid', gateway='sip:first.invalid')
                emu.receive(ref=2, call='second@invalid', gateway='sip:second.invalid')
                for reference, name in ((2, 'second'), (1, 'first')):
                    result = emu.send(ref=reference)
                    assert result['headers']['in-reply-to'] == [name+'@invalid']
                    assert result['target'] == 'sip:'+name+'.invalid'
                    assert result['headers']['to'] == ['<sip:'+name+'.invalid>']
                    assert result['headers']['call-id'] == ['fresh-ack@invalid']
            matrix.append({'variant': variant, 'operator': selected['operator'], 'mnc': mnc,
                           'image_sha256': hashlib.sha256(patched).hexdigest(),
                           'same_receive_and_report_hooks': True, 'emulated_callsite_aslr_cases': 3,
                           'device_sms_acceptance': False})
    return {'schema': 1, 'status': 'offline_native_correlation_checks_passed',
            'stock_sha256': image.STOCK_SHA,
            'default_voice_images_unchanged': True,
            'library_constructor_sms_default': False,
            'hardware_acceptance_record': 'materials/sms-device-validation-2026-11-01.json',
            'hardware_acceptance_evaluated_by_this_verifier': False,
            'shim_code_sha256': hashlib.sha256(image.SMS_ACK_CODE).hexdigest(),
            'receive_hook': '0x2eeff2', 'report_hook': '0x2ee3c6',
            'elf_checks': checks, 'matrix': matrix,
            'limitations': ['Native SIP header/URI/clock APIs are mocked at verified ABI boundaries.',
                            'No QNX process was launched and no carrier transaction was sent.',
                            'This offline report cannot establish delivery counts, gateway acceptance or voice regression.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.native.read_bytes())
    with args.report.open('x', encoding='ascii') as output:
        output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'matrix_cases': len(result['matrix']), 'elf_checks': result['elf_checks']}))


if __name__ == '__main__':
    main()
