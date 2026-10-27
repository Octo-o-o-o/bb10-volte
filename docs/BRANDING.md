# bb10-volte branding

The project, desktop title, package names and version metadata use `bb10-volte`.
The generated black-on-white BlackBerry-style icon places **4G in the upper-right**.
It is used for the README, Windows executable/window and GUI sidebar; ICNS is included for a future Mac build.

Assets: [PNG master](../assets/icon.png), [96px GUI PNG](../assets/icon-96.png), [multi-resolution Windows ICO](../assets/app.ico), [macOS ICNS](../assets/app.icns).
Generated using the built-in `image_gen` tool on 2026-10-27. Format/size conversion used Pillow 13.0.0; the master artwork was not manually redrawn.

The existing phone installation identifier `q10-unicom-volte` and `/var/rootdata/q10_volte` are retained for compatibility with deployed services. They are not device detection rules. The GitHub repository is already named `bb10-volte`. This is an independent project; the icon does not indicate endorsement by BlackBerry.

Final generation prompt:

> Create a brand-new clean, simple square desktop icon for the project bb10-volte. Use an entirely OPAQUE solid white square canvas extending perfectly to all four image edges, with NO transparency and NO border or framing tile. The main visual is the familiar BlackBerry seven black seed/pill pieces arranged as the classic BlackBerry berry emblem, centered slightly below and left of the canvas center. Each piece is a crisp solid-black slanted rounded shape, flat and smooth. Place the exact text "4G" in bold black sans-serif in the upper right corner, inset 8 percent from the top and right edges. The 4G label should be noticeably smaller than the berry emblem, and the label must not overlap it. This is the inverted black-on-white treatment of the BlackBerry 10 icon. High-contrast minimalist black and white only, polished vector-like geometry, balanced compact desktop icon, readable at 32 pixels. No extra words, no gradients, no shadows, no texture, no roughness, no speckles, no rounded outer tile, no framing border, no mockup. Pure white background everywhere beyond the black emblem and text. One final square image.
