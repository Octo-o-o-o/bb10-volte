"""A small, offline ttk theme; native widget behavior and no extra dependencies."""
import math
import struct
import tkinter as tk
from tkinter import ttk
import zlib

BG, INK, MUTED = '#F2F5F9', '#18273F', '#62738B'
BLUE, BORDER = '#235BD7', '#D6DEE9'


def _image(master, width, height, sample):
    """Antialiased RGBA artwork for ttk's stretchable image elements."""
    data = bytearray()
    for y in range(height):
        data.append(0)  # PNG scanline filter
        for x in range(width):
            pixels = [sample(x + (i + .5) / 4, y + (j + .5) / 4)
                      for i in range(4) for j in range(4)]
            visible = [p for p in pixels if p is not None]
            if visible:
                data.extend(round(sum(p[c] for p in visible) / len(visible)) for c in range(3))
                data.append(round(255 * len(visible) / 16))
            else:
                data.extend((0, 0, 0, 0))

    def chunk(kind, content):
        return (struct.pack('!I', len(content)) + kind + content +
                struct.pack('!I', zlib.crc32(kind + content) & 0xffffffff))

    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress(bytes(data))) + chunk(b'IEND', b''))
    return tk.PhotoImage(master=master, data=png)


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _rounded(master, size, radius, fill, outline=None, stroke=1):
    fill, outline = _rgb(fill), _rgb(outline or fill)

    def inside(x, y, inset):
        r = max(0, radius - inset)
        if not (inset <= x <= size - inset and inset <= y <= size - inset):
            return False
        cx = min(max(x, inset + r), size - inset - r)
        cy = min(max(y, inset + r), size - inset - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2

    return _image(master, size, size, lambda x, y:
                  (fill if inside(x, y, stroke) else outline) if inside(x, y, 0) else None)


def _chevron(master, scale, color):
    size, ink = round(16 * scale), _rgb(color)

    def sample(x, y):
        x, y = x / scale, y / scale
        for x1, y1, x2, y2 in ((4, 6, 8, 10), (8, 10, 12, 6)):
            t = max(0, min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / 32))
            if math.hypot(x - x1 - t * (x2 - x1), y - y1 - t * (y2 - y1)) <= .8:
                return ink
        return None

    return _image(master, size, size, sample)


def apply_theme(root, font):
    """Install once per Tcl interpreter, including all child dialogs."""
    style = ttk.Style(root)
    if 'bb10' in style.theme_names():
        style.theme_use('bb10')
        return style
    style.theme_create('bb10', parent='clam')
    style.theme_use('bb10')
    scale = max(1, float(root.tk.call('tk', 'scaling')) / (96 / 72))
    px = lambda value: max(1, round(value * scale))
    images = []
    # Tcl owns the elements but Python must keep their PhotoImages alive.
    root._bb10_theme_images = images

    def rounded(name, colors, radius=6, stroke=1):
        states = []
        for state, fill, border in colors:
            image = _rounded(root, px(radius * 2 + 4), px(radius), fill, border, px(stroke))
            images.append(image)
            states.append((state, image))
        style.element_create(name, 'image', states[0][1],
                             *[(state, image) for state, image in states[1:]],
                             border=px(radius + 1), sticky='nsew')

    neutral = [('', '#FFFFFF', BORDER), ('disabled', '#E9EDF3', '#E9EDF3'),
               ('pressed', '#E4EBF5', '#B6C6DE'), ('focus', '#FFFFFF', BLUE),
               ('active', '#F6F8FC', '#AEBED3')]
    rounded('Surface.button', neutral)
    rounded('Accent.button', [('', BLUE, BLUE), ('disabled', '#DCE5F5', '#DCE5F5'),
                             ('pressed', '#17449F', '#17449F'), ('focus', BLUE, '#102E6D'),
                             ('active', '#1C4FBE', '#1C4FBE')])
    for name, element in (('TButton', 'Surface.button'), ('Accent.TButton', 'Accent.button')):
        style.layout(name, [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])
        style.configure(name, font=(font, 11), padding=(px(14), px(9)), anchor='center',
                        foreground='white' if name.startswith('Accent') else INK)
        style.map(name, foreground=[('disabled', '#7C8BA0')])

    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, font=(font, 11), padding=(px(10), px(8)), foreground=INK,
                        fieldbackground='white', selectbackground=BLUE, selectforeground='white',
                        borderwidth=0, arrowsize=px(16))
        style.map(name, foreground=[('disabled', '#7C8BA0')],
                  fieldbackground=[('disabled', '#E9EDF3'), ('readonly', '#FFFFFF')])
    rounded('Surface.field', [('', '#FFFFFF', BORDER), ('disabled', '#E9EDF3', '#E9EDF3'),
                              ('focus', '#FFFFFF', BLUE), ('active', '#FFFFFF', '#AEBED3')])
    style.layout('TEntry', [('Surface.field', {'sticky': 'nsew', 'children': [
        ('Entry.padding', {'sticky': 'nsew', 'children': [('Entry.textarea', {'sticky': 'nsew'})]})]})])
    arrow, arrow_disabled = _chevron(root, scale, MUTED), _chevron(root, scale, '#99A6B8')
    images.extend((arrow, arrow_disabled))
    style.element_create('Surface.downarrow', 'image', arrow, ('disabled', arrow_disabled),
                         sticky='', width=px(30))
    style.layout('TCombobox', [('Surface.field', {'sticky': 'nsew', 'children': [
        ('Surface.downarrow', {'side': 'right', 'sticky': 'ns'}),
        ('Combobox.padding', {'sticky': 'nsew', 'children': [
            ('Combobox.textarea', {'sticky': 'nsew'})]})]})])
    style.layout('TMenubutton', [('Surface.button', {'sticky': 'nsew', 'children': [
        ('Surface.downarrow', {'side': 'right', 'sticky': 'ns'}),
        ('Menubutton.padding', {'sticky': 'nsew', 'children': [
            ('Menubutton.label', {'sticky': 'nsew'})]})]})])
    style.configure('TMenubutton', font=(font, 11), foreground=INK, padding=(px(13), px(9)))
    style.map('TMenubutton', foreground=[('disabled', '#7C8BA0')])

    rounded('Surface.thumb', [('', '#BAC6D6', '#BAC6D6'), ('pressed', '#71849F', '#71849F'),
                             ('active', '#91A2B9', '#91A2B9')], radius=3)
    for orientation, side in (('Vertical', 'top'), ('Horizontal', 'left')):
        style.layout(orientation + '.TScrollbar', [
            (orientation + '.Scrollbar.trough', {'sticky': 'ns' if side == 'top' else 'ew',
             'children': [('Surface.thumb', {'side': side, 'sticky': 'ns' if side == 'top' else 'ew'})]})])
        style.configure(orientation + '.TScrollbar', troughcolor=BG, bordercolor=BG,
                        lightcolor=BG, darkcolor=BG, borderwidth=0, arrowsize=px(10))

    rounded('Surface.track', [('', '#E2E8F2', '#E2E8F2')], radius=2)
    rounded('Surface.progress', [('', BLUE, BLUE)], radius=2)
    style.layout('Horizontal.TProgressbar', [('Surface.track', {'sticky': 'ew', 'children': [
        ('Surface.progress', {'side': 'left', 'sticky': 'ns'})]})])
    style.configure('Horizontal.TProgressbar', thickness=px(4), borderwidth=0)

    style.configure('.', font=(font, 11), background=BG, foreground=INK,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure('TFrame', background=BG)
    style.configure('TLabel', background=BG, foreground=INK, font=(font, 11))
    style.configure('TCheckbutton', font=(font, 11), background=BG, foreground=INK,
                    padding=(0, px(4)), indicatorbackground='white', indicatorforeground=BLUE,
                    indicatormargin=(0, 0, px(7), 0), borderwidth=1)
    style.map('TCheckbutton', background=[('active', BG)], foreground=[('disabled', '#7C8BA0')])
    style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(0, 0, 0, px(12)))
    style.configure('TNotebook', bordercolor=BG, lightcolor=BG, darkcolor=BG)
    rounded('Surface.tab', [('', BG, BG), ('selected', '#FFFFFF', BORDER),
                            ('focus', '#E8EEF7', BLUE), ('active', '#E8EEF7', '#E8EEF7')])
    style.layout('TNotebook.Tab', [('Surface.tab', {'sticky': 'nsew', 'children': [
        ('Notebook.padding', {'sticky': 'nsew', 'children': [
            ('Notebook.focus', {'sticky': 'nsew', 'children': [
                ('Notebook.label', {'sticky': 'nsew'})]})]})]})])
    style.configure('TNotebook.Tab', font=(font, 11), padding=(px(16), px(9)),
                    background=BG, foreground=MUTED, borderwidth=0)
    style.map('TNotebook.Tab', background=[('selected', 'white'), ('active', '#E8EEF7')],
              foreground=[('selected', BLUE)])
    style.configure('Treeview', font=(font, 12), rowheight=px(34), background='white',
                    fieldbackground='white', foreground=INK, borderwidth=0)
    style.configure('Treeview.Heading', font=(font, 11, 'bold'), background='#EDF1F7',
                    foreground=INK, padding=px(9), relief='flat')
    style.map('Treeview', background=[('selected', '#E4EDFF')], foreground=[('selected', INK)])
    style.configure('TSeparator', background=BORDER)
    for option, value in (('Font', (font, 11)), ('background', 'white'), ('foreground', INK),
                          ('selectBackground', '#E4EDFF'), ('selectForeground', INK),
                          ('relief', 'flat'), ('borderWidth', 0), ('highlightThickness', 0)):
        root.option_add('*TCombobox*Listbox.' + option, value)
    return style


class AutoScrollbar(ttk.Scrollbar):
    """Keep standard scrolling; hide the rail when the complete content fits."""
    def set(self, first, last):
        super().set(first, last)
        manager = self.winfo_manager()
        if float(first) <= 0 and float(last) >= 1:
            if manager == 'pack':
                self._placement = ('pack', self.pack_info())
                self.pack_forget()
            elif manager == 'grid':
                self._placement = ('grid', self.grid_info())
                self.grid_remove()
        elif not manager and hasattr(self, '_placement'):
            manager, options = self._placement
            if manager == 'pack':
                siblings = [w for w in self.master.pack_slaves() if w is not self]
                if siblings:
                    options['before'] = siblings[0]
                self.pack(**options)
            else:
                self.grid(**options)
