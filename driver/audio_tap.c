/* SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
 * Passive, zero-syscall VoLTE PCM ring-buffer tap for the hash-pinned BB10
 * 10.3.3.3216 ims_rrm temporary image (opt-in only; stock behavior when off).
 *
 * Hooks the only four QSA PLT call sites in ImsAudioImpl (ImsAudio.cpp):
 *   - 0x07f7d8: configMic                 -> snd_pcm_plugin_params (0x5b8c8)
 *   - 0x07fa92: configSpeaker             -> snd_pcm_plugin_params (0x5b8c8)
 *   - 0x07fdac: ImsAudioImpl::process     -> snd_pcm_plugin_write  (0x5c8a8)
 *   - 0x08078a: AudioCaptureThreadInternal -> snd_pcm_plugin_read  (0x5b028)
 *
 * Safety invariants:
 *   1. Zero syscalls, zero locks, zero file descriptors, zero dynamic memory.
 *   2. ims_rrm writes only into its own .bss ring buffer; external Root
 *      recorder reads /proc/<pid>/as with O_RDONLY and never writes memory.
 *   3. Original QSA return values and errno are preserved bit-for-bit.
 */
typedef unsigned int u32;
typedef int s32;
typedef unsigned char u8;
typedef char check_u32[sizeof(u32) == 4 ? 1 : -1];

#define AUDIO_TAP_CODE_VA 0x530000u
#define AUDIO_TAP_ANCHOR_VA 0x530020u
#define AUDIO_TAP_BSS_VA 0x4b0000u
#define AUDIO_TAP_RING_BYTES 65536u
#define AUDIO_TAP_RING_MASK (AUDIO_TAP_RING_BYTES - 1u)
#define AUDIO_TAP_MAX_CHUNK 4096u

#define PLT_SND_PCM_PLUGIN_READ 0x5b028u
#define PLT_SND_PCM_PLUGIN_PARAMS 0x5b8c8u
#define PLT_SND_PCM_PLUGIN_WRITE 0x5c8a8u

extern __attribute__((visibility("hidden"))) void audio_tap_anchor(void);

struct audio_tap_descriptor {
    char magic[8];      /* "BB10ATAP" */
    u32 schema;         /* 1 */
    u32 bss_va;         /* 0x4b0000 */
    u32 ring_bytes;     /* 65536 */
    u32 tx_offset;      /* offset of tx ring from bss_va (16) */
    u32 rx_offset;      /* offset of rx ring from bss_va (16 + sizeof(ring)) */
    u32 reserved;       /* 0 */
};

struct audio_tap_ring {
    volatile u32 seq_pre;       /* +0x00: incremented before PCM copy */
    volatile u32 total_bytes;   /* +0x04: monotonic byte counter (mod 2^32) */
    volatile u32 sample_rate;   /* +0x08: negotiated PCM rate (8000 / 16000) */
    volatile u32 channels;      /* +0x0c: negotiated channel count (1 / 2) */
    volatile u32 format;        /* +0x10: QSA format code (4 = S16_LE) */
    volatile u32 session_count; /* +0x14: incremented on successful params */
    volatile u32 chunk_count;   /* +0x18: number of PCM chunks captured */
    volatile u32 seq_post;      /* +0x1c: matches seq_pre after total_bytes */
    u8 pcm[AUDIO_TAP_RING_BYTES];
};

struct audio_tap_state {
    volatile u32 magic0;        /* 0x30314242 ('BB10' LE) */
    volatile u32 magic1;        /* 0x50415441 ('ATAP' LE) */
    volatile u32 schema;        /* 1 */
    volatile u32 ring_bytes;    /* 65536 */
    struct audio_tap_ring tx;   /* +0x10: uplink (microphone -> encoder) */
    struct audio_tap_ring rx;   /* +0x10030: downlink (decoder -> speaker) */
};

typedef char check_ring_size[sizeof(struct audio_tap_ring) == 0x10020 ? 1 : -1];
typedef char check_state_size[sizeof(struct audio_tap_state) == 0x20050 ? 1 : -1];

__attribute__((section(".rodata.descriptor"), used, visibility("hidden")))
const struct audio_tap_descriptor audio_tap_desc = {
    {'B', 'B', '1', '0', 'A', 'T', 'A', 'P'},
    1u,
    AUDIO_TAP_BSS_VA,
    AUDIO_TAP_RING_BYTES,
    0x10u,
    0x10030u,
    0u
};

static __attribute__((section(".bss.tap"), used))
struct audio_tap_state tap_state;

static u32 runtime_bias(void) {
    return ((u32)&audio_tap_anchor & ~1u) - AUDIO_TAP_ANCHOR_VA;
}

#define NATIVE_FN(type, address) ((type)(runtime_bias() + (address)))

static void init_header_once(void) {
    if (tap_state.magic0 != 0x30314242u) {
        tap_state.schema = 1u;
        tap_state.ring_bytes = AUDIO_TAP_RING_BYTES;
        tap_state.magic1 = 0x50415441u;
        __sync_synchronize();
        tap_state.magic0 = 0x30314242u;
    }
}

static void record_params(struct audio_tap_ring *ring, const u8 *params) {
    u32 fmt, rate, voices;
    if (!params) return;
    /* BB10 QSA snd_pcm_channel_params_t (ARM EABI, 752 bytes):
     *   +0x1c: format.format (int32, 4 = S16_LE)
     *   +0x20: format.rate   (int32, e.g. 8000 or 16000)
     *   +0x24: format.voices (int32, e.g. 1 or 2)
     */
    fmt = *(const u32 *)(params + 0x1cu);
    rate = *(const u32 *)(params + 0x20u);
    voices = *(const u32 *)(params + 0x24u);
    init_header_once();
    ring->format = fmt;
    ring->sample_rate = rate;
    ring->channels = voices;
    __sync_synchronize();
    ring->session_count = ring->session_count + 1u;
}

static void append_pcm(struct audio_tap_ring *ring, const u8 *src, u32 count) {
    u32 seq, pos, offset, first, i;
    if (!src || !count) return;
    if (count > AUDIO_TAP_MAX_CHUNK) count = AUDIO_TAP_MAX_CHUNK;
    init_header_once();
    seq = ring->seq_pre + 1u;
    ring->seq_pre = seq;
    __sync_synchronize();
    pos = ring->total_bytes;
    offset = pos & AUDIO_TAP_RING_MASK;
    first = AUDIO_TAP_RING_BYTES - offset;
    if (first > count) first = count;
    for (i = 0u; i < first; ++i) {
        ring->pcm[offset + i] = src[i];
    }
    for (i = 0u; i < count - first; ++i) {
        ring->pcm[i] = src[first + i];
    }
    __sync_synchronize();
    ring->total_bytes = pos + count;
    ring->chunk_count = ring->chunk_count + 1u;
    __sync_synchronize();
    ring->seq_post = seq;
}

__attribute__((visibility("hidden")))
s32 audio_mic_params(void *handle, const u8 *params) {
    s32 rc = NATIVE_FN(s32 (*)(void *, const void *), PLT_SND_PCM_PLUGIN_PARAMS)(handle, params);
    if (rc == 0) record_params(&tap_state.tx, params);
    return rc;
}

__attribute__((visibility("hidden")))
s32 audio_spk_params(void *handle, const u8 *params) {
    s32 rc = NATIVE_FN(s32 (*)(void *, const void *), PLT_SND_PCM_PLUGIN_PARAMS)(handle, params);
    if (rc == 0) record_params(&tap_state.rx, params);
    return rc;
}

__attribute__((visibility("hidden")))
s32 audio_read(void *handle, u8 *buffer, u32 requested) {
    s32 rc = NATIVE_FN(s32 (*)(void *, void *, u32), PLT_SND_PCM_PLUGIN_READ)(handle, buffer, requested);
    if (rc > 0 && buffer) {
        u32 got = (u32)rc;
        if (got > requested) got = requested;
        append_pcm(&tap_state.tx, buffer, got);
    }
    return rc;
}

__attribute__((visibility("hidden")))
s32 audio_write(void *handle, const u8 *buffer, u32 requested) {
    s32 rc = NATIVE_FN(s32 (*)(void *, const void *, u32), PLT_SND_PCM_PLUGIN_WRITE)(handle, buffer, requested);
    if (rc > 0 && buffer) {
        u32 written = (u32)rc;
        if (written > requested) written = requested;
        append_pcm(&tap_state.rx, buffer, written);
    }
    return rc;
}

/* Thumb BL replacements preserve AAPCS 8-byte stack alignment and callee-saved
 * registers. Descriptor sits at 0x530000..0x53001f (32 bytes); anchor is placed
 * at 0x530020 by the linker script. Wait: keep AUDIO_TAP_ANCHOR_VA synced!
 */
__asm__(
    ".syntax unified\n.thumb\n"
    ".section .text.anchor,\"ax\",%progbits\n"
    ".global audio_tap_anchor\n.hidden audio_tap_anchor\n.type audio_tap_anchor,%function\n.thumb_func\n"
    "audio_tap_anchor:\n bx lr\n.size audio_tap_anchor,.-audio_tap_anchor\n"
    ".section .text.audio_mic_params_hook,\"ax\",%progbits\n"
    ".global audio_mic_params_hook\n.hidden audio_mic_params_hook\n.type audio_mic_params_hook,%function\n.thumb_func\n"
    "audio_mic_params_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    "bl audio_mic_params\n pop {r4,pc}\n.fnend\n.size audio_mic_params_hook,.-audio_mic_params_hook\n"
    ".section .text.audio_spk_params_hook,\"ax\",%progbits\n"
    ".global audio_spk_params_hook\n.hidden audio_spk_params_hook\n.type audio_spk_params_hook,%function\n.thumb_func\n"
    "audio_spk_params_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    "bl audio_spk_params\n pop {r4,pc}\n.fnend\n.size audio_spk_params_hook,.-audio_spk_params_hook\n"
    ".section .text.audio_read_hook,\"ax\",%progbits\n"
    ".global audio_read_hook\n.hidden audio_read_hook\n.type audio_read_hook,%function\n.thumb_func\n"
    "audio_read_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    "bl audio_read\n pop {r4,pc}\n.fnend\n.size audio_read_hook,.-audio_read_hook\n"
    ".section .text.audio_write_hook,\"ax\",%progbits\n"
    ".global audio_write_hook\n.hidden audio_write_hook\n.type audio_write_hook,%function\n.thumb_func\n"
    "audio_write_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    "bl audio_write\n pop {r4,pc}\n.fnend\n.size audio_write_hook,.-audio_write_hook\n"
);
