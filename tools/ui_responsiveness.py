"""Measure a mapped Tk window, including native paints between Python callbacks."""
import time


def measure(window, duration_ms=800, interval_ms=16, action=None):
    """Run a bounded UI-only sample; action must not contact or change a phone.

    A withdrawn window or timing only configure() misses deferred native
    painting. Use mainloop and a heartbeat so expensive paints delay samples.
    Call only from an offline test, outside an existing mainloop.
    """
    started = previous = time.perf_counter()
    cpu = time.process_time()
    gaps = []
    pulse_job = None

    def pulse():
        nonlocal previous, pulse_job
        now = time.perf_counter()
        gaps.append((now - previous) * 1000)
        previous = now
        if action is not None:
            action(len(gaps))
        pulse_job = window.after(interval_ms, pulse)

    pulse_job = window.after(interval_ms, pulse)
    stop_job = window.after(duration_ms, window.quit)
    try:
        window.mainloop()
    finally:
        window.after_cancel(pulse_job)
        window.after_cancel(stop_job)
    ordered = sorted(gaps)
    return {'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
            'cpu_ms': round((time.process_time() - cpu) * 1000, 3),
            'samples': len(gaps), 'interval_ms': interval_ms,
            'max_gap_ms': round(max(gaps, default=0), 3),
            'p95_gap_ms': round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 3)
                          if ordered else 0}
