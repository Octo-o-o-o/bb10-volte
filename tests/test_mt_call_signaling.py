"""Cross-carrier MT call signaling checks and ARM/Thumb emulation."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'device'), str(ROOT / 'tools')]
import carrier_policy as policy
import ims_image
import service
import unified_service as unified

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (
        UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
        UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
        UC_ARM_REG_R6, UC_ARM_REG_R9, UC_ARM_REG_SP,
    )
except ModuleNotFoundError as error:
    if error.name != 'unicorn':
        raise
    Uc = None


def local_stock_binary():
    env_path = os.environ.get('BB10_STOCK_IMS_RRM')
    candidates = ([Path(env_path)] if env_path else []) + [
        ROOT.parents[1] / 'research/volte_session/radio-inspection/ims_rrm',
    ]
    for candidate in candidates:
        if candidate.is_file():
            raw = candidate.read_bytes()
            if hashlib.sha256(raw).hexdigest() == ims_image.STOCK_SHA:
                return raw
    return None


STOCK_RAW = local_stock_binary()


class MtSignalingSelectionTests(unittest.TestCase):
    def test_mt_voice_binary_requires_normal_voice_and_explicit_sms_flag(self):
        with self.assertRaises(AssertionError):
            ims_image.mt_voice_binary(b'unknown', False)
        with self.assertRaisesRegex(AssertionError, 'explicit'):
            ims_image.mt_voice_binary(b'unknown', True, sms_ack='yes')
        with self.assertRaisesRegex(AssertionError, 'Unknown stock IMS binary'):
            ims_image.mt_voice_binary(b'unknown', True, sms_ack=False)

    def test_mt_voice_binary_patches_both_early_sdp_and_omit_200_ok_sdp(self):
        fake = bytearray(0x370000)
        fake[0xb8e9c:0xb8ea0] = b'\x01\x21\x78\x44'
        fake[0xb8eb0:0xb8eb4] = b'\x02\x21\x78\x44'
        expected = bytearray(fake)
        expected[0xb8e9c] = 0
        expected[0xb8eb0] = 0
        expected_sha = hashlib.sha256(bytes(expected)).hexdigest()
        real_sha256 = ims_image.hashlib.sha256

        class ProxyDigest:
            def __init__(self, data=b''):
                self._inner = real_sha256(data)

            def hexdigest(self):
                digest = self._inner.hexdigest()
                if digest == expected_sha:
                    return '7479b023d634c1afddd46203251ec7613ab5170d8ea22d6e321c7dd7fc3e7411'
                return digest

        with patch.object(ims_image, '_voice_binary', return_value=(bytes(fake), [{'base': True}])), \
                patch.object(ims_image.hashlib, 'sha256', side_effect=ProxyDigest), \
                patch.object(ims_image, 'sms_ack_binary', side_effect=lambda raw, meta: (raw + b'!', meta)) as shim:
            voice_only, patches = ims_image.mt_voice_binary(b'stock', True, sms_ack=False)
            self.assertEqual(voice_only, bytes(expected))
            self.assertEqual([item.get('config_key') for item in patches[1:]],
                             ['MediaDialog.Omit200OkSdp', 'MediaDialog.EarlySdp'])
            shim.assert_not_called()
            with_sms, sms_patches = ims_image.mt_voice_binary(b'stock', True, sms_ack=True)
            self.assertEqual(with_sms, bytes(expected) + b'!')
            self.assertEqual(sms_patches, patches)
            shim.assert_called_once()

    def test_standalone_and_unified_services_select_mt_voice_binary_for_all_carriers(self):
        import unified_migrate as migration
        self.assertIs(service.temporary_binary, ims_image.mt_voice_binary)
        saved = (
            unified.selected,
            unified.s.ACTIVE_REQUEST,
            unified.s.ACTIVE_PROFILE,
            dict(unified.s.UPDATES),
            unified.s.temporary_binary,
            unified.s.j,
        )
        facts = {'variant': 'SQW100-4', 'os_version': policy.OS_VERSION,
                 'board_type': policy.MODELS['SQW100-4'][1]}
        try:
            for mnc, expected_operator in (('11', 'telecom'), ('01', 'unicom'),
                                           ('00', 'mobile'), ('07', 'mobile')):
                sim = {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': mnc,
                       'imsi': '460' + mnc + '1234512345'}
                with self.subTest(mnc=mnc, operator=expected_operator), ExitStack() as stack:
                    unified.s.temporary_binary = ims_image.temporary_binary
                    for ctx in (
                        patch.object(unified, 'verify', return_value=facts),
                        patch.object(unified.os.path, 'isfile', return_value=False),
                        patch.object(unified, 'boot_token', return_value=['boot-1']),
                        patch.object(unified.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
                        patch.object(unified, 'handoff'),
                        patch.object(migration, 'finish_previous_boot'),
                        patch.object(unified, 'reconcile'),
                        patch.object(unified, 'core_stopping', return_value=False),
                        patch.object(unified, 'card', return_value=sim),
                        patch.object(unified.profiles, 'carrier_template',
                                     return_value=({'path': '/etc/carrier/config/404.xml', 'sha256': 'a' * 64}, b'<xml/>')),
                        patch.object(unified.s, 'profile_updates', return_value={}),
                        patch.object(unified, 'save'),
                        patch.object(unified, 'notify_sim_change'),
                        patch.object(unified.s, 'init_journal'),
                        patch.object(unified.s, 'save_journal'),
                        patch.object(unified.s, 'status'),
                        patch.object(unified.s, 'wait_for_network', return_value=True),
                        patch.object(unified, 'reconcile_stale_sms_busy', return_value='out_of_scope'),
                        patch.object(unified.s, 'configure'),
                        patch.object(unified.n, 'ims_pids', return_value=[]),
                    ):
                        stack.enter_context(ctx)
                    import unified_dca
                    stack.enter_context(patch.object(unified_dca, 'prepare', return_value=True))
                    unified.s.j = {}
                    self.assertTrue(unified.prepare())
                    self.assertEqual(unified.selected['operator'], expected_operator)
                    self.assertIs(unified.s.temporary_binary, ims_image.mt_voice_binary)
        finally:
            (
                unified.selected,
                unified.s.ACTIVE_REQUEST,
                unified.s.ACTIVE_PROFILE,
                unified.s.UPDATES,
                unified.s.temporary_binary,
                unified.s.j,
            ) = saved


class MtDialogHarness:
    """Execute real Thumb-2 slices of ims_rrm with mocked external C++ edges."""

    EDGES = (
        0x15d658, 0x15d9a8, 0x1a0208, 0x1abe54, 0x1abe5a, 0x1abe60,
        0x19b616, 0x1b5dc4, 0x68ad8, 0x2195f4, 0x1ffebe, 0x1b6a5c,
        0x19c9b6, 0x1b5d8c, 0x1b5c3c, 0x1abba0, 0x174c80, 0x1ffd22,
        0x19ec54,
    )

    def __init__(self, elf_bytes, base=0x10000000):
        self.base = base
        self.heap = 0x70000000
        self.stack = 0x71020000
        self.stop = 0x7102f000
        self.config = {}
        self.content_types = []
        self.bodies_attached = 0
        self.last_18x_status = 180
        self.last_sdp_is_200_ok = False
        self.last_sdp_method = ''
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        size = (len(elf_bytes) + 0xffff) & ~0xffff
        self.uc.mem_map(base, size)
        self.uc.mem_map(self.heap, 0x100000)
        self.uc.mem_map(0x71000000, 0x40000)
        self.uc.mem_write(base, elf_bytes)
        for edge in self.EDGES:
            self.uc.mem_write(base + edge, b'\x70\x47')
        self.method_ptr = self._alloc(b'UPDATE\0')
        self.dialog = self._alloc(bytes(0xc00))
        self.uc.hook_add(UC_HOOK_CODE, self._hook)

    def _alloc(self, data):
        at = (self.heap + 7) & ~7
        self.heap = at + max(len(data), 8)
        self.uc.mem_write(at, data)
        return at

    def _cstr(self, address):
        out = bytearray()
        for index in range(256):
            byte = self.uc.mem_read(address + index, 1)[0]
            if not byte:
                return out.decode('ascii')
            out.append(byte)
        raise AssertionError('Unterminated C string')

    def _hook(self, uc, address, size, unused):
        if address == self.stop:
            uc.emu_stop()
            return
        offset = address - self.base
        if offset not in self.EDGES:
            return
        r0 = uc.reg_read(UC_ARM_REG_R0)
        r1 = uc.reg_read(UC_ARM_REG_R1)
        result = 0
        if offset == 0x15d658:
            self.config[self._cstr(r0)] = r1
        elif offset == 0x15d9a8:
            result = self.config.get(self._cstr(r0), r1)
        elif offset in (0x1a0208, 0x1b5dc4, 0x1ffebe, 0x1b5d8c):
            result = r0
        elif offset in (0x1abe54, 0x1abe5a, 0x1abe60, 0x19c9b6, 0x19ec54):
            result = 0
        elif offset == 0x19b616:
            result = 1
        elif offset == 0x68ad8:
            self.content_types.append(self._cstr(r1))
        elif offset == 0x2195f4:
            self.bodies_attached += 1
        elif offset == 0x1b6a5c:
            uc.mem_write(r0 + 4, struct.pack('<I', 1))
            result = r0
        elif offset == 0x1b5c3c:
            uc.mem_write(r0, struct.pack('<I', self.last_18x_status))
            result = r0
        elif offset == 0x1abba0:
            result = int(self.last_sdp_is_200_ok)
        elif offset == 0x174c80:
            result = self.method_ptr
        elif offset == 0x1ffd22:
            needle = self._cstr(r1)
            result = 0 if needle in self.last_sdp_method else 0xffffffff
        uc.reg_write(UC_ARM_REG_R0, result)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def _run_slice(self, start, end, regs=None):
        self.stop = self.base + end
        self.content_types = []
        self.bodies_attached = 0
        self.uc.reg_write(UC_ARM_REG_SP, self.stack)
        self.uc.reg_write(UC_ARM_REG_LR, (self.base + end) | 1)
        for reg, val in (regs or {}).items():
            self.uc.reg_write(reg, val)
        self.uc.emu_start(self.base + (start | 1), self.base + end, timeout=2000000, count=100000)
        assert self.uc.reg_read(UC_ARM_REG_PC) == self.base + end

    def load_stack_defaults(self):
        self._run_slice(0xb8e90, 0xb8ec2)
        return dict(self.config)

    def run_180_ringing_sdp(self, precondition_level, last_18x_present):
        self.uc.mem_write(self.dialog + 0xa78, struct.pack('<I', int(bool(last_18x_present))))
        self._run_slice(0x1a566e, 0x1a57f0, {
            UC_ARM_REG_R4: self.dialog,
            UC_ARM_REG_R6: precondition_level,
            UC_ARM_REG_R9: 0,
        })
        return {'content_types': list(self.content_types), 'bodies': self.bodies_attached}

    def run_200_ok_precondition(self):
        self.uc.mem_write(self.dialog + 0xe0, struct.pack('<I', 0xd))
        self._run_slice(0x1a8cc4, 0x1a8d2c, {
            UC_ARM_REG_R3: 0xd,
            UC_ARM_REG_R4: self.dialog,
        })
        state = struct.unpack('<I', self.uc.mem_read(self.dialog + 0xe0, 4))[0]
        return {'sdp_state': state, 'content_types': list(self.content_types), 'bodies': self.bodies_attached}

    def run_200_ok_offer_received(self, last_18x_present=False, last_18x_status=180,
                                  early_update_200_ok=False):
        self.last_18x_status = last_18x_status
        self.last_sdp_is_200_ok = early_update_200_ok
        self.last_sdp_method = 'UPDATE' if early_update_200_ok else ''
        self.uc.mem_write(self.dialog + 0xe0, struct.pack('<I', 0xb))
        self.uc.mem_write(self.dialog + 0xa6c, struct.pack('<I', int(bool(early_update_200_ok))))
        self.uc.mem_write(self.dialog + 0xa78, struct.pack('<I', int(bool(last_18x_present))))
        self._run_slice(0x1a9034, 0x1a9300, {
            UC_ARM_REG_R4: self.dialog,
            UC_ARM_REG_R5: 1,
        })
        return {'content_types': list(self.content_types), 'bodies': self.bodies_attached}


@unittest.skipIf(Uc is None or STOCK_RAW is None, 'Requires optional unicorn and local stock ims_rrm')
class MtSignalingMachineCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r44_unicom_telecom = ims_image.temporary_binary(STOCK_RAW, True, sms_ack=True)[0]
        cls.r44_mobile = ims_image.mobile_binary(STOCK_RAW, True, sms_ack=True)[0]
        cls.r45_unified = ims_image.mt_voice_binary(STOCK_RAW, True, sms_ack=True)[0]

    def test_stack_configure_registers_expected_media_dialog_flags(self):
        legacy = MtDialogHarness(self.r44_unicom_telecom).load_stack_defaults()
        mobile = MtDialogHarness(self.r44_mobile).load_stack_defaults()
        unified_cfg = MtDialogHarness(self.r45_unified).load_stack_defaults()
        self.assertEqual(legacy['MediaDialog.EarlySdp'], 2)
        self.assertEqual(legacy['MediaDialog.Omit200OkSdp'], 1)
        self.assertEqual(mobile['MediaDialog.EarlySdp'], 0)
        self.assertEqual(mobile['MediaDialog.Omit200OkSdp'], 1)
        self.assertEqual(unified_cfg['MediaDialog.PrackSDP'], 0)
        self.assertEqual(unified_cfg['MediaDialog.Send183Before180'], 1)
        self.assertEqual(unified_cfg['MediaDialog.EarlySdp'], 0)
        self.assertEqual(unified_cfg['MediaDialog.Omit200OkSdp'], 0)
        self.assertEqual(unified_cfg['MediaDialog.Timer'], 1)

    def test_precondition_and_non_precondition_180_ringing_no_longer_attach_sdp(self):
        legacy = MtDialogHarness(self.r44_unicom_telecom)
        legacy.load_stack_defaults()
        fixed = MtDialogHarness(self.r45_unified)
        fixed.load_stack_defaults()

        # Precondition MT call after 183 Session Progress: r44 Telecom/Unicom
        # re-attached SDP in 180 Ringing (triggering ZTE SBC/TAS immediate drop
        # or regional CAT AS muted ringback); r45 omits SDP in 180 Ringing.
        self.assertEqual(legacy.run_180_ringing_sdp(precondition_level=2, last_18x_present=True),
                         {'content_types': ['application/sdp'], 'bodies': 1})
        self.assertEqual(fixed.run_180_ringing_sdp(precondition_level=2, last_18x_present=True),
                         {'content_types': [], 'bodies': 0})

        # Non-precondition MT call (unreliable 180 Ringing): r44 Telecom/Unicom
        # attached preview SDP in 180; r45 omits preview SDP so caller hears ringback.
        self.assertEqual(legacy.run_180_ringing_sdp(precondition_level=0, last_18x_present=False),
                         {'content_types': ['application/sdp'], 'bodies': 1})
        self.assertEqual(fixed.run_180_ringing_sdp(precondition_level=0, last_18x_present=False),
                         {'content_types': [], 'bodies': 0})

    def test_200_ok_preserves_empty_precondition_path_and_mandatory_offer_answer_sdp(self):
        legacy = MtDialogHarness(self.r44_unicom_telecom)
        legacy.load_stack_defaults()
        mobile = MtDialogHarness(self.r44_mobile)
        mobile.load_stack_defaults()
        fixed = MtDialogHarness(self.r45_unified)
        fixed.load_stack_defaults()

        # Standard precondition call (SDPState 0xd -> 0x14): empty 200 OK unchanged.
        self.assertEqual(legacy.run_200_ok_precondition(),
                         {'sdp_state': 0x14, 'content_types': [], 'bodies': 0})
        self.assertEqual(fixed.run_200_ok_precondition(),
                         {'sdp_state': 0x14, 'content_types': [], 'bodies': 0})

        # Unreliable 180 with SDP in SDPState 0xb: r44 omitted mandatory 200 OK SDP; r45 keeps it.
        self.assertEqual(legacy.run_200_ok_offer_received(last_18x_present=True, last_18x_status=180),
                         {'content_types': [], 'bodies': 0})
        self.assertEqual(fixed.run_200_ok_offer_received(last_18x_present=True, last_18x_status=180),
                         {'content_types': ['application/sdp'], 'bodies': 1})

        # Early UPDATE 200 OK while initial INVITE is still in SDPState 0xb:
        # both r44 Telecom/Unicom and r44 Mobile omitted mandatory 200 OK (INVITE) SDP; r45 keeps it.
        self.assertEqual(legacy.run_200_ok_offer_received(early_update_200_ok=True),
                         {'content_types': [], 'bodies': 0})
        self.assertEqual(mobile.run_200_ok_offer_received(early_update_200_ok=True),
                         {'content_types': [], 'bodies': 0})
        self.assertEqual(fixed.run_200_ok_offer_received(early_update_200_ok=True),
                         {'content_types': ['application/sdp'], 'bodies': 1})


if __name__ == '__main__':
    unittest.main()
