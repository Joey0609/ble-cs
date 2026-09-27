// Static server for the presentation. Serves the parent docs/ folder at
// /tutorial-IPIN2026/, and opens the deck in the default browser.
//
// Usage: npm start [-- --port 8080] [-- --no-open]

import { createServer } from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { basename, dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const deckDir = dirname(fileURLToPath(import.meta.url));
const root = resolve(deckDir, '..');
const deckPath = `/${basename(deckDir)}/`;

const args = process.argv.slice(2);
const portArg = args.indexOf('--port');
const port = Number(portArg >= 0 ? args[portArg + 1] : process.env.PORT ?? 8000);
const openBrowser = !args.includes('--no-open');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.pdf': 'application/pdf',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

async function resolveFile(urlPath) {
  const filePath = resolve(join(root, decodeURIComponent(urlPath)));
  if (filePath !== root && !filePath.startsWith(root + sep)) {
    return null;
  }
  const info = await stat(filePath).catch(() => null);
  if (info?.isDirectory()) {
    // Relative URLs in index.html only resolve under a trailing slash.
    if (!urlPath.endsWith('/')) {
      return { redirect: `${urlPath}/` };
    }
    const index = join(filePath, 'index.html');
    return (await stat(index).catch(() => null))?.isFile() ? { file: index } : null;
  }
  return info?.isFile() ? { file: filePath } : null;
}

const server = createServer(async (req, res) => {
  const { pathname } = new URL(req.url, 'http://localhost');

  if (pathname === '/') {
    res.writeHead(302, { Location: deckPath }).end();
    return;
  }

  const target = await resolveFile(pathname).catch(() => null);
  if (!target) {
    res.writeHead(404, { 'Content-Type': 'text/plain' }).end('Not found');
    return;
  }
  if (target.redirect) {
    res.writeHead(301, { Location: target.redirect }).end();
    return;
  }

  const filePath = target.file;
  res.writeHead(200, {
    'Content-Type': MIME_TYPES[extname(filePath).toLowerCase()] ?? 'application/octet-stream',
    'Cache-Control': 'no-cache',
  });
  createReadStream(filePath).pipe(res);
});

server.on('error', (error) => {
  console.error(error.code === 'EADDRINUSE'
    ? `Port ${port} is in use; try: npm start -- --port ${port + 1}`
    : error.message);
  process.exit(1);
});

server.listen(port, '127.0.0.1', () => {
  const url = `http://localhost:${port}${deckPath}`;
  console.log(`Presentation: ${url}\nPress Ctrl+C to stop.`);
  if (openBrowser) {
    const [command, ...commandArgs] =
      process.platform === 'darwin' ? ['open', url]
        : process.platform === 'win32' ? ['cmd', '/c', 'start', '', url]
          : ['xdg-open', url];
    spawn(command, commandArgs, { stdio: 'ignore', detached: true })
      .on('error', () => {})
      .unref();
  }
});
