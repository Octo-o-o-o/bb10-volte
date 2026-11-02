# BB10 VoLTE website

A static, bilingual website. The website explains the tool; it does not change the desktop app's interface language.

## Pages and languages

- Chinese: `/index.html`, `/guide.html`, `/trials.html`, `/404.html`
- English: `/en/index.html`, `/en/guide.html`, `/en/trials.html`, `/en/404.html`
- Opening `/` chooses Chinese or English from the first browser language. Unsupported browser languages fall back to English. Explicit language URLs are never automatically redirected.
- The language link preserves query parameters and the current section. Switching also works if storage is blocked.
- Pages, downloads and language links remain available without JavaScript. Appearance preferences use local storage when available.

Both languages use shared CSS and scripts, but each has complete HTML content and localized metadata. Keep section IDs and release data attributes identical between translations. When changing requirements or safety warnings, update both language versions. Do not describe an untested phone, carrier, desktop package or flashing workflow as verified.

## Development

Requires Node.js 20+ and npm.

```sh
npm ci
npm run check
npm test
npm run test:browser
npm run dev
```

`npm test` builds the site and checks static references, section links, release selection, language metadata and safety copy. Browser tests use Microsoft Edge and check both languages, narrow layouts, language preferences, deep links, themes, offline API fallbacks and no-JavaScript content. They start an isolated preview on port 4174 so an already-running development server cannot serve stale routing code. Override that port with `BB10_TEST_PORT` if needed.

`npm run dev` serves the built `dist` directory at `http://127.0.0.1:4173`; run `npm run build` again after source edits. A different local port can be selected with `PORT`.

## Exact-variant progress and tester instructions

`src/compatibility.json` records the published r15 routes and dated progress for all 14 catalog suffixes. `tests/test_website_variant_matrix.py` compares its 42 carrier decisions with the actual desktop gates. Voice, SMS and first-Root acceptance remain distinct; never mark a manual candidate as hardware-accepted based on offline checks.

`scripts/compatibility.mjs` renders the static homepage matrix and both trial pages during the build. It also creates eight standalone instructions per language, plus two aggregate TXT downloads, under `dist/trials/`. Each copy button uses the same text as its download; no backend or automatic feedback upload is involved. Edit the source data/renderer, not generated `dist` files. The table and downloads work without JavaScript.

Browser checks cover 320–3840 px, both themes, containment of the SMS evidence note, keyboard table scrolling, copy/download equivalence, clipboard denial and no-script forwarding. Windows clipboard line endings are normalized for comparison.

## Publishing

Run `npm run build` and publish `dist` to the existing Cloudflare Pages project `bb10-volte`, production branch `main`. The official domain is https://bb10-volte.octoooo.com/; the Pages domain remains available. The output includes both languages, security headers, the sitemap and redacted `acceptance.json`.

Download links are pinned to `v0.5.0-r15` in static HTML and `src/site.js`. Primary downloads use the dedicated R2 bucket `bb10-volte-releases` through https://bb10-downloads.octoooo.com/, with matching GitHub alternatives. Upload and anonymously verify all files and checksums before deploying a version update. The GitHub API must not downgrade the curated version or replace its matching R2 URLs. Update both translations, `RELEASE_TAG`, file names and checksums together.

No Cloudflare credentials or raw phone evidence belong in this directory. Local builds and browser tests do not publish the website or establish real-phone call compatibility.

## Acceptance illustration

The shared [carrier acceptance graphic](src/assets/carrier-acceptance.png) appears above the detailed compatibility cards on both homepages and in both READMEs. It is an illustration, not a photograph of the test session. Its nine cells show current support; exact test revisions remain in `src/acceptance.json`. The accessible HTML matrix and evidence links remain below it. The image opens at full size on small screens. The [Windows illustration](src/assets/windows-setup.jpg) is a real application screenshot with synthetic, identifier-free demonstration state.

Generated with the built-in image_gen tool. The [edit specification](src/assets/carrier-acceptance.prompt.txt) is included. Update the visual and text together if the acceptance scope changes.

## Rooted phone installation

The bilingual homepage leads to `mobile.html`, with the native BAR/system-installer route as the recommended approach. Mobile pages remain static for BB10 WebKit and separate native package installation, phone-only first installation, everyday standalone use and per-device acceptance. The public desktop downloads stay at r15 until matching new artifacts are released. This website update must not upload a candidate BAR or change `mobile/latest.json`.
