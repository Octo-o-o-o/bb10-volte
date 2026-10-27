/* Temporary io-pkt helper for this exact BB10 build.
 *
 * Uses the existing software provider and its ordinary registration API.
 * No code patch, cipher change, SA/policy creation, or persistent config write.
 * Entry ABI: native devnp-sbgse_drv.so and QNX io-pkt driver documentation.
 * The caller must verify the stock binary hash and provider state first.
 * Rollback is permitted only after every test/IMS SA has been removed.
 */
#if defined(_WIN32)
# define EXPORT __declspec(dllexport)
#else
# define EXPORT __attribute__((visibility("default")))
_Static_assert(sizeof(void *) == 4, "This helper is only for 32-bit BB10 ARM");
#endif

extern int swcr_id;
extern void swcryptoattach(int number);
extern int crypto_unregister_all(unsigned int driver_id);

static int same(const char *a, const char *b)
{
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

EXPORT int volte_crypto_entry(void *dll_handle, void *iopkt, char *options)
{
    unsigned int expected = 0;
    int result;
    const char *p;
    if (!dll_handle || !iopkt || !options) return 22;

    if (same(options, "enable")) {
        if (swcr_id != -1) return 17;
        swcryptoattach(1);
        return swcr_id >= 0 ? 0 : 5;
    }

    p = options;
    {
        const char *prefix = "rollback=";
        while (*prefix) {
            if (*p++ != *prefix++) return 22;
        }
    }
    if (*p < '0' || *p > '9') return 22;
    do {
        expected = expected * 10 + (unsigned int)(*p++ - '0');
        if (expected > 127) return 22;
    } while (*p >= '0' && *p <= '9');
    if (*p || swcr_id < 0 || (unsigned int)swcr_id != expected) return 22;
    result = crypto_unregister_all(expected);
    if (result) return result;
    swcr_id = -1;
    return 0;
}

struct verified_iopkt_driver_entry {
    unsigned int version;
    unsigned int flags;
    int (*entry)(void *, void *, char *);
};
#if !defined(_WIN32)
_Static_assert(sizeof(struct verified_iopkt_driver_entry) == 12, "Native ABI mismatch");
#endif
EXPORT struct verified_iopkt_driver_entry iopkt_drvr_entry = {
    1, 0, volte_crypto_entry
};
