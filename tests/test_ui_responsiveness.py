"""Catch native redraw stalls that withdrawn-window GUI tests cannot see."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from profile_editor import FONT
from ui_theme import apply_theme, BLUE, INK
from ui_responsiveness import measure


@unittest.skipUnless(sys.platform == 'win32', 'Windows GDI redraw regression')
class WindowsRedrawTests(unittest.TestCase):
    def test_large_controls_remain_responsive_during_resize_and_animation(self):
        for scaling in (96 / 72, 1.6, 2.0):
            with self.subTest(scaling=scaling):
                root = tk.Tk()
                try:
                    # Invisible but mapped: native paints still run on Windows.
                    root.attributes('-alpha', 0.0)
                    root.tk.call('tk', 'scaling', scaling)
                    root.geometry('1000x600')
                    style = apply_theme(root, FONT)
                    tabs = ttk.Notebook(root)
                    tabs.pack(fill='both', expand=True)
                    for title in ('Connection', 'Root'):
                        panel = ttk.Frame(tabs, padding=20)
                        tabs.add(panel, text=title)
                        ttk.Entry(panel).pack(fill='x', pady=8)
                        ttk.Combobox(panel, values=('One', 'Two')).pack(fill='x', pady=8)
                        ttk.Button(panel, text='Continue', style='Accent.TButton').pack(fill='x', pady=8)
                        text = tk.Text(panel, height=3)
                        text.insert('1.0', '\n'.join(str(i) for i in range(100)))
                        scroll = ttk.Scrollbar(panel, command=text.yview)
                        scroll.pack(side='right', fill='y')
                        text.configure(yscrollcommand=scroll.set)
                        text.pack(fill='both', expand=True)
                    progress = ttk.Progressbar(root, mode='indeterminate')
                    progress.pack(fill='x')
                    progress.start()

                    def repaint(count):
                        root.geometry('{}x600'.format(1000 + count % 10 * 4))
                        if count % 8 == 0:
                            tabs.select((count // 8) % 2)

                    sample = measure(root, duration_ms=900, action=repaint)
                    progress.stop()
                    # Deliberately generous for shared CI. The old theme loses
                    # entire seconds per repaint, not a few scheduling ticks.
                    self.assertGreaterEqual(sample['samples'], 10, sample)
                    self.assertLess(sample['p95_gap_ms'], 250, sample)
                    self.assertLess(sample['max_gap_ms'], 750, sample)
                    self.assertEqual(style.lookup('Accent.TButton', 'background'), BLUE)
                    self.assertEqual(style.lookup('TButton', 'foreground'), INK)
                    self.assertNotEqual(style.lookup('Accent.TButton', 'foreground', ('disabled',)),
                                        style.lookup('Accent.TButton', 'foreground'))
                    self.assertEqual(style.lookup('TEntry', 'bordercolor', ('focus',)), BLUE)
                finally:
                    root.destroy()


if __name__ == '__main__':
    unittest.main()
