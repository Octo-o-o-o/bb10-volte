"""Celebrate a verified setup, with entirely optional, local support choices."""
import math
import tkinter as tk
import webbrowser
from tkinter import ttk

from desktop_paths import resource_root
from i18n import tr
from mac_help import scrolled_page
from profile_editor import FONT
from support_config import (AMOUNTS, CONTACT_EMAIL, OCTOLAB_URL, PROJECT_WEBSITE_URL,
                            PROVIDERS, QR_AVATARS, REPOSITORY_URL, SUPPORT_ICON,
                            receipt_image, receipt_view)
from ui_theme import BG, BLUE, INK, MUTED

GREEN = '#137860'
PALE_GREEN = '#E8F5EE'


class CompletionDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(tr('恭喜，老黑莓重获新生'))
        self.configure(bg=BG)
        self.transient(parent)
        self.geometry('{}x{}'.format(min(920, self.winfo_screenwidth() - 60),
                                     min(820, self.winfo_screenheight() - 90)))
        self.minsize(660, 540)
        self.bind('<Escape>', lambda _: self.destroy())
        self.resource_root = resource_root()
        self.qr_image = None
        self.provider = tk.StringVar(self, value=next(
            (p for p in PROVIDERS if any(receipt_image(self.resource_root, p, a)[0]
                                       for a in AMOUNTS)), PROVIDERS[0]))
        self.amount = tk.StringVar(self, value=AMOUNTS[0])

        # Reserve a visible exit even when the optional support area is expanded.
        footer = tk.Frame(self, bg=BG, padx=24, pady=16)
        footer.pack(side='bottom', fill='x')
        self.brand_button = tk.Button(footer, text=tr('OctoLab 出品'),
                                      command=lambda: self.open_link(OCTOLAB_URL),
                                      font=(FONT, 11, 'underline'), fg=BLUE, bg=BG,
                                      activeforeground=BLUE, activebackground=BG,
                                      relief='flat', borderwidth=0, cursor='hand2',
                                      highlightbackground=BG, highlightcolor=BLUE,
                                      highlightthickness=1, padx=0, pady=4)
        self.brand_button.pack(side='left')
        self.done_button = ttk.Button(footer, text=tr('完成，去用我的黑莓'),
                                      style='Accent.TButton', command=self.destroy)
        self.done_button.pack(side='right')
        self.page, self.content = scrolled_page(self, padding=24)
        self.page.pack(fill='both', expand=True)

        hero = tk.Frame(self.content, bg=PALE_GREEN, padx=28, pady=18)
        hero.pack(fill='x', pady=(0, 18))
        introduction = tk.Frame(hero, bg=PALE_GREEN)
        introduction.pack(fill='x')
        introduction.columnconfigure(1, weight=1)
        self.draw_phone(introduction).grid(row=0, column=0, rowspan=2, padx=(0, 20))
        self.label(introduction, tr('恭喜，你的老黑莓重获新生。'), size=23, bold=True,
                   color=GREEN, wrap=True, wrap_inset=134).grid(row=0, column=1, sticky='w', pady=(6, 8))
        self.label(introduction, tr('熟悉的按键，久违的铃声。\n让这台经典，继续陪你过新的日常。'),
                   size=12, wrap=True, wrap_inset=134).grid(row=1, column=1, sticky='w')
        self.label(hero, tr('VoLTE 服务已启用 · 4G 网络注册成功'), color=GREEN,
                   bold=True, wrap=True).pack(pady=(12, 8))
        self.label(hero, tr('接下来，请试着拨出和接听一通电话，确认双向声音与全程 4G；重启后再复测。'),
                   color=MUTED, wrap=True, justify='center').pack()

        self.label(self.content, tr('如果你愿意，也可以支持一下这个小项目'),
                   color=MUTED, wrap=True).pack(anchor='w', pady=(0, 12))
        coffee = tk.Frame(self.content, bg='white', padx=22, pady=18)
        coffee.pack(fill='x', pady=(0, 12))
        self.label(coffee, tr('请开发者喝杯咖啡'), size=14, bold=True).pack(anchor='w')
        self.label(coffee, tr('为了让这些老黑莓重新打上电话，我花了不少 Token，也熬了几个晚上。'
                             '\n如果它帮到了你，愿意请我喝杯咖啡吗？'
                             '随意就好，能让老手机继续陪伴你，我已经很开心。'),
                   color=MUTED, wrap=True).pack(fill='x', pady=(8, 12))
        self.coffee_button = ttk.Button(coffee, text=tr('我想请你喝杯咖啡'), command=self.toggle_coffee)
        self.coffee_button.pack(anchor='w')
        self.payment = tk.Frame(coffee, bg='white')
        self.build_payment()
        self.label(coffee, tr('打赏完全自愿，金额随心；不影响任何功能。'),
                   color=MUTED, wrap=True).pack(anchor='w', pady=(12, 0))

        other_support = tk.Frame(self.content, bg=BG)
        other_support.pack(fill='x')
        other_support.columnconfigure((0, 1), weight=1, uniform='support')
        star = tk.Frame(other_support, bg='white', padx=18, pady=16)
        star.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        self.label(star, tr('让更多人发现这个项目'), size=14, bold=True, wrap=True).pack(anchor='w')
        self.label(star, tr('让更多老黑莓爱好者，\n发现它还能继续发光。'),
                   color=MUTED, wrap=True).pack(anchor='w', pady=(6, 12))
        share_actions = tk.Frame(star, bg='white')
        share_actions.pack(fill='x')
        star_button = ttk.Button(share_actions, text=tr('去 GitHub 加星'),
                                 command=lambda: self.open_link(REPOSITORY_URL))
        star_button.grid(row=0, column=0, sticky='w')
        self.share_button = ttk.Button(share_actions, text=tr('分享给好友'), command=self.copy_share)
        self.share_button.grid(row=0, column=1, sticky='w', padx=(8, 0))

        def arrange_share_actions(event):
            stacked = event.width < star_button.winfo_reqwidth() + self.share_button.winfo_reqwidth() + 8
            self.share_button.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                              padx=0 if stacked else (8, 0),
                                              pady=(8, 0) if stacked else 0)

        share_actions.bind('<Configure>', arrange_share_actions)

        contact = tk.Frame(other_support, bg='white', padx=18, pady=16)
        contact.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        self.label(contact, tr('还有想做的东西？一起聊聊'), size=14, bold=True, wrap=True).pack(anchor='w')
        self.label(contact, tr('产品点子、小工具，或其他开发需求，\n欢迎写信，一起把想法做出来。'),
                   color=MUTED, wrap=True).pack(anchor='w', pady=(6, 10))
        self.label(contact, CONTACT_EMAIL, color=BLUE, bold=True).pack(anchor='w', pady=(0, 10))
        actions = tk.Frame(contact, bg='white')
        actions.pack(anchor='w')
        ttk.Button(actions, text=tr('写封邮件'),
                   command=lambda: self.open_link('mailto:' + CONTACT_EMAIL)).pack(side='left')
        self.copy_button = ttk.Button(actions, text=tr('复制邮箱'), command=self.copy_email)
        self.copy_button.pack(side='left', padx=(8, 0))
        self.link_status = self.label(self.content, '', color=MUTED, wrap=True)
        self.link_status.pack(anchor='w', pady=(12, 0))
        self.done_button.focus_set()

    def label(self, parent, text, size=11, color=INK, bold=False, wrap=False, wrap_inset=0, **kwargs):
        background = parent.cget('bg') if isinstance(parent, tk.Frame) else BG
        label = tk.Label(parent, text=text, bg=background, fg=color,
                         font=(FONT, size, 'bold' if bold else 'normal'),
                         justify=kwargs.pop('justify', 'left'), anchor=kwargs.pop('anchor', 'w'), **kwargs)
        if wrap:
            label.configure(wraplength=720)
            padding = int(parent.cget('padx')) if isinstance(parent, tk.Frame) else 24
            parent.bind('<Configure>', lambda event: label.configure(
                wraplength=max(180, event.width - 2 * padding - wrap_inset - 8)), add='+')
        return label

    def draw_phone(self, parent):
        art = tk.Canvas(parent, width=114, height=78, bg=PALE_GREEN, highlightthickness=0)
        for x, y, color in ((24, 22, '#C49643'), (132, 43, GREEN), (28, 84, BLUE), (124, 10, GREEN)):
            art.create_line(x - 4, y, x + 4, y, fill=color, width=2)
            art.create_line(x, y - 4, x, y + 4, fill=color, width=2)
        art.create_oval(37, 8, 121, 96, fill='#D2EBDD', outline='')
        art.create_rectangle(55, 6, 103, 97, fill=INK, outline=INK, width=3)
        art.create_line(70, 13, 87, 13, fill='#A4B8C5', width=2)
        art.create_rectangle(60, 21, 98, 65, fill='#F7FCF9', outline='')
        art.create_line(68, 43, 76, 51, 91, 34, fill=GREEN, width=4, joinstyle='round')
        for row in range(3):
            for col in range(5):
                x, y = 61 + col * 7, 73 + row * 6
                art.create_rectangle(x, y, x + 4, y + 2, fill='#B7C9CE', outline='')
        art.scale('all', 0, 0, .73, .73)
        return art

    def build_payment(self):
        self.label(self.payment, tr('选一份心意（人民币）'), bold=True).pack(anchor='w', pady=(16, 8))
        amounts = tk.Frame(self.payment, bg='white')
        amounts.pack(fill='x')
        self.amount_buttons = {}
        for index, amount in enumerate(AMOUNTS):
            button = ttk.Button(amounts, text=tr('自定义金额') if amount == 'custom' else '¥' + amount,
                                command=lambda value=amount: self.select_amount(value))
            button.grid(row=0, column=index, sticky='ew', padx=(0, 8) if index < 3 else 0)
            amounts.columnconfigure(index, weight=1)
            self.amount_buttons[amount] = button
        platforms = tk.Frame(self.payment, bg='white')
        platforms.pack(anchor='w', pady=12)
        self.provider_buttons = {}
        for provider, title in (('alipay', tr('支付宝')), ('wechat', tr('微信支付'))):
            button = ttk.Button(platforms, text=title, command=lambda value=provider: self.select_provider(value))
            button.pack(side='left', padx=(0, 8))
            self.provider_buttons[provider] = button
        self.receipt_note = self.label(self.payment, '', wrap=True)
        self.receipt_note.pack(anchor='w', pady=(0, 12))
        self.qr_label = self.label(self.payment, '', color=MUTED, wrap=True, justify='center')
        self.qr_label.pack(pady=(0, 10))
        self.label(self.payment, tr('请在支付 App 中确认收款人和金额。是否转账，由你决定。'),
                   color=MUTED, wrap=True).pack(anchor='w')

    def toggle_coffee(self):
        if self.payment.winfo_manager():
            self.payment.pack_forget()
            self.coffee_button.configure(text=tr('我想请你喝杯咖啡'))
        else:
            self.payment.pack(fill='x', after=self.coffee_button)
            self.coffee_button.configure(text=tr('收起打赏'))
            self.update_receipt()
            # The full receipt adds height. Bring the amount choices and code
            # into view after this explicit opt-in, keeping Done pinned below.
            canvas = self.content.master
            if canvas.winfo_ismapped():
                self.update_idletasks()
                offset = self.payment.winfo_rooty() - self.content.winfo_rooty()
                canvas.yview_moveto(max(0, offset - 12) / max(1, self.content.winfo_reqheight()))

    def select_amount(self, amount):
        self.amount.set(amount)
        self.update_receipt()

    def select_provider(self, provider):
        self.provider.set(provider)
        self.update_receipt()

    def update_receipt(self):
        amount, provider = self.amount.get(), self.provider.get()
        for value, button in self.amount_buttons.items():
            button.configure(style='Accent.TButton' if value == amount else 'TButton')
        for value, button in self.provider_buttons.items():
            button.configure(style='Accent.TButton' if value == provider else 'TButton')
        path, fixed = receipt_image(self.resource_root, provider, amount)
        self.qr_image = None
        self.qr_label.configure(image='', text='')
        if path is None:
            self.receipt_note.configure(text=tr('收款码暂未开放，感谢你的心意。'))
            self.qr_label.configure(text=tr('也可以给项目一颗 Star，或把它分享给需要的人。'))
            return
        platform = tr('支付宝') if provider == 'alipay' else tr('微信支付')
        if amount == 'custom':
            note = tr('用{}扫码，在支付 App 中填写你想支持的金额。').format(platform)
        elif fixed:
            note = tr('用{}扫码，支持 ¥{}。').format(platform, amount)
        else:
            note = tr('用{}扫码后，请手动填写 ¥{}；此收款码不预设金额。').format(platform, amount)
        try:
            source = tk.PhotoImage(master=self, file=str(path))
            region = receipt_view(path.name, (source.width(), source.height()))
            if region:
                source = source.copy(from_coords=region)
            if not region and max(source.width(), source.height()) <= 264:
                # Public assets are pre-framed, branded and decode-verified.
                self.qr_image = source
                self.qr_label.configure(image=source)
                self.receipt_note.configure(text=note)
                return
            # Frame the QR at a readable size; no interpolation or redraw of
            # modules. Keep an explicit white quiet zone around every receipt.
            factor = max(1, math.ceil(max(source.width(), source.height()) / 216))
            code = source.subsample(factor) if factor > 1 else source
            margin = 24
            width, height = code.width() + margin * 2, code.height() + margin * 2
            self.qr_image = tk.PhotoImage(master=self, width=width, height=height)
            self.qr_image.put('white', to=(0, 0, width, height))
            self.qr_image.tk.call(str(self.qr_image), 'copy', str(code), '-to', margin, margin)
            self.apply_brand_avatar(path, region, factor, margin)
            self.qr_label.configure(image=self.qr_image)
            self.receipt_note.configure(text=note)
        except (tk.TclError, OSError):
            self.receipt_note.configure(text=tr('收款码暂时无法显示，感谢你的心意。'))
            self.qr_label.configure(text=tr('也可以给项目一颗 Star，或把它分享给需要的人。'))

    def apply_brand_avatar(self, path, region, factor, margin):
        avatar = QR_AVATARS.get(path.name)
        icon_path = self.resource_root / SUPPORT_ICON
        if not region or not avatar or not icon_path.is_file():
            return
        icon = tk.PhotoImage(master=self, file=str(icon_path))
        left = margin + math.floor((avatar[0] - region[0]) / factor)
        top = margin + math.floor((avatar[1] - region[1]) / factor)
        right = margin + math.ceil((avatar[2] - region[0]) / factor)
        bottom = margin + math.ceil((avatar[3] - region[1]) / factor)
        # The site's 64px favicon is displayed at 48px or 56px. Small integer
        # zoom/subsample ratios avoid a new image library in the desktop app.
        size = min(56, (min(right - left, bottom - top) - 2) // 8 * 8)
        divisor = math.gcd(size, icon.width())
        logo = icon.zoom(size // divisor).subsample(icon.width() // divisor)
        self.qr_image.put('white', to=(left, top, right, bottom))
        x = left + (right - left - logo.width()) // 2
        y = top + (bottom - top - logo.height()) // 2
        self.qr_image.tk.call(str(self.qr_image), 'copy', str(logo), '-to', x, y)

    def copy_email(self):
        self.clipboard_clear()
        self.clipboard_append(CONTACT_EMAIL)
        self.copy_button.configure(text=tr('邮箱已复制'))

    def copy_share(self):
        message = tr('分享一个让老黑莓重获新生的项目：BB10 VoLTE。'
                     '\n喜欢实体键盘、想让经典继续陪伴你的朋友，可以来看看：'
                     '\n{}').format(PROJECT_WEBSITE_URL)
        self.clipboard_clear()
        self.clipboard_append(message)
        self.share_button.configure(text=tr('分享文案已复制'))
        self.link_status.configure(text=tr('已复制文案和官网链接，可以粘贴给好友。'))

    def open_link(self, url):
        try:
            opened = webbrowser.open(url)
        except (OSError, webbrowser.Error):
            opened = False
        self.link_status.configure(text='' if opened else tr('未能打开，请手动访问：{}').format(url))
