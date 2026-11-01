"""Public, optional support destinations and explicitly named receipt images."""

REPOSITORY_URL = 'https://github.com/Octo-o-o-o/bb10-volte'
PROJECT_WEBSITE_URL = 'https://bb10-volte.octoooo.com/'
OCTOLAB_URL = 'https://octoooo.com/'
CONTACT_EMAIL = 'octoooo@octoooo.com'
SUPPORT_ICON = 'assets/support/octoooo-favicon.png'
AMOUNTS = ('9.90', '19.90', '29.90', 'custom')
PROVIDERS = ('alipay', 'wechat')
QR_FILES = {provider: {
    amount: 'assets/support/{}-{}.png'.format(provider, amount.replace('.', '_'))
    for amount in AMOUNTS
} for provider in PROVIDERS}

# Publish only the previously verified, branded QR presentation images.
# Original payment screenshots (names and personal avatars) stay private.
# These images already include their quiet zone and must not be downsampled.
QR_VIEWS = {}
QR_AVATARS = {}


def receipt_view(filename, size):
    view = QR_VIEWS.get(filename)
    return view[1] if view and view[0] == size else None


def receipt_image(root, provider, amount):
    """Return (path, fixed_amount); a generic code never implies a preset total."""
    choices = QR_FILES[provider]
    path = root / choices[amount]
    if path.is_file():
        return path, amount != 'custom'
    generic = root / choices['custom']
    return (generic, False) if generic.is_file() else (None, False)


def bundled_receipt_images(root):
    """Only the eight intended public receipt images may enter a release."""
    return sorted(name for choices in QR_FILES.values() for name in choices.values()
                  if (root / name).is_file())
