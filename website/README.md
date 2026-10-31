# BB10 VoLTE website

A static, bilingual website. The website explains the tool; it does not change the desktop app's interface language.

## Pages and languages

- Chinese: `/index.html`, `/guide.html`, `/404.html`
- English: `/en/index.html`, `/en/guide.html`, `/en/404.html`
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

## Publishing

Run `npm run build` and publish `dist` to the existing Cloudflare Pages project `bb10-volte`, production branch `main`. The official domain is https://bb10-volte.octoooo.com/; the Pages domain remains available. The output includes both languages, security headers, the sitemap and redacted `acceptance.json`.

Download links are pinned to `v0.5.0-r8` in static HTML and `src/site.js`. Primary downloads use the dedicated R2 bucket `bb10-volte-releases` through https://bb10-downloads.octoooo.com/, with matching GitHub alternatives. Upload and anonymously verify all files and checksums before deploying a version update. The GitHub API must not downgrade the curated version or replace its matching R2 URLs. Update both translations, `RELEASE_TAG`, file names and checksums together.

No Cloudflare credentials or raw phone evidence belong in this directory. Local builds and browser tests do not publish the website or establish real-phone call compatibility.
