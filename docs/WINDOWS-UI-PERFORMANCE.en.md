# Windows UI stalls (2026-11-09, included in r43)

The r42 Windows UI can stall when opening connection/Root pages or resizing windows, even without a connected phone or a download.

The small translucent images in `tools/ui_theme.py` leave an approximately two-pixel center. Tk tiles that center across each control; Windows performs many expensive GDI operations per repaint, blocking the UI event loop. Background workers cannot prevent this native paint stall. Windows now uses built-in `clam` drawing elements with the existing colors, layout and control states. Other window systems retain the rounded theme. Progress animation uses Tk's default 50 ms interval instead of 12 ms. Device identity, firmware, Root, backup and flashing checks are unchanged.

See the [Tk image element documentation](https://www.tcl-lang.org/man/tcl9.0/TkCmd/ttk_image.html) and the discussion in [TIP 754](https://core.tcl-lang.org/tips/doc/trunk/tip/754.md). That proposal is withdrawn; this fix does not assume an upstream fix or replace the pinned runtime.

On the same Windows computer with Python 3.14.9, Tk 9.0.4 and ordinary opaque windows, the longest 10 ms heartbeat interval fell from 644 to 23 ms during main-window resizing, from 3693 to 58 ms on the connection page's first paint, and from 1082 to 29 ms during Root-page resizing. These are short local measurements, not performance or battery-life guarantees for other computers. No phone was contacted.

The new Windows regression maps real widgets at three Tk scaling values and exercises large controls, page changes, resizing and animation. The old theme fails all three cases; the fix passes. Scrollbar and progress geometry tests also pass. Packaged `--self-test <report.json>` now measures actual UI heartbeats for the main, connection and Root windows without phone operations.

The working-tree suite ran 1100 tests: 1032 passed, 65 skipped and three existing issues failed (two website copy assertions and local paths in untracked recording notes). Desktop tests passed. Those unrelated edits were preserved. The preview is built from a frozen explicit source list excluding the unrelated untracked recording directories, with separate archive verification and offline EXE checks. Published r42 assets remain unchanged. Full local measurements are summarized in the [Chinese report](WINDOWS-UI-PERFORMANCE.md).
