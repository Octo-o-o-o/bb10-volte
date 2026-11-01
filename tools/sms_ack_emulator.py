"""Execute the compiled ARM/Thumb shim; mock only documented native API edges.

Requires Unicorn 2.1.4. Synthetic identifiers stay in emulator memory. This is
instruction/ABI validation, not QNX loader or carrier acceptance.
"""
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'device'))
import ims_image as image

REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
EDGES = (0x5b57c, 0x16d14c, 0x1ffa94, 0x2185e8, 0x23ea94, 0x23c596,
         0x1b5d54, 0x218e80, 0x66140)


class Emulator:
    def __init__(self, base=0x10000000):
        self.base, self.time, self.clock_error = base, 1000, False
        self.heap, self.stack, self.stop = 0x70000000, 0x71010000, 0x71020000
        self.messages, self.uris, self.calls = {}, {}, []
        self.reject_uri = False
        self.rx_entry, self.tx_entry, self.callsites = image.SMS_ACK_RX, image.SMS_ACK_TX, False
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(base, 0x600000)
        self.uc.mem_map(self.heap, 0x200000)
        self.uc.mem_map(0x71000000, 0x30000)
        self.uc.mem_write(base + image.SMS_ACK_CODE_VA, image.SMS_ACK_CODE)
        for offset in EDGES:
            self.uc.mem_write(base + offset, b'\x1e\xff\x2f\xe1' if offset == 0x5b57c else b'\x70\x47')
        self.uc.hook_add(UC_HOOK_CODE, self._native)

    def install_callsites(self, patched):
        """Execute the BL instructions from a patched, hash-verified image."""
        self.rx_entry, self.tx_entry, self.callsites = 0x2eeff2, 0x2ee3c6, True
        for offset in (self.rx_entry, self.tx_entry):
            self.uc.mem_write(self.base + offset, patched[offset:offset+4])

    def allocate(self, raw, padding=0):
        at = (self.heap + 7) & ~7
        self.heap = at + len(raw) + max(padding, 8)
        self.uc.mem_write(at, raw)
        return at

    def word(self, at):
        return struct.unpack('<I', self.uc.mem_read(at, 4))[0]

    def set_cache_busy(self, busy):
        """Model a different thread holding the cache's first-word lock."""
        self.uc.mem_write(self.base + image.SMS_ACK_BSS_VA, struct.pack('<I', int(busy)))

    def string(self, at):
        result = bytearray()
        for i in range(1024):
            value = self.uc.mem_read(at+i, 1)[0]
            if not value:
                return result.decode('ascii')
            result.append(value)
        raise AssertionError('Unbounded string read')

    def message(self, headers=None, rp=b'', target='sip:stock.invalid'):
        msg = self.allocate(bytes(128))
        body = self.allocate(struct.pack('<III', len(rp), 0, 1) + rp + b'\0') + 12
        self.uc.mem_write(msg + 0x20, struct.pack('<I', body))
        self.messages[msg] = {'headers': {k.lower(): ([v] if isinstance(v, str) else list(v))
                                        for k, v in (headers or {}).items()},
                              'target': target, 'rp': bytes(rp)}
        return msg

    def _native(self, uc, address, size, unused):
        if address == self.stop:
            uc.emu_stop()
            return
        offset = address - self.base
        if offset not in EDGES:
            return
        args = [uc.reg_read(r) for r in REGS[:4]]
        self.calls.append((offset, tuple(args)))
        result = 0
        if offset == 0x5b57c:
            assert args[0] == 2
            uc.mem_write(args[1], struct.pack('<II', self.time, 0))
            result = 0xffffffff if self.clock_error else 0
        elif offset == 0x16d14c:
            fields = self.messages[args[0]-8]['headers'].get(self.string(args[1]).lower(), [])
            if fields:
                pointers = [self.allocate(v.encode() + b'\0') for v in fields]
                array = self.allocate(struct.pack('<' + 'I'*len(pointers), *pointers))
                result = self.allocate(struct.pack('<III', 0, array, len(pointers)))
        elif offset == 0x1ffa94:
            result = self.word(self.word(args[0])-12)
        elif offset == 0x2185e8:
            result = bool(self.messages[args[0]]['headers'].get(self.string(args[1]).lower()))
        elif offset == 0x23ea94:
            self.uris[args[0]] = self.string(args[1])
        elif offset == 0x23c596:
            result = not self.reject_uri and self.uris[args[0]].startswith(('sip:', 'sips:', 'tel:'))
        elif offset == 0x1b5d54:
            self.messages[args[0]]['target'] = self.uris[args[1]]
        elif offset == 0x218e80:
            self.messages[args[0]]['headers'][self.string(args[1]).lower()] = [self.string(args[2])]
        elif offset == 0x66140:
            del self.uris[args[0]]
        uc.reg_write(UC_ARM_REG_R0, int(result))
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def run(self, entry, args, extra=None):
        self.stop = self.base + (entry & ~1) + 4 if self.callsites else 0x71020000
        for i, register in enumerate(REGS):
            self.uc.reg_write(register, 0x1100 + i)
        for register, value in zip(REGS, args):
            self.uc.reg_write(register, value)
        for register, value in (extra or {}).items():
            self.uc.reg_write(register, value)
        before = [self.uc.reg_read(r) for r in REGS[4:]]
        self.uc.reg_write(UC_ARM_REG_SP, self.stack)
        self.uc.reg_write(UC_ARM_REG_LR, self.stop | 1)
        self.uc.emu_start(self.base + entry, self.stop, timeout=2000000, count=500000)
        assert self.uc.reg_read(UC_ARM_REG_PC) == self.stop, 'Execution did not return'
        assert self.uc.reg_read(UC_ARM_REG_SP) == self.stack, 'Stack not restored'
        assert [self.uc.reg_read(r) for r in REGS[4:]] == before, 'Callee-saved register corruption'
        return self.uc.reg_read(UC_ARM_REG_R0)

    def receive(self, ref=0xe3, call='mt-first@invalid', gateway='<sip:gw.invalid>',
                owner=0x1234, rp=None, headers=None, content_type='application/vnd.3gpp.sms'):
        values = {'Content-Type': content_type}
        values.update({'Call-ID': call, 'P-Asserted-Identity': gateway} if headers is None else headers)
        msg = self.message(values, bytes([1, ref, 0, 0]) if rp is None else rp)
        result = self.run(self.rx_entry | 1, [msg], {UC_ARM_REG_R5: owner})
        assert result == msg + 0x20, 'Original body getter result changed'
        return msg

    def send(self, ref=0xe3, owner=0x1234, kind=2, headers=None, rp=None):
        values = {'Call-ID': 'fresh-ack@invalid', 'To': 'sip:stock.invalid'}
        values.update(headers or {})
        raw = bytes([kind, ref]) if rp is None else rp
        msg = self.message(values, raw)
        pdu = self.word(msg + 0x20)
        old_uri = self.allocate(bytes(124))
        self.uris[old_uri] = 'sip:stock.invalid'
        self.run(self.tx_entry | 1, [msg, old_uri],
                 {UC_ARM_REG_R4: owner, UC_ARM_REG_R9: len(raw), UC_ARM_REG_R10: pdu})
        del self.uris[old_uri]
        return self.messages[msg]
