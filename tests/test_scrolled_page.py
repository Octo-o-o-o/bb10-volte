"""Regression coverage for overflow, resize and platform wheel behavior."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from mac_help import scrolled_page
from ui_theme import apply_theme, AutoScrollbar
from profile_editor import FONT


class ScrolledPageTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('Tk display unavailable: ' + str(error))
        self.root.attributes('-alpha', 0)
        self.root.geometry('480x300')
        apply_theme(self.root, FONT)
        self.page, self.content = scrolled_page(self.root, padding=0)
        self.page.pack(fill='both', expand=True)
        self.canvas = next(w for w in self.page.winfo_children() if isinstance(w, tk.Canvas))
        self.scrollbar = next(w for w in self.page.winfo_children() if isinstance(w, AutoScrollbar))

    def tearDown(self):
        if hasattr(self, 'root'):
            self.root.destroy()

    def test_scrollbar_tracks_overflow_and_resize(self):
        content = ttk.Frame(self.content, height=600, width=200)
        content.pack(fill='x')
        self.root.update()
        self.assertEqual(self.scrollbar.winfo_manager(), 'pack')
        self.canvas.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(self.canvas.yview()[1], 1)
        self.root.geometry('480x800')
        self.root.update()
        self.assertFalse(self.scrollbar.winfo_manager())
        self.assertEqual(self.canvas.yview(), (0.0, 1.0))
        self.root.geometry('480x300')
        self.root.update()
        self.assertEqual(self.scrollbar.winfo_manager(), 'pack')
        self.assertGreater(self.canvas.winfo_width(), 400)
        content.destroy()
        ttk.Label(self.content, text='Short content').pack()
        self.root.update()
        self.assertFalse(self.scrollbar.winfo_manager())

    def test_windows_wheel_moves_a_few_rows_and_short_pages_do_not_scroll(self):
        for i in range(60):
            ttk.Label(self.content, text='Instruction ' + str(i)).pack()
        self.root.update()
        self.content.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        first, last = self.canvas.yview()
        self.assertGreater(first, 0)
        self.assertLess(first, .1)
        for widget in self.content.winfo_children():
            widget.destroy()
        ttk.Label(self.content, text='Short content').pack()
        self.root.update()
        self.content.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertEqual(self.canvas.yview(), (0.0, 1.0))

    def test_native_text_scrolling_does_not_also_move_the_page(self):
        text = tk.Text(self.content, height=4)
        text.insert('1.0', '\n'.join(str(i) for i in range(80)))
        text.pack()
        ttk.Frame(self.content, height=700).pack()
        self.root.update()
        before = self.canvas.yview()
        text.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertEqual(self.canvas.yview(), before)
        self.assertGreater(text.yview()[0], 0)

    def test_scroll_thumb_size_and_position_follow_the_view(self):
        ttk.Frame(self.content, height=1200, width=200).pack()
        self.root.update()
        x = self.scrollbar.winfo_width() // 2
        thumb_pixels = [y for y in range(self.scrollbar.winfo_height())
                        if self.scrollbar.identify(x, y).endswith('.thumb')]
        self.assertGreater(len(thumb_pixels), 40)
        self.assertLess(len(thumb_pixels), 100)
        self.canvas.yview_moveto(1)
        self.root.update()
        self.assertTrue(self.scrollbar.identify(x, 280).endswith('.thumb'))
        self.assertFalse(self.scrollbar.identify(x, 20).endswith('.thumb'))

    def test_progress_fill_tracks_value(self):
        progress = ttk.Progressbar(self.content, value=36, maximum=100, length=400)
        progress.pack()
        self.root.update()
        y = progress.winfo_height() // 2
        self.assertTrue(progress.identify(80, y).endswith('.pbar'))
        self.assertFalse(progress.identify(300, y).endswith('.pbar'))
        progress.configure(value=85)
        self.root.update()
        self.assertTrue(progress.identify(300, y).endswith('.pbar'))


if __name__ == '__main__':
    unittest.main()
