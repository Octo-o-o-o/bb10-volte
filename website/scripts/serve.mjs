import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../dist/', import.meta.url));
const port = Number(process.env.PORT || 4173);
const types = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.json': 'application/json; charset=utf-8',
  '.mp4': 'video/mp4',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.vtt': 'text/vtt; charset=utf-8',
  '.webp': 'image/webp',
  '.xml': 'application/xml; charset=utf-8',
};

createServer(async (request, response) => {
  let pathname = '/';
  try {
    pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const relative = pathname.endsWith('/') ? `${pathname.replace(/^\/+/, '')}index.html` : pathname.replace(/^\/+/, '');
    let file = path.resolve(root, relative);
    if (!file.startsWith(root)) throw new Error('Invalid path');
    if (!path.extname(file)) file += '.html';
    const body = await readFile(file);
    const headers = {
      'Content-Type': types[path.extname(file)] || 'application/octet-stream',
      'Cache-Control': 'no-store',
      'Accept-Ranges': 'bytes',
    };
    // Browsers request byte ranges when seeking within the tutorial video.
    if (request.headers.range) {
      const match = /^bytes=(\d*)-(\d*)$/.exec(request.headers.range);
      let start = 0;
      let end = body.length - 1;
      if (match?.[1]) {
        start = Number(match[1]);
        if (match[2]) end = Math.min(Number(match[2]), end);
      } else if (match?.[2]) {
        start = Math.max(0, body.length - Number(match[2]));
      }
      if (!match || (!match[1] && !match[2]) || !Number.isSafeInteger(start) ||
          !Number.isSafeInteger(end) || start > end || start >= body.length) {
        response.writeHead(416, { ...headers, 'Content-Range': `bytes */${body.length}`, 'Content-Length': 0 });
        response.end();
        return;
      }
      response.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${body.length}`, 'Content-Length': end - start + 1 });
      response.end(request.method === 'HEAD' ? undefined : body.subarray(start, end + 1));
    } else {
      response.writeHead(200, { ...headers, 'Content-Length': body.length });
      response.end(request.method === 'HEAD' ? undefined : body);
    }
  } catch {
    response.writeHead(404, { 'Content-Type': types['.html'] });
    response.end(await readFile(path.join(root, pathname.startsWith('/en/') ? 'en/404.html' : '404.html')));
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`Preview: http://127.0.0.1:${port}`);
});
