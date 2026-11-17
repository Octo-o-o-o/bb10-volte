"""Execute pinned native rejection paths; do not infer live call acceptance.

State predicates, MediaDialog::reject and the late call-state dispatch execute
real ARM instructions. Fixtures replace C++ ownership/logging/mutex operations,
dialog lookup, TLV serialization and transport; this is not a QNX/network test.
No native binaries, real identifiers or device I/O are included.
"""
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import ims_image

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_SP,
        UC_ARM_REG_LR, UC_ARM_REG_PC)
except ModuleNotFoundError as error:
    if error.name != 'unicorn':
        raise
    Uc = None


def stock_image():
    override = os.environ.get('BB10_STOCK_IMS_RRM')
    candidates = ([Path(override)] if override else []) + [
        ROOT.parents[1] / 'research/volte_session/radio-inspection/ims_rrm']
    for path in candidates:
        if path.is_file():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == ims_image.STOCK_SHA:
                return raw
    return None


STOCK_RAW = stock_image()
BASES = (0x10000000, 0x16543000, 0x321ab000, 0x51234000)


class CallRejectionHarness:
    def __init__(self, raw=STOCK_RAW, base=0x10000000):
        self.base, self.heap, self.stack, self.stop = base, 0x70000000, 0x71020000, 0x71030000
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(base, 0x600000)
        self.uc.mem_map(self.heap, 0x100000)
        self.uc.mem_map(0x71000000, 0x40000)
        self.uc.mem_write(base, raw)
        self.edges, self.calls, self.trace = {}, [], []
        self.put(base + 0x488b8c, self.alloc(struct.pack('<I', 0x12345678)))
        self.uc.hook_add(UC_HOOK_CODE, self.hook)

    def alloc(self, data):
        ptr = self.heap
        self.heap += (len(data) + 15) & ~15
        self.uc.mem_write(ptr, data)
        return ptr

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def word(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def edge(self, off, callback=None):
        self.edges[self.base + off] = callback

    def hook(self, uc, address, size, unused):
        if address == self.stop:
            uc.emu_stop()
            return
        self.trace.append(address - self.base)
        if address not in self.edges:
            return
        args = [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        self.calls.append((address - self.base, args))
        fn = self.edges[address]
        result = fn(*args) if fn else 0
        uc.reg_write(UC_ARM_REG_R0, result or 0)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def run(self, start, regs=None, stop=None):
        self.trace, self.calls = [], []
        self.stop = self.base + stop if stop else 0x71030000
        self.uc.reg_write(UC_ARM_REG_SP, self.stack)
        self.uc.reg_write(UC_ARM_REG_LR, self.stop | 1)
        for reg, val in (regs or {}).items():
            self.uc.reg_write(reg, val & 0xffffffff)
        try:
            self.uc.emu_start(self.base + start | 1, self.stop, timeout=2000000, count=100000)
            assert self.uc.reg_read(UC_ARM_REG_PC) == self.stop, 'Emulator did not return'
        except Exception:
            print('last instructions', [hex(n) for n in self.trace[-15:]])
            raise
        return self.uc.reg_read(UC_ARM_REG_R0)

    def prepare_reject(self, state, sdp=0xb):
        self.sip = self.alloc(bytes(0x300))
        self.dialog = self.alloc(bytes(0xc00))
        self.ua = self.alloc(bytes(0x100))
        vtable = self.alloc(bytes(0x100))
        self.put(self.sip + 0x2c, state)
        self.put(self.sip + 0x30, 1)
        self.put(self.dialog + 8, self.sip)
        self.put(self.dialog + 0xe0, sdp)
        self.put(self.dialog + 0xdc, self.ua)
        self.put(self.ua, vtable)
        self.put(vtable + 0x44, self.base + 0x3f0001)
        for off in (0x1abe5a, 0x19c9b6, 0x1493c0, 0x11e538, 0x7aaa4):
            self.edge(off)
        self.edge(0xd64a8, lambda dst, src, *_: self.put(dst, self.word(src)))
        self.edge(0x7a7c0, lambda dst, code, *_: self.put(dst, code))
        self.rejects = []
        def rejected(ua, ref, code, text):
            self.rejects.append((self.word(ref), self.word(code)))
        self.edge(0x3f0000, rejected)
        return self.dialog

    def end_call(self, direction=1, status=2, busy=0, code=486):
        """Execute the end-state tail with a supplied derived call status.

        Status 2 is the busy case under investigation. This fixture does not
        derive that status from a real SIP response or exercise earlier events.
        """
        manager = self.alloc(bytes(0x800))
        cmgr = self.alloc(bytes(0x100))
        vt = self.alloc(bytes(0x200))
        sip = self.alloc(bytes(0x100))
        dialog = self.alloc(bytes(0xc00))
        cid = self.alloc(b'example-call.invalid\0')
        cid_ref = self.alloc(struct.pack('<I', cid))
        self.put(cmgr, vt)
        self.put(vt + 0x110, self.base + 0x3f0011)
        self.put(sip + 0x30, direction or 0)
        self.put(dialog + 8, sip)
        self.put(manager + 0x2c4, busy)
        self.put(self.stack + 0x34, self.stack + 0x88)
        self.put(self.stack + 0x84, status)
        self.put(self.stack + 0x88, 0x80000002)
        self.put(self.stack + 0x40, 0)
        for off in (0xedf04, 0xedf16, 0x5c830, 0x7aa68, 0x7a83a, 0xcc11c, 0x7a7ec,
                    0x200bd4, 0x5af60, 0x5a8e4):
            self.edge(off)
        self.edge(0x7a8c4, lambda dst, *_: self.put(dst, cmgr))
        for off in (0x7a9c4, 0x7aa80, 0x7a854):
            self.edge(off, lambda ref, *_: self.word(ref))
        self.edge(0x3f0010, lambda dst, *_: self.put(dst, dialog if direction is not None else 0))
        self.edge(0x5b9d4, lambda dst, value, size, unused: self.uc.mem_write(dst, bytes([value])*size) or dst)
        def tlv(dst, maximum, count, kind):
            sp = self.uc.reg_read(UC_ARM_REG_SP)
            body = bytearray()
            for i in range(count):
                tag, size, ptr = struct.unpack('<III', self.uc.mem_read(sp+i*12, 12))
                body.extend(struct.pack('<HH', tag, (size+3)//4))
                body.extend(self.uc.mem_read(ptr, size))
                body.extend(bytes(-size % 4))
            data = struct.pack('<HH', kind, len(body)//4) + body
            assert len(data) <= maximum
            self.uc.mem_write(dst, data)
            return len(data)
        self.edge(0x139084, tlv)
        self.messages = []
        self.edge(0x11ec60, lambda transport, ptr, size, flags: self.messages.append(bytes(self.uc.mem_read(ptr,size))))
        self.run(0xd4964, {UC_ARM_REG_R4: manager, UC_ARM_REG_R6: 0,
                          UC_ARM_REG_R7: self.stack+0x84, UC_ARM_REG_R8: cid_ref,
                          UC_ARM_REG_R9: code}, stop=0xd5356)
        return [m.hex() for m in self.messages], self.word(manager+0x2c4)


def decode_message(message):
    kind, words = struct.unpack_from('<HH', message)
    assert len(message) == 4 + words * 4
    fields = {}
    at = 4
    while at < len(message):
        tag, count = struct.unpack_from('<HH', message, at)
        assert count == 1 and tag not in fields
        fields[tag] = struct.unpack_from('<I', message, at + 4)[0]
        at += 4 + count * 4
    return kind, fields


@unittest.skipIf(Uc is None or STOCK_RAW is None, 'Requires optional unicorn and local stock ims_rrm')
class NativeCallRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = {
            'stock': STOCK_RAW,
            'r48_three_carrier': ims_image.mt_voice_binary(STOCK_RAW, True, sms_ack=True)[0],
            'r48_telecom': ims_image.mt_voice_binary(STOCK_RAW, True, sms_ack=True, telecom_mo_ack=True)[0],
        }

    def test_state_names_and_predicates_use_the_real_jump_table(self):
        for base in BASES:
            h = CallRejectionHarness(base=base)
            for state, expected in ((-1, 'null'), (0, 'early'), (1, 'completed'),
                                    (2, 'confirmed'), (3, 'cancelling'), (4, 'terminated')):
                with self.subTest(base=hex(base), state=state):
                    ptr = h.run(0x16b3aa, {UC_ARM_REG_R0: state})
                    self.assertEqual(bytes(h.uc.mem_read(ptr, 32)).split(b'\0')[0].decode(), expected)
                    sip = h.alloc(bytes(0x100))
                    h.put(sip + 0x2c, state)
                    self.assertEqual(h.run(0x16b30a, {UC_ARM_REG_R0: sip}), int(state == 0))
                    self.assertEqual(h.run(0x16b2dc, {UC_ARM_REG_R0: sip}), int(state in (-1, 0)))

    def test_incoming_constructor_receives_early_not_null_state(self):
        for base in BASES:
            for direction, state, start, stop in ((1, 0, 0x1726b2, 0x1726da),
                                                  (0, 0xffffffff, 0x17201c, 0x172042)):
                with self.subTest(base=hex(base), direction=direction):
                    h = CallRejectionHarness(base=base)
                    captured = []
                    def constructor(dst, identity, owner, incoming):
                        sp = h.uc.reg_read(UC_ARM_REG_SP)
                        captured.append((incoming, h.word(sp + 0x1c)))
                    h.edge(0x16c3b0, constructor)
                    h.run(start, stop=stop)
                    self.assertEqual(captured, [(direction, state)])

    def test_ringing_rejection_reaches_sip_reject_for_486_and_603(self):
        for name, raw in self.images.items():
            for base in BASES:
                for sdp, code in ((0xb, 486), (0xc, 603), (0x1f, 486)):
                    with self.subTest(image=name, base=hex(base), sdp=sdp, code=code):
                        h = CallRejectionHarness(raw, base)
                        dialog = h.prepare_reject(0, sdp)
                        h.run(0x1a033c, {UC_ARM_REG_R0: dialog, UC_ARM_REG_R1: code, UC_ARM_REG_R2: 0})
                        self.assertEqual(h.rejects, [(h.sip, code)])
                        self.assertIn(0x1a05c4, h.trace)

    def test_no_new_initial_rejection_for_completed_or_ended_dialogs(self):
        for state in (-1, 1, 2, 3, 4):
            with self.subTest(state=state):
                h = CallRejectionHarness(self.images['r48_telecom'])
                dialog = h.prepare_reject(state)
                # There is no pending in-dialog request in this fixture (+0xe8=0).
                h.run(0x1a033c, {UC_ARM_REG_R0: dialog, UC_ARM_REG_R1: 486, UC_ARM_REG_R2: 0})
                self.assertEqual(h.rejects, [])

    def test_negative_control_detects_a_wrong_rejection_predicate(self):
        damaged = bytearray(self.images['r48_three_carrier'])
        # Synthetic negative control only, never a product or device image.
        damaged[0x1a0596:0x1a059a] = ims_image.thumb_bl(0x1a0596, 0x16b2fc)
        h = CallRejectionHarness(bytes(damaged))
        dialog = h.prepare_reject(0)
        h.run(0x1a033c, {UC_ARM_REG_R0: dialog, UC_ARM_REG_R1: 486, UC_ARM_REG_R2: 0})
        self.assertEqual(h.rejects, [])

    def test_incoming_busy_or_removed_dialog_still_emits_late_ended_state(self):
        for name, raw in self.images.items():
            for base in BASES:
                for direction in (None, 1):
                    for code in (480, 486, 603):
                        with self.subTest(image=name, base=hex(base), direction=direction, code=code):
                            h = CallRejectionHarness(raw, base)
                            messages, busy = h.end_call(direction, code=code)
                            self.assertIn(0xd4af6, h.trace)
                            self.assertIn(0xcc2c4, h.trace)
                            self.assertEqual(busy, 0)
                            self.assertEqual([decode_message(bytes.fromhex(m)) for m in messages],
                                             [(0xa01, {0xa02: 0x80000002, 0xa03: 0})])

    def test_outgoing_busy_retains_distinct_deferred_disconnect_path(self):
        for base in BASES:
            for code in (480, 486, 603):
                with self.subTest(base=hex(base), code=code):
                    h = CallRejectionHarness(self.images['r48_telecom'], base)
                    messages, busy = h.end_call(0, code=code)
                    self.assertEqual(busy, 0x80000002)
                    self.assertNotIn(0xcc2c4, h.trace)
                    self.assertEqual([decode_message(bytes.fromhex(m)) for m in messages],
                                     [(0xa03, {0xa02: 0x80000002, 0xa04: 2, 0xa2b: 0xe})])


if __name__ == '__main__':
    unittest.main()
