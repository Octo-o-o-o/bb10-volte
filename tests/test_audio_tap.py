"""Offline Unicorn verification for the opt-in PCM ring buffer in ims_image.py."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'device') not in sys.path:
    sys.path.insert(0, str(ROOT / 'device'))
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))

import ims_image as image
import build_audio_tap

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (
        UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP,
        UC_ARM_REG_LR, UC_ARM_REG_PC,
    )
except ImportError:
    Uc = None

PLT_READ = 0x5b028
PLT_PARAMS = 0x5b8c8
PLT_WRITE = 0x5c8a8


class AudioTapEmulator:
    def __init__(self, base=0x10000000):
        self.base = base
        self.heap = 0x70000000
        self.stack = 0x71010000
        self.stop = 0x71020000
        self.params_rc = 0
        self.read_data = b''
        self.read_rc = 0
        self.write_rc = 0
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(base, 0x600000)
        self.uc.mem_map(self.heap, 0x100000)
        self.uc.mem_map(0x71000000, 0x30000)
        self.uc.mem_write(base + image.AUDIO_TAP_CODE_VA, image.AUDIO_TAP_CODE)
        for plt in (PLT_READ, PLT_PARAMS, PLT_WRITE):
            self.uc.mem_write(base + plt, b'\x1e\xff\x2f\xe1')  # ARM: bx lr
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)

    def alloc(self, raw):
        addr = (self.heap + 7) & ~7
        self.heap = addr + len(raw) + 16
        self.uc.mem_write(addr, raw)
        return addr

    def _on_code(self, uc, address, size, unused):
        if address == self.stop:
            uc.emu_stop()
            return
        offset = address - self.base
        if offset == PLT_PARAMS:
            uc.reg_write(UC_ARM_REG_R0, self.params_rc & 0xffffffff)
        elif offset == PLT_READ:
            buf = uc.reg_read(UC_ARM_REG_R1)
            if self.read_rc > 0 and self.read_data:
                uc.mem_write(buf, self.read_data[:self.read_rc])
            uc.reg_write(UC_ARM_REG_R0, self.read_rc & 0xffffffff)
        elif offset == PLT_WRITE:
            uc.reg_write(UC_ARM_REG_R0, self.write_rc & 0xffffffff)

    def call_thumb(self, va, r0=0, r1=0, r2=0, stop_at=None):
        self.uc.reg_write(UC_ARM_REG_SP, self.stack)
        self.uc.reg_write(UC_ARM_REG_LR, self.stop)
        self.uc.reg_write(UC_ARM_REG_R0, r0)
        self.uc.reg_write(UC_ARM_REG_R1, r1)
        self.uc.reg_write(UC_ARM_REG_R2, r2)
        self.uc.emu_start(self.base + (va | 1), stop_at if stop_at is not None else self.stop, count=200000)
        raw = self.uc.reg_read(UC_ARM_REG_R0)
        return raw - 0x100000000 if raw & 0x80000000 else raw

    def ring_header(self, ring_offset):
        raw = bytes(self.uc.mem_read(self.base + image.AUDIO_TAP_BSS_VA + ring_offset, 32))
        return struct.unpack('<8I', raw)

    def ring_pcm(self, ring_offset, pos, length):
        base_addr = self.base + image.AUDIO_TAP_BSS_VA + ring_offset + 32
        out = bytearray()
        for i in range(length):
            idx = (pos + i) & 0xffff
            out.extend(self.uc.mem_read(base_addr + idx, 1))
        return bytes(out)


class AudioTapManifestTests(unittest.TestCase):
    def test_generated_manifest_matches_module(self):
        value = build_audio_tap.check_generated(ROOT)
        self.assertEqual(value['bss_va'], 0x4b0000)
        self.assertEqual(value['code_va'], 0x530000)
        desc = struct.unpack_from('<8s6I', image.AUDIO_TAP_CODE, 0)
        self.assertEqual(desc, (b'BB10ATAP', 1, 0x4b0000, 65536, 0x10, 0x10030, 0))

    def test_service_audio_tap_flag_validation(self):
        import service as s
        old_base = s.BASE
        with tempfile.TemporaryDirectory() as tmp:
            try:
                s.BASE = tmp
                self.assertFalse(s.audio_tap_requested())
                flag = Path(tmp) / 'audio-tap.json'
                flag.write_bytes(b'{"schema":1,"enabled":true}\n')
                os.chmod(flag, 0o600)
                if hasattr(os, 'geteuid') and os.geteuid() == 0:
                    self.assertTrue(s.audio_tap_requested())
            finally:
                s.BASE = old_base


@unittest.skipIf(Uc is None, 'Unicorn is required for ARM Thumb-2 emulation')
class AudioTapEmulationTests(unittest.TestCase):
    def test_params_read_write_and_wrap_across_aslr_bases(self):
        for base in (0x08000000, 0x13579000, 0x24680000):
            with self.subTest(base=hex(base)):
                emu = AudioTapEmulator(base=base)
                params = bytearray(752)
                struct.pack_into('<iii', params, 0x1c, 4, 16000, 1)
                params_ptr = emu.alloc(bytes(params))

                emu.params_rc = -22
                self.assertEqual(emu.call_thumb(image.AUDIO_TAP_MIC_PARAMS, 0x111, params_ptr), -22)
                self.assertEqual(emu.ring_header(0x10)[5], 0)

                emu.params_rc = 0
                self.assertEqual(emu.call_thumb(image.AUDIO_TAP_MIC_PARAMS, 0x111, params_ptr), 0)
                struct.pack_into('<iii', params, 0x1c, 4, 8000, 1)
                spk_ptr = emu.alloc(bytes(params))
                self.assertEqual(emu.call_thumb(image.AUDIO_TAP_SPK_PARAMS, 0x222, spk_ptr), 0)

                tx_hdr = emu.ring_header(0x10)
                rx_hdr = emu.ring_header(0x10030)
                self.assertEqual((tx_hdr[2], tx_hdr[3], tx_hdr[4], tx_hdr[5]), (16000, 1, 4, 1))
                self.assertEqual((rx_hdr[2], rx_hdr[3], rx_hdr[4], rx_hdr[5]), (8000, 1, 4, 1))

                # Drive > 64 KiB of uplink PCM to exercise circular wrap-around.
                read_buf = emu.alloc(bytes(1024))
                stream = bytearray()
                for step in range(68):
                    chunk = bytes(((step + i) & 0xff) for i in range(1000))
                    emu.read_data = chunk
                    emu.read_rc = 1000
                    rc = emu.call_thumb(image.AUDIO_TAP_READ, 0x111, read_buf, 1000)
                    self.assertEqual(rc, 1000)
                    stream.extend(chunk)
                tx_hdr = emu.ring_header(0x10)
                self.assertEqual(tx_hdr[0], tx_hdr[7])
                self.assertEqual(tx_hdr[1], 68000)
                self.assertEqual(tx_hdr[6], 68)
                # Last 4000 bytes spanning the 65536 wrap boundary must match exactly.
                tail_start = 68000 - 4000
                self.assertEqual(emu.ring_pcm(0x10, tail_start, 4000), bytes(stream[tail_start:]))

                # Partial write: requested 640, hardware accepted 320.
                tx_sample = bytes((i & 0xff) for i in range(640))
                write_buf = emu.alloc(tx_sample)
                emu.write_rc = 320
                self.assertEqual(emu.call_thumb(image.AUDIO_TAP_WRITE, 0x222, write_buf, 640), 320)
                rx_hdr = emu.ring_header(0x10030)
                self.assertEqual(rx_hdr[0], rx_hdr[7])
                self.assertEqual(rx_hdr[1], 320)
                self.assertEqual(emu.ring_pcm(0x10030, 0, 320), tx_sample[:320])

                # Negative read/write error leaves ring unchanged.
                emu.read_rc = -11
                self.assertEqual(emu.call_thumb(image.AUDIO_TAP_READ, 0x111, read_buf, 640), -11)
                self.assertEqual(emu.ring_header(0x10)[1], 68000)

    def test_full_ims_image_callsites_when_stock_provided(self):
        stock_env = os.environ.get('BB10_STOCK_IMS_RRM')
        if not stock_env or not Path(stock_env).is_file():
            self.skipTest('Set BB10_STOCK_IMS_RRM to run full ELF callsite verification')
        stock = Path(stock_env).read_bytes()
        base_general, _ = image.mt_voice_binary(stock, True, sms_ack=True, telecom_mo_ack=False, audio_tap=False)
        base_default, _ = image.mt_voice_binary(stock, True, sms_ack=True, telecom_mo_ack=False)
        self.assertEqual(base_general, base_default)
        for telecom in (False, True):
            with self.subTest(telecom=telecom):
                patched, meta = image.mt_voice_binary(stock, True, sms_ack=True,
                                                      telecom_mo_ack=telecom, audio_tap=True)
                self.assertEqual(meta[-1]['function'], 'ImsAudioImpl passive PCM ring buffer')
                emu = AudioTapEmulator(base=0x08000000)
                for site in (0x7f7d8, 0x7fa92, 0x7fdac, 0x8078a):
                    emu.uc.mem_write(0x08000000 + site, patched[site:site + 4])
                params = bytearray(752)
                struct.pack_into('<iii', params, 0x1c, 4, 16000, 1)
                p_ptr = emu.alloc(bytes(params))
                self.assertEqual(emu.call_thumb(0x7f7d8, 1, p_ptr, stop_at=0x08000000 + 0x7f7dc), 0)
                self.assertEqual(emu.call_thumb(0x7fa92, 2, p_ptr, stop_at=0x08000000 + 0x7fa96), 0)
                pcm = bytes((i & 0xff) for i in range(640))
                b_ptr = emu.alloc(pcm)
                emu.read_data = pcm
                emu.read_rc = 640
                emu.write_rc = 640
                self.assertEqual(emu.call_thumb(0x8078a, 1, b_ptr, 640, stop_at=0x08000000 + 0x8078e), 640)
                self.assertEqual(emu.call_thumb(0x7fdac, 2, b_ptr, 640, stop_at=0x08000000 + 0x7fdb0), 640)
                self.assertEqual(emu.ring_pcm(0x10, 0, 640), pcm)
                self.assertEqual(emu.ring_pcm(0x10030, 0, 640), pcm)


if __name__ == '__main__':
    unittest.main()
