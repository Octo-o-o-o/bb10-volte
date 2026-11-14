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
         0x1b5d54, 0x218e80, 0x66140, 0xda97c, 0x139084, 0x11ec60)


def decode_tlv(raw):
    assert len(raw) >= 4 and len(raw) % 4 == 0
    msg_id, total_words = struct.unpack_from('<HH', raw, 0)
    assert 4 + total_words * 4 == len(raw)
    items, at = [], 4
    while at < len(raw):
        tag, words = struct.unpack_from('<HH', raw, at)
        end = at + 4 + words * 4
        assert end <= len(raw)
        items.append((tag, bytes(raw[at + 4:end])))
        at = end
    return msg_id, items


class Emulator:
    def __init__(self, base=0x10000000, telecom_mo_ack=False):
        self.base, self.time, self.clock_error = base, 1000, False
        self.telecom_mo_ack = telecom_mo_ack
        self.heap, self.stack, self.stop = 0x70000000, 0x71010000, 0x71020000
        self.messages, self.uris, self.calls = {}, {}, []
        self.pending_mo, self.ipc_sent, self.ipc_error = {}, [], False
        self.reject_uri = False
        self.rx_entry = image.SMS_ACK_RX
        self.tx_entry = image.SMS_ACK_TELECOM_TX if telecom_mo_ack else image.SMS_ACK_TX
        self.pop_entry = image.SMS_ACK_MO_POP
        self.mo_send_entry = image.SMS_ACK_MO_SEND
        self.callsites = False
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(base, 0x600000)
        self.uc.mem_map(self.heap, 0x200000)
        self.uc.mem_map(0x71000000, 0x30000)
        self.uc.mem_write(base + image.SMS_ACK_CODE_VA, image.SMS_ACK_CODE)
        for offset in EDGES:
            self.uc.mem_write(base + offset, b'\x1e\xff\x2f\xe1' if offset == 0x5b57c else b'\x70\x47')
        self.uc.hook_add(UC_HOOK_CODE, self._native)

    def install_callsites(self, patched, telecom_mo_ack=False):
        """Execute the BL instructions from a patched, hash-verified image."""
        self.telecom_mo_ack = telecom_mo_ack
        self.rx_entry, self.tx_entry, self.callsites = 0x2eeff2, 0x2ee3c6, True
        offsets = [self.rx_entry, self.tx_entry]
        if telecom_mo_ack:
            self.pop_entry, self.mo_send_entry = 0xdaae2, 0xdab44
            offsets.extend((self.pop_entry, self.mo_send_entry))
        for offset in offsets:
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
        elif offset == 0xda97c:
            out2 = self.word(uc.reg_read(UC_ARM_REG_SP))
            cid = ''
            if args[1]:
                ptr = self.word(args[1])
                if ptr:
                    cid = self.string(ptr)
            key = (args[0], cid)
            if key not in self.pending_mo:
                result = 0xff
            else:
                pdu_id, b1, b2 = self.pending_mo.pop(key) if args[2] else self.pending_mo[key]
                if args[3]:
                    uc.mem_write(args[3], bytes([b1]))
                if out2:
                    uc.mem_write(out2, bytes([b2]))
                result = pdu_id
        elif offset == 0x139084:
            buf, buf_size, count, msg_id = args
            sp = uc.reg_read(UC_ARM_REG_SP)
            out = bytearray(struct.pack('<HH', msg_id & 0xffff, 0))
            overflow = buf == 0 or buf_size <= 3
            for i in range(count):
                tag, vlen, vptr = struct.unpack('<III', uc.mem_read(sp + i * 12, 12))
                padded = (vlen + 3) & ~3
                if len(out) + 4 + padded > buf_size:
                    overflow = True
                    break
                val = bytes(uc.mem_read(vptr, vlen))
                out.extend(struct.pack('<HH', tag & 0xffff, padded >> 2))
                out.extend(val + b'\0' * (padded - vlen))
            if overflow:
                if buf and buf_size:
                    uc.mem_write(buf, b'\0' * buf_size)
                result = 0xffffffff
            else:
                words = (len(out) - 1) >> 2
                struct.pack_into('<H', out, 2, words)
                uc.mem_write(buf, bytes(out))
                result = (words << 2) + 4
        elif offset == 0x11ec60:
            if self.ipc_error:
                result = 0xffffffff
            else:
                self.ipc_sent.append((args[0], bytes(uc.mem_read(args[1], args[2])), args[3]))
                result = 0
        uc.reg_write(UC_ARM_REG_R0, int(result) & 0xffffffff)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def run(self, entry, args, extra=None, stack_words=()):
        self.stop = self.base + (entry & ~1) + 4 if self.callsites else 0x71020000
        for i, register in enumerate(REGS):
            self.uc.reg_write(register, 0x1100 + i)
        for register, value in zip(REGS, args):
            self.uc.reg_write(register, value)
        for register, value in (extra or {}).items():
            self.uc.reg_write(register, value)
        for index, word in enumerate(stack_words):
            self.uc.mem_write(self.stack + index * 4, struct.pack('<I', word))
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

    def send_mo(self, ref=0x38, call='mo-first@invalid', owner=0x1234,
                engine=0x2000, pdu_id=5, rp=None, headers=None):
        if pdu_id is not None and call is not None:
            self.pending_mo[(engine, call)] = (pdu_id, 0xaa, 0xbb)
        merged = {} if call is None else {'Call-ID': call}
        merged.update(headers or {})
        raw = bytes([0, ref, 0, 1]) if rp is None else rp
        return self.send(ref=ref, owner=owner, kind=0, headers=merged, rp=raw)

    def deliver_mo_success(self, call='mo-first@invalid', engine=0x2000, ipc=0x3000,
                           out1_used=False, out2_used=False):
        if call is None:
            call_obj = 0
        else:
            cstr = self.allocate(call.encode('ascii') + b'\0')
            call_obj = self.allocate(struct.pack('<I', cstr))
        out1 = self.allocate(b'\x00') if out1_used else 0
        out2 = self.allocate(b'\x00') if out2_used else 0
        pdu_id = self.run(self.pop_entry | 1, [engine, call_obj, 1, out1], stack_words=(out2,))
        if out1_used and pdu_id != 0xff:
            assert self.uc.mem_read(out1, 1) == b'\xaa'
        if out2_used and pdu_id != 0xff:
            assert self.uc.mem_read(out2, 1) == b'\xbb'
        if pdu_id == 0xff:
            return pdu_id, None
        # Exact ImsEngineSmsMgr::onSmsDeliverySuccess stack layout around sp+0x44:
        # [sp+0x30] = engine, [sp+0x43] = pdu_id, [sp+0x44..] = 0x1014 TLV.
        frame = bytearray(0x80)
        struct.pack_into('<I', frame, 0x30, engine)
        frame[0x43] = pdu_id & 0xff
        status_tlv = struct.pack(
            '<HHHHBBBBHHIHHI',
            0x1014, 6,
            0x1000, 1, pdu_id & 0xff, 0, 0, 0,
            0x1045, 1, 0,
            0x1048, 1, 0,
        )
        frame[0x44:0x44 + len(status_tlv)] = status_tlv
        frame_addr = self.allocate(bytes(frame))
        rc = self.run(self.mo_send_entry | 1, [ipc, frame_addr + 0x44, len(status_tlv), 0])
        return pdu_id, rc
