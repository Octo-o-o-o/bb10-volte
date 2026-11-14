/* SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
 * Correlate raw 3GPP MT reports in the hash-pinned BB10 10.3.3.3216 IMS image,
 * and synthesize local 3GPP MO RP-ACK after SIP 2xx on China Telecom (460-03/11)
 * where the IP-SM-GW returns 202 Accepted without a downstream SIP RP-ACK.
 * Native addresses/ABI are documented in docs/SMS-ACK-NATIVE.md.
 */
typedef unsigned int u32;
typedef unsigned char u8;
typedef char check_u32[sizeof(u32) == 4 ? 1 : -1];

#define CODE_VA 0x500000u
#define SLOTS 32u
#define MO_SLOTS 16u
#define MO_STAGED 8u
#define HEADER_MAX 512u
#define RP_MAX 255u
#define TTL_SECONDS 180u

extern __attribute__((visibility("hidden"))) void sms_anchor(void);
struct entry {
    u32 owner, reference, at, ambiguous, rp_size, epoch;
    char call_id[HEADER_MAX], gateway[HEADER_MAX];
    u8 rp[RP_MAX];
};
static __attribute__((section(".bss.cache"))) struct {
    volatile u32 lock, epoch;
    u32 captured, correlated, conflict, missing, malformed, full;
    struct entry entries[SLOTS];
} cache;

struct mo_entry {
    u32 used, reference, at;
    char call_id[HEADER_MAX];
};
struct mo_stage {
    u32 used, engine, pdu_id, reference, at;
};
static struct {
    volatile u32 lock;
    u32 captured, popped, synthesized, conflict, full;
    struct mo_entry entries[MO_SLOTS];
    struct mo_stage pending[MO_STAGED];
} mo_cache;

static u32 base(void) { return ((u32)&sms_anchor & ~1u) - CODE_VA; }
#define NATIVE(type, address) ((type)(base() + (address)))

static void copy(void *dst, const void *src, u32 count) {
    u8 *d = dst; const u8 *s = src;
    while (count--) *d++ = *s++;
}
static void zero(void *dst, u32 count) {
    volatile u8 *d = dst;
    while (count--) *d++ = 0;
}
static int equal(const void *a, const void *b, u32 count) {
    const u8 *x = a, *y = b;
    while (count--) if (*x++ != *y++) return 0;
    return 1;
}
static u32 length(const char *s, u32 limit) {
    u32 i;
    if (!s) return limit;
    for (i = 0; i < limit && s[i]; ++i) {}
    return i;
}
static int same(const char *a, const char *b) {
    u32 n = length(a, HEADER_MAX);
    return n < HEADER_MAX && n == length(b, HEADER_MAX) && equal(a, b, n);
}
static int lock(void) { return !__sync_lock_test_and_set(&cache.lock, 1); }
static void unlock(void) { __sync_lock_release(&cache.lock); }
static int mo_lock(void) { return !__sync_lock_test_and_set(&mo_cache.lock, 1); }
static void mo_unlock(void) { __sync_lock_release(&mo_cache.lock); }
/* A missed MT capture might reuse an old reference. Invalidate old snapshots
 * even if another thread holds the cache lock; never borrow stale context. */
static void missed_capture(void) { __sync_fetch_and_add(&cache.epoch, 1); }

/* The pinned native timer code uses clock_gettime(2, two 32-bit words).
 * Expiry also rejects backwards movement. Failure leaves stock behavior.
 */
static int now(u32 *seconds) {
    u32 stamp[2];
    int rc = NATIVE(int (*)(int, void *), 0x5b57c)(2, stamp); /* ARM PLT */
    if (rc || stamp[1] >= 1000000000u) return 0;
    *seconds = stamp[0];
    return 1;
}
static int current(const struct entry *e, u32 time) {
    return e->owner && e->epoch == cache.epoch && time >= e->at && time - e->at < TTL_SECONDS;
}
static int mo_live(u32 used, u32 at, u32 time) {
    return used && time >= at && time - at < TTL_SECONDS;
}

/* SAL header map lookup: { ..., String *values, int count }. String is one
 * data pointer. Require exactly one field value; never guess between IDs.
 */
static const char *single(void *message, const char *name) {
    u32 *array = NATIVE(u32 *(*)(void *, const char *), 0x16d14d)((u8 *)message + 8, name);
    if (!array || array[2] != 1 || !array[1]) return 0;
    return *(const char **)array[1];
}
static int is_3gpp(void *message) {
    const char *type = single(message, "Content-Type");
    const char expected[] = "application/vnd.3gpp.sms";
    u32 i, n = sizeof(expected) - 1, size = length(type, HEADER_MAX);
    if (size < n || size == HEADER_MAX) return 0;
    for (i = 0; i < n; ++i) {
        char c = type[i];
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c != expected[i]) return 0;
    }
    return !type[n] || type[n] == ';' || type[n] == ' ' || type[n] == '\t';
}
static int token(char *dst, const char *src) {
    u32 i, n = length(src, HEADER_MAX);
    if (!n || n == HEADER_MAX) return 0;
    for (i = 0; i < n; ++i)
        if ((u8)src[i] < 33 || (u8)src[i] > 126 || src[i] == ',') return 0;
    copy(dst, src, n + 1);
    return 1;
}
static int uri(char *dst, const char *src) {
    u32 i, start = 0, end, n = length(src, HEADER_MAX);
    if (!n || n == HEADER_MAX) return 0;
    for (i = 0; i < n; ++i)
        if (src[i] == '\r' || src[i] == '\n' || src[i] == ',') return 0;
    while (start < n && (src[start] == ' ' || src[start] == '\t')) ++start;
    end = n;
    for (i = start; i < n; ++i) if (src[i] == '<') { start = i + 1; break; }
    if (i < n) {
        for (end = start; end < n && src[end] != '>'; ++end) {}
        if (end == n) return 0;
        for (i = end + 1; i < n; ++i) if (src[i] != ' ' && src[i] != '\t') return 0;
    } else {
        while (end > start && (src[end - 1] == ' ' || src[end - 1] == '\t')) --end;
    }
    n = end - start;
    if (n < 5 || n >= HEADER_MAX) return 0;
    if (!(equal(src + start, "sip:", 4) || equal(src + start, "tel:", 4) ||
          (n > 5 && equal(src + start, "sips:", 5)))) return 0;
    for (i = start; i < end; ++i)
        if ((u8)src[i] < 33 || (u8)src[i] > 126 || src[i] == ',' ||
            src[i] == '<' || src[i] == '>' || src[i] == '"') return 0;
    copy(dst, src + start, n); dst[n] = 0;
    return 1;
}

/* The native raw receiver is shared by content types. Explicitly require
 * 3GPP here; capture before the callback can synchronously produce a report.
 */
__attribute__((visibility("hidden"))) void sms_capture(u32 owner, void *message) {
    struct entry candidate, *slot = 0;
    const u8 *rp = *(const u8 **)((u8 *)message + 0x20);
    u32 time, size, i, epoch;
    if (!owner || !rp || !is_3gpp(message)) return;
    size = NATIVE(u32 (*)(void *), 0x1ffa95)((u8 *)message + 0x20);
    if (size < 2 || rp[0] != 1) return;
    epoch = cache.epoch;
    if (size > RP_MAX || !now(&time)) { missed_capture(); return; }
    candidate.call_id[0] = candidate.gateway[0] = 0;
    if (!token(candidate.call_id, single(message, "Call-ID")) ||
        !uri(candidate.gateway, single(message, "P-Asserted-Identity"))) {
        /* Invalidate a matching live key even when this new MT is malformed. */
        if (lock()) {
            ++cache.malformed;
            for (i = 0; i < SLOTS; ++i)
                if (cache.entries[i].owner == owner && cache.entries[i].reference == rp[1])
                    cache.entries[i].ambiguous = 1;
            unlock();
        } else missed_capture();
        return;
    }
    if (!lock()) { missed_capture(); return; }
    if (epoch != cache.epoch) { unlock(); return; }
    for (i = 0; i < SLOTS; ++i) {
        struct entry *e = &cache.entries[i];
        if (!current(e, time)) { if (!slot) slot = e; continue; }
        if (e->owner != owner || e->reference != rp[1]) continue;
        if (e->ambiguous || !same(e->call_id, candidate.call_id) ||
            !same(e->gateway, candidate.gateway) || e->rp_size != size || !equal(e->rp, rp, size)) {
            e->ambiguous = 1; ++cache.conflict;
        }
        /* Retransmission does not extend the lifetime of a reference. */
        unlock(); return;
    }
    if (slot) {
        slot->owner = owner; slot->reference = rp[1]; slot->at = time;
        slot->ambiguous = 0; slot->rp_size = size; slot->epoch = epoch;
        copy(slot->call_id, candidate.call_id, length(candidate.call_id, HEADER_MAX) + 1);
        copy(slot->gateway, candidate.gateway, length(candidate.gateway, HEADER_MAX) + 1);
        copy(slot->rp, rp, size); ++cache.captured;
    } else ++cache.full;
    unlock();
}

/* Called after the stock Request-URI setter, before transaction submission.
 * Only modify a correlated RP-ACK/RP-ERROR; never create another MESSAGE.
 */
__attribute__((visibility("hidden"))) void sms_correlate(void *message, const u8 *rp, u32 size, u32 owner) {
    char call_id[HEADER_MAX], gateway[HEADER_MAX], to[HEADER_MAX + 2];
    u32 native_uri[31], time, i, epoch, n;
    int found = 0;
    if (!owner || !rp || size < 2 || size > RP_MAX || (rp[0] != 2 && rp[0] != 4) || !now(&time)) return;
    /* Respect any pre-existing correlation instead of overwriting it. */
    if (NATIVE(int (*)(void *, const char *), 0x2185e9)(message, "In-Reply-To")) return;
    if (!lock()) return;
    epoch = cache.epoch;
    for (i = 0; i < SLOTS; ++i) {
        struct entry *e = &cache.entries[i];
        if (e->owner != owner || e->reference != rp[1] || !current(e, time)) continue;
        if (!e->ambiguous) {
            copy(call_id, e->call_id, length(e->call_id, HEADER_MAX) + 1);
            copy(gateway, e->gateway, length(e->gateway, HEADER_MAX) + 1);
            found = 1;
        }
        break;
    }
    if (!found) ++cache.missing;
    unlock();
    if (!found || epoch != cache.epoch) return;
    /* Native URI value type is 0x7c bytes; use its constructor, validator,
     * copy setter and destructor, not a guessed representation. */
    NATIVE(void (*)(void *, const char *), 0x23ea95)(native_uri, gateway);
    if (NATIVE(int (*)(void *), 0x23c597)(native_uri) && epoch == cache.epoch) {
        NATIVE(void (*)(void *, void *), 0x1b5d55)(message, native_uri);
        /* name-addr preserves URI parameters instead of treating them as To
         * header parameters (RFC 3261 section 20.10). */
        n = length(gateway, HEADER_MAX);
        to[0] = '<'; copy(to + 1, gateway, n); to[n + 1] = '>'; to[n + 2] = 0;
        NATIVE(void (*)(void *, const char *, const char *), 0x218e81)(message, "To", to);
        NATIVE(void (*)(void *, const char *, const char *), 0x218e81)(message, "In-Reply-To", call_id);
        if (lock()) { ++cache.correlated; unlock(); }
    }
    NATIVE(void (*)(void *), 0x66141)(native_uri);
}

/* Telecom-only MO capture at 0x2ee3c6: record outbound 3GPP MO RP-DATA
 * (rp[0] == 0) Call-ID -> RP-MR so ImsEngineSmsMgr::onSmsDeliverySuccess can
 * complete qct_rrm's WAIT_FOR_RP_ACK state after SIP 2xx.
 */
__attribute__((visibility("hidden"))) void sms_mo_capture(void *message, const u8 *rp, u32 size, u32 owner) {
    char cid[HEADER_MAX];
    struct mo_entry *slot = 0;
    u32 time, i;
    if (!owner || !rp || size < 2 || size > RP_MAX || rp[0] != 0 || !now(&time)) return;
    cid[0] = 0;
    if (!token(cid, single(message, "Call-ID"))) return;
    if (!mo_lock()) return;
    for (i = 0; i < MO_SLOTS; ++i) {
        struct mo_entry *e = &mo_cache.entries[i];
        if (!mo_live(e->used, e->at, time)) { if (!slot) slot = e; continue; }
        if (!same(e->call_id, cid)) continue;
        if (e->used != 1 || e->reference != rp[1]) {
            e->used = 2; ++mo_cache.conflict;
        }
        mo_unlock(); return;
    }
    if (slot) {
        slot->used = 1; slot->reference = rp[1]; slot->at = time;
        copy(slot->call_id, cid, length(cid, HEADER_MAX) + 1);
        ++mo_cache.captured;
    } else ++mo_cache.full;
    mo_unlock();
}

/* Telecom-only hook target for 0xdaae2 inside ImsEngineSmsMgr::onSmsDeliverySuccess.
 * Runs only on SIP 2xx delivery success (never on 4xx/5xx/timeout failure).
 */
__attribute__((visibility("hidden")))
u32 sms_mo_pop(u32 engine, const char * const *call_id_obj, u32 remove, void *out1, void *out2) {
    u32 pdu_id = NATIVE(u32 (*)(u32, const char * const *, u32, void *, void *), 0xda97d)(
        engine, call_id_obj, remove, out1, out2);
    char cid[HEADER_MAX];
    u32 time, i, ref = 0;
    int matched = 0;
    struct mo_stage *slot = 0;
    if (pdu_id >= 0xffu || !engine || !call_id_obj || !now(&time)) return pdu_id;
    cid[0] = 0;
    if (!token(cid, *call_id_obj)) return pdu_id;
    if (!mo_lock()) return pdu_id;
    for (i = 0; i < MO_SLOTS; ++i) {
        struct mo_entry *e = &mo_cache.entries[i];
        if (!mo_live(e->used, e->at, time) || !same(e->call_id, cid)) continue;
        if (e->used == 1) {
            ref = e->reference;
            matched = 1;
        }
        e->used = 0;
        break;
    }
    if (matched) {
        for (i = 0; i < MO_STAGED; ++i) {
            struct mo_stage *s = &mo_cache.pending[i];
            if (mo_live(s->used, s->at, time) && s->engine == engine && s->pdu_id == pdu_id) {
                slot = s; break;
            }
            if (!mo_live(s->used, s->at, time) && !slot) slot = s;
        }
        if (slot) {
            slot->used = 1; slot->engine = engine; slot->pdu_id = pdu_id;
            slot->reference = ref; slot->at = time;
            ++mo_cache.popped;
        } else ++mo_cache.full;
    }
    mo_unlock();
    return pdu_id;
}

typedef int (*tlv_create_fn)(void *, u32, u32, u32,
                             u32, u32, const void *,
                             u32, u32, const void *,
                             u32, u32, const void *);

/* Telecom-only hook target for 0xdab44 inside ImsEngineSmsMgr::onSmsDeliverySuccess.
 * Sends stock NOTIFY_SMS_RP_PDU_STATUS (0x1014) first so qct_rrm enters
 * WAIT_FOR_RP_ACK, then injects NOTIFY_SMS_INCOMING_RP_PDU (0x1015) carrying
 * 3GPP Network->MS RP-ACK {0x03, rp_mr} (len=2, format=0).
 */
__attribute__((visibility("hidden")))
int sms_mo_send(void *ipc, const u8 *status_buf, u32 status_len, u32 flags) {
    int (*send_fn)(void *, const void *, u32, u32) =
        NATIVE(int (*)(void *, const void *, u32, u32), 0x11ec61);
    int rc = send_fn(ipc, status_buf, status_len, flags);
    u32 engine, pdu_id, time, i, ref = 0, fmt_3gpp;
    int found = 0, tlv_len;
    u8 tlv_buf[64], rp_ack[2], rp_len;
    if (!ipc || !status_buf) return rc;
    engine = *(const u32 *)(const void *)(status_buf - 0x14);
    pdu_id = *(status_buf - 1);
    if (!now(&time) || !mo_lock()) return rc;
    for (i = 0; i < MO_STAGED; ++i) {
        struct mo_stage *s = &mo_cache.pending[i];
        if (!mo_live(s->used, s->at, time)) continue;
        if (s->engine == engine && s->pdu_id == pdu_id) {
            ref = s->reference;
            s->used = 0;
            found = 1;
            break;
        }
    }
    mo_unlock();
    if (rc != 0 || !found) return rc;
    zero(tlv_buf, sizeof(tlv_buf));
    rp_ack[0] = 3u;
    rp_ack[1] = (u8)ref;
    rp_len = 2u;
    fmt_3gpp = 0u;
    tlv_len = NATIVE(tlv_create_fn, 0x139085)(
        tlv_buf, sizeof(tlv_buf), 3u, 0x1015u,
        0x1041u, 2u, rp_ack,
        0x1042u, 1u, &rp_len,
        0x1044u, 4u, &fmt_3gpp);
    if (tlv_len > 0 && (u32)tlv_len <= sizeof(tlv_buf)) {
        if (send_fn(ipc, tlv_buf, (u32)tlv_len, 0u) == 0) {
            if (mo_lock()) { ++mo_cache.synthesized; mo_unlock(); }
        }
    }
    return rc;
}

/* Thumb BL replacements preserve the original arguments, 8-byte stack alignment
 * and callee-saved registers. Every patched callsite in ims_rrm executes Thumb
 * BL (not BLX), so every hook entry here must be a .thumb_func; ld.lld inserts
 * Thumb->ARM interworking on internal bl instructions to C helpers.
 */
__asm__(
    ".syntax unified\n.thumb\n"
    ".section .text.anchor,\"ax\",%progbits\n"
    ".global sms_anchor\n.hidden sms_anchor\n.type sms_anchor,%function\n.thumb_func\n"
    "sms_anchor:\n bx lr\n.size sms_anchor,.-sms_anchor\n"
    ".section .text.sms_rx_hook,\"ax\",%progbits\n"
    ".global sms_rx_hook\n.hidden sms_rx_hook\n.type sms_rx_hook,%function\n.thumb_func\n"
    "sms_rx_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    "mov r4,r0\n mov r1,r0\n mov r0,r5\n bl sms_capture\n"
    "add.w r0,r4,#0x20\n pop {r4,pc}\n.fnend\n.size sms_rx_hook,.-sms_rx_hook\n"
    ".section .text.sms_tx_hook,\"ax\",%progbits\n"
    ".global sms_tx_hook\n.hidden sms_tx_hook\n.type sms_tx_hook,%function\n.thumb_func\n"
    "sms_tx_hook:\n.fnstart\n.save {r4,r5,r6,lr}\n push {r4,r5,r6,lr}\n"
    "mov r5,r0\n mov r6,r1\n bl sms_native_uri_setter\n"
    "mov r3,r4\n mov r0,r5\n mov r1,r10\n mov r2,r9\n bl sms_correlate\n"
    "pop {r4,r5,r6,pc}\n.fnend\n.size sms_tx_hook,.-sms_tx_hook\n"
    ".section .text.sms_telecom_tx_hook,\"ax\",%progbits\n"
    ".global sms_telecom_tx_hook\n.hidden sms_telecom_tx_hook\n.type sms_telecom_tx_hook,%function\n.thumb_func\n"
    "sms_telecom_tx_hook:\n.fnstart\n.save {r4,r5,r6,lr}\n push {r4,r5,r6,lr}\n"
    "mov r5,r0\n mov r6,r1\n bl sms_native_uri_setter\n"
    "mov r3,r4\n mov r0,r5\n mov r1,r10\n mov r2,r9\n bl sms_correlate\n"
    "mov r3,r4\n mov r0,r5\n mov r1,r10\n mov r2,r9\n bl sms_mo_capture\n"
    "pop {r4,r5,r6,pc}\n.fnend\n.size sms_telecom_tx_hook,.-sms_telecom_tx_hook\n"
    ".section .text.sms_mo_pop_hook,\"ax\",%progbits\n"
    ".global sms_mo_pop_hook\n.hidden sms_mo_pop_hook\n.type sms_mo_pop_hook,%function\n.thumb_func\n"
    "sms_mo_pop_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    ".pad #8\n sub sp,#8\n ldr r4,[sp,#16]\n str r4,[sp,#0]\n"
    "bl sms_mo_pop\n add sp,#8\n pop {r4,pc}\n.fnend\n.size sms_mo_pop_hook,.-sms_mo_pop_hook\n"
    ".section .text.sms_mo_send_hook,\"ax\",%progbits\n"
    ".global sms_mo_send_hook\n.hidden sms_mo_send_hook\n.type sms_mo_send_hook,%function\n.thumb_func\n"
    "sms_mo_send_hook:\n.fnstart\n.save {r4,lr}\n push {r4,lr}\n"
    "bl sms_mo_send\n pop {r4,pc}\n.fnend\n.size sms_mo_send_hook,.-sms_mo_send_hook\n"
);

/* r0/r1 are still the stock setter's arguments at entry to this helper. */
__attribute__((visibility("hidden"))) void sms_native_uri_setter(void *message, void *value) {
    NATIVE(void (*)(void *, void *), 0x1b5d55)(message, value);
}
