/* SPDX-License-Identifier: MIT
 * Correlate raw 3GPP MT reports in the hash-pinned BB10 10.3.3.3216 IMS image.
 * No sends, retries, RPDU changes, message suppression, or persistent state.
 * Native addresses/ABI are documented in docs/SMS-ACK-NATIVE.md.
 */
typedef unsigned int u32;
typedef unsigned char u8;
typedef char check_u32[sizeof(u32) == 4 ? 1 : -1];

#define CODE_VA 0x500000u
#define SLOTS 32u
#define HEADER_MAX 512u
#define RP_MAX 255u
#define TTL_SECONDS 180u

extern __attribute__((visibility("hidden"))) void sms_anchor(void);
struct entry {
    u32 owner, reference, at, ambiguous, rp_size, epoch;
    char call_id[HEADER_MAX], gateway[HEADER_MAX];
    u8 rp[RP_MAX];
};
static struct {
    volatile u32 lock, epoch;
    u32 captured, correlated, conflict, missing, malformed, full;
    struct entry entries[SLOTS];
} cache;

static u32 base(void) { return ((u32)&sms_anchor & ~1u) - CODE_VA; }
#define NATIVE(type, address) ((type)(base() + (address)))

static void copy(void *dst, const void *src, u32 count) {
    u8 *d = dst; const u8 *s = src;
    while (count--) *d++ = *s++;
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

/* Two BL replacements preserve the original arguments and callee-saved
 * registers. Both call sites have an aligned stack and no live condition flags.
 * The receive hook reproduces the original getter (message + 0x20).
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
);

/* r0/r1 are still the stock setter's arguments at entry to this helper. */
__attribute__((visibility("hidden"))) void sms_native_uri_setter(void *message, void *value) {
    NATIVE(void (*)(void *, void *), 0x1b5d55)(message, value);
}
