# bb10-volte branding

The project, desktop title, package names and version metadata use `bb10-volte`.
The generated black-on-white BlackBerry-style icon places **4G in the upper-right**.
It is used for the README, Windows executable/window, macOS application and GUI sidebar. The 4G lettering sits close to the emblem's upper-right edge.

Assets: [PNG master](../assets/icon.png), [96px GUI PNG](../assets/icon-96.png), [multi-resolution Windows ICO](../assets/app.ico), [macOS ICNS](../assets/app.icns).
The original was generated with the built-in `image_gen` tool on 2026-10-27 and edited with the same tool on 2026-10-28 to reduce the spacing. Format/size conversion used Pillow 13.0.0; the master artwork was not manually redrawn.

The existing phone installation identifier `q10-unicom-volte` and `/var/rootdata/q10_volte` are retained for compatibility with deployed services. They are not device detection rules. The GitHub repository is already named `bb10-volte`. This is an independent project; the icon does not indicate endorsement by BlackBerry.

Final edit prompt:

> Use case: precise-object-edit. Asset type: existing bb10-volte app and project icon. Image 1 is the edit target. Primary request: reduce the white gap between the black BlackBerry berry emblem and the “4G” text while keeping “4G” in the upper-right of the emblem. Move the text down and slightly left so it sits close to the emblem’s upper-right edge, separated by a small clean white gap, never overlapping the seven berry pieces. Keep the solid white square background, solid black monochrome colors, exact “4G” lettering, and the overall seven-piece BlackBerry-style emblem. Flat crisp logo, no border, no gradients, no additional text, no shadows. Change only the spacing and position needed for a tighter, balanced icon; preserve the existing identity.
