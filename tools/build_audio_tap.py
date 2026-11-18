"""Build or verify the freestanding ARM VoLTE audio capture shim with Zig 0.13.0.

Offline, deterministic compilation; --write explicitly updates generated tables.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'driver/audio_tap.c'
MANIFEST = 'materials/audio-tap-shim.json'
BEGIN = '# BEGIN GENERATED AUDIO TAP SHIM\n'
END = '# END GENERATED AUDIO TAP SHIM\n'
LINK_SCRIPT = '''ENTRY(audio_tap_anchor)
SECTIONS {
 . = 0x530000;
 .text : {
  KEEP(*(.rodata.descriptor))
  . = ALIGN(16);
  KEEP(*(.text.anchor))
  KEEP(*(.text.audio_mic_params_hook))
  KEEP(*(.text.audio_spk_params_hook))
  KEEP(*(.text.audio_read_hook))
  KEEP(*(.text.audio_write_hook))
  *(.text*)
  *(.rodata*)
 }
 .ARM.extab : { *(.ARM.extab*) }
 .ARM.exidx : { *(.ARM.exidx*) }
 . = 0x4b0000;
 .bss (NOLOAD) : { KEEP(*(.bss.tap)) *(.bss*) *(COMMON) }
 /DISCARD/ : { *(.comment) *(.note*) }
}
'''


def sections(raw):
    assert raw[:7] == b'\x7fELF\x01\x01\x01'
    head = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    assert head[2] == 40 and head[11] == 40
    table = [struct.unpack_from('<10I', raw, head[6] + i * 40) for i in range(head[12])]
    strings = table[head[13]]
    names = raw[strings[4]:strings[4] + strings[5]]
    return {names[h[0]:].split(b'\0', 1)[0].decode(): h for h in table}


def section_bytes(raw, header):
    return raw[header[4]:header[4] + header[5]]


def build(compiler):
    version = subprocess.check_output([str(compiler), 'version'], text=True).strip()
    assert version == '0.13.0', 'Use the pinned Zig 0.13.0 compiler'
    flags = ['-target', 'arm-linux-gnueabi', '-mcpu=cortex_a9', '-mthumb',
             '-mfloat-abi=soft', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-fno-sanitize=all', '-funwind-tables', '-fPIC', '-Oz', '-g0',
             '-ffunction-sections', '-fdata-sections', '-fvisibility=hidden']
    with tempfile.TemporaryDirectory(prefix='bb10-audio-build-') as folder:
        folder = Path(folder)
        obj, script, binary = folder / 'tap.o', folder / 'tap.ld', folder / 'tap.elf'
        script.write_text(LINK_SCRIPT, encoding='ascii')
        commands = [
            [str(compiler), 'cc'] + flags + ['-c', str(ROOT / SOURCE), '-o', str(obj)],
            [str(compiler), 'ld.lld', '-m', 'armelf_linux_eabi', '--gc-sections',
             '--no-undefined', '-T', str(script), str(obj), '-o', str(binary)],
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr)
        raw = binary.read_bytes()
    table = sections(raw)
    assert not any(h[1] in (4, 9) and h[5] for h in table.values()), 'Unresolved relocations'
    sym, strings = section_bytes(raw, table['.symtab']), section_bytes(raw, table['.strtab'])
    exports = {}
    wanted = ('audio_tap_desc', 'audio_tap_anchor', 'audio_mic_params_hook',
              'audio_spk_params_hook', 'audio_read_hook', 'audio_write_hook',
              'audio_mic_params', 'audio_spk_params', 'audio_read', 'audio_write', 'tap_state')
    for offset in range(0, len(sym), 16):
        name_off, value, size, info, unused, sec = struct.unpack_from('<IIIBBH', sym, offset)
        name = strings[name_off:].split(b'\0', 1)[0].decode()
        if name and sec == 0 and name not in ('__aeabi_unwind_cpp_pr0', '__aeabi_unwind_cpp_pr1'):
            raise AssertionError('Unexpected external symbol: ' + name)
        if name in wanted:
            exports[name] = value
    assert exports['audio_tap_desc'] == 0x530000
    assert exports['audio_tap_anchor'] == 0x530021
    for hook in ('audio_mic_params_hook', 'audio_spk_params_hook', 'audio_read_hook', 'audio_write_hook'):
        assert exports[hook] & 1 == 1, 'Entry must be Thumb: ' + hook
    assert exports['tap_state'] == table['.bss'][3] == 0x4b0000
    text = table['.text']
    extab = table.get('.ARM.extab')
    code_end = max(text[3] + text[5], (extab[3] + extab[5]) if extab else 0)
    code = bytearray(code_end - text[3])
    for name in ('.text', '.ARM.extab'):
        if name in table:
            h = table[name]
            code[h[3] - text[3]:h[3] - text[3] + h[5]] = section_bytes(raw, h)
    assert bytes(code[:8]) == b'BB10ATAP'
    assert len(code) < 8192 and table['.bss'][5] == 0x20050
    unexpected = [name for name, h in table.items() if h[2] & 2 and
                  name not in ('.text', '.ARM.extab', '.ARM.exidx', '.bss')]
    assert not unexpected, 'Unexpected allocated sections: ' + repr(unexpected)
    return {
        'schema': 1,
        'compiler': 'zig 0.13.0',
        'flags': flags,
        'source': SOURCE,
        'source_sha256': hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
        'code_va': text[3],
        'code_hex': bytes(code).hex(),
        'code_sha256': hashlib.sha256(code).hexdigest(),
        'bss_va': table['.bss'][3],
        'bss_size': table['.bss'][5],
        'exidx_va': table['.ARM.exidx'][3],
        'exidx_hex': section_bytes(raw, table['.ARM.exidx']).hex(),
        'symbols': exports,
    }


def render(value):
    lines = [
        BEGIN,
        'AUDIO_TAP_CODE_VA = ' + hex(value['code_va']) + '\n',
        'AUDIO_TAP_BSS_VA = ' + hex(value['bss_va']) + '\n',
        'AUDIO_TAP_BSS_SIZE = ' + str(value['bss_size']) + '\n',
        'AUDIO_TAP_EXIDX_VA = ' + hex(value['exidx_va']) + '\n',
        'AUDIO_TAP_MIC_PARAMS = ' + hex(value['symbols']['audio_mic_params_hook'] & ~1) + '\n',
        'AUDIO_TAP_SPK_PARAMS = ' + hex(value['symbols']['audio_spk_params_hook'] & ~1) + '\n',
        'AUDIO_TAP_READ = ' + hex(value['symbols']['audio_read_hook'] & ~1) + '\n',
        'AUDIO_TAP_WRITE = ' + hex(value['symbols']['audio_write_hook'] & ~1) + '\n',
    ]
    for name, field in (('AUDIO_TAP_CODE', 'code_hex'), ('AUDIO_TAP_EXIDX', 'exidx_hex')):
        lines.append(name + ' = bytes.fromhex(\n')
        lines.extend("    '" + value[field][i:i + 96] + "'\n" for i in range(0, len(value[field]), 96))
        lines.append(')\n')
    lines.append(END)
    return ''.join(lines)


def check_generated(root=ROOT):
    value = json.loads((root / MANIFEST).read_text(encoding='ascii'))
    assert value['schema'] == 1 and value['source'] == SOURCE
    assert hashlib.sha256((root / SOURCE).read_bytes()).hexdigest() == value['source_sha256'], 'Stale audio tap source'
    assert hashlib.sha256(bytes.fromhex(value['code_hex'])).hexdigest() == value['code_sha256'], 'Changed audio tap bytes'
    current = (root / 'device/ims_image.py').read_text(encoding='utf-8')
    start = current.index(BEGIN)
    finish = current.index(END, start) + len(END)
    assert current[start:finish] == render(value), 'Stale generated audio tap shim'
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    value = build(args.zig.resolve())
    module = ROOT / 'device/ims_image.py'
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
        (ROOT / MANIFEST).write_text(json.dumps(value, indent=2) + '\n', encoding='ascii', newline='\n')
    else:
        assert current == changed, 'Generated audio tap changed; review before --write'
        assert json.loads((ROOT / MANIFEST).read_text(encoding='ascii')) == value
    print(json.dumps({k: value[k] for k in ('code_sha256', 'bss_size', 'symbols')}, indent=2))


if __name__ == '__main__':
    main()
