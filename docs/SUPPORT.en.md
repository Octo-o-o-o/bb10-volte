# Completion and optional support

Windows and macOS share the completion page. It celebrates an installation, update or service start after the current service passes IMS / LTE registration verification. Pending registration does not open it. A subsequent status check or preflight can finish the same pending flow once. Opening the app, discovering an existing service and repeated status checks do not repeatedly show the page. Automatic setup additionally requires the current boot, current SIM, native IMS and LTE. Passport extra-restart states cannot complete early. An already registered device also offers a manual “Automatic carrier setup → Completion and support” entry.

Registration is not call acceptance. The page still asks users to check incoming and outgoing calls, audio in both directions, 4G throughout and testing after a restart. Disconnected use must also be verified.

The primary action is “Done. Enjoy my BlackBerry”. Secondary, optional actions let users:

- Expand the coffee section, choose CNY 9.90 / 19.90 / 29.90 / a custom amount and view an Alipay or WeChat receipt code.
- Open the [GitHub project](https://github.com/Octo-o-o-o/bb10-volte) and choose whether to star it.
- Choose “Share with friends” to copy a Chinese or English message matching the interface language. Both include `https://bb10-volte.octoooo.com/`; users can paste and send it themselves.
- Open an email client or copy `octoooo@octoooo.com` for development ideas and enquiries.

The fixed footer includes a “Made by OctoLab” link to the [OctoLab website](https://octoooo.com/).

There is no payment requirement, payment tracking, automatic charge or automatic star. Close, Escape and Done always dismiss the page. After completion, “More → Completion and support” reopens it during the current app session.

## Receipt images

Public packages contain only eight verified QR presentation images with quiet zones and the OctoLab icon. Original payment screenshots, personal avatars, receipt names and unrelated screen content stay outside Git, source ZIPs and desktop packages.

These assets reuse the previously rendered UI images with the [octoooo.com favicon](https://octoooo.com/site-assets/favicon-64.png). Each is decoded offline and compared with the owner-supplied original. The application loads the verified pixels directly without downsampling or changing them again.

For each supported payment app, provide three fixed-amount receipt codes (9.90, 19.90 and 29.90) and one code without an amount. One payment app needs four images; both need eight. Use receipt codes, not payment authorization codes, friend codes, keys or merchant credentials.

In the mobile receipt screen, set each amount and save its code. Clear the amount and save another code for custom amounts. Users enter custom amounts in the payment app after scanning.

Place PNG files in `assets/support/`:

| Amount (CNY) | Alipay | WeChat |
| --- | --- | --- |
| 9.90 | `alipay-9_90.png` | `wechat-9_90.png` |
| 19.90 | `alipay-19_90.png` | `wechat-19_90.png` |
| 29.90 | `alipay-29_90.png` | `wechat-29_90.png` |
| Custom | `alipay-custom.png` | `wechat-custom.png` |

A single generic code also works. Preset selections then explicitly instruct the user to enter that amount manually; the UI does not claim that the code presets it. Missing or unreadable codes leave every other action available.

Keep original payment screenshots private. Public assets must contain only the branded QR presentation with quiet zones, at most 264 × 264 pixels. Verify that the original, public asset and actual UI decode identically; never redraw QR modules. Offline decoding cannot establish the recipient or amount shown by the payment service. No transfer is required for testing.

Only these eight named images are eligible for source ZIP, Windows EXE and macOS DMG resources. Other images in the directory are excluded. Missing codes are marked unavailable, without fake payment codes. Rebuild and verify packages after replacing images.
