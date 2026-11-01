"""Build/check the freestanding ARM SMS shim with an explicit Zig 0.13.0 path.

No network, phone I/O, native firmware input or automatic manifest blessing.
--write is the explicit maintainer operation; default checks reproducibility.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'driver/sms_ack.c'
MANIFEST = 'materials/sms-ack-shim.json'
BEGIN = '# BEGIN GENERATED SMS ACK SHIM\n'
END = '# END GENERATED SMS ACK SHIM\n'
LINK_SCRIPT = '''ENTRY(sms_anchor)
SECTIONS {
 . = 0x500000;
 .text : { KEEP(*(.text.anchor)) KEEP(*(.text.sms_rx_hook)) KEEP(*(.text.sms_tx_hook)) *(.text*) *(.rodata*) }
 .ARM.extab : { *(.ARM.extab*) }
 .ARM.exidx : { *(.ARM.exidx*) }
 . = 0x4a3000;
 .bss (NOLOAD) : { *(.bss*) *(COMMON) }
 /DISCARD/ : { *(.comment) *(.note*) }
}
'''


def sections(raw):
    assert raw[:7] == b'\x7fELF\x01\x01\x01'
    head = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    assert head[2] == 40 and head[11] == 40  # ARM, section header size
    table = [struct.unpack_from('<10I', raw, head[6] + i * 40) for i in range(head[12])]
    strings = table[head[13]]
    names = raw[strings[4]:strings[4] + strings[5]]
    return {names[h[0]:].split(b'\0', 1)[0].decode(): h for h in table}


def data(raw, section):
    return raw[section[4]:section[4] + section[5]]


def build(compiler):
    version = subprocess.check_output([str(compiler), 'version'], text=True).strip()
    assert version == '0.13.0', 'Use the pinned Zig 0.13.0 compiler'
    flags = ['-target', 'arm-linux-gnueabi', '-mcpu=cortex_a9', '-mthumb',
             '-mfloat-abi=soft', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-fno-sanitize=all', '-funwind-tables', '-fPIC', '-Oz', '-g0',
             '-ffunction-sections', '-fdata-sections', '-fvisibility=hidden']
    with tempfile.TemporaryDirectory(prefix='bb10-sms-build-') as folder:
        folder = Path(folder)
        obj, script, binary = folder/'shim.o', folder/'shim.ld', folder/'shim.elf'
        script.write_text(LINK_SCRIPT, encoding='ascii')
        commands = [[str(compiler), 'cc'] + flags + ['-c', str(ROOT/SOURCE), '-o', str(obj)],
                    [str(compiler), 'ld.lld', '-m', 'armelf_linux_eabi', '--gc-sections',
                     '--no-undefined', '-T', str(script), str(obj), '-o', str(binary)]]
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr)
        raw = binary.read_bytes()
    table = sections(raw)
    assert not any(h[1] in (4, 9) and h[5] for h in table.values()), 'Unresolved relocations'
    sym, strings = data(raw, table['.symtab']), data(raw, table['.strtab'])
    exports = {}
    for offset in range(0, len(sym), 16):
        name, value, size, info, unused, section = struct.unpack_from('<IIIBBH', sym, offset)
        name = strings[name:].split(b'\0', 1)[0].decode()
        # ARM_EXIDX compact records use built-in personality indices. These
        # R_ARM_NONE link markers have no runtime relocation or code address.
        if name and section == 0 and name not in ('__aeabi_unwind_cpp_pr0', '__aeabi_unwind_cpp_pr1'):
            raise AssertionError('Unexpected external symbol: ' + name)
        if name in ('sms_anchor', 'sms_rx_hook', 'sms_tx_hook', 'sms_capture', 'sms_correlate', 'cache'):
            exports[name] = value
    assert exports['sms_anchor'] == 0x500001
    text = table['.text']
    extab = table.get('.ARM.extab')
    code_end = max(text[3] + text[5], (extab[3] + extab[5]) if extab else 0)
    code = bytearray(code_end - text[3])
    for name in ('.text', '.ARM.extab'):
        if name in table:
            h = table[name]
            code[h[3]-text[3]:h[3]-text[3]+h[5]] = data(raw, h)
    assert len(code) < 16384 and table['.bss'][5] < 65536
    # No allocated data may silently be omitted from the runtime image.
    unexpected = [name for name, h in table.items() if h[2] & 2 and
                  name not in ('.text', '.ARM.extab', '.ARM.exidx', '.bss')]
    assert not unexpected, 'Unexpected allocated sections: ' + repr(unexpected)
    return {'schema': 1, 'compiler': 'zig 0.13.0', 'flags': flags,
            'source': SOURCE, 'source_sha256': hashlib.sha256((ROOT/SOURCE).read_bytes()).hexdigest(),
            'code_va': text[3], 'code_hex': bytes(code).hex(),
            'code_sha256': hashlib.sha256(code).hexdigest(),
            'bss_va': table['.bss'][3], 'bss_size': table['.bss'][5],
            'exidx_va': table['.ARM.exidx'][3], 'exidx_hex': data(raw, table['.ARM.exidx']).hex(),
            'symbols': exports}


def render(value):
    lines = [BEGIN, 'SMS_ACK_CODE_VA = ' + hex(value['code_va']) + '\n',
             'SMS_ACK_BSS_VA = ' + hex(value['bss_va']) + '\n',
             'SMS_ACK_BSS_SIZE = ' + str(value['bss_size']) + '\n',
             'SMS_ACK_EXIDX_VA = ' + hex(value['exidx_va']) + '\n',
             'SMS_ACK_RX = ' + hex(value['symbols']['sms_rx_hook'] & ~1) + '\n',
             'SMS_ACK_TX = ' + hex(value['symbols']['sms_tx_hook'] & ~1) + '\n']
    for name, field in (('SMS_ACK_CODE', 'code_hex'), ('SMS_ACK_EXIDX', 'exidx_hex')):
        lines.append(name + ' = bytes.fromhex(\n')
        lines.extend("    '" + value[field][i:i+96] + "'\n" for i in range(0, len(value[field]), 96))
        lines.append(')\n')
    lines.append(END)
    return ''.join(lines)


def check_generated(root=ROOT):
    value = json.loads((root/MANIFEST).read_text(encoding='ascii'))
    assert value['schema'] == 1 and value['source'] == SOURCE
    assert hashlib.sha256((root/SOURCE).read_bytes()).hexdigest() == value['source_sha256'], 'Stale SMS shim source'
    assert hashlib.sha256(bytes.fromhex(value['code_hex'])).hexdigest() == value['code_sha256'], 'Changed SMS shim bytes'
    current = (root/'device/ims_image.py').read_text(encoding='utf-8')
    start = current.index(BEGIN)
    finish = current.index(END, start) + len(END)
    assert current[start:finish] == render(value), 'Stale generated SMS shim'
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    value = build(args.zig.resolve())
    module = ROOT/'device/ims_image.py'
    current = module.read_text(encoding='utf-8')
    generated = render(value)
    if BEGIN in current:
        start = current.index(BEGIN)
        finish = current.index(END, start) + len(END)
        changed = current[:start] + generated + current[finish:]
    else:
        changed = current.rstrip() + '\n\n\n' + generated
    if args.write:
        module.write_text(changed, encoding='utf-8', newline='\n')
        (ROOT/MANIFEST).write_text(json.dumps(value, indent=2) + '\n', encoding='ascii', newline='\n')
    else:
        assert current == changed, 'Generated shim changed; review before --write'
        assert json.loads((ROOT/MANIFEST).read_text(encoding='ascii')) == value
    print(json.dumps({k: value[k] for k in ('code_sha256', 'bss_size', 'symbols')}))


if __name__ == '__main__':
    main()
